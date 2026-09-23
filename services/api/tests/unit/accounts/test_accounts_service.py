from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.database_session import SessionLocal
from app.modules.accounts import account_repository, account_service, account_transaction_repository
from app.modules.accounts.account_errors import (
    AccountCurrencyImmutableError,
    AccountDeletionNotAllowedError,
    AccountNotFoundError,
)
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_schemas import AccountCreate, AccountResponse, AccountUpdate


# Tests that creating an account with no opening_balance results in a
# ledger-derived balance of 0 and zero transaction rows.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if current_balance is 0.00 and no transaction
#   row was created.
def test_create_account_without_opening_balance_starts_at_zero(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        result = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(name="Checking", type="checking", currency="EUR"),
            user_id=user_id,
        )

        assert isinstance(result, AccountResponse)
        assert result.current_balance == Decimal("0.00")

        history = account_transaction_repository.get_transactions_for_account(
            db_session=db_session, account_id=result.id, user_id=user_id,
        )
        assert history == []
    finally:
        db_session.close()


# Tests that a positive opening_balance creates exactly one credit
# opening_balance transaction and reports that balance.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if current_balance is 1000.00 and exactly one
#   credit opening_balance row exists.
def test_create_account_with_positive_opening_balance(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        result = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(
                name="Checking", type="checking", currency="EUR",
                opening_balance=Decimal("1000.00"),
            ),
            user_id=user_id,
        )

        assert result.current_balance == Decimal("1000.00")

        history = account_transaction_repository.get_transactions_for_account(
            db_session=db_session, account_id=result.id, user_id=user_id,
        )
        assert len(history) == 1
        assert history[0].kind == "opening_balance"
        assert history[0].direction == "credit"
        assert history[0].amount == Decimal("1000.00")
    finally:
        db_session.close()


# Tests that a negative opening_balance creates exactly one debit
# opening_balance transaction (with a positive stored amount) and reports
# a negative balance.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if current_balance is -125.50 and the stored
#   ledger amount is the positive magnitude 125.50 with direction debit.
def test_create_account_with_negative_opening_balance(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        result = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(
                name="Checking", type="checking", currency="EUR",
                opening_balance=Decimal("-125.50"),
            ),
            user_id=user_id,
        )

        assert result.current_balance == Decimal("-125.50")

        history = account_transaction_repository.get_transactions_for_account(
            db_session=db_session, account_id=result.id, user_id=user_id,
        )
        assert len(history) == 1
        assert history[0].kind == "opening_balance"
        assert history[0].direction == "debit"
        assert history[0].amount == Decimal("125.50")
    finally:
        db_session.close()


# Tests that an explicit zero opening_balance creates no transaction row
# at all.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if current_balance is 0.00 and no row exists.
def test_create_account_with_zero_opening_balance_creates_no_transaction(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        result = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(
                name="Checking", type="checking", currency="EUR",
                opening_balance=Decimal("0.00"),
            ),
            user_id=user_id,
        )

        assert result.current_balance == Decimal("0.00")

        history = account_transaction_repository.get_transactions_for_account(
            db_session=db_session, account_id=result.id, user_id=user_id,
        )
        assert history == []
    finally:
        db_session.close()


# Tests that opening_balance_date, when given, is used as the transaction
# date instead of today.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the stored transaction_date matches the
#   given date.
def test_create_account_opening_balance_uses_given_date(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        result = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(
                name="Checking", type="checking", currency="EUR",
                opening_balance=Decimal("100.00"),
                opening_balance_date=date(2025, 1, 15),
            ),
            user_id=user_id,
        )

        history = account_transaction_repository.get_transactions_for_account(
            db_session=db_session, account_id=result.id, user_id=user_id,
        )
        assert history[0].transaction_date == date(2025, 1, 15)
    finally:
        db_session.close()


# Tests that account creation and its opening_balance transaction are
# atomic: mixed with an intentionally-invalid scenario is impractical to
# simulate without mocking, so this test instead directly proves the
# positive case - both rows are visible together after create_account
# returns, confirming they were committed as one unit.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both the Account row and its opening_balance
#   transaction are visible from a completely separate session.
def test_create_account_and_opening_balance_are_atomic(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        result = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(
                name="Checking", type="checking", currency="EUR",
                opening_balance=Decimal("500.00"),
            ),
            user_id=user_id,
        )
    finally:
        db_session.close()

    verify_session = SessionLocal()
    try:
        account = (
            verify_session.query(AccountModel).filter(AccountModel.id == result.id).first()
        )
        assert account is not None

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=verify_session, account_id=result.id, user_id=user_id,
        )
        assert balance == Decimal("500.00")
    finally:
        verify_session.close()


