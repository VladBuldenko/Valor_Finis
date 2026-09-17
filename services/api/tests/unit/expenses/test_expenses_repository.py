from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.database_session import SessionLocal
from app.modules.expenses import expenses_repository
from app.modules.expenses.expenses_errors import ExpenseNotFoundError
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.expenses.expenses_schemas import ExpenseCreate, ExpenseUpdate


# Default identity FX snapshot kwargs shared by every create_expense() call
# in this file. This file tests pure persistence, not FX correctness (that
# is covered by tests/unit/fx and tests/unit/expenses/test_expenses_service.py),
# so every fixture here uses a plain EUR identity snapshot.
def _identity_snapshot_kwargs(amount: Decimal, expense_date: date) -> dict:
    return {
        "base_amount": amount,
        "base_currency": "EUR",
        "fx_rate": Decimal("1"),
        "fx_rate_date": expense_date,
        "fx_source": "identity",
    }


# Tests that the repository creates a new expense in the database.
# This test exists to verify that expense data and authenticated user id are converted into ExpenseModel and persisted through SQLAlchemy.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the created database model contains the expected values.
def test_create_expense_creates_new_expense(clean_database: None) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    expense_data = ExpenseCreate(
        category_id=None,
        title="Lidl groceries",
        amount=Decimal("24.99"),
        currency="EUR",
        expense_date=date(2026, 5, 7),
        description="Milk, bread and fruits",
        source="manual",
    )

    try:
        # Act
        created_expense = expenses_repository.create_expense(
            db_session=db_session,
            expense_data=expense_data,
            user_id=user_id,
            **_identity_snapshot_kwargs(expense_data.amount, expense_data.expense_date),
        )

        # Assert
        assert isinstance(created_expense, ExpenseModel)
        assert created_expense.user_id == user_id
        assert created_expense.category_id is None
        assert created_expense.title == expense_data.title
        assert created_expense.amount == Decimal("24.99")
        assert created_expense.currency == expense_data.currency
        assert created_expense.expense_date == expense_data.expense_date
        assert created_expense.description == expense_data.description
        assert created_expense.source == expense_data.source
        assert created_expense.id is not None
        assert created_expense.created_at is not None
        assert created_expense.updated_at is not None
        assert created_expense.base_amount == Decimal("24.99")
        assert created_expense.base_currency == "EUR"
        assert created_expense.fx_rate == Decimal("1.00000000")
        assert created_expense.fx_rate_date == expense_data.expense_date
        assert created_expense.fx_source == "identity"
    finally:
        db_session.close()


# Tests that the repository persists all five FX snapshot fields together,
# using a non-identity (foreign-currency-shaped) snapshot.
# This test exists to verify the repository stores exactly what it is
# given, independent of whether the snapshot happens to be identity.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if all five snapshot fields round-trip exactly.
def test_create_expense_persists_foreign_currency_snapshot(clean_database: None) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    expense_data = ExpenseCreate(
        category_id=None,
        title="NYC taxi",
        amount=Decimal("40.00"),
        currency="USD",
        expense_date=date(2026, 5, 7),
        description=None,
        source="manual",
    )

    try:
        # Act
        created_expense = expenses_repository.create_expense(
            db_session=db_session,
            expense_data=expense_data,
            user_id=user_id,
            base_amount=Decimal("34.69"),
            base_currency="EUR",
            fx_rate=Decimal("0.86730000"),
            fx_rate_date=date(2026, 5, 6),
            fx_source="ecb",
        )

        # Assert
        assert created_expense.base_amount == Decimal("34.69")
        assert created_expense.base_currency == "EUR"
        assert created_expense.fx_rate == Decimal("0.86730000")
        assert created_expense.fx_rate_date == date(2026, 5, 6)
        assert created_expense.fx_source == "ecb"
    finally:
        db_session.close()


