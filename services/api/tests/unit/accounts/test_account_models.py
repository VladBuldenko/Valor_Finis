from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.db.database_session import SessionLocal
from app.modules.accounts.account_models import AccountModel


# Tests that an account with valid fields persists.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the row is persisted with the expected fields.
def test_account_with_valid_fields_persists(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = AccountModel(
            user_id=user_id,
            name="Main Checking",
            type="checking",
            currency="EUR",
            status="active",
        )
        db_session.add(account)
        db_session.commit()
        db_session.refresh(account)

        assert account.id is not None
        assert account.user_id == user_id
        assert account.name == "Main Checking"
        assert account.type == "checking"
        assert account.currency == "EUR"
        assert account.status == "active"
        assert account.created_at is not None
        assert account.updated_at is not None
    finally:
        db_session.close()


# Tests that an invalid type is rejected by the type CHECK constraint.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_invalid_type_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        db_session.add(
            AccountModel(
                user_id=user_id,
                name="Card",
                type="credit_card",
                currency="EUR",
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for invalid type"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that every allowed type value is accepted.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if all three rows persist successfully.
def test_account_all_allowed_types_accepted(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        for allowed_type in ("checking", "savings", "cash"):
            db_session.add(
                AccountModel(
                    user_id=user_id,
                    name=f"Account {allowed_type}",
                    type=allowed_type,
                    currency="EUR",
                )
            )
        db_session.commit()

        rows = (
            db_session.query(AccountModel)
            .filter(AccountModel.user_id == user_id)
            .all()
        )
        assert {row.type for row in rows} == {"checking", "savings", "cash"}
    finally:
        db_session.close()


# Tests that an invalid status is rejected by the status CHECK constraint.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_invalid_status_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        db_session.add(
            AccountModel(
                user_id=user_id,
                name="Wallet",
                type="cash",
                currency="EUR",
                status="closed",
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for invalid status"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that status defaults to active when omitted.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the persisted status is "active".
def test_account_status_defaults_to_active(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = AccountModel(
            user_id=user_id,
            name="Wallet",
            type="cash",
            currency="EUR",
        )
        db_session.add(account)
        db_session.commit()
        db_session.refresh(account)

        assert account.status == "active"
    finally:
        db_session.close()


# Tests that duplicate account names for the same user are allowed.
# This test exists because Accounts, unlike Categories, deliberately do
# not enforce name uniqueness - a user may have multiple similarly named
# accounts (e.g. two "Cash" wallets).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both rows persist successfully.
def test_account_duplicate_names_allowed(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        db_session.add(
            AccountModel(user_id=user_id, name="Cash", type="cash", currency="EUR")
        )
        db_session.add(
            AccountModel(user_id=user_id, name="Cash", type="cash", currency="EUR")
        )
        db_session.commit()

        rows = (
            db_session.query(AccountModel)
            .filter(AccountModel.user_id == user_id)
            .all()
        )
        assert len(rows) == 2
    finally:
        db_session.close()


# Tests that AccountModel has no persisted balance column at all.
# This test exists as the definitive invariant for this domain: an
# Account's balance can only ever be computed from account_transactions,
# matching the VF-016G Goal architecture.
# Parameters:
# - None.
# Returns:
# - None. The test passes if "current_balance" is not a mapped column.
def test_account_model_has_no_current_balance_column() -> None:
    column_names = {column.name for column in AccountModel.__table__.columns}

    assert "current_balance" not in column_names
