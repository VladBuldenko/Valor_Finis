"""
Bootstrap, binding, reset and seed against a REAL disposable PostgreSQL.

These are actual database tests (real `alembic upgrade head`, real catalog
queries, real domain services). Only the Supabase probe is replaced, because no
test may reach a cloud service.
"""

import contextlib
import json
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal

import psycopg2
import pytest

from staging_ops import database
from staging_ops.bootstrap import bootstrap, verify_target
from staging_ops.errors import StagingRefused
from staging_ops.evidence import EvidenceRecord
from staging_ops.identity import verify_configuration, verify_facts
from staging_ops.operations import API_DIRECTORY, child_environment, real_operations
from staging_ops.reset import reset
from staging_ops.seed import seed

from .helpers import SpyOperations, approved_for, environ_for, snapshot

USERS = {"QA-A": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "QA-B": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}
AS_OF = date.today()


def quiet(_text: str) -> None:
    return None


@pytest.fixture
def target(local_cluster):
    name, oid = local_cluster.create_database()

    return local_cluster, name, oid


def run_bootstrap(cluster, name, oid, spy=None, evidence_dir=None):
    spy = spy or SpyOperations()

    return spy, bootstrap("staging", "STG-1", environ_for(cluster, name), approved_for(cluster, name, oid), spy.operations(), evidence_dir, quiet)


def alembic_head():
    return real_operations().repository_heads()[0]


class TestBootstrapOnARealDatabase:
    def test_builds_an_empty_database_to_the_single_head(self, target, tmp_path):
        cluster, name, oid = target
        spy, record = run_bootstrap(cluster, name, oid, evidence_dir=str(tmp_path))
        relations, revisions = snapshot(cluster, name)

        assert record.outcome == "OK" and spy.alembic_runs == 1
        assert revisions == (alembic_head(),)
        assert "accounts" in relations and "rule_alerts" in relations and "alembic_version" in relations
        assert record.details["alembic_current"] == alembic_head()

        (evidence,) = os.listdir(tmp_path)
        text = (tmp_path / evidence).read_text()
        assert json.loads(text)["outcome"] == "OK" and "postgresql://" not in text and cluster.host not in text

    def test_a_second_bootstrap_is_refused_and_changes_nothing(self, target):
        cluster, name, oid = target
        run_bootstrap(cluster, name, oid)
        before = snapshot(cluster, name)
        spy = SpyOperations()

        with pytest.raises(StagingRefused) as caught:
            run_bootstrap(cluster, name, oid, spy)

        assert caught.value.code == "REVISION_UNEXPECTED" and spy.alembic_runs == 0
        assert snapshot(cluster, name) == before

    def test_a_nonempty_database_is_refused_before_alembic_runs(self, target):
        cluster, name, oid = target

        with contextlib.closing(cluster.connect(name)) as connection, connection.cursor() as cursor:
            cursor.execute("CREATE TABLE stray_table (id int)")

        spy = SpyOperations()

        with pytest.raises(StagingRefused) as caught:
            run_bootstrap(cluster, name, oid, spy)

        assert caught.value.code == "DATABASE_NOT_EMPTY" and spy.alembic_runs == 0
        assert snapshot(cluster, name) == (("stray_table",), ())

    def test_a_wrong_pinned_oid_is_refused_and_the_database_stays_empty(self, target):
        cluster, name, oid = target
        spy = SpyOperations()

        with pytest.raises(StagingRefused) as caught:
            run_bootstrap(cluster, name, oid + 1, spy)

        assert caught.value.code == "CONNECTED_OID_MISMATCH" and spy.alembic_runs == 0
        assert snapshot(cluster, name) == ((), ())

    def test_the_wrong_database_name_for_the_approved_entry_is_refused(self, target):
        cluster, name, oid = target
        other, _ = cluster.create_database()
        spy = SpyOperations()

        with pytest.raises(StagingRefused) as caught:
            bootstrap("staging", "STG-1", environ_for(cluster, other), approved_for(cluster, name, oid), spy.operations(), None, quiet)

        assert caught.value.code == "DATABASE_NOT_ALLOWLISTED" and spy.alembic_runs == 0
        assert snapshot(cluster, other) == ((), ())


