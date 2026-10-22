from datetime import date, timedelta
from typing import Any, Optional
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db.database_session import SessionLocal, engine
from app.modules.financial_events import financial_event_processor as processor
from app.modules.financial_events import financial_event_queue_repository as queue
from app.modules.financial_rules import rule_execution_service
from tests.integration.financial_rules.execution_helpers import (
    enabled_rule,
    funded_account,
    goal_with_target,
    post_income,
    scalar,
)

# VF-020E7 outbox processing tests: strict per-user FIFO (head selected
# before claimability, P52), lease / retry / dead semantics (P82), rollback on
# technical failure and exactly-once through re-delivery. The queue is driven
# through the real drain function against real PostgreSQL; time is moved by
# editing the stored timestamps, never by sleeping.


def _drain(user_id: str, limit: int = 20) -> processor.DrainSummary:
    session = SessionLocal()
    try:
        return processor.drain_user_events(session, UUID(user_id), limit)
    finally:
        session.close()


def _two_events(client: TestClient, user_id: Optional[str] = None) -> tuple[str, str, str]:
    user_id = user_id or str(uuid4())
    account = funded_account(client, user_id, opening="100.00")
    post_income(client, user_id, "10.00", account["id"])
    post_income(client, user_id, "20.00", account["id"])
    first, second = _ids(user_id)
    return user_id, first, second


def _ids(user_id: str) -> list[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id FROM financial_events WHERE user_id = :u AND event_type = 'income.created' "
                 "ORDER BY occurred_at, id"),
            {"u": user_id},
        ).all()
    return [str(row[0]) for row in rows]


def _set(event_id: str, **assignments: Any) -> None:
    columns = ", ".join(f"{name} = {value}" for name, value in assignments.items())
    with engine.begin() as connection:
        connection.execute(text(f"UPDATE financial_events SET {columns} WHERE id = :id"), {"id": event_id})


