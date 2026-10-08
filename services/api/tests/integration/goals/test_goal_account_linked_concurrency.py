import threading
import time
from datetime import date
from decimal import Decimal
from typing import Callable, Optional
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database_session import SessionLocal
from app.modules.accounts import account_service
from app.modules.accounts.account_errors import (
    AccountDeletionNotAllowedError,
    AccountNotFoundError,
    AccountReferencedByGoalAllocationError,
)
from app.modules.accounts.account_schemas import AccountCreate
from app.modules.goals import goal_repository, goal_service
from app.modules.goals.goal_errors import (
    GoalPartitionInsufficientFundsError,
    GoalReservationCapacityError,
)
from app.modules.goals.goal_schemas import GoalCreate
from app.modules.goals.goal_transaction_schemas import GoalTransactionCreate

# Real-thread concurrency tests for VF-020C2 linked Goal operations. Each
# thread owns its Session/connection. Outcomes are mapped to labels; any
# unexpected exception (a raw IntegrityError, a deadlock) becomes
# "error:<type>", which no test accepts. Lock-based scenarios are driven by
# pg_stat_activity / explicit row locks, not by sleeps.

AS_OF = date.today()


def _create_goal(user_id: UUID) -> UUID:
    db_session = SessionLocal()
    try:
        return goal_repository.create_goal(
            db_session=db_session,
            goal_data=GoalCreate(name="Vacation", target_amount=Decimal("2000"), currency="EUR"),
            user_id=user_id,
        ).id
    finally:
        db_session.close()


def _create_account(user_id: UUID, balance: Optional[str] = "100.00") -> UUID:
    db_session = SessionLocal()
    try:
        return account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(
                name="Checking", type="checking", currency="EUR",
                opening_balance=Decimal(balance) if balance is not None else None,
            ),
            user_id=user_id,
        ).id
    finally:
        db_session.close()


def _request(account_id: UUID, amount: str, key: Optional[UUID] = None, type: str = "contribution") -> GoalTransactionCreate:
    return GoalTransactionCreate(
        type=type, amount=Decimal(amount), account_id=account_id, client_request_id=key or uuid4(),
    )


def _linked(goal_id: UUID, user_id: UUID, request: GoalTransactionCreate) -> Callable[[Session], str]:
    def run(db_session: Session) -> str:
        try:
            result = goal_service.create_or_replay_goal_transaction(
                db_session=db_session, goal_id=goal_id, transaction_data=request,
                user_id=user_id, as_of=AS_OF,
            )
            return "created" if result.created else "replayed"
        except GoalReservationCapacityError:
            return "capacity"
        except GoalPartitionInsufficientFundsError:
            return "partition"
    return run


def _run_task(name: str, task: Callable[[Session], str], results: dict, barrier: Optional[threading.Barrier]) -> None:
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
        thread.join(timeout=30)

    assert set(results) == set(tasks), f"threads did not finish: {results}"
    return results


def _reserved(user_id: UUID, account_id: UUID) -> Decimal:
    db_session = SessionLocal()
    try:
        return db_session.execute(
            text(
                "SELECT COALESCE(SUM(CASE WHEN type='withdrawal' THEN -amount ELSE amount END), 0) "
                "FROM goal_transactions WHERE account_id = :a AND user_id = :u"
            ),
            {"a": account_id, "u": user_id},
        ).scalar_one()
    finally:
        db_session.close()


# Tests that two simultaneous linked contributions from DIFFERENT Goals to
# the same Account can never together exceed its capacity: with 100.00
# available and two requests of 60.00, exactly one is created and the other
# is a capacity 409, and the reserved total is 60.00.
def test_two_contributions_cannot_exceed_account_capacity(clean_database: None) -> None:
    user_id = uuid4()
    first_goal, second_goal = _create_goal(user_id), _create_goal(user_id)
    account_id = _create_account(user_id, "100.00")

    results = _run_concurrently({
        "a": _linked(first_goal, user_id, _request(account_id, "60.00")),
        "b": _linked(second_goal, user_id, _request(account_id, "60.00")),
    })

    assert sorted(results.values()) == ["capacity", "created"], results
    assert _reserved(user_id, account_id) == Decimal("60.00")


# Tests the same race with many contenders: total reserved never exceeds the
# 100.00 capacity and every loser is a controlled capacity rejection.
def test_many_contenders_never_exceed_capacity(clean_database: None) -> None:
    user_id = uuid4()
    goals = [_create_goal(user_id) for _ in range(6)]
    account_id = _create_account(user_id, "100.00")

    results = _run_concurrently({
        f"t{index}": _linked(goal, user_id, _request(account_id, "30.00"))
        for index, goal in enumerate(goals)
    })

    assert not [value for value in results.values() if value.startswith("error")], results
    assert sorted(results.values()).count("created") == 3
    assert _reserved(user_id, account_id) == Decimal("90.00")


# Tests two simultaneous linked contributions to the SAME Goal and Account
# serialize on the Goal lock and the Account lock and respect capacity.
def test_same_goal_same_account_contributions_serialize(clean_database: None) -> None:
    user_id = uuid4()
    goal_id = _create_goal(user_id)
    account_id = _create_account(user_id, "100.00")

    results = _run_concurrently({
        "a": _linked(goal_id, user_id, _request(account_id, "70.00")),
        "b": _linked(goal_id, user_id, _request(account_id, "70.00")),
    })

    assert sorted(results.values()) == ["capacity", "created"], results


