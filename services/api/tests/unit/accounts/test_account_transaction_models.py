from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.database_session import SessionLocal
from app.modules.accounts import account_repository
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_schemas import AccountCreate
from app.modules.accounts.account_transaction_models import AccountTransactionModel
from app.modules.accounts.account_transfer_models import AccountTransferModel
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.income.income_models import IncomeModel


def _create_account(db_session, user_id) -> AccountModel:
    return account_repository.create_account(
        db_session=db_session,
        account_data=AccountCreate(name="Main Checking", type="checking", currency="EUR"),
        user_id=user_id,
    )


def _create_income(db_session, user_id, amount=Decimal("2500.00")) -> IncomeModel:
    income = IncomeModel(
        user_id=user_id,
        amount=amount,
        currency="EUR",
        received_at=date(2026, 9, 23),
        source="salary",
        base_amount=amount,
        base_currency="EUR",
        fx_rate=Decimal("1.00000000"),
        fx_rate_date=date(2026, 9, 23),
        fx_source="identity",
    )
    db_session.add(income)
    db_session.commit()
    db_session.refresh(income)
    return income


def _create_expense(db_session, user_id, amount=Decimal("50.00")) -> ExpenseModel:
    expense = ExpenseModel(
        user_id=user_id,
        category_id=None,
        title="Groceries",
        amount=amount,
        currency="EUR",
        expense_date=date(2026, 9, 23),
        description=None,
        source="manual",
        base_amount=amount,
        base_currency="EUR",
        fx_rate=Decimal("1.00000000"),
        fx_rate_date=date(2026, 9, 23),
        fx_source="identity",
    )
    db_session.add(expense)
    db_session.commit()
    db_session.refresh(expense)
    return expense


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


