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
    AccountCurrencyImmutableError,
    AccountDeletionNotAllowedError,
    AccountNotFoundError,
    AccountReferencedByGoalAllocationError,
)
from app.modules.accounts.account_schemas import AccountCreate, AccountUpdate
from app.modules.goals import goal_repository, goal_service, goal_transaction_repository
from app.modules.goals.goal_errors import (
    GoalAccountCurrencyMismatchError,
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
        except AccountNotFoundError:
            return "account_missing"
        except GoalAccountCurrencyMismatchError:
            return "currency_mismatch"
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


# ------------------------------------------------------------------
# Deterministic Account-lock races (review fixes)
# ------------------------------------------------------------------


# Polls pg_stat_activity until a backend is blocked on a lock while running
# a statement that reads accounts - i.e. it is queued on an Account ROW lock
# (SELECT ... FROM accounts ... FOR UPDATE), not on anything else.
# Returns:
# - True if such a waiter was observed within the timeout.
def _wait_for_account_row_waiter(timeout_seconds: float = 10.0) -> bool:
    session = SessionLocal()
    try:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            waiting = session.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND pid <> pg_backend_pid() AND query ILIKE '%FROM accounts%'"
                )
            ).scalar_one()
            session.rollback()
            if waiting > 0:
                return True
            time.sleep(0.02)
        return False
    finally:
        session.close()


def _start(name: str, task: Callable[[Session], str], results: dict) -> threading.Thread:
    thread = threading.Thread(target=_run_task, args=(name, task, results, None), name=name)
    thread.start()
    return thread


# Gates ONE named thread right after it inserts its linked GoalTransaction
# (row flushed, Goal and Account locks still held, nothing committed).
def _gate_after_insert(monkeypatch, thread_name: str):
    original = goal_transaction_repository.create_transaction
    inserted, release = threading.Event(), threading.Event()

    def gated(**kwargs):
        model = original(**kwargs)
        if threading.current_thread().name == thread_name:
            inserted.set()
            assert release.wait(timeout=15)
        return model

    monkeypatch.setattr(goal_transaction_repository, "create_transaction", gated)
    return inserted, release


# Gates ONE named thread inside Account update/delete right after it holds
# the Account row lock and has run the linked-history predicate (the lock
# stays held until the thread's transaction ends).
def _gate_in_account_mutation(monkeypatch, thread_name: str):
    original = goal_transaction_repository.has_linked_transactions_for_account
    reached, release = threading.Event(), threading.Event()

    def gated(**kwargs):
        result = original(**kwargs)
        if threading.current_thread().name == thread_name:
            reached.set()
            assert release.wait(timeout=15)
        return result

    monkeypatch.setattr(goal_transaction_repository, "has_linked_transactions_for_account", gated)
    return reached, release


def _account_state(account_id: UUID):
    db_session = SessionLocal()
    try:
        currency = db_session.execute(
            text("SELECT currency FROM accounts WHERE id = :a"), {"a": account_id},
        ).scalar_one_or_none()
        linked_rows = db_session.execute(
            text("SELECT count(*) FROM goal_transactions WHERE account_id = :a"), {"a": account_id},
        ).scalar_one()
        return currency, linked_rows
    finally:
        db_session.close()


def _update_currency(account_id: UUID, user_id: UUID, currency: str) -> Callable[[Session], str]:
    def run(db_session: Session) -> str:
        try:
            account_service.update_account(db_session, account_id, AccountUpdate(currency=currency), user_id)
            return "changed"
        except AccountCurrencyImmutableError:
            return "immutable"
        except AccountReferencedByGoalAllocationError:
            return "referenced"
    return run


# Scenario A - the contribution wins. A funded Account has capacity. The
# contribution inserts its linked row and is held (it owns the Goal and
# Account locks). The currency update starts in another session and is
# proven to be queued on the Account row. Once the contribution commits, the
# update is rejected with the controlled 409 (the Account already has ledger
# history, which takes precedence over the linked-history check), the
# Account keeps its currency and exactly one linked row exists. The thread
# sessions stay usable afterwards.
def test_currency_update_waits_for_linked_contribution_then_is_rejected(
    clean_database: None, monkeypatch,
) -> None:
    user_id = uuid4()
    goal_id = _create_goal(user_id)
    account_id = _create_account(user_id, "100.00")
    inserted, release = _gate_after_insert(monkeypatch, "contribute")
    results: dict = {}

    contribute = _start("contribute", _linked(goal_id, user_id, _request(account_id, "10.00")), results)
    assert inserted.wait(timeout=10), "the contribution never reached its insert"
    update = _start("currency", _update_currency(account_id, user_id, "USD"), results)
    waiter_seen = _wait_for_account_row_waiter()
    assert "currency" not in results, "the update must not finish while the Account row is locked"
    release.set()
    contribute.join(timeout=15)
    update.join(timeout=15)

    assert waiter_seen, "the currency update was never observed waiting on the Account row"
    assert results == {"contribute": "created", "currency": "immutable"}
    assert _account_state(account_id) == ("EUR", 1)

    follow_up = SessionLocal()
    try:
        assert follow_up.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        follow_up.close()


