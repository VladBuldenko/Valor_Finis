import threading
from datetime import date
from decimal import Decimal
from typing import Callable, Optional
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database_session import SessionLocal
from app.modules.goals import goal_repository, goal_service, goal_transaction_repository
from app.modules.goals.goal_errors import (
    GoalTransactionClientRequestIdTakenError,
    GoalTransactionIdempotencyConflictError,
)
from app.modules.goals.goal_schemas import GoalCreate
from app.modules.goals.goal_transaction_models import GoalTransactionModel
from app.modules.goals.goal_transaction_schemas import GoalTransactionCreate

# Real-thread concurrency tests for VF-020B3 goal transaction create
# idempotency. Each thread uses its own Session/connection. Barrier-only
# tests release both requests at the same instant and assert every legal
# outcome without claiming which serialization occurred; the forced tests
# gate the first request after its INSERT (row flushed, transaction not
# committed) and release it only once PostgreSQL reports the second request
# blocked on a lock, so one specific path is exercised deterministically.
# Every outcome is mapped to a label; any unexpected exception (a raw
# IntegrityError, a deadlock) becomes "error:<type>", which no test accepts.

AS_OF = date(2026, 10, 5)


def _create_goal(user_id: UUID) -> UUID:
    db_session = SessionLocal()
    try:
        goal = goal_repository.create_goal(
            db_session=db_session,
            goal_data=GoalCreate(name="Vacation", target_amount=Decimal("2000"), currency="EUR"),
            user_id=user_id,
        )
        return goal.id
    finally:
        db_session.close()


def _request(key: UUID, amount: str = "100.00") -> GoalTransactionCreate:
    return GoalTransactionCreate(type="contribution", amount=Decimal(amount), client_request_id=key)


def _create(goal_id: UUID, user_id: UUID, request: GoalTransactionCreate) -> Callable[[Session], str]:
    def run(db_session: Session) -> str:
        try:
            result = goal_service.create_or_replay_goal_transaction(
                db_session=db_session,
                goal_id=goal_id,
                transaction_data=request,
                user_id=user_id,
                as_of=AS_OF,
            )
            return "created" if result.created else "replayed"
        except GoalTransactionIdempotencyConflictError:
            return "conflict"
    return run


def _run_task(name: str, task: Callable[[Session], str], results: dict,
              barrier: Optional[threading.Barrier] = None) -> None:
    db_session = SessionLocal()
    try:
        if barrier is not None:
            barrier.wait(timeout=10)
        outcome = task(db_session)
    except Exception as error:
        outcome = f"error:{type(error).__name__}"
    finally:
        db_session.close()
    results[name] = outcome


def _run_concurrently(tasks: dict) -> dict:
    barrier = threading.Barrier(len(tasks))
    results: dict = {}
    threads = [
        threading.Thread(target=_run_task, args=(name, task, results, barrier), name=name)
        for name, task in tasks.items()
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert set(results) == set(tasks), f"threads did not finish: {results}"
    return results


# Polls pg_stat_activity until some other backend in this database is
# waiting on a lock (the same helper as the goal lifecycle concurrency
# tests).
# Parameters:
# - timeout_seconds: how long to wait.
# Returns:
# - True if a lock waiter was observed.
def _wait_for_lock_waiter(timeout_seconds: float = 10.0) -> bool:
    observed = threading.Event()
    stop = threading.Event()

    def poll() -> None:
        session = SessionLocal()
        try:
            while not stop.is_set():
                waiting = session.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND wait_event_type = 'Lock' "
                        "AND pid <> pg_backend_pid()"
                    )
                ).scalar_one()
                session.rollback()

                if waiting > 0:
                    observed.set()
                    return

                # Event.wait doubles as a short, bounded poll interval.
                stop.wait(0.05)
        finally:
            session.close()

    poller = threading.Thread(target=poll)
    poller.start()
    observed.wait(timeout=timeout_seconds)
    stop.set()
    poller.join(timeout=5)
    return observed.is_set()