def _row(event_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        return dict(connection.execute(
            text("SELECT status, attempts, last_error_code, lease_expires_at, next_attempt_at, claim_token "
                 "FROM financial_events WHERE id = :id"),
            {"id": event_id},
        ).mappings().one())


def _status(event_id: str) -> str:
    return _row(event_id)["status"]


def _seconds_until(event_id: str, column: str) -> float:
    return float(scalar(
        f"SELECT EXTRACT(EPOCH FROM ({column} - now())) FROM financial_events WHERE id = :id", id=event_id,
    ))


# ------------------------------------------------------------------
# Strict per-user FIFO (P52)
# ------------------------------------------------------------------


def test_events_are_processed_in_occurred_at_then_id_order(client: TestClient, clean_database: None) -> None:
    user_id, first, second = _two_events(client)

    summary = _drain(user_id, limit=1)

    assert summary.processed == 1
    assert _status(first) == "processed" and _status(second) == "pending"
    assert _drain(user_id).processed == 1
    assert _status(second) == "processed"


def test_live_lease_on_the_head_blocks_newer_events(client: TestClient, clean_database: None) -> None:
    user_id, first, second = _two_events(client)
    _set(first, status="'processing'", attempts="1", claim_token="gen_random_uuid()",
         lease_expires_at="now() + interval '5 minutes'")

    summary = _drain(user_id)

    assert summary.processed == 0 and summary.blocked is True
    assert _status(first) == "processing" and _status(second) == "pending"


def test_waiting_retry_on_the_head_blocks_newer_events(client: TestClient, clean_database: None) -> None:
    user_id, first, second = _two_events(client)
    _set(first, status="'failed_retryable'", attempts="1", next_attempt_at="now() + interval '10 minutes'")

    summary = _drain(user_id)

    assert summary.processed == 0 and summary.blocked is True
    assert _status(first) == "failed_retryable" and _status(second) == "pending"


def test_due_retry_is_claimed_before_newer_events(client: TestClient, clean_database: None) -> None:
    user_id, first, second = _two_events(client)
    _set(first, status="'failed_retryable'", attempts="1", next_attempt_at="now() - interval '1 second'")

    summary = _drain(user_id, limit=1)

    assert summary.processed == 1
    assert _status(first) == "processed" and _row(first)["attempts"] == 2
    assert _status(second) == "pending"


def test_business_date_deferred_event_does_not_block_newer_due_events(
    client: TestClient, clean_database: None,
) -> None:
    user_id, first, second = _two_events(client)
    _set(first, not_before="now() + interval '2 days'")

    summary = _drain(user_id)

    assert summary.processed == 1
    assert _status(first) == "pending" and _status(second) == "processed"

    _set(first, not_before="now() - interval '1 second'")  # the date arrives: normal order again
    assert _drain(user_id).processed == 1 and _status(first) == "processed"


def test_processed_and_dead_events_never_block(client: TestClient, clean_database: None) -> None:
    user_id, first, second = _two_events(client)
    _set(first, status="'dead'", attempts="6", last_error_code="'processing_error'")

    assert _drain(user_id).processed == 1

    assert _status(first) == "dead" and _status(second) == "processed"


def test_other_users_are_independent_of_a_blocked_head(client: TestClient, clean_database: None) -> None:
    user_a, first_a, _ = _two_events(client)
    user_b, first_b, second_b = _two_events(client)
    _set(first_a, status="'processing'", attempts="1", claim_token="gen_random_uuid()",
         lease_expires_at="now() + interval '5 minutes'")

    assert _drain(user_a).processed == 0
    assert _drain(user_b).processed == 2
    assert _status(first_b) == "processed" and _status(second_b) == "processed"


def test_a_claimed_event_that_is_not_the_head_gives_the_attempt_back(
    client: TestClient, clean_database: None,
) -> None:
    user_id, first, second = _two_events(client)
    session = SessionLocal()
    try:
        claim = processor._Claim(event_id=UUID(second), claim_token=uuid4())
        _set(second, status="'processing'", attempts="1", claim_token=f"'{claim.claim_token}'",
             lease_expires_at="now() + interval '5 minutes'")
        outcome = processor._process_claimed(session, UUID(user_id), claim, processor.DrainSummary())
    finally:
        session.close()

    assert outcome == "not_head"
    row = _row(second)
    assert (row["status"], row["attempts"], row["claim_token"], row["lease_expires_at"]) == ("pending", 0, None, None)
    assert _status(first) == "pending"


# ------------------------------------------------------------------
# Lease expiry, reclaim, max attempts
# ------------------------------------------------------------------


def test_expired_lease_is_reclaimed_and_counts_a_new_attempt(client: TestClient, clean_database: None) -> None:
    user_id, first, _ = _two_events(client)
    _set(first, status="'processing'", attempts="2", claim_token="gen_random_uuid()",
         lease_expires_at="now() - interval '1 second'")

    assert _drain(user_id, limit=1).processed == 1

    row = _row(first)
    assert row["status"] == "processed" and row["attempts"] == 3 and row["claim_token"] is None


def test_expired_lease_at_the_last_attempt_becomes_dead_without_a_seventh_attempt(
    client: TestClient, clean_database: None,
) -> None:
    user_id, first, second = _two_events(client)
    _set(first, status="'processing'", attempts="6", claim_token="gen_random_uuid()",
         lease_expires_at="now() - interval '1 second'")

    summary = _drain(user_id)

    row = _row(first)
    assert row["status"] == "dead" and row["attempts"] == 6
    assert row["last_error_code"] == "lease_expired_max_attempts"
    assert row["lease_expires_at"] is None and row["next_attempt_at"] is None
    # Dead no longer blocks: the newer event went through in the same drain.
    assert summary.processed == 1 and _status(second) == "processed"


def test_live_lease_at_the_last_attempt_is_not_touched(client: TestClient, clean_database: None) -> None:
    user_id, first, second = _two_events(client)
    _set(first, status="'processing'", attempts="6", claim_token="gen_random_uuid()",
         lease_expires_at="now() + interval '1 minute'")

    assert _drain(user_id).processed == 0

    assert _status(first) == "processing" and _status(second) == "pending"


# ------------------------------------------------------------------
# Technical failure, retry schedule, rollback
# ------------------------------------------------------------------


@pytest.fixture
def failing_processing(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("injected technical failure")

    monkeypatch.setattr(rule_execution_service, "process_event", fail)


def test_retry_delays_follow_the_contract_and_the_sixth_failure_is_dead(
    client: TestClient, clean_database: None, failing_processing,
) -> None:
    user_id, first, second = _two_events(client)
    expected_minutes = [1, 5, 30, 120, 720]

    for attempt, minutes in enumerate(expected_minutes, start=1):
        summary = _drain(user_id)
        row = _row(first)

        assert summary.failed_retryable == 1 and summary.processed == 0
        assert (row["status"], row["attempts"], row["last_error_code"]) == (
            "failed_retryable", attempt, "processing_error",
        )
        assert row["claim_token"] is None and row["lease_expires_at"] is None
        assert abs(_seconds_until(first, "next_attempt_at") - minutes * 60) < 30
        # Head-of-line: while the retry waits, the newer event is blocked.
        assert _drain(user_id).blocked is True and _status(second) == "pending"

        _set(first, next_attempt_at="now() - interval '1 second'")

    summary = _drain(user_id)
    row = _row(first)
    assert summary.dead == 1
    assert (row["status"], row["attempts"], row["next_attempt_at"]) == ("dead", 6, None)

    # A dead head no longer blocks: with processing healthy again the newer event runs.


def test_dead_head_releases_newer_events_once_processing_recovers(
    client: TestClient, clean_database: None, monkeypatch,
) -> None:
    user_id, first, second = _two_events(client)
    _set(first, status="'failed_retryable'", attempts="5", next_attempt_at="now() - interval '1 second'")
    original = rule_execution_service.process_event
    calls = {"count": 0}

    def fail_first(db_session, user, event):
        calls["count"] += 1
        if str(event.id) == first:
            raise RuntimeError("injected technical failure")
        return original(db_session, user, event)

    monkeypatch.setattr(rule_execution_service, "process_event", fail_first)

    assert _drain(user_id).dead == 1
    assert _status(first) == "dead"
    assert _drain(user_id).processed == 1
    assert _status(second) == "processed"


def test_technical_failure_rolls_back_every_financial_write_and_the_retry_is_exactly_once(
    client: TestClient, clean_database: None, monkeypatch,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goals = [goal_with_target(client, user_id, f"G{i}", 3000) for i in range(3)]
    enabled_rule(
        client, user_id, account["id"], [goal["id"] for goal in goals],
        targets=[{"goal_id": goal["id"], "amount_or_cap": "100.00"} for goal in goals],
    )
    post_income(client, user_id, "10.00", account["id"])
    (event_id,) = _ids(user_id)
    original = rule_execution_service._assert_item_matches_transaction
    seen = {"count": 0}

    def fail_after_two_items(item, execution, transaction):
        original(item, execution, transaction)
        seen["count"] += 1
        if seen["count"] == 2:  # S29: crash after staging writes for two of three targets
            raise RuntimeError("crash mid-execution")

    monkeypatch.setattr(rule_execution_service, "_assert_item_matches_transaction", fail_after_two_items)

    assert _drain(user_id).failed_retryable == 1

    assert scalar("SELECT count(*) FROM rule_executions") == 0
    assert scalar("SELECT count(*) FROM rule_execution_items") == 0
    assert scalar("SELECT count(*) FROM rule_execution_audit") == 0
    assert scalar("SELECT count(*) FROM goal_transactions WHERE rule_execution_id IS NOT NULL") == 0
    assert _status(event_id) == "failed_retryable"

    monkeypatch.setattr(rule_execution_service, "_assert_item_matches_transaction", original)
    _set(event_id, next_attempt_at="now() - interval '1 second'")

    assert _drain(user_id).processed == 1

    assert scalar("SELECT count(*) FROM rule_executions") == 1
    assert scalar("SELECT count(*) FROM rule_execution_items") == 3
    assert scalar("SELECT count(*) FROM goal_transactions WHERE rule_execution_id IS NOT NULL") == 3
    assert _row(event_id)["attempts"] == 2


def test_failure_record_is_conditional_on_the_claim_still_being_ours(
    client: TestClient, clean_database: None,
) -> None:
    user_id, first, _ = _two_events(client)
    token = uuid4()
    _set(first, status="'processing'", attempts="1", claim_token=f"'{token}'",
         lease_expires_at="now() + interval '5 minutes'")
    session = SessionLocal()
    try:
        # A stale worker (its lease expired and another claim replaced it).
        assert queue.record_technical_failure(session, UUID(first), uuid4(), "processing_error") is None
        session.commit()
        assert queue.record_technical_failure(session, UUID(first), token, "processing_error") == "failed_retryable"
        session.commit()
    finally:
        session.close()

    assert _status(first) == "failed_retryable"


@pytest.mark.parametrize(
    ("pgcode", "expected"),
    [("40P01", "deadlock_detected"), ("40001", "serialization_failure"), ("23505", "processing_error")],
)
def test_technical_error_codes_are_classified_without_message_text(pgcode: str, expected: str) -> None:
    class Orig(Exception):
        pass

    orig = Orig("secret detail")
    orig.pgcode = pgcode  # type: ignore[attr-defined]

    assert processor._error_code(OperationalError("SELECT 1", {}, orig)) == expected
    assert processor._error_code(RuntimeError("anything")) == "processing_error"


def test_attempts_never_exceed_six_so_the_check_constraint_is_never_hit(
    client: TestClient, clean_database: None,
) -> None:
    user_id, first, _ = _two_events(client)
    _set(first, status="'pending'", attempts="6")  # impossible state, defended anyway

    _drain(user_id, limit=1)

    row = _row(first)
    assert row["status"] == "dead" and row["attempts"] == 6


def test_manual_requeue_of_a_dead_event_reprocesses_without_a_second_execution(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]])
    post_income(client, user_id, "10.00", account["id"])
    (event_id,) = _ids(user_id)
    assert _drain(user_id).processed == 1
    before = scalar("SELECT count(*) FROM rule_executions")

    with engine.begin() as connection:  # the E1 manual re-queue: dead -> pending, retry cycle reset
        connection.execute(text(
            "UPDATE financial_events SET status = 'pending', attempts = 0, next_attempt_at = NULL, "
            "lease_expires_at = NULL, claim_token = NULL, last_error_code = NULL, processed_at = NULL "
            "WHERE id = :id"), {"id": event_id})

    assert _drain(user_id).processed == 1
    assert scalar("SELECT count(*) FROM rule_executions") == before == 1
    assert scalar("SELECT count(*) FROM goal_transactions WHERE rule_execution_id IS NOT NULL") == 1
    assert date.today() - timedelta(days=1) < date.today()
