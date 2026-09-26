import threading
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.db.database_session import SessionLocal
from app.modules.accounts import account_service, account_transaction_repository
from app.modules.accounts.account_schemas import AccountCreate
from app.modules.accounts.account_transaction_models import AccountTransactionModel
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.receipts import receipt_repository, receipt_service
from app.modules.receipts.receipt_errors import ReceiptAlreadyConfirmedError
from app.modules.receipts.receipt_schemas import (
    ReceiptConfirmRequest,
    ReceiptCreate,
    ReceiptUpdate,
)


# Polls pg_stat_activity until some other backend in this database is
# waiting on a heavyweight lock, or the timeout expires.
# This function exists so the test can observe - rather than guess from
# timing - that the second confirmation is genuinely blocked on the
# receipt row lock while the first confirmation still holds it.
# Parameters:
# - timeout_seconds: maximum time to wait.
# Returns:
# - True when a lock-waiting backend was observed, otherwise False.
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


# Creates an active EUR Account with a 100.00 opening balance and a
# processed EUR receipt ready for confirmation.
# Parameters:
# - user_id: owner of both records.
# Returns:
# - (account_id, receipt_id).
def _create_account_and_processed_receipt(user_id: UUID) -> "tuple[UUID, UUID]":
    session = SessionLocal()
    try:
        account = account_service.create_account(
            db_session=session,
            account_data=AccountCreate(
                name="Checking",
                type="checking",
                currency="EUR",
                opening_balance=Decimal("100.00"),
                opening_balance_date=date(2026, 7, 1),
            ),
            user_id=user_id,
        )

        receipt = receipt_repository.create_receipt(
            db_session=session,
            receipt_data=ReceiptCreate(
                storage_path=f"receipts/{user_id}/receipt-1.jpg",
            ),
            user_id=user_id,
        )

        receipt_repository.update_receipt(
            db_session=session,
            receipt_id=receipt.id,
            receipt_data=ReceiptUpdate(
                status="processed",
                merchant_detected="LIDL",
                total_amount_detected=Decimal("24.99"),
                currency_detected="EUR",
                purchase_date_detected=date(2026, 7, 31),
            ),
            user_id=user_id,
        )

        return account.id, receipt.id
    finally:
        session.close()


# Tests that two concurrent confirmations of the SAME processed receipt,
# both linked to the same Account, produce exactly one Expense and one
# debit (VF-017I).
#
# Determinism: create_expense is gated so the first confirmation stops
# AFTER acquiring the receipt row lock and passing the confirmability
# checks, but BEFORE writing anything. The second confirmation is started
# only then, and the test waits until PostgreSQL reports a backend
# blocked on a lock before releasing the first. Without the receipt row
# lock the second confirmation would never block (the lock-waiter
# assertion fails) and would pass the "processed" check, creating a
# second Expense and a second debit.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to gate create_expense.
# Returns:
# - None. The test passes if exactly one confirmation succeeds, the other
#   is rejected as already confirmed, and the ledger shows one debit.
def test_concurrent_linked_confirmations_create_single_expense_and_debit(
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    account_id, receipt_id = _create_account_and_processed_receipt(user_id)

    original_create_expense = receipt_service.expenses_service.create_expense
    first_call_entered = threading.Event()
    release_first_call = threading.Event()
    call_count = [0]
    call_count_lock = threading.Lock()

    def gated_create_expense(**kwargs):
        with call_count_lock:
            call_index = call_count[0]
            call_count[0] += 1

        if call_index == 0:
            first_call_entered.set()
            assert release_first_call.wait(timeout=15)

        return original_create_expense(**kwargs)

    monkeypatch.setattr(
        receipt_service.expenses_service,
        "create_expense",
        gated_create_expense,
    )

    results: dict = {}
    results_lock = threading.Lock()

    def attempt_confirm(name: str) -> None:
        db_session = SessionLocal()
        outcome: Optional[str]
        try:
            receipt_service.confirm_receipt(
                db_session=db_session,
                receipt_id=receipt_id,
                confirmation_data=ReceiptConfirmRequest(account_id=account_id),
                user_id=user_id,
            )
            outcome = "succeeded"
        except ReceiptAlreadyConfirmedError:
            outcome = "already_confirmed"
        except Exception as error:  # pragma: no cover - diagnostic only
            outcome = f"error: {error!r}"
        finally:
            db_session.close()
        with results_lock:
            results[name] = outcome

    thread_first = threading.Thread(target=attempt_confirm, args=("first",))
    thread_second = threading.Thread(target=attempt_confirm, args=("second",))

    try:
        thread_first.start()
        assert first_call_entered.wait(timeout=10), "first confirmation never reached create_expense"

        thread_second.start()
        assert _wait_for_lock_waiter(), (
            "second confirmation was not blocked on the receipt row lock"
        )
    finally:
        release_first_call.set()
        thread_first.join(timeout=20)
        thread_second.join(timeout=20)

    assert results == {"first": "succeeded", "second": "already_confirmed"}
    # The second confirmation was rejected before reaching create_expense.
    assert call_count[0] == 1

    verify_session = SessionLocal()
    try:
        receipt = receipt_repository.get_receipt_by_id(
            db_session=verify_session, receipt_id=receipt_id, user_id=user_id,
        )
        assert receipt.status == "confirmed"
        assert receipt.expense_id is not None

        expenses = (
            verify_session.query(ExpenseModel)
            .filter(ExpenseModel.user_id == user_id)
            .all()
        )
        assert [expense.id for expense in expenses] == [receipt.expense_id]

        expense_transactions = (
            verify_session.query(AccountTransactionModel)
            .filter(
                AccountTransactionModel.account_id == account_id,
                AccountTransactionModel.kind == "expense",
            )
            .all()
        )
        assert len(expense_transactions) == 1
        assert expense_transactions[0].expense_id == receipt.expense_id
        assert expense_transactions[0].direction == "debit"

        assert account_transaction_repository.calculate_ledger_balance(
            db_session=verify_session, account_id=account_id, user_id=user_id,
        ) == Decimal("75.01")
    finally:
        verify_session.close()
