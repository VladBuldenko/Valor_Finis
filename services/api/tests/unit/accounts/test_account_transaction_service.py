from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.database_session import SessionLocal
from app.modules.accounts import account_service, account_transaction_repository
from app.modules.accounts.account_errors import AccountArchivedError, AccountNotFoundError
from app.modules.accounts.account_schemas import AccountCreate, AccountUpdate
from app.modules.accounts.account_transaction_schemas import (
    AccountTransactionCreate,
    AccountTransactionResponse,
)


def _create_account(db_session, user_id, opening_balance=None):
    return account_service.create_account(
        db_session=db_session,
        account_data=AccountCreate(
            name="Checking", type="checking", currency="EUR",
            opening_balance=opening_balance,
        ),
        user_id=user_id,
    )


# Tests that a credit adjustment increases the ledger balance.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the balance reflects the credit.
def test_create_account_transaction_credit_increases_balance(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, opening_balance=Decimal("100.00"))

        result = account_service.create_account_transaction(
            db_session=db_session, account_id=account.id,
            transaction_data=AccountTransactionCreate(
                direction="credit", amount=Decimal("50.00"), transaction_date=date(2026, 9, 23),
            ),
            user_id=user_id,
        )

        assert isinstance(result, AccountTransactionResponse)
        assert result.kind == "adjustment"

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("150.00")
    finally:
        db_session.close()


# Tests that a debit adjustment decreases the ledger balance.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the balance reflects the debit.
def test_create_account_transaction_debit_decreases_balance(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, opening_balance=Decimal("100.00"))

        account_service.create_account_transaction(
            db_session=db_session, account_id=account.id,
            transaction_data=AccountTransactionCreate(
                direction="debit", amount=Decimal("30.00"), transaction_date=date(2026, 9, 23),
            ),
            user_id=user_id,
        )

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("70.00")
    finally:
        db_session.close()


# Tests the critical VF-017B invariant: a debit larger than the current
# balance is explicitly ALLOWED, producing a negative balance. This is the
# opposite of Goal's insufficient-funds rule and must never be enforced
# here.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the debit succeeds and the balance is
#   exactly -25.00 (opening 50, debit 75).
def test_create_account_transaction_debit_larger_than_balance_is_allowed(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, opening_balance=Decimal("50.00"))

        result = account_service.create_account_transaction(
            db_session=db_session, account_id=account.id,
            transaction_data=AccountTransactionCreate(
                direction="debit", amount=Decimal("75.00"), transaction_date=date(2026, 9, 23),
            ),
            user_id=user_id,
        )
        assert result.amount == Decimal("75.00")

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("-25.00")
    finally:
        db_session.close()


# Tests that repeated debit adjustments continue to succeed and stack a
# more negative balance, with no floor anywhere in the write path.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the final balance is the exact sum.
def test_create_account_transaction_repeated_debits_no_floor(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        for amount in (Decimal("10.00"), Decimal("20.00"), Decimal("30.00")):
            account_service.create_account_transaction(
                db_session=db_session, account_id=account.id,
                transaction_data=AccountTransactionCreate(
                    direction="debit", amount=amount, transaction_date=date(2026, 9, 23),
                ),
                user_id=user_id,
            )

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("-60.00")
    finally:
        db_session.close()


# Tests that a new adjustment into an archived account is rejected.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if AccountArchivedError is raised.
def test_create_account_transaction_into_archived_account_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        account_service.update_account(
            db_session=db_session, account_id=account.id,
            account_data=AccountUpdate(status="archived"), user_id=user_id,
        )

        with pytest.raises(AccountArchivedError):
            account_service.create_account_transaction(
                db_session=db_session, account_id=account.id,
                transaction_data=AccountTransactionCreate(
                    direction="credit", amount=Decimal("10.00"),
                    transaction_date=date(2026, 9, 23),
                ),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that a new adjustment succeeds again after reactivating a
# previously archived account.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the adjustment succeeds post-reactivation.
def test_create_account_transaction_after_reactivation_succeeds(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        account_service.update_account(
            db_session=db_session, account_id=account.id,
            account_data=AccountUpdate(status="archived"), user_id=user_id,
        )
        account_service.update_account(
            db_session=db_session, account_id=account.id,
            account_data=AccountUpdate(status="active"), user_id=user_id,
        )

        result = account_service.create_account_transaction(
            db_session=db_session, account_id=account.id,
            transaction_data=AccountTransactionCreate(
                direction="credit", amount=Decimal("10.00"), transaction_date=date(2026, 9, 23),
            ),
            user_id=user_id,
        )
        assert result.direction == "credit"
    finally:
        db_session.close()


# Tests that transaction history for an archived account remains fully
# readable.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the pre-existing history is still returned.
def test_archived_account_history_remains_readable(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, opening_balance=Decimal("40.00"))
        account_service.update_account(
            db_session=db_session, account_id=account.id,
            account_data=AccountUpdate(status="archived"), user_id=user_id,
        )

        history = account_service.get_account_transactions(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert len(history) == 1
        assert history[0].kind == "opening_balance"
    finally:
        db_session.close()


# Tests that creating a transaction for a missing/other-user account
# behaves as not found.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if AccountNotFoundError is raised.
def test_create_account_transaction_missing_account_raises_not_found(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        other_account = _create_account(db_session, other_user_id)

        with pytest.raises(AccountNotFoundError):
            account_service.create_account_transaction(
                db_session=db_session, account_id=other_account.id,
                transaction_data=AccountTransactionCreate(
                    direction="credit", amount=Decimal("10.00"),
                    transaction_date=date(2026, 9, 23),
                ),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that reading transaction history for a missing/other-user account
# behaves as not found.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if AccountNotFoundError is raised.
def test_get_account_transactions_missing_account_raises_not_found(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        other_account = _create_account(db_session, other_user_id)

        with pytest.raises(AccountNotFoundError):
            account_service.get_account_transactions(
                db_session=db_session, account_id=other_account.id, user_id=user_id,
            )
    finally:
        db_session.close()
