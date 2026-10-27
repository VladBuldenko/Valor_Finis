import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.database_session import SessionLocal, engine
from app.modules.financial_rules import alert_dispatch_progress_repository as progress
from app.modules.financial_rules import dispatcher, rule_alert_repository, rule_alert_service
from app.modules.financial_rules.dispatcher import DispatcherConfig
from app.modules.goals import goal_user_lock
from tests.integration.financial_rules.execution_helpers import scalar
from tests.integration.financial_rules.test_dispatcher import _alert_count, _floor_user, _run, _threads, _tx

# VF-020E10R-02: alert progress consistency.
#
# 1. Timestamps: now() is the transaction START time and wall clocks can step back,
#    so a failed attempt may legitimately carry a timestamp EARLIER than a stored
#    last_success_at. The writers clamp (GREATEST) instead of trusting the clock.
# 2. Ordering: a failure is recorded AFTER the attempt's lock is released, so an
#    older failure could overwrite a newer success. Every attempt draws a sequence
#    value under the user lock and the writers only replace OLDER rows.

ONE = DispatcherConfig(max_alert_users=1)
FUTURE = timedelta(days=2)

# The failure statement exactly as merged in PR #95 (before this correction).
LEGACY_FAILURE_SQL = (
    "INSERT INTO alert_dispatch_progress "
    "(user_id, service_seq, last_attempted_at, last_success_at, consecutive_failures, last_error_code) "
    "VALUES (:user_id, nextval('alert_dispatch_service_seq'), now(), NULL, 1, :code) "
    "ON CONFLICT (user_id) DO UPDATE SET "
    "service_seq = EXCLUDED.service_seq, last_attempted_at = EXCLUDED.last_attempted_at, "
    "consecutive_failures = alert_dispatch_progress.consecutive_failures + 1, "
    "last_error_code = EXCLUDED.last_error_code"
)


def _row(user_id: str) -> Optional[dict[str, Any]]:
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT service_seq, last_attempted_at, last_success_at, consecutive_failures, last_error_code "
            "FROM alert_dispatch_progress WHERE user_id = :u"), {"u": user_id}).mappings().first()
    return dict(row) if row else None


def _seed_future_success(user_id: str) -> datetime:
    """A row whose last success lies in the (relative) future: a clock that later stepped back."""
    future = datetime.now(timezone.utc) + FUTURE
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO alert_dispatch_progress "
            "(user_id, service_seq, last_attempted_at, last_success_at, consecutive_failures) "
            "VALUES (:u, nextval('alert_dispatch_service_seq'), :t, :t, 0)"), {"u": user_id, "t": future})
    return future


def _write(function, user_id: str, *args: Any) -> bool:
    with SessionLocal() as session:
        applied = function(session, UUID(user_id), *args)
        session.commit()
    return applied


def _draw() -> int:
    with SessionLocal() as session:
        seq = progress.allocate_attempt_seq(session)
        session.commit()
    return seq


# ------------------------------------------------------------------
# MEDIUM-1: timestamp invariant
# ------------------------------------------------------------------


def test_the_legacy_failure_statement_violates_the_check_when_the_clock_stepped_back(
    client: TestClient, clean_database: None,
) -> None:
    user_id = _floor_user(client)[0]
    _seed_future_success(user_id)

    with pytest.raises(IntegrityError):  # reproduces the defect: now() < stored last_success_at
        with engine.begin() as connection:
            connection.execute(text(LEGACY_FAILURE_SQL), {"user_id": user_id, "code": "RuntimeError"})


def test_a_failure_with_an_earlier_timestamp_is_recorded_without_violating_the_check(
    client: TestClient, clean_database: None,
) -> None:
    user_id = _floor_user(client)[0]
    future = _seed_future_success(user_id)

    assert _write(progress.record_failure, user_id, _draw(), "RuntimeError") is True

    row = _row(user_id)
    assert row["consecutive_failures"] == 1 and row["last_error_code"] == "RuntimeError"
    assert row["last_success_at"] == future  # success time is preserved, never rewritten
    assert row["last_attempted_at"] >= row["last_success_at"]  # the CHECK stays valid, monotonic


