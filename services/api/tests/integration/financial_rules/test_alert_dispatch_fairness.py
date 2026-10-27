import math
import time
from typing import Any, Optional
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db.database_session import SessionLocal, engine
from app.modules.financial_rules import (
    alert_dispatch_progress_repository as progress,
    dispatcher,
    rule_alert_repository,
    rule_alert_service,
)
from app.modules.financial_rules.dispatcher import DispatcherConfig
from tests.integration.financial_rules.execution_helpers import scalar
from tests.integration.financial_rules.test_dispatcher import (
    _alert_count,
    _cut_after,
    _floor_user,
    _run,
    _threads,
)

# VF-020E10 persistent alert dispatch fairness (progress-ordered selection).
#
# BOUND. Let M be the number of users with an enabled alert rule, constant between
# runs, and let every run attempt (and commit the progress of) at least n distinct
# users. Each attempt draws a fresh, strictly larger service_seq, so a user attempted
# in this cycle always sorts AFTER every user not yet attempted in it (those hold
# older sequence values or no row, which sorts first). Each run therefore takes the
# n front users of the not-yet-attempted set until it is empty: after k runs at
# least min(M, k*n) distinct users have been attempted, i.e. every user within
# ceil(M / n) runs. The bound counts runs, not wall-clock time (no deadline is
# claimed), needs the progress commit to be durable, and assumes no overlapping
# runs shrink the number of DISTINCT users per run. Users who FAIL are attempted
# too (they move to the back), so the bound holds for attempts; successful
# coverage of a persistently failing user is naturally once per cycle.

CAP2 = DispatcherConfig(max_alert_users=2)


def _users(client: TestClient, count: int) -> list[str]:
    return [_floor_user(client)[0] for _ in range(count)]


def _seq(user_id: str) -> Optional[int]:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT service_seq FROM alert_dispatch_progress WHERE user_id = :u"), {"u": user_id}).scalar()


def _row(user_id: str) -> Optional[dict[str, Any]]:
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT service_seq, last_success_at, consecutive_failures, last_error_code "
            "FROM alert_dispatch_progress WHERE user_id = :u"), {"u": user_id}).mappings().first()
    return dict(row) if row else None


def _snapshot(users: list[str]) -> dict[str, Optional[int]]:
    return {u: _seq(u) for u in users}


def _attempted_since(users: list[str], before: dict[str, Optional[int]]) -> set[str]:
    return {u for u in users if _seq(u) is not None and _seq(u) != before[u]}


# ------------------------------------------------------------------
# The deterministic bound
# ------------------------------------------------------------------


def test_six_users_two_per_run_are_covered_in_exactly_three_runs_in_a_fixed_order(
    client: TestClient, clean_database: None,
) -> None:
    users = sorted(_users(client, 6))
    summaries = []
    served: list[set[str]] = []

    for _ in range(3):
        before = _snapshot(users)
        summaries.append(_run(CAP2))
        served.append(_attempted_since(users, before))

    assert served == [set(users[0:2]), set(users[2:4]), set(users[4:6])]  # never-attempted users by user_id
    assert all(s.alert_selection == "progress" and s.alert_coverage == "deterministic" for s in summaries)
    assert all(_alert_count(u) == 1 for u in users) and all(_row(u)["last_success_at"] for u in users)

    before = _snapshot(users)  # the cycle wraps: least recently attempted first
    _run(CAP2)
    assert _attempted_since(users, before) == set(users[0:2])


@pytest.mark.parametrize(("population", "per_run"), [(6, 2), (7, 3), (5, 5), (9, 4), (4, 1), (3, 10)])
def test_every_user_is_attempted_within_ceil_m_over_n_runs(
    client: TestClient, clean_database: None, population: int, per_run: int,
) -> None:
    users = _users(client, population)

    for _ in range(math.ceil(population / per_run)):
        _run(DispatcherConfig(max_alert_users=per_run))

    assert all(_seq(u) is not None for u in users)
    assert all(_alert_count(u) == 1 for u in users)


def test_repeated_partial_page_interruption_never_loses_the_unprocessed_users(
    client: TestClient, clean_database: None,
) -> None:
    users = sorted(_users(client, 6))
    config = DispatcherConfig(max_alert_users=6, time_budget_seconds=100)
    served: list[set[str]] = []

    for _ in range(3):  # every pass is cut after two users
        before = _snapshot(users)
        summary = _run(config, monotonic=_cut_after(2))
        served.append(_attempted_since(users, before))
        assert summary.budget_exhausted is True and summary.alert_users_evaluated == 2

    assert served == [set(users[0:2]), set(users[2:4]), set(users[4:6])]  # the unprocessed stayed at the front


