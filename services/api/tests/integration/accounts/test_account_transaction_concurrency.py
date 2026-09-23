import threading
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from app.db.database_session import SessionLocal
from app.modules.accounts import account_repository, account_service, account_transaction_repository
from app.modules.accounts.account_schemas import AccountCreate
from app.modules.accounts.account_transaction_schemas import AccountTransactionCreate


# Tests the critical concurrency invariant (VF-017B): two simultaneous
# debit adjustment requests against an Account with a 100 EUR opening
# balance, each for 80 EUR, must BOTH succeed - unlike Goal, there is no
# insufficient-funds check to reject either one.
# This test exists to prove SELECT ... FOR UPDATE still correctly
# serializes concurrent writes at the PostgreSQL level even though there
# is no balance validation to protect: the final ledger balance must be
# the exact sum of both debits, never a lost update from one thread's
# write overwriting the other's. It uses two real threads, each with its
# own SQLAlchemy Session/connection, synchronized with a Barrier so both
# requests reach create_account_transaction at essentially the same
# instant.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both debits succeed and the final ledger
#   balance is exactly -60.00 (100 - 80 - 80).
def test_concurrent_debit_adjustments_both_succeed_and_sum_exactly(
    clean_database: None,
) -> None:
    # Arrange: an account with a 100 EUR opening balance.
    setup_session = SessionLocal()
    user_id = uuid4()

    try:
        account = account_repository.create_account(
            db_session=setup_session,
            account_data=AccountCreate(name="Checking", type="checking", currency="EUR"),
            user_id=user_id,
        )
        account_id = account.id

        account_transaction_repository.create_transaction(
            db_session=setup_session,
            account_id=account_id,
            user_id=user_id,
            kind="opening_balance",
            direction="credit",
            amount=Decimal("100.00"),
            transaction_date=date(2026, 9, 1),
            description=None,
        )
    finally:
        setup_session.close()

    barrier = threading.Barrier(2)
    results: dict[str, Optional[str]] = {}
    results_lock = threading.Lock()

    def attempt_debit(thread_name: str) -> None:
        db_session = SessionLocal()

        try:
            barrier.wait(timeout=10)

            account_service.create_account_transaction(
                db_session=db_session,
                account_id=account_id,
                transaction_data=AccountTransactionCreate(
                    direction="debit",
                    amount=Decimal("80.00"),
                    transaction_date=date(2026, 9, 23),
                ),
                user_id=user_id,
            )
            outcome = "succeeded"
        except Exception:
            outcome = "failed"
        finally:
            db_session.close()

        with results_lock:
            results[thread_name] = outcome

    thread_a = threading.Thread(target=attempt_debit, args=("a",))
    thread_b = threading.Thread(target=attempt_debit, args=("b",))

    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    # Assert: both debits succeed - there is no insufficient-funds
    # rejection anywhere in this domain.
    assert results["a"] == "succeeded"
    assert results["b"] == "succeeded"

    verify_session = SessionLocal()

    try:
        ledger_balance = account_transaction_repository.calculate_ledger_balance(
            db_session=verify_session,
            account_id=account_id,
            user_id=user_id,
        )
        assert ledger_balance == Decimal("-60.00")

        transactions = account_transaction_repository.get_transactions_for_account(
            db_session=verify_session,
            account_id=account_id,
            user_id=user_id,
        )
        debit_count = sum(1 for t in transactions if t.direction == "debit")
        assert debit_count == 2
    finally:
        verify_session.close()