class TestMutationConnectionIsBoundToTheCheckedIdentity:
    def verified(self, cluster, name, oid):
        environ = environ_for(cluster, name)
        configured = verify_configuration("staging", "STG-1", environ, approved_for(cluster, name, oid))

        return environ, verify_facts(configured, database.probe_database(configured))

    def test_alembic_refuses_when_its_own_connection_reached_another_database(self, target):
        cluster, name, oid = target
        decoy, _ = cluster.create_database()
        _environ, verified = self.verified(cluster, name, oid)
        # The parent verified `name`; the child is (mis)directed at `decoy`, as a DNS or proxy switch would do.
        child = child_environment(environ_for(cluster, decoy), verified, require_empty=True)
        result = real_operations().run_alembic(("upgrade", "head"), child)

        assert result.returncode != 0 and "VF_STAGING_BINDING_MISMATCH" in result.output
        assert snapshot(cluster, decoy) == ((), ()), "the decoy database must not receive a single object"
        assert snapshot(cluster, name) == ((), ())

    def test_alembic_refuses_when_the_database_stopped_being_empty_after_the_check(self, target):
        cluster, name, oid = target
        environ, verified = self.verified(cluster, name, oid)

        with contextlib.closing(cluster.connect(name)) as connection, connection.cursor() as cursor:
            cursor.execute("CREATE TABLE late_arrival (id int)")

        result = real_operations().run_alembic(("upgrade", "head"), child_environment(environ, verified, require_empty=True))

        assert result.returncode != 0 and "VF_STAGING_NOT_EMPTY" in result.output
        assert snapshot(cluster, name) == (("late_arrival",), ())

    def test_a_bound_engine_rejects_a_connection_to_a_different_database(self, target):
        cluster, name, oid = target
        decoy, _ = cluster.create_database()
        _environ, verified = self.verified(cluster, name, oid)
        redirected = type(verified)(
            configured=type(verified.configured)(**{**verified.configured.__dict__, "database_url": cluster.url(decoy)}),
            oid=verified.oid,
            postmaster_start=verified.postmaster_start,
            server_version_num=verified.server_version_num,
        )
        engine = database.bound_engine(redirected)

        with pytest.raises(StagingRefused) as caught:
            engine.connect()

        assert caught.value.code == "CONNECTION_IDENTITY_CHANGED"

    def test_the_child_environment_cannot_be_redirected_by_libpq_variables(self, target):
        cluster, name, oid = target
        environ, verified = self.verified(cluster, name, oid)
        child = child_environment({**environ, "PGHOST": "203.0.113.9", "PGDATABASE": "elsewhere"}, verified, True)

        assert "PGHOST" not in child and "PGDATABASE" not in child


class TestResetOnARealDatabase:
    def bootstrapped_with_seed(self, target):
        cluster, name, oid = target
        spy = SpyOperations()
        environ, approved = environ_for(cluster, name), approved_for(cluster, name, oid)
        bootstrap("staging", "STG-1", environ, approved, spy.operations(), None, quiet)
        seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

        return cluster, name, oid, environ, approved

    def count(self, cluster, name, table):
        with contextlib.closing(cluster.connect(name)) as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM {table}")

            return cursor.fetchone()[0]

    def phrase(self, cluster, name):
        return f"STG-1/{name}@{cluster.host}:{cluster.port}"

    def test_a_wrong_confirmation_destroys_nothing(self, target):
        cluster, name, oid, environ, approved = self.bootstrapped_with_seed(target)
        before = self.count(cluster, name, "accounts")
        spy = SpyOperations()

        with pytest.raises(StagingRefused) as caught:
            reset("staging", "STG-1", environ, approved, spy.operations(), lambda _p: self.phrase(cluster, "vfqa1_other_staging"), None, quiet)

        assert caught.value.code == "CONFIRMATION_MISMATCH" and spy.destroys == 0 and spy.alembic_runs == 0
        assert self.count(cluster, name, "accounts") == before > 0

    def test_a_confirmed_reset_destroys_everything_and_rebuilds_to_head(self, target, tmp_path):
        cluster, name, oid, environ, approved = self.bootstrapped_with_seed(target)
        assert self.count(cluster, name, "accounts") > 0
        spy = SpyOperations()
        said = []
        record = reset("staging", "STG-1", environ, approved, spy.operations(), lambda _p: self.phrase(cluster, name), str(tmp_path), said.append)

        assert record.outcome == "OK" and spy.destroys == 1 and spy.alembic_runs == 1
        assert "PERMANENTLY DESTROY" in "\n".join(said) and "accounts:" in "\n".join(said)
        assert self.count(cluster, name, "accounts") == 0 and self.count(cluster, name, "financial_rules") == 0
        assert snapshot(cluster, name)[1] == (alembic_head(),)

    def test_a_destroy_that_cannot_take_the_lock_changes_nothing(self, target):
        cluster, name, oid, environ, approved = self.bootstrapped_with_seed(target)
        before = snapshot(cluster, name)
        _environ, verified = TestMutationConnectionIsBoundToTheCheckedIdentity().verified(cluster, name, oid)

        with contextlib.closing(cluster.connect(name)) as holder, holder.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(7165, 3)")

            with pytest.raises(StagingRefused) as caught:
                database.destroy_application_objects(verified)

        assert caught.value.code == "LOCK_BUSY" and snapshot(cluster, name) == before

    def test_the_reset_never_touches_other_schemas_or_extension_objects(self, target):
        cluster, name, oid = target
        spy = SpyOperations()
        environ, approved = environ_for(cluster, name), approved_for(cluster, name, oid)

        with contextlib.closing(cluster.connect(name)) as connection, connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA auth_like; CREATE TABLE auth_like.users (id int); INSERT INTO auth_like.users VALUES (1)")

        bootstrap("staging", "STG-1", environ, approved, spy.operations(), None, quiet)
        reset("staging", "STG-1", environ, approved, spy.operations(), lambda _p: self.phrase(cluster, name), None, quiet)

        with contextlib.closing(cluster.connect(name)) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM auth_like.users")
            assert cursor.fetchone()[0] == 1