def test_missed_delayed_and_clockless_ticks_do_not_matter(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    users = _users(client, 6)
    ticks = iter(range(1_000_000, 100_000_000, 7919))  # arbitrary irregular wall-clock jumps
    monkeypatch.setattr(time, "time", lambda: float(next(ticks)))

    for _ in range(3):
        _run(CAP2)
    assert all(_seq(u) is not None for u in users)

    frozen = sorted(_users(client, 4))
    monkeypatch.setattr(time, "time", lambda: 1_000.0)  # the clock never advances
    before = _snapshot(frozen)
    _run(CAP2, monotonic=lambda: 0.0)
    _run(CAP2, monotonic=lambda: 0.0)
    assert _attempted_since(frozen, before) == set(frozen)  # ceil(4/2) runs, order from the sequence alone


def test_users_added_while_the_cycle_is_running_are_served_without_losing_the_rest(
    client: TestClient, clean_database: None,
) -> None:
    original = _users(client, 4)
    _run(CAP2)  # two of the original four attempted
    newcomers = _users(client, 2)  # never attempted: no manual initialization needed
    everyone = original + newcomers

    for _ in range(3):  # six users are now not yet attempted -> ceil(6/2) more runs
        _run(CAP2)

    assert all(_seq(u) is not None for u in everyone)
    assert all(_alert_count(u) == 1 for u in everyone)


def test_disabled_and_removed_users_are_never_processed_and_their_old_state_is_purged(
    client: TestClient, clean_database: None,
) -> None:
    users = _users(client, 4)
    _run(DispatcherConfig(max_alert_users=4))
    leaver = users[0]
    assert _row(leaver) is not None
    with engine.begin() as connection:
        connection.execute(text("UPDATE financial_rules SET status = 'disabled' WHERE user_id = :u"), {"u": leaver})
    alerts_before = _alert_count(leaver)

    summary = _run(DispatcherConfig(max_alert_users=4))

    assert summary.alert_users_considered == 3 and summary.alert_progress_purged == 1
    assert _row(leaver) is None and _alert_count(leaver) == alerts_before  # no processing, no leftover state

    with engine.begin() as connection:  # enabled again: no row, so served first without any initialization
        connection.execute(text("UPDATE financial_rules SET status = 'enabled' WHERE user_id = :u"), {"u": leaver})
    _run(DispatcherConfig(max_alert_users=1))
    assert _row(leaver) is not None and _row(leaver)["last_success_at"] is not None


def test_purge_is_bounded(client: TestClient, clean_database: None) -> None:
    users = _users(client, 3)
    _run(DispatcherConfig(max_alert_users=3))
    with engine.begin() as connection:
        connection.execute(text("UPDATE financial_rules SET status = 'disabled'"))

    with SessionLocal() as session:
        assert progress.purge_stale(session, 2) == 2
        session.commit()
        assert progress.purge_stale(session, 2) == 1
        session.commit()
    assert all(_row(u) is None for u in users)


# ------------------------------------------------------------------
# Failures
# ------------------------------------------------------------------


def _fail_for(monkeypatch: pytest.MonkeyPatch, bad: set[str]) -> None:
    original = rule_alert_service.evaluate_user_alerts

    def selective(session, user_id, on_success=None, on_locked=None):
        if str(user_id) in bad:
            # A failure INSIDE the evaluation: the user lock is held and the attempt
            # identity drawn, exactly like a real evaluation error.
            session.execute(text("SELECT 1"))
            if on_locked is not None:
                on_locked(session)
            session.rollback()
            raise RuntimeError("persistent failure")
        return original(session, user_id, on_success=on_success, on_locked=on_locked)

    monkeypatch.setattr(rule_alert_service, "evaluate_user_alerts", selective)


def test_one_repeatedly_failing_user_never_monopolizes_the_queue(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    users = sorted(_users(client, 4))
    bad = users[0]  # sorts first among the never-attempted: the worst case for monopolizing
    _fail_for(monkeypatch, {bad})
    healthy = users[1:]

    first = _run(CAP2)
    second = _run(CAP2)

    assert first.alert_failures == 1 and second.alert_failures == 0  # the failing user moved to the back
    assert all(_alert_count(u) == 1 for u in healthy)  # all healthy users covered within ceil(4/2) runs
    assert _row(bad)["consecutive_failures"] == 1 and _row(bad)["last_error_code"] == "RuntimeError"
    assert _row(bad)["last_success_at"] is None and _alert_count(bad) == 0
    assert first.outcome == "completed_with_failures" and dispatcher.exit_code_for(first) == 3
    assert second.outcome == "success"

    third = _run(CAP2)  # the cycle wrapped: the failing user is retried once per cycle
    assert third.alert_failures == 1 and _row(bad)["consecutive_failures"] == 2


def test_a_recovered_user_resets_its_failure_state(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    users = sorted(_users(client, 2))
    with monkeypatch.context() as patched:
        _fail_for(patched, {users[0]})
        _run(CAP2)
    assert _row(users[0])["consecutive_failures"] == 1

    _run(CAP2)

    row = _row(users[0])
    assert row["consecutive_failures"] == 0 and row["last_error_code"] is None and row["last_success_at"] is not None


def test_a_database_failure_while_recording_success_rolls_the_alert_back_and_keeps_the_cycle_moving(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    users = sorted(_users(client, 2))

    def broken(*_args, **_kwargs):
        raise OperationalError("INSERT", {}, Exception("connection lost"))

    with monkeypatch.context() as patched:
        patched.setattr(progress, "record_success", broken)
        summary = _run(DispatcherConfig(max_alert_users=1))

    assert summary.alert_failures == 1 and summary.outcome == "completed_with_failures"
    assert _alert_count(users[0]) == 0  # success is atomic with the alert transaction: nothing committed
    assert _row(users[0])["last_success_at"] is None and _row(users[0])["consecutive_failures"] == 1

    _run(DispatcherConfig(max_alert_users=1))  # the other user is served next, then the first is retried
    _run(DispatcherConfig(max_alert_users=1))
    assert _alert_count(users[0]) == 1 and _alert_count(users[1]) == 1


def test_a_failure_that_cannot_even_be_recorded_is_counted_and_the_user_stays_in_front(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    users = sorted(_users(client, 2))
    _fail_for(monkeypatch, {users[0]})

    def cannot_record(*_args, **_kwargs):
        raise OperationalError("INSERT", {}, Exception("connection lost"))

    monkeypatch.setattr(progress, "record_failure", cannot_record)
    summary = _run(DispatcherConfig(max_alert_users=1))

    assert summary.progress_update_failures == 1 and summary.alert_failures == 1
    assert summary.outcome == "completed_with_failures" and _row(users[0]) is None  # still at the very front


def test_a_crash_after_the_successful_commit_leaves_progress_and_alert_together(
    client: TestClient, clean_database: None,
) -> None:
    users = sorted(_users(client, 3))

    with SessionLocal() as session:  # the evaluation commits (alert + progress), then the process "dies"
        seqs: list[int] = []
        rule_alert_service.evaluate_user_alerts(
            session, UUID(users[0]),
            on_locked=lambda s: seqs.append(progress.allocate_attempt_seq(s)),
            on_success=lambda s: progress.record_success(s, UUID(users[0]), seqs[0]),
        )

    assert _alert_count(users[0]) == 1 and _row(users[0])["last_success_at"] is not None  # durable together
    before = _snapshot(users)
    _run(CAP2)
    assert _attempted_since(users, before) == set(users[1:])  # the serviced user is now behind the others
    assert _alert_count(users[0]) == 1  # not duplicated


# ------------------------------------------------------------------
# Concurrency
# ------------------------------------------------------------------


def test_concurrent_dispatchers_never_duplicate_alerts_and_keep_a_unique_order(
    client: TestClient, clean_database: None,
) -> None:
    users = _users(client, 6)

    results = _threads([lambda: _run(DispatcherConfig(max_alert_users=6)) for _ in range(4)])

    assert not [r for r in results if isinstance(r, Exception)], results
    assert all(_alert_count(u) == 1 for u in users)
    seqs = [_seq(u) for u in users]
    assert all(s is not None for s in seqs) and len(set(seqs)) == 6  # a strict total order


def test_a_user_triggered_evaluation_overlapping_cron_creates_one_alert(client: TestClient, clean_database: None) -> None:
    (user,) = _users(client, 1)

    def manual():
        with SessionLocal() as session:
            return rule_alert_service.evaluate_user_alerts(session, UUID(user))

    results = _threads([lambda: _run(DispatcherConfig()), manual, lambda: _run(DispatcherConfig())])

    assert not [r for r in results if isinstance(r, Exception)], results
    assert _alert_count(user) == 1


# ------------------------------------------------------------------
# Schema availability and fallback
# ------------------------------------------------------------------


def test_without_the_progress_table_the_random_fallback_is_used_and_reported_as_probabilistic(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    users = _users(client, 4)
    monkeypatch.setattr(progress, "table_exists", lambda _session: False)

    summary = _run(DispatcherConfig(max_alert_users=2), seed="fallback")

    assert summary.alert_selection == "random" and summary.alert_coverage == "probabilistic"
    assert summary.alert_users_evaluated == 2 and summary.alert_failures == 0
    assert all(_row(u) is None for u in users)  # nothing was written to the progress table


def test_the_progress_mode_can_be_switched_off_as_a_rollback(client: TestClient, clean_database: None) -> None:
    users = _users(client, 3)

    summary = _run(DispatcherConfig(max_alert_users=3, alert_progress="off"), seed="x")

    assert summary.alert_selection == "random" and summary.alert_coverage == "probabilistic"
    assert all(_row(u) is None for u in users) and all(_alert_count(u) == 1 for u in users)


def test_a_genuine_database_error_is_not_mistaken_for_an_absent_progress_schema(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _users(client, 2)

    def down(*_args, **_kwargs):
        raise RuntimeError("could not run the existence check")

    monkeypatch.setattr(progress, "table_exists", down)
    summary = _run(DispatcherConfig())

    assert summary.alert_failures == 1 and summary.alert_selection == "none"
    assert summary.outcome == "completed_with_failures" and dispatcher.exit_code_for(summary) == 3


def test_a_missing_alert_table_skips_alerts_without_touching_progress(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    users = _users(client, 2)
    monkeypatch.setattr(rule_alert_repository, "table_exists", lambda _session: False)

    summary = _run(DispatcherConfig())

    assert summary.alerts_unavailable is True and summary.alert_failures == 0 and summary.alert_selection == "none"
    assert all(_row(u) is None for u in users) and dispatcher.exit_code_for(summary) == 0


def test_the_alert_phase_has_no_financial_side_effects_and_progress_is_tenant_scoped(
    client: TestClient, clean_database: None,
) -> None:
    users = _users(client, 2)
    tables = ("goal_transactions", "account_transactions", "rule_executions", "financial_events", "income")
    counts = {table: scalar(f"SELECT count(*) FROM {table}") for table in tables}
    outsider = "00000000-0000-0000-0000-000000000001"

    _run(DispatcherConfig())

    assert {table: scalar(f"SELECT count(*) FROM {table}") for table in tables} == counts
    assert scalar("SELECT count(*) FROM alert_dispatch_progress") == 2 and _row(outsider) is None
    with SessionLocal() as session:
        assert {str(u) for u in progress.select_next_users(session, 10)} == set(users)


def test_the_selection_order_is_never_attempted_first_then_least_recently_attempted(
    client: TestClient, clean_database: None,
) -> None:
    users = sorted(_users(client, 4))
    with SessionLocal() as session:
        progress.record_success(session, UUID(users[2]), progress.allocate_attempt_seq(session))
        progress.record_success(session, UUID(users[0]), progress.allocate_attempt_seq(session))
        session.commit()

    with SessionLocal() as session:
        order = [str(u) for u in progress.select_next_users(session, 10)]

    assert order == [users[1], users[3], users[2], users[0]]  # never attempted by id, then oldest attempt first


def test_the_progress_table_is_reached_only_through_its_repository() -> None:
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[3] / "app"
    referencing = sorted(
        str(path.relative_to(app_dir.parent))
        for path in app_dir.rglob("*.py")
        if "alert_dispatch_progress" in path.read_text(encoding="utf-8")
    )

    # The model, its registry, the repository that owns every query, and the
    # dispatcher that imports the repository module; no router or API schema.
    assert referencing == [
        "app/db/database_models.py",
        "app/modules/financial_rules/alert_dispatch_progress_models.py",
        "app/modules/financial_rules/alert_dispatch_progress_repository.py",
        "app/modules/financial_rules/dispatcher.py",
    ]
