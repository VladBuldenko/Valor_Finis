"""
Seed serialization, crash recovery and retry against a REAL disposable PostgreSQL.

The seed commits between steps, so a transaction-scoped lock would not cover
it. These tests prove the session advisory lock does: a competing seed or
bootstrap is refused while a seed is mid-run, a lost lock stops the run, and
a stopped seed is never topped up (no duplicated financial effect).
"""

import contextlib
import threading
import uuid
from datetime import date

import pytest

from staging_ops import database, seed as seed_module
from staging_ops.bootstrap import bootstrap
from staging_ops.errors import StagingRefused
from staging_ops.seed import seed

from .helpers import SpyOperations, approved_for, environ_for, execute, fetch, snapshot, verified_target

USERS = {"QA-A": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "QA-B": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}
AS_OF = date.today()
COUNTED = ("accounts", "goals", "budgets", "income", "expenses", "financial_rules", "goal_transactions", "rule_executions", "rule_alerts", "account_transactions", "financial_events", "categories")


def quiet(_text):
    return None


def counts(cluster, name):
    return {table: fetch(cluster, name, f"SELECT count(*) FROM {table}")[0][0] for table in COUNTED}


def lock_is_free(cluster, name):
    connection = cluster.connect(name)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(7165, 3)")

            return cursor.fetchone()[0]
    finally:
        connection.close()


@pytest.fixture
def world(local_cluster):
    name, oid = local_cluster.create_database()
    environ, approved, spy = environ_for(local_cluster, name), approved_for(local_cluster, name, oid), SpyOperations()
    bootstrap("staging", "STG-1", environ, approved, spy.operations(), None, quiet)

    return local_cluster, name, oid, environ, approved, spy


@pytest.fixture(scope="module")
def single_seed_counts(local_cluster):
    """Row counts after exactly one clean seed: the oracle for 'no duplicate effect'."""

    name, oid = local_cluster.create_database()
    environ, approved, spy = environ_for(local_cluster, name), approved_for(local_cluster, name, oid), SpyOperations()
    bootstrap("staging", "STG-1", environ, approved, spy.operations(), None, quiet)
    seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

    return counts(local_cluster, name)


class PausingSteps:
    """Wraps seed._run_step: pauses (or fails, or kills the lock) when the Nth step is reached."""

    def __init__(self, monkeypatch, at, action="pause", on_reach=None):
        self.original = seed_module._run_step
        self.at, self.action, self.on_reach = at, action, on_reach
        self.calls = 0
        self.reached, self.proceed = threading.Event(), threading.Event()
        monkeypatch.setattr(seed_module, "_run_step", self)

    def __call__(self, *args, **kwargs):
        self.calls += 1

        if self.calls == self.at:
            if self.on_reach:
                self.on_reach()

            if self.action == "crash":
                raise RuntimeError("simulated crash in the middle of a seed")

            if self.action == "pause":
                self.reached.set()
                assert self.proceed.wait(60)

        return self.original(*args, **kwargs)


def run_in_thread(function):
    outcome = {}

    def target():
        try:
            outcome["result"] = function()
        except BaseException as error:  # noqa: BLE001 - handed to the test thread
            outcome["error"] = error

    thread = threading.Thread(target=target)
    thread.start()

    return thread, outcome


class TestCompetingOperationsAreRefusedWhileASeedRuns:
    def test_a_second_seed_cannot_pass_its_preflight_or_write(self, world, monkeypatch, single_seed_counts):
        cluster, name, _oid, environ, approved, spy = world
        pause = PausingSteps(monkeypatch, at=3)
        thread, first = run_in_thread(lambda: seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet))

        try:
            assert pause.reached.wait(60), "the first seed never reached the pause point"
            midway = counts(cluster, name)
            assert sum(midway.values()) > 0, "the first seed must already have committed rows"

            with pytest.raises(StagingRefused) as caught:
                seed("staging", "STG-1", environ, approved, SpyOperations().operations(), USERS, AS_OF, None, quiet)

            assert caught.value.code == "LOCK_BUSY" and not caught.value.mutated
            assert counts(cluster, name) == midway, "the competing seed must not have written anything"
        finally:
            pause.proceed.set()
            thread.join(120)

        assert "error" not in first, first.get("error")
        assert first["result"].outcome == "OK"
        assert counts(cluster, name) == single_seed_counts, "exactly one seed's worth of financial effects"
        assert lock_is_free(cluster, name), "the lock must be released when the seed ends"

    def test_a_bootstrap_during_a_seed_is_refused_by_the_alembic_binding(self, local_cluster):
        name, oid = local_cluster.create_database()
        environ, approved = environ_for(local_cluster, name), approved_for(local_cluster, name, oid)
        _environ, verified = verified_target(local_cluster, name, oid)

        with database.seed_lock(verified):
            with pytest.raises(StagingRefused) as caught:
                bootstrap("staging", "STG-1", environ, approved, SpyOperations().operations(), None, quiet)

        assert caught.value.code == "UPGRADE_FAILED"
        assert snapshot(local_cluster, name) == ((), ()), "the held lock must stop Alembic before any DDL"

    def test_two_seeds_started_together_never_duplicate_an_effect(self, world, single_seed_counts):
        cluster, name, _oid, environ, approved, _spy = world
        barrier = threading.Barrier(2)

        def attempt():
            barrier.wait(30)

            try:
                return seed("staging", "STG-1", environ, approved, SpyOperations().operations(), USERS, AS_OF, None, quiet).outcome
            except StagingRefused as error:
                return error.code

        first_thread, first = run_in_thread(attempt)
        second_thread, second = run_in_thread(attempt)
        first_thread.join(180)
        second_thread.join(180)

        results = sorted([first.get("result", repr(first.get("error"))), second.get("result", repr(second.get("error")))])
        assert set(results) <= {"OK", "LOCK_BUSY"} and "OK" in results, results
        assert counts(cluster, name) == single_seed_counts


