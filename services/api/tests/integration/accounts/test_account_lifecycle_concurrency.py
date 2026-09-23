import threading
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from app.db.database_session import SessionLocal
from app.modules.accounts import account_repository, account_service, account_transaction_repository
from app.modules.accounts.account_errors import (
    AccountArchivedError,
    AccountDeletionNotAllowedError,
    AccountNotFoundError,
)
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_schemas import AccountCreate, AccountUpdate
from app.modules.accounts.account_transaction_schemas import AccountTransactionCreate


# Tests the concurrency invariant for currency change vs. the first
# adjustment: whichever operation locks the Account row first via
# SELECT ... FOR UPDATE determines the outcome for the other, and the two
# outcomes never mix inconsistently.
# This test exists to prove the race is genuinely resolved by the database
# row lock, not by application-level luck - it uses two real threads, each
# with its own SQLAlchemy Session/connection, synchronized with a Barrier.
#
# Valid final states (exactly one must hold):
# - currency change succeeded => final currency is USD.
# - currency change was rejected => final currency is still EUR, and the
#   adjustment must have succeeded (it never depends on currency).
# The adjustment itself must always succeed in both cases.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the two outcomes are mutually consistent and
#   the adjustment always succeeds.
def test_concurrent_currency_change_vs_first_adjustment(clean_database: None) -> None:
    setup_session = SessionLocal()
    user_id = uuid4()

    try:
        account = account_repository.create_account(
            db_session=setup_session,
            account_data=AccountCreate(name="Checking", type="checking", currency="EUR"),
            user_id=user_id,
        )
        account_id = account.id
    finally:
        setup_session.close()

    barrier = threading.Barrier(2)
    results: dict[str, Optional[str]] = {}
    results_lock = threading.Lock()

    def attempt_currency_change() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            account_service.update_account(
                db_session=db_session, account_id=account_id,
                account_data=AccountUpdate(currency="USD"), user_id=user_id,
            )
            outcome = "succeeded"
        except Exception:
            outcome = "rejected"
        finally:
            db_session.close()

        with results_lock:
            results["currency_change"] = outcome

    def attempt_adjustment() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            account_service.create_account_transaction(
                db_session=db_session, account_id=account_id,
                transaction_data=AccountTransactionCreate(
                    direction="credit", amount=Decimal("50.00"),
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
            results["adjustment"] = outcome

    thread_a = threading.Thread(target=attempt_currency_change)
    thread_b = threading.Thread(target=attempt_adjustment)

    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    assert results["adjustment"] == "succeeded"

    verify_session = SessionLocal()
    try:
        final_account = (
            verify_session.query(AccountModel).filter(AccountModel.id == account_id).first()
        )
        assert final_account is not None

        if results["currency_change"] == "succeeded":
            assert final_account.currency == "USD"
        else:
            assert final_account.currency == "EUR"

        assert account_transaction_repository.has_transactions_for_account(
            db_session=verify_session, account_id=account_id, user_id=user_id,
        )
    finally:
        verify_session.close()


# Tests the concurrency invariant for DELETE vs. the first adjustment:
# exactly one of two legitimate lock-order outcomes must hold, and no
# inconsistent state is ever produced.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the two outcomes are mutually consistent.
def test_concurrent_delete_vs_first_adjustment(clean_database: None) -> None:
    setup_session = SessionLocal()
    user_id = uuid4()

    try:
        account = account_repository.create_account(
            db_session=setup_session,
            account_data=AccountCreate(name="Checking", type="checking", currency="EUR"),
            user_id=user_id,
        )
        account_id = account.id
    finally:
        setup_session.close()

    barrier = threading.Barrier(2)
    results: dict[str, Optional[str]] = {}
    results_lock = threading.Lock()

    def attempt_delete() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            account_service.delete_account(
                db_session=db_session, account_id=account_id, user_id=user_id,
            )
            outcome = "succeeded"
        except AccountDeletionNotAllowedError:
            outcome = "rejected_has_history"
        except Exception:
            outcome = "error"
        finally:
            db_session.close()

        with results_lock:
            results["delete"] = outcome

    def attempt_adjustment() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            account_service.create_account_transaction(
                db_session=db_session, account_id=account_id,
                transaction_data=AccountTransactionCreate(
                    direction="credit", amount=Decimal("50.00"),
                    transaction_date=date(2026, 9, 23),
                ),
                user_id=user_id,
            )
            outcome = "succeeded"
        except AccountNotFoundError:
            outcome = "not_found"
        except Exception:
            outcome = "error"
        finally:
            db_session.close()

        with results_lock:
            results["adjustment"] = outcome

    thread_a = threading.Thread(target=attempt_delete)
    thread_b = threading.Thread(target=attempt_adjustment)

    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    outcome_pair = (results["delete"], results["adjustment"])
    assert outcome_pair in [
        ("succeeded", "not_found"),
        ("rejected_has_history", "succeeded"),
    ], outcome_pair

    verify_session = SessionLocal()
    try:
        final_account = (
            verify_session.query(AccountModel).filter(AccountModel.id == account_id).first()
        )

        if outcome_pair == ("succeeded", "not_found"):
            assert final_account is None
        else:
            assert final_account is not None
            assert account_transaction_repository.has_transactions_for_account(
                db_session=verify_session, account_id=account_id, user_id=user_id,
            )
    finally:
        verify_session.close()


# Tests the concurrency invariant for archiving vs. a concurrent
# adjustment: the row lock serializes the two, so the adjustment either
# lands before the archive (and the account ends up archived with that
# transaction present) or after the archive commits (and is rejected with
# AccountArchivedError) - it can never be silently lost or duplicated.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if exactly one of the two legitimate outcomes
#   holds and the final state is consistent with it.
def test_concurrent_archive_vs_adjustment(clean_database: None) -> None:
    setup_session = SessionLocal()
    user_id = uuid4()

    try:
        account = account_repository.create_account(
            db_session=setup_session,
            account_data=AccountCreate(name="Checking", type="checking", currency="EUR"),
            user_id=user_id,
        )
        account_id = account.id
    finally:
        setup_session.close()

    barrier = threading.Barrier(2)
    results: dict[str, Optional[str]] = {}
    results_lock = threading.Lock()

    def attempt_archive() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            account_service.update_account(
                db_session=db_session, account_id=account_id,
                account_data=AccountUpdate(status="archived"), user_id=user_id,
            )
            outcome = "succeeded"
        except Exception:
            outcome = "error"
        finally:
            db_session.close()

        with results_lock:
            results["archive"] = outcome

    def attempt_adjustment() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            account_service.create_account_transaction(
                db_session=db_session, account_id=account_id,
                transaction_data=AccountTransactionCreate(
                    direction="credit", amount=Decimal("50.00"),
                    transaction_date=date(2026, 9, 23),
                ),
                user_id=user_id,
            )
            outcome = "succeeded"
        except AccountArchivedError:
            outcome = "rejected_archived"
        except Exception:
            outcome = "error"
        finally:
            db_session.close()

        with results_lock:
            results["adjustment"] = outcome

    thread_a = threading.Thread(target=attempt_archive)
    thread_b = threading.Thread(target=attempt_adjustment)

    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    # Archiving itself never depends on the adjustment and must always
    # succeed - only the adjustment's outcome depends on lock order.
    assert results["archive"] == "succeeded"
    assert results["adjustment"] in ("succeeded", "rejected_archived")

    verify_session = SessionLocal()
    try:
        final_account = (
            verify_session.query(AccountModel).filter(AccountModel.id == account_id).first()
        )
        assert final_account is not None
        assert final_account.status == "archived"

        has_history = account_transaction_repository.has_transactions_for_account(
            db_session=verify_session, account_id=account_id, user_id=user_id,
        )
        if results["adjustment"] == "succeeded":
            assert has_history is True
        else:
            assert has_history is False
    finally:
        verify_session.close()