def test_a_success_with_an_earlier_timestamp_is_recorded_and_keeps_both_timestamps_consistent(
    client: TestClient, clean_database: None,
) -> None:
    user_id = _floor_user(client)[0]
    future = _seed_future_success(user_id)

    assert _write(progress.record_success, user_id, _draw()) is True

    row = _row(user_id)
    assert row["last_attempted_at"] >= future and row["last_success_at"] == row["last_attempted_at"]
    assert row["consecutive_failures"] == 0


def test_a_dispatcher_run_survives_a_future_dated_row_and_never_goes_backwards(
    client: TestClient, clean_database: None,
) -> None:
    user_id = _floor_user(client)[0]
    future = _seed_future_success(user_id)

    summary = _run(ONE)

    assert summary.outcome == "success" and summary.alert_users_evaluated == 1
    assert _row(user_id)["last_attempted_at"] >= future and _alert_count(user_id) == 1


# ------------------------------------------------------------------
# MEDIUM-2: stale writes
# ------------------------------------------------------------------


def test_attempt_identities_are_strictly_increasing_and_never_rolled_back() -> None:
    with SessionLocal() as session:
        first = progress.allocate_attempt_seq(session)
        session.rollback()  # nextval survives a rollback: the identity of a failed attempt stays valid

    assert _draw() > first


def test_an_older_failure_never_overwrites_a_newer_success(client: TestClient, clean_database: None) -> None:
    user_id = _floor_user(client)[0]
    older, newer = _draw(), _draw()

    assert _write(progress.record_success, user_id, newer) is True
    assert _write(progress.record_failure, user_id, older, "RuntimeError") is False

    row = _row(user_id)
    assert row["service_seq"] == newer and row["consecutive_failures"] == 0
    assert row["last_error_code"] is None and row["last_success_at"] is not None


def test_an_older_success_never_overwrites_a_newer_failure(client: TestClient, clean_database: None) -> None:
    user_id = _floor_user(client)[0]
    older, newer = _draw(), _draw()

    assert _write(progress.record_failure, user_id, newer, "RuntimeError") is True
    assert _write(progress.record_success, user_id, older) is False

    row = _row(user_id)
    assert row["service_seq"] == newer and row["consecutive_failures"] == 1 and row["last_error_code"] == "RuntimeError"


def test_overlapping_failures_count_each_attempt_once_in_any_arrival_order(
    client: TestClient, clean_database: None,
) -> None:
    user_id = _floor_user(client)[0]
    first, second, third = _draw(), _draw(), _draw()

    assert _write(progress.record_failure, user_id, second, "B") is True
    assert _write(progress.record_failure, user_id, first, "A") is False  # late, older: ignored
    assert _write(progress.record_failure, user_id, third, "C") is True

    row = _row(user_id)
    assert row["service_seq"] == third and row["consecutive_failures"] == 2 and row["last_error_code"] == "C"


def test_a_stale_attempt_followed_by_a_fresh_one_is_recorded_normally(client: TestClient, clean_database: None) -> None:
    user_id = _floor_user(client)[0]
    stale, newer = _draw(), _draw()
    _write(progress.record_success, user_id, newer)
    assert _write(progress.record_failure, user_id, stale, "X") is False

    assert _write(progress.record_failure, user_id, _draw(), "Y") is True  # a fresh attempt is not blocked

    row = _row(user_id)
    assert row["consecutive_failures"] == 1 and row["last_error_code"] == "Y"