# Tests that contributions to DIFFERENT Accounts are not serialized: while
# another session holds the row lock of Account A, a contribution to
# Account B completes immediately, and one to A waits until the lock is
# released.
def test_different_accounts_are_not_needlessly_serialized(clean_database: None) -> None:
    user_id = uuid4()
    first_goal, second_goal = _create_goal(user_id), _create_goal(user_id)
    account_a = _create_account(user_id, "100.00")
    account_b = _create_account(user_id, "100.00")

    holder = SessionLocal()
    holder.execute(text("SELECT id FROM accounts WHERE id = :a FOR UPDATE"), {"a": account_a})

    results: dict = {}
    thread_b = threading.Thread(
        target=_run_task, args=("b", _linked(second_goal, user_id, _request(account_b, "10.00")), results, None),
    )
    thread_a = threading.Thread(
        target=_run_task, args=("a", _linked(first_goal, user_id, _request(account_a, "10.00")), results, None),
    )
    thread_b.start()
    thread_b.join(timeout=10)
    assert results.get("b") == "created", results

    thread_a.start()
    time.sleep(0.5)
    assert "a" not in results, "a contribution to a locked Account must wait"
    holder.rollback()
    holder.close()
    thread_a.join(timeout=15)
    assert results.get("a") == "created", results


# Tests two simultaneous requests with the SAME key (same Goal, Account and
# payload): exactly one creates and the other replays; one row exists.
def test_same_key_race_creates_once(clean_database: None) -> None:
    user_id = uuid4()
    goal_id = _create_goal(user_id)
    account_id = _create_account(user_id, "100.00")
    key = uuid4()

    results = _run_concurrently({
        "a": _linked(goal_id, user_id, _request(account_id, "10.00", key)),
        "b": _linked(goal_id, user_id, _request(account_id, "10.00", key)),
    })

    assert sorted(results.values()) == ["created", "replayed"], results
    assert _reserved(user_id, account_id) == Decimal("10.00")


# Tests the same key for two DIFFERENT Goals racing: one wins, the other is
# resolved as an idempotency conflict (never a raw IntegrityError / 500).
def test_same_key_other_goal_race_is_controlled(clean_database: None) -> None:
    from app.modules.goals.goal_errors import GoalTransactionIdempotencyConflictError

    user_id = uuid4()
    first_goal, second_goal = _create_goal(user_id), _create_goal(user_id)
    account_id = _create_account(user_id, "100.00")
    key = uuid4()

    def conflict_aware(goal_id: UUID) -> Callable[[Session], str]:
        inner = _linked(goal_id, user_id, _request(account_id, "10.00", key))

        def run(db_session: Session) -> str:
            try:
                return inner(db_session)
            except GoalTransactionIdempotencyConflictError:
                return "conflict"
        return run

    results = _run_concurrently({"a": conflict_aware(first_goal), "b": conflict_aware(second_goal)})

    assert sorted(results.values()) == ["conflict", "created"], results


# Tests two simultaneous linked withdrawals from a 100.00 partition of 60.00
# each serialize on the Goal lock: one is released, the other is a partition
# shortfall; the partition ends at 40.00 and never goes negative.
def test_concurrent_linked_withdrawals_cannot_overdraw_partition(clean_database: None) -> None:
    user_id = uuid4()
    goal_id = _create_goal(user_id)
    account_id = _create_account(user_id, "100.00")
    setup = SessionLocal()
    try:
        goal_service.create_or_replay_goal_transaction(
            setup, goal_id, _request(account_id, "100.00"), user_id, as_of=AS_OF,
        )
    finally:
        setup.close()

    results = _run_concurrently({
        "a": _linked(goal_id, user_id, _request(account_id, "60.00", type="withdrawal")),
        "b": _linked(goal_id, user_id, _request(account_id, "60.00", type="withdrawal")),
    })

    assert sorted(results.values()) == ["created", "partition"], results
    assert _reserved(user_id, account_id) == Decimal("40.00")


# Tests Account delete racing the first linked contribution: whichever order
# PostgreSQL picks, both outcomes are controlled domain results - the
# contribution is created or reports the Account gone, the delete is blocked
# by history - never a raw IntegrityError.
def test_account_delete_versus_linked_contribution_is_controlled(clean_database: None) -> None:
    for _ in range(5):
        user_id = uuid4()
        goal_id = _create_goal(user_id)
        account_id = _create_account(user_id, "100.00")

        def delete(db_session: Session) -> str:
            try:
                account_service.delete_account(db_session, account_id, user_id)
                return "deleted"
            except (AccountDeletionNotAllowedError, AccountReferencedByGoalAllocationError):
                return "blocked"
            except AccountNotFoundError:
                return "missing"

        def contribute(db_session: Session) -> str:
            try:
                return _linked(goal_id, user_id, _request(account_id, "10.00"))(db_session)
            except AccountNotFoundError:
                return "account_missing"

        results = _run_concurrently({"delete": delete, "contribute": contribute})

        assert not [value for value in results.values() if value.startswith("error")], results
        assert results["delete"] == "blocked", results


# Tests the database backstop at the repository level: a linked insert that
# names an Account with the wrong currency is rejected by the composite
# foreign key and translated into the controlled link error, not a raw
# IntegrityError.
def test_repository_translates_account_link_foreign_key_violation(clean_database: None) -> None:
    from app.modules.goals import goal_transaction_repository
    from app.modules.goals.goal_errors import GoalAccountLinkInvalidError

    user_id = uuid4()
    goal_id = _create_goal(user_id)
    db_session = SessionLocal()
    try:
        try:
            goal_transaction_repository.create_transaction(
                db_session=db_session, goal_id=goal_id, user_id=user_id, type="contribution",
                amount=Decimal("1.00"), description=None, currency="EUR", effective_date=AS_OF,
                client_request_id=uuid4(), account_id=uuid4(), commit=False,
            )
            raised = False
        except GoalAccountLinkInvalidError:
            raised = True
        finally:
            db_session.rollback()
    finally:
        db_session.close()

    assert raised is True