# Runs "first" until it has flushed its INSERT (inside its still-open
# transaction), then starts "second", waits until PostgreSQL reports a
# backend blocked on a lock, and only then lets "first" commit.
# Parameters:
# - monkeypatch: pytest fixture used to gate create_transaction.
# - first: task of the request that inserts first.
# - second: task of the request that must wait on it.
# Returns:
# - (outcomes by name, whether a lock waiter was observed, names of the
#   threads whose INSERT hit the client_request_id unique constraint).
def _run_first_inserts_then_second(monkeypatch, first, second):
    original_create_transaction = goal_transaction_repository.create_transaction
    first_inserted = threading.Event()
    release_first = threading.Event()
    unique_violations: list = []

    def gated_create_transaction(**kwargs):
        try:
            model = original_create_transaction(**kwargs)
        except GoalTransactionClientRequestIdTakenError:
            unique_violations.append(threading.current_thread().name)
            raise
        if threading.current_thread().name == "first":
            first_inserted.set()
            assert release_first.wait(timeout=15)
        return model

    monkeypatch.setattr(goal_transaction_repository, "create_transaction", gated_create_transaction)
    results: dict = {}
    first_thread = threading.Thread(target=_run_task, args=("first", first, results), name="first")
    second_thread = threading.Thread(target=_run_task, args=("second", second, results), name="second")

    first_thread.start()
    assert first_inserted.wait(timeout=10), "first request never reached its INSERT"
    second_thread.start()
    lock_waiter_observed = _wait_for_lock_waiter()
    release_first.set()
    first_thread.join(timeout=15)
    second_thread.join(timeout=15)

    assert not first_thread.is_alive() and not second_thread.is_alive()
    return results, lock_waiter_observed, unique_violations


def _row_count(user_id: UUID) -> int:
    db_session = SessionLocal()
    try:
        return (
            db_session.query(GoalTransactionModel)
            .filter(GoalTransactionModel.user_id == user_id)
            .count()
        )
    finally:
        db_session.close()


def _stored_amounts(user_id: UUID) -> list:
    db_session = SessionLocal()
    try:
        return [
            row.amount
            for row in db_session.query(GoalTransactionModel).filter(
                GoalTransactionModel.user_id == user_id,
            )
        ]
    finally:
        db_session.close()


# ------------------------------------------------------------------
# Barrier: both requests released at the same instant
# ------------------------------------------------------------------


# Tests that two identical requests with the same key, started together
# repeatedly, always produce exactly one transaction - one "created" (201)
# and one "replayed" (200) - and never an error.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if each round yields one row.
def test_same_key_same_payload_concurrently_creates_one_row(clean_database: None) -> None:
    user_id = uuid4()
    goal_id = _create_goal(user_id)
    rounds = 5

    for _ in range(rounds):
        request = _request(uuid4())
        results = _run_concurrently({
            "a": _create(goal_id, user_id, request),
            "b": _create(goal_id, user_id, request),
        })
        assert sorted(results.values()) == ["created", "replayed"]

    assert _row_count(user_id) == rounds


# Tests that the same key sent concurrently with two different amounts
# yields one created transaction and one conflict (409), never a second row.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if exactly one row with one of the two amounts exists.
def test_same_key_conflicting_payloads_concurrently_one_row(clean_database: None) -> None:
    user_id = uuid4()
    goal_id = _create_goal(user_id)
    key = uuid4()

    results = _run_concurrently({
        "a": _create(goal_id, user_id, _request(key, "100.00")),
        "b": _create(goal_id, user_id, _request(key, "200.00")),
    })

    assert sorted(results.values()) == ["conflict", "created"]
    assert _stored_amounts(user_id) in ([Decimal("100.00")], [Decimal("200.00")])