class TestLostLockAndCrashRecovery:
    def test_a_lost_lock_stops_the_run_before_the_next_step(self, world, monkeypatch):
        cluster, name, _oid, environ, approved, spy = world

        def kill_lock_connection():
            execute(
                cluster, name,
                "SELECT pg_terminate_backend(pid) FROM pg_locks WHERE locktype = 'advisory' AND classid = 7165 AND objid = 3 AND granted",
            )

        # The lock connection dies while step 4 runs; step 4 itself still completes
        # (the window is bounded to the in-flight step), step 5 must never start.
        steps = PausingSteps(monkeypatch, at=4, action="kill", on_reach=kill_lock_connection)

        with pytest.raises(StagingRefused) as caught:
            seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

        assert caught.value.code == "SEED_LOCK_LOST" and caught.value.mutated
        assert steps.calls == 4, "no step may start after the lock is gone"

    def test_a_lock_connection_that_dies_is_detected_by_the_next_check(self, world):
        cluster, name, oid, *_ = world
        _environ, verified = verified_target(cluster, name, oid)

        with database.seed_lock(verified) as check:
            check()
            execute(cluster, name, "SELECT pg_terminate_backend(pid) FROM pg_locks WHERE locktype = 'advisory' AND classid = 7165 AND objid = 3 AND granted")

            with pytest.raises(StagingRefused) as caught:
                check()

        assert caught.value.code == "SEED_LOCK_LOST"

    def test_a_lock_that_was_released_while_the_connection_lives_is_detected(self, world, monkeypatch):
        cluster, name, oid, *_ = world
        _environ, verified = verified_target(cluster, name, oid)
        connections = []
        real_engine = database.bound_engine

        def spying_engine(target):
            engine = real_engine(target)
            real_connect = engine.connect

            def connect(*args, **kwargs):
                connections.append(real_connect(*args, **kwargs))

                return connections[-1]

            engine.connect = connect

            return engine

        monkeypatch.setattr(database, "bound_engine", spying_engine)

        with database.seed_lock(verified) as check:
            check()
            connections[0].exec_driver_sql("SELECT pg_advisory_unlock(7165, 3)")

            with pytest.raises(StagingRefused) as caught:
                check()

        assert caught.value.code == "SEED_LOCK_LOST" and "no longer held" in caught.value.message
        assert lock_is_free(cluster, name)

    def test_a_crash_midway_is_never_topped_up_and_the_message_is_accurate(self, world, monkeypatch, single_seed_counts):
        cluster, name, _oid, environ, approved, spy = world
        PausingSteps(monkeypatch, at=6, action="crash")

        with pytest.raises(StagingRefused) as crashed:
            seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

        assert crashed.value.code == "UNEXPECTED" and crashed.value.mutated
        assert lock_is_free(cluster, name), "a crashed seed must not leave the lock held"
        monkeypatch.undo()
        partial = counts(cluster, name)
        assert 0 < sum(partial.values()) < sum(single_seed_counts.values())

        with pytest.raises(StagingRefused) as rerun:
            seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

        assert rerun.value.code == "ACTOR_HAS_DATA" and not rerun.value.mutated, "a refusal before any write reports no change"
        assert "QA-A" in rerun.value.message and "accounts=" in rerun.value.message and "newly provisioned" in rerun.value.message
        assert counts(cluster, name) == partial, "the rerun must not add, repeat or repair anything"

    def test_recovery_after_a_crash_is_a_new_empty_database_and_a_complete_seed(self, world, local_cluster, monkeypatch, single_seed_counts):
        """The reset is disabled: the crashed database is abandoned and a newly provisioned empty one is bootstrapped and seeded."""

        cluster, name, _oid, environ, approved, spy = world
        PausingSteps(monkeypatch, at=6, action="crash")

        with pytest.raises(StagingRefused):
            seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

        monkeypatch.undo()
        crashed = counts(cluster, name)
        fresh_name, fresh_oid = cluster.create_database()
        fresh_environ, fresh_approved = environ_for(cluster, fresh_name), approved_for(cluster, fresh_name, fresh_oid)
        bootstrap("staging", "STG-1", fresh_environ, fresh_approved, spy.operations(), None, quiet)
        seed("staging", "STG-1", fresh_environ, fresh_approved, spy.operations(), USERS, AS_OF, None, quiet)

        assert counts(cluster, fresh_name) == single_seed_counts
        assert counts(cluster, name) == crashed, "the abandoned database is left exactly as it was"

    def test_a_crash_while_seeding_the_second_actor_leaves_the_first_complete_and_the_second_refused(self, world, monkeypatch):
        cluster, name, _oid, environ, approved, spy = world
        qa_a_steps = len(seed_module.build_scenarios(AS_OF)["QA-A"])
        PausingSteps(monkeypatch, at=qa_a_steps + 2, action="crash")

        with pytest.raises(StagingRefused):
            seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

        monkeypatch.undo()
        before = counts(cluster, name)

        with pytest.raises(StagingRefused) as rerun:
            seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

        assert rerun.value.code == "ACTOR_HAS_DATA" and "QA-B" in rerun.value.message
        assert counts(cluster, name) == before, "QA-A was complete, so it is skipped, and nothing is added for QA-B"

    def test_a_completed_seed_can_be_repeated_without_any_change(self, world, single_seed_counts):
        cluster, name, _oid, environ, approved, spy = world
        seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)
        seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

        assert counts(cluster, name) == single_seed_counts and lock_is_free(cluster, name)