# Tests that the repository returns expense records for a specific user.
# This test exists to verify that users only receive their own expenses from the repository layer.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the requested user's expense is returned.
def test_get_expenses_returns_expenses_for_user(clean_database: None) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    user_expense_data = ExpenseCreate(
        category_id=None,
        title="Lidl groceries",
        amount=Decimal("24.99"),
        currency="EUR",
        expense_date=date(2026, 5, 7),
        description="Milk, bread and fruits",
        source="manual",
    )

    other_user_expense_data = ExpenseCreate(
        category_id=None,
        title="Train ticket",
        amount=Decimal("12.50"),
        currency="EUR",
        expense_date=date(2026, 5, 8),
        description="Munich transport",
        source="manual",
    )

    try:
        expenses_repository.create_expense(
            db_session=db_session,
            expense_data=user_expense_data,
            user_id=user_id,
            **_identity_snapshot_kwargs(
                user_expense_data.amount, user_expense_data.expense_date,
            ),
        )
        expenses_repository.create_expense(
            db_session=db_session,
            expense_data=other_user_expense_data,
            user_id=other_user_id,
            **_identity_snapshot_kwargs(
                other_user_expense_data.amount, other_user_expense_data.expense_date,
            ),
        )

        # Act
        expenses = expenses_repository.get_expenses(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert len(expenses) == 1
        assert isinstance(expenses[0], ExpenseModel)
        assert expenses[0].user_id == user_id
        assert expenses[0].title == user_expense_data.title
        assert expenses[0].amount == Decimal("24.99")
        assert expenses[0].currency == user_expense_data.currency
        assert expenses[0].expense_date == user_expense_data.expense_date
        assert expenses[0].description == user_expense_data.description
        assert expenses[0].source == user_expense_data.source
    finally:
        db_session.close()


# Tests that get_expenses_in_date_range (VF-015B) includes expenses exactly
# on the inclusive start/end boundaries, excludes anything outside them, and
# stays scoped to the requesting user.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the in-range, same-user expenses return.
def test_get_expenses_in_date_range_includes_boundaries_excludes_outside_and_other_user(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    def _create(user, expense_date, title):
        data = ExpenseCreate(
            category_id=None, title=title, amount=Decimal("10.00"), currency="EUR",
            expense_date=expense_date, description=None, source="manual",
        )
        expenses_repository.create_expense(
            db_session=db_session, expense_data=data, user_id=user,
            **_identity_snapshot_kwargs(data.amount, data.expense_date),
        )

    try:
        _create(user_id, date(2026, 8, 31), "Before range")  # excluded
        _create(user_id, date(2026, 9, 1), "Exact start")  # included
        _create(user_id, date(2026, 9, 15), "Inside range")  # included
        _create(user_id, date(2026, 9, 30), "Exact end")  # included
        _create(user_id, date(2026, 10, 1), "After range")  # excluded
        _create(other_user_id, date(2026, 9, 15), "Other user in range")  # excluded

        # Act
        expenses = expenses_repository.get_expenses_in_date_range(
            db_session=db_session,
            user_id=user_id,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        )

        # Assert
        titles = {expense.title for expense in expenses}
        assert titles == {"Exact start", "Inside range", "Exact end"}
        assert all(expense.user_id == user_id for expense in expenses)
    finally:
        db_session.close()


# Tests that the repository updates an existing expense owned by the user,
# including its FX snapshot fields.
# This test exists to verify that only the provided original fields are
# changed and persisted, while the caller-supplied snapshot values are
# always written (the service layer decides what those should be).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the updated fields are persisted and unset fields are unchanged.
def test_update_expense_updates_expense_fields(clean_database: None) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    expense_data = ExpenseCreate(
        category_id=None,
        title="Lidl groceries",
        amount=Decimal("24.99"),
        currency="EUR",
        expense_date=date(2026, 5, 7),
        description="Milk, bread and fruits",
        source="manual",
    )

    try:
        created_expense = expenses_repository.create_expense(
            db_session=db_session,
            expense_data=expense_data,
            user_id=user_id,
            **_identity_snapshot_kwargs(expense_data.amount, expense_data.expense_date),
        )

        update_data = ExpenseUpdate(
            title="Rewe groceries",
            amount=Decimal("31.20"),
        )

        # Act
        updated_expense = expenses_repository.update_expense(
            db_session=db_session,
            expense_id=created_expense.id,
            expense_data=update_data,
            user_id=user_id,
            base_amount=Decimal("31.20"),
            base_currency="EUR",
            fx_rate=Decimal("1"),
            fx_rate_date=expense_data.expense_date,
            fx_source="identity",
        )

        # Assert
        assert updated_expense.id == created_expense.id
        assert updated_expense.title == "Rewe groceries"
        assert updated_expense.amount == Decimal("31.20")
        assert updated_expense.currency == expense_data.currency
        assert updated_expense.expense_date == expense_data.expense_date
        assert updated_expense.description == expense_data.description
        assert updated_expense.base_amount == Decimal("31.20")
    finally:
        db_session.close()


# Tests that updating another user's expense raises ExpenseNotFoundError.
# This test exists to verify ownership isolation at the repository layer.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if ExpenseNotFoundError is raised.
def test_update_expense_raises_not_found_for_other_user_expense(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    expense_data = ExpenseCreate(
        category_id=None,
        title="Lidl groceries",
        amount=Decimal("24.99"),
        currency="EUR",
        expense_date=date(2026, 5, 7),
        description="Milk, bread and fruits",
        source="manual",
    )

    try:
        created_expense = expenses_repository.create_expense(
            db_session=db_session,
            expense_data=expense_data,
            user_id=user_id,
            **_identity_snapshot_kwargs(expense_data.amount, expense_data.expense_date),
        )

        # Act / Assert
        with pytest.raises(ExpenseNotFoundError):
            expenses_repository.update_expense(
                db_session=db_session,
                expense_id=created_expense.id,
                expense_data=ExpenseUpdate(title="Hijacked"),
                user_id=other_user_id,
                base_amount=Decimal("24.99"),
                base_currency="EUR",
                fx_rate=Decimal("1"),
                fx_rate_date=expense_data.expense_date,
                fx_source="identity",
            )
    finally:
        db_session.close()


# Tests that the repository deletes an existing expense owned by the user.
# This test exists to verify that the expense row is removed from the database.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the expense no longer appears in get_expenses.
def test_delete_expense_deletes_expense(clean_database: None) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    expense_data = ExpenseCreate(
        category_id=None,
        title="Lidl groceries",
        amount=Decimal("24.99"),
        currency="EUR",
        expense_date=date(2026, 5, 7),
        description="Milk, bread and fruits",
        source="manual",
    )

    try:
        created_expense = expenses_repository.create_expense(
            db_session=db_session,
            expense_data=expense_data,
            user_id=user_id,
            **_identity_snapshot_kwargs(expense_data.amount, expense_data.expense_date),
        )

        # Act
        expenses_repository.delete_expense(
            db_session=db_session,
            expense_id=created_expense.id,
            user_id=user_id,
        )

        remaining_expenses = expenses_repository.get_expenses(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert remaining_expenses == []
    finally:
        db_session.close()


# Tests that deleting another user's expense raises ExpenseNotFoundError.
# This test exists to verify ownership isolation at the repository layer.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if ExpenseNotFoundError is raised and the expense is not deleted.
def test_delete_expense_raises_not_found_for_other_user_expense(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    expense_data = ExpenseCreate(
        category_id=None,
        title="Lidl groceries",
        amount=Decimal("24.99"),
        currency="EUR",
        expense_date=date(2026, 5, 7),
        description="Milk, bread and fruits",
        source="manual",
    )

    try:
        created_expense = expenses_repository.create_expense(
            db_session=db_session,
            expense_data=expense_data,
            user_id=user_id,
            **_identity_snapshot_kwargs(expense_data.amount, expense_data.expense_date),
        )

        # Act / Assert
        with pytest.raises(ExpenseNotFoundError):
            expenses_repository.delete_expense(
                db_session=db_session,
                expense_id=created_expense.id,
                user_id=other_user_id,
            )

        remaining_expenses = expenses_repository.get_expenses(
            db_session=db_session,
            user_id=user_id,
        )

        assert len(remaining_expenses) == 1
    finally:
        db_session.close()