# Tests that a kind="income" row with income_id set and direction="credit"
# persists - the valid shape of an Income projection.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the row is persisted.
def test_account_transaction_income_kind_valid_shape_persists(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        income = _create_income(db_session, user_id)

        projection = AccountTransactionModel(
            account_id=account.id,
            user_id=user_id,
            kind="income",
            direction="credit",
            amount=Decimal("2500.00"),
            transaction_date=date(2026, 9, 23),
            income_id=income.id,
        )
        db_session.add(projection)
        db_session.commit()
        db_session.refresh(projection)

        assert projection.income_id == income.id
        assert projection.kind == "income"
    finally:
        db_session.close()


# Tests that a kind="income" row is rejected when income_id is NULL.
# This test exists to prove the linkage CHECK, not merely application
# code, enforces that every income-kind row identifies its source.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_income_kind_without_income_id_rejected(
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
                kind="income",
                direction="credit",
                amount=Decimal("100.00"),
                transaction_date=date(2026, 9, 23),
                income_id=None,
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for income kind without income_id"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a kind="income" row is rejected when direction is "debit".
# This test exists to prove the linkage CHECK enforces "every Income
# projection is a credit" at the database level.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_income_kind_debit_direction_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        income = _create_income(db_session, user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="income",
                direction="debit",
                amount=Decimal("100.00"),
                transaction_date=date(2026, 9, 23),
                income_id=income.id,
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for income kind with debit direction"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a direct (opening_balance/adjustment) row is rejected when
# income_id is set.
# This test exists to prove a direct row can never "pretend" to belong to
# an Income - the linkage CHECK's other branch requires income_id NULL
# for both direct kinds.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_direct_kind_with_income_id_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        income = _create_income(db_session, user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="adjustment",
                direction="credit",
                amount=Decimal("100.00"),
                transaction_date=date(2026, 9, 23),
                income_id=income.id,
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for direct kind with income_id set"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a second AccountTransaction row referencing the same
# income_id is rejected.
# This test exists to prove "at most one projection per Income" is
# enforced at the database level via UNIQUE(income_id), not only by
# application code.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing the second row raises
#   IntegrityError.
def test_account_transaction_second_row_same_income_id_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        income = _create_income(db_session, user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="income",
                direction="credit",
                amount=Decimal("100.00"),
                transaction_date=date(2026, 9, 23),
                income_id=income.id,
            )
        )
        db_session.commit()

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="income",
                direction="credit",
                amount=Decimal("50.00"),
                transaction_date=date(2026, 9, 24),
                income_id=income.id,
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for duplicate income_id"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a projection whose user_id does not match the referenced
# Income's own user_id is rejected by the composite ownership foreign key
# - the database-level backstop for cross-user linkage, not merely a
# service-layer check.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_cross_user_income_link_rejected_at_db_level(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        other_users_income = _create_income(db_session, other_user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                # user_id matches the Account (and this row's own
                # ownership), but NOT the referenced Income's user_id -
                # this must violate fk_account_transactions_income_id_user_id.
                user_id=user_id,
                kind="income",
                direction="credit",
                amount=Decimal("100.00"),
                transaction_date=date(2026, 9, 23),
                income_id=other_users_income.id,
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for cross-user income linkage"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a projection whose user_id does not match the referenced
# Account's own user_id is rejected by the composite ownership foreign
# key.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_cross_user_account_link_rejected_at_db_level(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        other_users_account = _create_account(db_session, other_user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=other_users_account.id,
                user_id=user_id,
                kind="adjustment",
                direction="credit",
                amount=Decimal("10.00"),
                transaction_date=date(2026, 9, 23),
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for cross-user account linkage"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a kind="expense" row with expense_id set and
# direction="debit" persists - the valid shape of an Expense projection
# (VF-017E). Exact mirror of the income-kind valid-shape test.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the row is persisted.
def test_account_transaction_expense_kind_valid_shape_persists(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        expense = _create_expense(db_session, user_id)

        projection = AccountTransactionModel(
            account_id=account.id,
            user_id=user_id,
            kind="expense",
            direction="debit",
            amount=Decimal("50.00"),
            transaction_date=date(2026, 9, 23),
            expense_id=expense.id,
        )
        db_session.add(projection)
        db_session.commit()
        db_session.refresh(projection)

        assert projection.expense_id == expense.id
        assert projection.kind == "expense"
        assert projection.income_id is None
    finally:
        db_session.close()


# Tests that a kind="expense" row is rejected when expense_id is NULL.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_expense_kind_without_expense_id_rejected(
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
                kind="expense",
                direction="debit",
                amount=Decimal("100.00"),
                transaction_date=date(2026, 9, 23),
                expense_id=None,
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for expense kind without expense_id"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a kind="expense" row is rejected when direction is "credit".
# This test exists to prove the source-linkage CHECK enforces "every
# Expense projection is a debit" at the database level.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_expense_kind_credit_direction_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        expense = _create_expense(db_session, user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="expense",
                direction="credit",
                amount=Decimal("100.00"),
                transaction_date=date(2026, 9, 23),
                expense_id=expense.id,
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for expense kind with credit direction"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a direct (opening_balance/adjustment) row is rejected when
# expense_id is set.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_direct_kind_with_expense_id_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        expense = _create_expense(db_session, user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="adjustment",
                direction="debit",
                amount=Decimal("100.00"),
                transaction_date=date(2026, 9, 23),
                expense_id=expense.id,
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for direct kind with expense_id set"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a kind="income" row is rejected when expense_id is also set -
# a row must never simultaneously claim to be both an Income and an
# Expense projection.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_income_kind_with_expense_id_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        income = _create_income(db_session, user_id)
        expense = _create_expense(db_session, user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="income",
                direction="credit",
                amount=Decimal("100.00"),
                transaction_date=date(2026, 9, 23),
                income_id=income.id,
                expense_id=expense.id,
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for income kind with expense_id also set"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a kind="expense" row is rejected when income_id is also set -
# the mirror image of the previous test.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_expense_kind_with_income_id_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        income = _create_income(db_session, user_id)
        expense = _create_expense(db_session, user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="expense",
                direction="debit",
                amount=Decimal("100.00"),
                transaction_date=date(2026, 9, 23),
                expense_id=expense.id,
                income_id=income.id,
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for expense kind with income_id also set"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a second AccountTransaction row referencing the same
# expense_id is rejected.
# This test exists to prove "at most one projection per Expense" is
# enforced at the database level via UNIQUE(expense_id).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing the second row raises
#   IntegrityError.
def test_account_transaction_second_row_same_expense_id_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        expense = _create_expense(db_session, user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="expense",
                direction="debit",
                amount=Decimal("100.00"),
                transaction_date=date(2026, 9, 23),
                expense_id=expense.id,
            )
        )
        db_session.commit()

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="expense",
                direction="debit",
                amount=Decimal("50.00"),
                transaction_date=date(2026, 9, 24),
                expense_id=expense.id,
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for duplicate expense_id"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a projection whose user_id does not match the referenced
# Expense's own user_id is rejected by the composite ownership foreign
# key - the database-level backstop for cross-user linkage.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_cross_user_expense_link_rejected_at_db_level(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        other_users_expense = _create_expense(db_session, other_user_id)

        db_session.add(
            AccountTransactionModel(
                account_id=account.id,
                user_id=user_id,
                kind="expense",
                direction="debit",
                amount=Decimal("100.00"),
                transaction_date=date(2026, 9, 23),
                expense_id=other_users_expense.id,
            )
        )

        try:
            db_session.commit()
            assert False, "expected IntegrityError for cross-user expense linkage"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Creates a committed posted AccountTransfer between two fresh EUR
# Accounts owned by user_id (VF-018B) and returns (transfer, source,
# destination). Inserted directly, with no ledger projections - each test
# adds exactly the projection rows it is exercising.
def _create_posted_transfer(db_session, user_id):
    source = _create_account(db_session, user_id)
    destination = _create_account(db_session, user_id)

    transfer = AccountTransferModel(
        user_id=user_id,
        client_request_id=uuid4(),
        source_account_id=source.id,
        destination_account_id=destination.id,
        amount=Decimal("300.00"),
        currency="EUR",
        status="posted",
        planned_date=None,
        effective_date=date(2026, 9, 28),
        posted_at=datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc),
    )
    db_session.add(transfer)
    db_session.commit()
    db_session.refresh(transfer)
    return transfer, source, destination


# Builds an unsaved kind="transfer" AccountTransactionModel for one side of
# the given transfer.
def _transfer_row(transfer, account_id, direction, **overrides) -> AccountTransactionModel:
    values = {
        "account_id": account_id,
        "user_id": transfer.user_id,
        "kind": "transfer",
        "direction": direction,
        "amount": transfer.amount,
        "transaction_date": transfer.effective_date,
        "transfer_id": transfer.id,
    }
    values.update(overrides)
    return AccountTransactionModel(**values)


# Commits a row that must violate a database constraint and asserts the
# commit raises IntegrityError, leaving the session usable afterward.
def _assert_rejected(db_session, row, reason: str) -> None:
    db_session.add(row)

    try:
        db_session.commit()
        assert False, f"expected IntegrityError for {reason}"
    except IntegrityError:
        db_session.rollback()


# Tests that a kind="transfer" debit row with transfer_id set persists -
# the valid shape of a transfer's source-side projection (VF-018B).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the row is persisted.
def test_account_transaction_transfer_debit_row_persists(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        transfer, source, _ = _create_posted_transfer(db_session, user_id)

        row = _transfer_row(transfer, source.id, "debit")
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)

        assert row.kind == "transfer"
        assert row.direction == "debit"
        assert row.transfer_id == transfer.id
        assert row.income_id is None
        assert row.expense_id is None
    finally:
        db_session.close()


# Tests that a kind="transfer" credit row with transfer_id set persists -
# the valid shape of a transfer's destination-side projection. The
# transfer branch of the linkage CHECK must not force a single direction.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the row is persisted.
def test_account_transaction_transfer_credit_row_persists(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        transfer, _, destination = _create_posted_transfer(db_session, user_id)

        row = _transfer_row(transfer, destination.id, "credit")
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)

        assert row.kind == "transfer"
        assert row.direction == "credit"
        assert row.transfer_id == transfer.id
    finally:
        db_session.close()


# Tests that one debit and one credit row for the same transfer are both
# allowed - UNIQUE(transfer_id, direction) permits exactly one of each.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both rows persist.
def test_account_transaction_transfer_debit_and_credit_same_transfer_allowed(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        transfer, source, destination = _create_posted_transfer(db_session, user_id)

        db_session.add_all([
            _transfer_row(transfer, source.id, "debit"),
            _transfer_row(transfer, destination.id, "credit"),
        ])
        db_session.commit()

        rows = (
            db_session.query(AccountTransactionModel)
            .filter(AccountTransactionModel.transfer_id == transfer.id)
            .all()
        )
        assert sorted(row.direction for row in rows) == ["credit", "debit"]
    finally:
        db_session.close()


# Tests that invalid source-linkage combinations involving transfer_id are
# rejected by ck_account_transactions_source_linkage_valid, while existing
# income/expense/direct shapes stay protected.
# Parameters:
# - case: which invalid combination to build.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
@pytest.mark.parametrize(
    "case",
    [
        "transfer_kind_without_transfer_id",
        "transfer_kind_with_income_id",
        "transfer_kind_with_expense_id",
        "income_kind_with_transfer_id",
        "expense_kind_with_transfer_id",
        "direct_kind_with_transfer_id",
    ],
)
def test_account_transaction_invalid_transfer_linkage_rejected(
    case: str, clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        transfer, source, _ = _create_posted_transfer(db_session, user_id)

        if case == "transfer_kind_without_transfer_id":
            row = _transfer_row(transfer, source.id, "debit", transfer_id=None)
        elif case == "transfer_kind_with_income_id":
            income = _create_income(db_session, user_id)
            row = _transfer_row(transfer, source.id, "debit", income_id=income.id)
        elif case == "transfer_kind_with_expense_id":
            expense = _create_expense(db_session, user_id)
            row = _transfer_row(transfer, source.id, "debit", expense_id=expense.id)
        elif case == "income_kind_with_transfer_id":
            income = _create_income(db_session, user_id)
            row = _transfer_row(
                transfer, source.id, "credit", kind="income", income_id=income.id,
            )
        elif case == "expense_kind_with_transfer_id":
            expense = _create_expense(db_session, user_id)
            row = _transfer_row(
                transfer, source.id, "debit", kind="expense", expense_id=expense.id,
            )
        else:
            row = _transfer_row(transfer, source.id, "credit", kind="adjustment")

        _assert_rejected(db_session, row, case)
    finally:
        db_session.close()


# Tests that a second projection with the same direction for the same
# transfer is rejected by uq_account_transactions_transfer_id_direction.
# Parameters:
# - direction: the duplicated direction under test.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the second commit raises IntegrityError.
@pytest.mark.parametrize("direction", ["debit", "credit"])
def test_account_transaction_duplicate_transfer_direction_rejected(
    direction: str, clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        transfer, source, destination = _create_posted_transfer(db_session, user_id)
        account_id = source.id if direction == "debit" else destination.id

        db_session.add(_transfer_row(transfer, account_id, direction))
        db_session.commit()

        _assert_rejected(
            db_session,
            _transfer_row(transfer, account_id, direction),
            f"duplicate {direction} for the same transfer",
        )
    finally:
        db_session.close()


# Tests that a projection whose user_id does not match the referenced
# transfer's user_id is rejected by the composite ownership foreign key
# fk_account_transactions_transfer_id_user_id.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transaction_cross_user_transfer_link_rejected_at_db_level(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        other_users_transfer, _, _ = _create_posted_transfer(db_session, other_user_id)
        own_account = _create_account(db_session, user_id)

        _assert_rejected(
            db_session,
            _transfer_row(
                other_users_transfer, own_account.id, "debit", user_id=user_id,
            ),
            "cross-user transfer linkage",
        )
    finally:
        db_session.close()


# Tests that deleting a transfer removes its ledger projections through
# ON DELETE CASCADE, leaving other ledger rows on the same Accounts intact.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the transfer rows disappear.
def test_account_transaction_transfer_rows_cascade_on_transfer_delete(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        transfer, source, destination = _create_posted_transfer(db_session, user_id)
        adjustment = AccountTransactionModel(
            account_id=source.id,
            user_id=user_id,
            kind="adjustment",
            direction="credit",
            amount=Decimal("1000.00"),
            transaction_date=date(2026, 9, 1),
        )
        db_session.add_all([
            adjustment,
            _transfer_row(transfer, source.id, "debit"),
            _transfer_row(transfer, destination.id, "credit"),
        ])
        db_session.commit()
        adjustment_id = adjustment.id

        db_session.delete(transfer)
        db_session.commit()
        db_session.expire_all()

        remaining = db_session.query(AccountTransactionModel).all()
        assert [row.id for row in remaining] == [adjustment_id]
    finally:
        db_session.close()