class TestSeedOnARealDatabase:
    def build(self, target):
        cluster, name, oid = target
        environ, approved = environ_for(cluster, name), approved_for(cluster, name, oid)
        spy = SpyOperations()
        bootstrap("staging", "STG-1", environ, approved, spy.operations(), None, quiet)

        return cluster, name, environ, approved, spy

    def rows(self, cluster, name):
        tables = ("accounts", "goals", "budgets", "income", "expenses", "financial_rules", "goal_transactions", "rule_executions", "rule_alerts", "account_transactions", "financial_events")

        with contextlib.closing(cluster.connect(name)) as connection, connection.cursor() as cursor:
            counts = {}

            for table in tables:
                cursor.execute(f"SELECT count(*) FROM {table}")
                counts[table] = cursor.fetchone()[0]

            return counts

    def test_seeds_two_isolated_users_through_the_domain_services(self, target, tmp_path):
        cluster, name, environ, approved, spy = self.build(target)
        record = seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, str(tmp_path), quiet)
        counts = self.rows(cluster, name)

        assert record.outcome == "OK"
        assert counts["accounts"] == 5 + 2, counts  # QA-A 4 + marker, QA-B 1 + marker
        assert counts["goals"] == 4 and counts["budgets"] == 2 and counts["income"] == 3 and counts["expenses"] == 3
        assert counts["financial_rules"] == 5
        assert counts["rule_executions"] >= 3 and counts["rule_alerts"] >= 2

        with contextlib.closing(cluster.connect(name)) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT user_id, count(*) FROM accounts GROUP BY user_id ORDER BY 1")
            assert [(str(user), n) for user, n in cursor.fetchall()] == [(USERS["QA-A"], 5), (USERS["QA-B"], 2)]
            cursor.execute("SELECT count(*) FROM accounts WHERE name = 'QA-SEED-STG-1'")
            assert cursor.fetchone()[0] == 2
            cursor.execute("SELECT count(*) FROM goal_transactions g JOIN goals o ON o.id = g.goal_id WHERE g.user_id <> o.user_id")
            assert cursor.fetchone()[0] == 0

        (evidence,) = [f for f in os.listdir(tmp_path)]
        manifest = json.loads((tmp_path / evidence).read_text())["details"]["manifest"]
        assert set(manifest) == {"QA-A", "QA-B"} and "QA1-S07" in manifest["QA-A"]

    def test_the_ledger_balances_are_what_the_domain_rules_produce(self, target):
        cluster, name, environ, approved, spy = self.build(target)
        seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

        with contextlib.closing(cluster.connect(name)) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT a.name, COALESCE(SUM(CASE t.direction WHEN 'credit' THEN t.amount ELSE -t.amount END), 0) "
                "FROM accounts a LEFT JOIN account_transactions t ON t.account_id = a.id WHERE a.user_id = %s GROUP BY a.name",
                (USERS["QA-A"],),
            )
            balances = {row[0]: Decimal(row[1]) for row in cursor.fetchall()}

        assert balances["QA-A EUR Checking"] == Decimal("5000.00") + Decimal("3000.00") - Decimal("250.00") - Decimal("180.00")
        assert balances["QA-A USD Cash"] == Decimal("800.00")

    def test_a_failed_verification_leaves_no_completion_marker(self, target, monkeypatch):
        from staging_ops import seed_scenarios

        cluster, name, environ, approved, spy = self.build(target)
        monkeypatch.setitem(seed_scenarios.MINIMUM_ROWS["QA-A"], "rule_alerts", 99)

        with pytest.raises(StagingRefused) as caught:
            seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

        assert caught.value.code == "SEED_VERIFICATION_FAILED" and caught.value.mutated

        with contextlib.closing(cluster.connect(name)) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM accounts WHERE name = 'QA-SEED-STG-1'")
            assert cursor.fetchone()[0] == 0

        monkeypatch.undo()

        with pytest.raises(StagingRefused) as again:
            seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

        assert again.value.code == "ACTOR_HAS_DATA", "a half-seeded actor needs the reset procedure, never a top-up"

    def test_a_second_run_changes_nothing(self, target):
        cluster, name, environ, approved, spy = self.build(target)
        seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)
        first = self.rows(cluster, name)
        again = seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

        assert self.rows(cluster, name) == first
        assert any("already-seeded" in step["check"] for step in again.steps)

    def test_an_actor_with_data_but_no_marker_is_refused_not_topped_up(self, target):
        cluster, name, environ, approved, spy = self.build(target)

        with contextlib.closing(cluster.connect(name)) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO accounts (id, user_id, name, type, currency, status) VALUES (gen_random_uuid(), %s, 'hand-made', 'cash', 'EUR', 'active')",
                (USERS["QA-A"],),
            )

        before = self.rows(cluster, name)

        with pytest.raises(StagingRefused) as caught:
            seed("staging", "STG-1", environ, approved, spy.operations(), USERS, AS_OF, None, quiet)

        assert caught.value.code == "ACTOR_HAS_DATA"
        assert self.rows(cluster, name) == before

    def test_a_seed_against_a_target_that_is_not_the_approved_one_writes_nothing(self, target):
        cluster, name, environ, approved, spy = self.build(target)
        other, other_oid = cluster.create_database()

        with pytest.raises(StagingRefused):
            seed("staging", "STG-1", environ_for(cluster, other), approved, spy.operations(), USERS, AS_OF, None, quiet)

        assert snapshot(cluster, other) == ((), ())


