from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.db.database_session import SessionLocal
from app.modules.accounts import account_repository
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_schemas import AccountCreate
from app.modules.accounts.account_transaction_models import AccountTransactionModel


def _create_account(db_session, user_id) -> AccountModel:
    return account_repository.create_account(
        db_session=db_session,
        account_data=AccountCreate(name="Main Checking", type="checking", currency="EUR"),
        user_id=user_id,
    )


# Tests that a transaction with a positive amount and valid kind/direction
# persists.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the row is persisted with the expected fields.
def test_account_transaction_with_valid_fields_persists(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        transaction = AccountTransactionModel(
            account_id=account.id,
            user_id=user_id,
            kind="adjustment",
            direction="credit",
            amount=Decimal("150.00"),
            transaction_date=date(2026, 9, 23),
            description="Bank fee correction",
        )
        db_session.add(transaction)
        db_session.commit()
        db_session.refresh(transaction)

        assert transaction.id is not None
        assert transaction.account_id == account.id
        assert transaction.user_id == user_id
        assert transaction.kind == "adjustment"
        assert transaction.direction == "credit"
        assert transaction.amount == Decimal("150.00")
        assert transaction.transaction_date == date(2026, 9, 23)
        assert transaction.description == "Bank fee correction"
        assert transaction.created_at is not None
    finally:
        db_session.close()


# Tests that a zero amount is rejected by the amount > 0 CHECK constraint.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_zero_amount_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="adjustment",
                direction="credit",
                amount=Decimal("0.00"),
                transaction_date=date(2026, 9, 23),
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for zero amount"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a negative amount is rejected by the amount > 0 CHECK
# constraint.
# This test exists to prove direction must be carried by the direction
# column, never by sign - identical philosophy to GoalTransaction.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_negative_amount_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="adjustment",
                direction="debit",
                amount=Decimal("-50.00"),
                transaction_date=date(2026, 9, 23),
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for negative amount"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a kind outside the allowed set is rejected.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_invalid_kind_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="income",
                direction="credit",
                amount=Decimal("10.00"),
                transaction_date=date(2026, 9, 23),
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for invalid kind"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a direction outside the allowed set is rejected.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_invalid_direction_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="adjustment",
                direction="sideways",
                amount=Decimal("10.00"),
                transaction_date=date(2026, 9, 23),
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for invalid direction"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a transaction referencing a non-existent account is rejected
# by the foreign key constraint.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_foreign_key_to_account_enforced(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        db_session.add(
            AccountTransactionModel(
                account_id=uuid4(),
                user_id=user_id,
                kind="adjustment",
                direction="credit",
                amount=Decimal("10.00"),
                transaction_date=date(2026, 9, 23),
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for missing account"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that an Account with existing transaction history cannot be
# deleted directly at the database level.
# This test exists to prove the RESTRICT foreign key (not CASCADE) keeps
# financial history from silently disappearing when an Account row is
# deleted.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if deleting the account raises IntegrityError
#   and the transaction row still exists afterward.
def test_account_with_transaction_history_cannot_be_deleted(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        transaction = AccountTransactionModel(
            account_id=account.id,
            user_id=user_id,
            kind="opening_balance",
            direction="credit",
            amount=Decimal("100.00"),
            transaction_date=date(2026, 9, 23),
        )
        db_session.add(transaction)
        db_session.commit()

        try:
            db_session.query(AccountModel).filter(AccountModel.id == account.id).delete()
            db_session.commit()
            assert False, "expected IntegrityError deleting a funded account"
        except IntegrityError:
            db_session.rollback()

        surviving = (
            db_session.query(AccountTransactionModel)
            .filter(AccountTransactionModel.account_id == account.id)
            .all()
        )
        assert len(surviving) == 1
    finally:
        db_session.close()


# Tests that a second opening_balance row for the same account is rejected
# by the partial unique index.
# This test exists to prove "at most one opening_balance per account" is
# enforced at the database level, not only in application code.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing the second row raises
#   IntegrityError.
def test_account_transaction_second_opening_balance_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="opening_balance",
                direction="credit",
                amount=Decimal("100.00"),
                transaction_date=date(2026, 9, 23),
            )
        )
        db_session.commit()

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="opening_balance",
                direction="debit",
                amount=Decimal("50.00"),
                transaction_date=date(2026, 9, 23),
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for second opening_balance row"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that multiple adjustment rows on the same account are allowed
# (only opening_balance is limited to one per account).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both adjustment rows persist successfully.
def test_account_transaction_multiple_adjustments_allowed(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="adjustment",
                direction="credit",
                amount=Decimal("10.00"),
                transaction_date=date(2026, 9, 23),
            )
        )
        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="adjustment",
                direction="debit",
                amount=Decimal("5.00"),
                transaction_date=date(2026, 9, 24),
            )
        )
        db_session.commit()

        rows = (
            db_session.query(AccountTransactionModel)
            .filter(AccountTransactionModel.account_id == account.id)
            .all()
        )
        assert len(rows) == 2
    finally:
        db_session.close()