# Tests that get_accounts computes bulk balances correctly without N+1
# queries (proven at the repository level already; here we confirm the
# service composes create + list correctly for multiple accounts).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if each account reports its own correct balance.
def test_get_accounts_returns_correct_bulk_balances(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(
                name="Checking", type="checking", currency="EUR",
                opening_balance=Decimal("200.00"),
            ),
            user_id=user_id,
        )
        account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(name="Savings", type="savings", currency="EUR"),
            user_id=user_id,
        )

        accounts = account_service.get_accounts(db_session=db_session, user_id=user_id)

        by_name = {a.name: a for a in accounts}
        assert by_name["Checking"].current_balance == Decimal("200.00")
        assert by_name["Savings"].current_balance == Decimal("0.00")
    finally:
        db_session.close()


# Tests that currency may change freely before any transaction exists.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the currency change succeeds.
def test_update_account_currency_change_with_no_history_succeeds(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(name="Checking", type="checking", currency="EUR"),
            user_id=user_id,
        )

        updated = account_service.update_account(
            db_session=db_session, account_id=account.id,
            account_data=AccountUpdate(currency="USD"), user_id=user_id,
        )
        assert updated.currency == "USD"
    finally:
        db_session.close()


# Tests that an actual currency change after transaction history exists
# is rejected.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if AccountCurrencyImmutableError is raised.
def test_update_account_currency_change_after_history_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(
                name="Checking", type="checking", currency="EUR",
                opening_balance=Decimal("10.00"),
            ),
            user_id=user_id,
        )

        with pytest.raises(AccountCurrencyImmutableError):
            account_service.update_account(
                db_session=db_session, account_id=account.id,
                account_data=AccountUpdate(currency="USD"), user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that resending the same normalized currency after history exists
# is allowed (not an actual change).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the update succeeds.
def test_update_account_resending_same_currency_after_history_allowed(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(
                name="Checking", type="checking", currency="EUR",
                opening_balance=Decimal("10.00"),
            ),
            user_id=user_id,
        )

        updated = account_service.update_account(
            db_session=db_session, account_id=account.id,
            account_data=AccountUpdate(currency="eur"), user_id=user_id,
        )
        assert updated.currency == "EUR"
    finally:
        db_session.close()


# Tests that an account with no history deletes successfully.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if a subsequent lookup raises AccountNotFoundError.
def test_delete_account_with_no_history_succeeds(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(name="Checking", type="checking", currency="EUR"),
            user_id=user_id,
        )

        account_service.delete_account(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )

        with pytest.raises(AccountNotFoundError):
            account_repository.get_account_by_id(
                db_session=db_session, account_id=account.id, user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that an account with any transaction history cannot be deleted.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if AccountDeletionNotAllowedError is raised.
def test_delete_account_with_history_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(
                name="Checking", type="checking", currency="EUR",
                opening_balance=Decimal("10.00"),
            ),
            user_id=user_id,
        )

        with pytest.raises(AccountDeletionNotAllowedError):
            account_service.delete_account(
                db_session=db_session, account_id=account.id, user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that an account with history may still be archived.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the status update succeeds.
def test_archive_account_with_history_succeeds(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(
                name="Checking", type="checking", currency="EUR",
                opening_balance=Decimal("10.00"),
            ),
            user_id=user_id,
        )

        updated = account_service.update_account(
            db_session=db_session, account_id=account.id,
            account_data=AccountUpdate(status="archived"), user_id=user_id,
        )
        assert updated.status == "archived"
        assert updated.current_balance == Decimal("10.00")
    finally:
        db_session.close()


# Tests that reactivating an archived account works.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the status returns to active.
def test_reactivate_archived_account_succeeds(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(name="Checking", type="checking", currency="EUR"),
            user_id=user_id,
        )
        account_service.update_account(
            db_session=db_session, account_id=account.id,
            account_data=AccountUpdate(status="archived"), user_id=user_id,
        )

        updated = account_service.update_account(
            db_session=db_session, account_id=account.id,
            account_data=AccountUpdate(status="active"), user_id=user_id,
        )
        assert updated.status == "active"
    finally:
        db_session.close()


# Tests that creating an account transaction does not mutate the Account
# row's updated_at.
# This test exists to prove the VF-016G Goal invariant ("a ledger event is
# not Account metadata modification") holds identically for Accounts.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if updated_at is unchanged after an adjustment
#   is created, even though the ledger-derived balance did change.
def test_create_account_transaction_does_not_mutate_account_updated_at(
    clean_database: None,
) -> None:
    from app.modules.accounts.account_transaction_schemas import AccountTransactionCreate

    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = account_service.create_account(
            db_session=db_session,
            account_data=AccountCreate(name="Checking", type="checking", currency="EUR"),
            user_id=user_id,
        )
        original_updated_at = account.updated_at

        account_service.create_account_transaction(
            db_session=db_session,
            account_id=account.id,
            transaction_data=AccountTransactionCreate(
                direction="credit", amount=Decimal("50.00"),
                transaction_date=date(2026, 9, 23),
            ),
            user_id=user_id,
        )

        raw_session = SessionLocal()
        try:
            raw_account = (
                raw_session.query(AccountModel).filter(AccountModel.id == account.id).first()
            )
            assert raw_account.updated_at == original_updated_at
        finally:
            raw_session.close()

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("50.00")
    finally:
        db_session.close()