def test_forced_interleaving_a_late_failure_cannot_overwrite_a_newer_success(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = _floor_user(client)[0]
    drawn: list[int] = []
    state = {"evaluations": 0, "failure_writes": 0}
    guard = threading.Lock()
    a_paused, b_done = threading.Event(), threading.Event()

    original_fetch = rule_alert_repository.get_enabled_alert_rules
    original_draw = progress.allocate_attempt_seq
    original_failure = progress.record_failure

    def failing_first_evaluation(session, uid):
        with guard:
            state["evaluations"] += 1
            first = state["evaluations"] == 1
        if first:  # A: fails INSIDE the evaluation, after L0 was acquired and its identity drawn
            raise RuntimeError("evaluation failed")
        return original_fetch(session, uid)

    def recording_draw(session):
        seq = original_draw(session)
        drawn.append(seq)
        return seq

    def paused_failure_write(session, uid, seq, code):
        with guard:
            state["failure_writes"] += 1
        a_paused.set()  # A has rolled back, released L0 and is about to write its failure ...
        assert b_done.wait(timeout=60)  # ... but B runs to completion first
        return original_failure(session, uid, seq, code)

    monkeypatch.setattr(rule_alert_repository, "get_enabled_alert_rules", failing_first_evaluation)
    monkeypatch.setattr(progress, "allocate_attempt_seq", recording_draw)
    monkeypatch.setattr(progress, "record_failure", paused_failure_write)

    outcome: dict[str, Any] = {}
    thread_a = threading.Thread(target=lambda: outcome.update(a=_run(ONE)))
    thread_a.start()
    assert a_paused.wait(timeout=60)

    summary_b = _run(ONE)  # B: a complete, successful attempt that commits while A is paused
    b_done.set()
    thread_a.join(timeout=60)
    assert not thread_a.is_alive()

    summary_a = outcome["a"]
    assert len(drawn) == 2 and drawn[0] < drawn[1]  # attempt order == L0 order
    assert summary_b.outcome == "success" and summary_b.alert_users_evaluated == 1

    row = _row(user_id)  # B's success is authoritative
    assert row["service_seq"] == drawn[1] and row["consecutive_failures"] == 0
    assert row["last_error_code"] is None and row["last_success_at"] is not None

    # A's failure is NOT lost for reporting: it is in its run counters and exit code ...
    assert summary_a.alert_failures == 1 and summary_a.outcome == "completed_with_failures"
    assert dispatcher.exit_code_for(summary_a) == 3
    assert summary_a.progress_stale_ignored == 1 and summary_a.progress_update_failures == 0
    # ... and nothing was duplicated or moved
    assert state["failure_writes"] == 1 and _alert_count(user_id) == 1 and _tx(user_id) == 0
    assert scalar("SELECT count(*) FROM goal_transactions WHERE user_id = :u AND rule_execution_id IS NOT NULL",
                  u=user_id) == 0


def test_overlapping_successful_attempts_keep_the_newest_identity_and_one_alert(
    client: TestClient, clean_database: None,
) -> None:
    user_id = _floor_user(client)[0]
    drawn: list[int] = []

    def attempt():
        with SessionLocal() as session:
            return rule_alert_service.evaluate_user_alerts(
                session, UUID(user_id),
                on_locked=lambda s: drawn.append(progress.allocate_attempt_seq(s)),
                on_success=lambda s: progress.record_success(s, UUID(user_id), drawn[-1]),
            )

    results = _threads([attempt, attempt])

    assert all(not isinstance(r, Exception) for r in results)
    assert sorted(drawn) == drawn  # drawn strictly in L0 order: the second attempt started after the first ended
    row = _row(user_id)
    assert row["service_seq"] == max(drawn) and row["consecutive_failures"] == 0 and _alert_count(user_id) == 1


# ------------------------------------------------------------------
# Failure paths around the new identity
# ------------------------------------------------------------------


def test_a_failure_before_the_user_lock_is_held_is_counted_but_not_written_to_progress(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = _floor_user(client)[0]

    def cannot_lock(*_args, **_kwargs):
        raise RuntimeError("lock unavailable")

    monkeypatch.setattr(goal_user_lock, "acquire_goal_user_lock", cannot_lock)
    summary = _run(ONE)

    assert summary.alert_failures == 1 and summary.progress_unordered_failures == 1
    assert summary.outcome == "completed_with_failures" and _row(user_id) is None  # keeps its place at the front


def test_a_failure_inside_the_evaluation_is_recorded_with_its_own_identity(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = _floor_user(client)[0]

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(rule_alert_repository, "get_enabled_alert_rules", boom)
    summary = _run(ONE)

    assert summary.alert_failures == 1 and summary.progress_stale_ignored == 0
    row = _row(user_id)
    assert row["consecutive_failures"] == 1 and row["last_error_code"] == "RuntimeError" and _alert_count(user_id) == 0


def test_a_normal_run_has_no_stale_or_unordered_progress_events(client: TestClient, clean_database: None) -> None:
    user_id = _floor_user(client)[0]

    summary = _run(ONE)

    assert summary.outcome == "success"
    assert summary.progress_stale_ignored == 0 and summary.progress_unordered_failures == 0
    assert _row(user_id)["consecutive_failures"] == 0