# Tests that the same key sent concurrently for two different goals of the
# same user - which share no goal row lock - yields one created transaction
# and one conflict, never a second row or a raw IntegrityError.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if exactly one row exists.
def test_same_key_for_two_goals_concurrently_one_row(clean_database: None) -> None:
    user_id = uuid4()
    first_goal = _create_goal(user_id)
    second_goal = _create_goal(user_id)
    key = uuid4()

    results = _run_concurrently({
        "a": _create(first_goal, user_id, _request(key)),
        "b": _create(second_goal, user_id, _request(key)),
    })

    assert sorted(results.values()) == ["conflict", "created"]
    assert _row_count(user_id) == 1


# Tests that the same key used concurrently by two different users creates
# two independent transactions.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if each user owns one row.
def test_same_key_for_two_users_concurrently_is_independent(clean_database: None) -> None:
    first_user = uuid4()
    second_user = uuid4()
    first_goal = _create_goal(first_user)
    second_goal = _create_goal(second_user)
    key = uuid4()

    results = _run_concurrently({
        "a": _create(first_goal, first_user, _request(key)),
        "b": _create(second_goal, second_user, _request(key)),
    })

    assert results == {"a": "created", "b": "created"}
    assert _row_count(first_user) == 1
    assert _row_count(second_user) == 1


# ------------------------------------------------------------------
# Forced serializations
# ------------------------------------------------------------------


# Tests the second-lookup path: a same-key, same-payload request that found
# nothing in its fast lookup (the first request had not committed yet)
# blocks on the goal row lock, then finds the committed row under the lock
# and resolves as a replay.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to gate create_transaction.
# Returns:
# - None. The test passes if the waiter replays and one row exists.
def test_same_goal_waiter_replays_after_first_commits(
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    goal_id = _create_goal(user_id)
    request = _request(uuid4())

    results, lock_waiter_observed, unique_violations = _run_first_inserts_then_second(
        monkeypatch,
        _create(goal_id, user_id, request),
        _create(goal_id, user_id, request),
    )

    assert lock_waiter_observed, "the second request never blocked on the goal row lock"
    assert results == {"first": "created", "second": "replayed"}
    assert unique_violations == []
    assert _row_count(user_id) == 1


# Tests the same path with a conflicting payload: the waiter finds the
# committed row under the goal lock and resolves as a conflict.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to gate create_transaction.
# Returns:
# - None. The test passes if the waiter conflicts and one row exists.
def test_same_goal_waiter_with_different_payload_conflicts(
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    goal_id = _create_goal(user_id)
    key = uuid4()

    results, lock_waiter_observed, unique_violations = _run_first_inserts_then_second(
        monkeypatch,
        _create(goal_id, user_id, _request(key, "100.00")),
        _create(goal_id, user_id, _request(key, "250.00")),
    )

    assert lock_waiter_observed, "the second request never blocked on the goal row lock"
    assert results == {"first": "created", "second": "conflict"}
    assert unique_violations == []
    assert _stored_amounts(user_id) == [Decimal("100.00")]


# Tests the unique-violation recovery path: a same-key request for ANOTHER
# goal is not serialized by the first goal's row lock, so its INSERT blocks
# on the uncommitted key in uq_goal_transactions_user_id_client_request_id.
# When the first request commits, the second INSERT fails on that
# constraint; the service rolls back, reloads the winner and resolves a
# conflict - no raw IntegrityError reaches the caller.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to gate create_transaction.
# Returns:
# - None. The test passes if the recovery path ran and one row exists.
def test_other_goal_insert_race_recovers_from_unique_violation(
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    first_goal = _create_goal(user_id)
    second_goal = _create_goal(user_id)
    key = uuid4()

    results, lock_waiter_observed, unique_violations = _run_first_inserts_then_second(
        monkeypatch,
        _create(first_goal, user_id, _request(key)),
        _create(second_goal, user_id, _request(key)),
    )

    assert lock_waiter_observed, "the second INSERT never blocked on the uncommitted key"
    assert results == {"first": "created", "second": "conflict"}
    assert unique_violations == ["second"]
    assert _row_count(user_id) == 1