# Scenario A2 - the linked-history check is the deciding rule. An Account
# without ledger history gets a linked row through a direct fixture insert
# (a legacy-shaped state the service itself cannot create); the currency
# update must then be rejected by the linked-history rule, not by ledger
# history.
def test_currency_update_rejected_by_linked_history_alone(clean_database: None) -> None:
    user_id = uuid4()
    goal_id = _create_goal(user_id)
    account_id = _create_account(user_id, None)
    db_session = SessionLocal()
    try:
        db_session.execute(
            text(
                "INSERT INTO goal_transactions (id, goal_id, user_id, type, amount, currency, effective_date, "
                "client_request_id, account_id, created_at) VALUES (gen_random_uuid(), :g, :u, 'contribution', 5, "
                "'EUR', current_date, gen_random_uuid(), :a, now())"
            ),
            {"g": goal_id, "u": user_id, "a": account_id},
        )
        db_session.commit()
    finally:
        db_session.close()

    results: dict = {}
    _start("currency", _update_currency(account_id, user_id, "USD"), results).join(timeout=15)

    assert results == {"currency": "referenced"}
    assert _account_state(account_id) == ("EUR", 1)


# Scenario B - the currency change wins. An Account with no ledger history
# is being changed to USD; its transaction holds the Account row lock. A
# linked contribution (capacity is made irrelevant by the currency rule
# coming first) starts, passes the Goal lock and is proven to be queued on
# the Account row. When the change commits, the contribution re-reads the
# USD Account and fails with the controlled currency mismatch (422); no
# linked row is committed.
def test_linked_contribution_after_currency_change_is_controlled_mismatch(
    clean_database: None, monkeypatch,
) -> None:
    user_id = uuid4()
    goal_id = _create_goal(user_id)
    account_id = _create_account(user_id, None)
    reached, release = _gate_in_account_mutation(monkeypatch, "currency")
    results: dict = {}

    update = _start("currency", _update_currency(account_id, user_id, "USD"), results)
    assert reached.wait(timeout=10), "the currency update never took the Account lock"
    contribute = _start("contribute", _linked(goal_id, user_id, _request(account_id, "10.00")), results)
    waiter_seen = _wait_for_account_row_waiter()
    assert "contribute" not in results
    release.set()
    update.join(timeout=15)
    contribute.join(timeout=15)

    assert waiter_seen, "the contribution was never observed waiting on the Account row"
    assert results == {"currency": "changed", "contribute": "currency_mismatch"}
    assert _account_state(account_id) == ("USD", 0)


# Account delete vs the first linked contribution, constructed so the
# ledger-history precheck cannot decide the outcome: the Account has NO
# ledger rows (the capacity check is bypassed in the test only, to let a
# contribution reach the insert for such an Account). The linked-history /
# row-lock path is therefore the only protection.
#
# Order 1 - the contribution wins: it inserts and is held with the Account
# lock; the delete waits on the Account row, then is rejected with the
# controlled 409 (linked history). The Account survives with one linked row.
def test_delete_waits_for_linked_contribution_then_is_blocked_by_linked_history(
    clean_database: None, monkeypatch,
) -> None:
    monkeypatch.setattr(
        account_service, "get_reservable_amount", lambda **kwargs: Decimal("1000.00"),
    )
    user_id = uuid4()
    goal_id = _create_goal(user_id)
    account_id = _create_account(user_id, None)
    inserted, release = _gate_after_insert(monkeypatch, "contribute")
    results: dict = {}

    def delete(db_session: Session) -> str:
        try:
            account_service.delete_account(db_session, account_id, user_id)
            return "deleted"
        except AccountReferencedByGoalAllocationError:
            return "referenced"
        except AccountDeletionNotAllowedError:
            return "ledger_history"

    contribute = _start("contribute", _linked(goal_id, user_id, _request(account_id, "10.00")), results)
    assert inserted.wait(timeout=10)
    deleter = _start("delete", delete, results)
    waiter_seen = _wait_for_account_row_waiter()
    assert "delete" not in results
    release.set()
    contribute.join(timeout=15)
    deleter.join(timeout=15)

    assert waiter_seen
    assert results == {"contribute": "created", "delete": "referenced"}
    assert _account_state(account_id) == ("EUR", 1)


# Order 2 - the delete wins: it holds the Account row lock (gated right after
# the linked-history predicate found nothing); the contribution is queued on
# the Account row. After the delete commits, the contribution gets the
# controlled Account-not-found; no linked row exists and the Account is gone
# (no deleted Account with a linked GoalTransaction, no raw FK error).
def test_linked_contribution_after_account_delete_is_account_not_found(
    clean_database: None, monkeypatch,
) -> None:
    monkeypatch.setattr(
        account_service, "get_reservable_amount", lambda **kwargs: Decimal("1000.00"),
    )
    user_id = uuid4()
    goal_id = _create_goal(user_id)
    account_id = _create_account(user_id, None)
    reached, release = _gate_in_account_mutation(monkeypatch, "delete")
    results: dict = {}

    def delete(db_session: Session) -> str:
        try:
            account_service.delete_account(db_session, account_id, user_id)
            return "deleted"
        except AccountReferencedByGoalAllocationError:
            return "referenced"

    deleter = _start("delete", delete, results)
    assert reached.wait(timeout=10), "the delete never took the Account lock"
    contribute = _start("contribute", _linked(goal_id, user_id, _request(account_id, "10.00")), results)
    waiter_seen = _wait_for_account_row_waiter()
    assert "contribute" not in results
    release.set()
    deleter.join(timeout=15)
    contribute.join(timeout=15)

    assert waiter_seen
    assert results == {"delete": "deleted", "contribute": "account_missing"}
    assert _account_state(account_id) == (None, 0)