class TestCommandLineRefusals:
    def run_cli(self, cluster, name, oid, tmp_path, *arguments, environment=None):
        from tests.unit.staging_tooling import helpers as unit_helpers  # noqa: F401  (document shape reuse)

        approved_file = tmp_path / "approved.json"
        approved_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "staging": [{"id": "STG-1", "database": {"host": cluster.host, "port": cluster.port, "name": name, "oid": oid}, "supabase_project_ref": "stgprojectrefabcdefgh", "approved_by": "Owner", "approved_on": "2026-11-20"}],
                    "production_denylist": {"database_hosts": ["prod-db.example.test"], "supabase_project_refs": ["prdprojectrefabcdefgh"], "database_names": ["valor"], "recorded_by": "Owner", "recorded_on": "2026-11-19"},
                }
            )
        )
        approved_file.chmod(0o600)
        child = {**environ_for(cluster, name), **(environment or {})}

        return subprocess.run(
            [sys.executable, "-m", "staging_ops", *arguments, "--staging", "STG-1", "--approved-targets", str(approved_file), "--evidence-dir", str(tmp_path / "evidence")],
            cwd=str(API_DIRECTORY), env=child, capture_output=True, text=True, timeout=120,
        )

    def test_missing_and_wrong_environment_flags_exit_11_and_touch_nothing(self, target, tmp_path):
        cluster, name, oid = target

        for extra in ([], ["--environment", "production"]):
            completed = self.run_cli(cluster, name, oid, tmp_path, "bootstrap", *extra)

            assert completed.returncode == 11, completed.stderr
            assert "ENV_FLAG" in completed.stderr
            assert "postgresql://" not in completed.stdout + completed.stderr

        assert snapshot(cluster, name) == ((), ())

    def test_libpq_override_variables_exit_11_before_any_connection(self, target, tmp_path):
        cluster, name, oid = target
        completed = self.run_cli(cluster, name, oid, tmp_path, "bootstrap", "--environment", "staging", environment={"PGHOST": "203.0.113.9"})

        assert completed.returncode == 11 and "CONFIG_OVERRIDE" in completed.stderr
        assert snapshot(cluster, name) == ((), ())

    def test_a_production_looking_target_exits_11(self, target, tmp_path):
        cluster, name, oid = target
        completed = self.run_cli(cluster, name, oid, tmp_path, "bootstrap", "--environment", "staging", environment={"DATABASE_URL": "postgresql://svc@prod-db.example.test:5432/valor_staging?sslmode=require"})

        assert completed.returncode == 11 and "DENYLIST_HIT" in completed.stderr
        assert snapshot(cluster, name) == ((), ())