class TestOwnedDataDetectionIncludesCategories:
    def test_a_user_created_category_counts_as_data(self, world):
        cluster, name, _oid, environ, approved, spy = world
        execute(cluster, name, f"INSERT INTO categories (id, user_id, name, is_default) VALUES (gen_random_uuid(), '{USERS['QA-A']}', 'hand made', false)")
        before = counts(cluster, name)

        with pytest.raises(StagingRefused) as caught:
            seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

        assert caught.value.code == "ACTOR_HAS_DATA" and "categories=1" in caught.value.message
        assert counts(cluster, name) == before

    def test_default_categories_alone_do_not_block_the_seed(self, world, single_seed_counts):
        cluster, name, oid, environ, approved, spy = world
        from app.modules.categories import service as category_service

        session = spy.operations().open_session(verified_target(cluster, name, oid)[1])

        try:
            category_service.get_categories(session, uuid.UUID(USERS["QA-A"]))
        finally:
            session.close()

        assert fetch(cluster, name, f"SELECT count(*) FROM categories WHERE user_id = '{USERS['QA-A']}' AND is_default")[0][0] > 0

        seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

        assert counts(cluster, name) == single_seed_counts


class TestOwnerConsistencyEvidence:
    def test_the_evidence_names_what_was_checked_and_what_was_not(self, world):
        cluster, name, _oid, environ, approved, spy = world
        record = seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)
        details = record.details["owner_consistency"]

        assert "budgets.category_id->categories.id" in details["checked_relationships"]
        assert "goal_transactions.goal_id->goals.id" in details["checked_relationships"]
        assert details["composite_user_foreign_keys_enforced_by_database"] >= 10
        assert "API-level" in details["not_covered"]
        assert [step["check"] for step in record.steps][-1] == "foreign-key-owner-consistency-checked"
        assert not any("isolation-verified" in step["check"] for step in record.steps), "the old over-claiming step name must be gone"

    def test_a_row_pointing_at_another_users_parent_is_detected(self, world):
        cluster, name, oid, environ, approved, spy = world
        seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)
        # budgets.category_id is a single-column FK: PostgreSQL itself would accept this cross-user pointer.
        execute(
            cluster, name,
            f"UPDATE budgets SET category_id = (SELECT id FROM categories WHERE user_id = '{USERS['QA-B']}' AND NOT is_default LIMIT 1) WHERE user_id = '{USERS['QA-A']}'",
        )
        session = spy.operations().open_session(verified_target(cluster, name, oid)[1])

        try:
            with pytest.raises(StagingRefused) as caught:
                seed_module._verify_owner_consistency(session)
        finally:
            session.close()

        assert caught.value.code == "SEED_OWNER_MISMATCH" and "budgets.category_id" in caught.value.message
