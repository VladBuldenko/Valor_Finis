from uuid import uuid4

import pytest

from app.db.database_session import SessionLocal
from app.modules.accounts import account_repository
from app.modules.accounts.account_errors import AccountNotFoundError
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_schemas import AccountCreate


# Tests that the repository creates a new account in the database.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the created database model contains the
#   expected values.
def test_create_account_creates_new_account(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    account_data = AccountCreate(name="Main Checking", type="checking", currency="EUR")

    try:
        created_account = account_repository.create_account(
            db_session=db_session,
            account_data=account_data,
            user_id=user_id,
        )

        assert isinstance(created_account, AccountModel)
        assert created_account.user_id == user_id
        assert created_account.name == "Main Checking"
        assert created_account.type == "checking"
        assert created_account.currency == "EUR"
        assert created_account.status == "active"
        assert created_account.id is not None
        assert created_account.created_at is not None
        assert created_account.updated_at is not None
    finally:
        db_session.close()


# Tests that the repository returns account records for a specific user.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the requested user's account is
#   returned.
def test_get_accounts_returns_accounts_for_user(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        account_repository.create_account(
            db_session=db_session,
            account_data=AccountCreate(name="Checking", type="checking", currency="EUR"),
            user_id=user_id,
        )
        account_repository.create_account(
            db_session=db_session,
            account_data=AccountCreate(name="Savings", type="savings", currency="EUR"),
            user_id=other_user_id,
        )

        accounts = account_repository.get_accounts(
            db_session=db_session,
            user_id=user_id,
        )

        assert len(accounts) == 1
        assert accounts[0].user_id == user_id
        assert accounts[0].name == "Checking"
    finally:
        db_session.close()


# Tests that get_account_by_id_for_update returns the owned account,
# locked.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the correct AccountModel instance is
#   returned.
def test_get_account_by_id_for_update_returns_owned_account(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        created_account = account_repository.create_account(
            db_session=db_session,
            account_data=AccountCreate(name="Checking", type="checking", currency="EUR"),
            user_id=user_id,
        )

        locked_account = account_repository.get_account_by_id_for_update(
            db_session=db_session,
            account_id=created_account.id,
            user_id=user_id,
        )

        assert locked_account.id == created_account.id
        assert locked_account.user_id == user_id
    finally:
        db_session.close()


# Tests that get_account_by_id_for_update raises AccountNotFoundError for
# a missing or other-user account.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if AccountNotFoundError is raised.
def test_get_account_by_id_for_update_raises_not_found_for_other_user(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        created_account = account_repository.create_account(
            db_session=db_session,
            account_data=AccountCreate(name="Checking", type="checking", currency="EUR"),
            user_id=other_user_id,
        )

        with pytest.raises(AccountNotFoundError):
            account_repository.get_account_by_id_for_update(
                db_session=db_session,
                account_id=created_account.id,
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that get_account_by_id raises AccountNotFoundError for a missing
# account.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if AccountNotFoundError is raised.
def test_get_account_by_id_raises_not_found_for_missing_account(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        with pytest.raises(AccountNotFoundError):
            account_repository.get_account_by_id(
                db_session=db_session,
                account_id=uuid4(),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that AccountModel has no persisted balance column at all.
# This test exists as the definitive invariant: the Account's balance can
# only ever be computed from account_transactions.
# Parameters:
# - None.
# Returns:
# - None. The test passes if "current_balance" is not a mapped column.
def test_account_model_has_no_current_balance_column() -> None:
    column_names = {column.name for column in AccountModel.__table__.columns}

    assert "current_balance" not in column_names
