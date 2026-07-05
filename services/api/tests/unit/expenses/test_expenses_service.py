from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.db.database_session import SessionLocal
from app.modules.expenses import expenses_service
from app.modules.expenses.expenses_schemas import ExpenseCreate, ExpenseResponse


# Tests that the service creates a new expense through the repository layer.
# This test exists to verify that the service maps the created database model to ExpenseResponse.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if an ExpenseResponse object is returned with expected values.
def test_service_create_expense_creates_expense_response(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    expense_data = ExpenseCreate(
        user_id=user_id,
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
        created_expense = expenses_service.create_expense(
            db_session=db_session,
            expense_data=expense_data,
        )

        # Assert
        assert isinstance(created_expense, ExpenseResponse)
        assert created_expense.user_id == user_id
        assert created_expense.category_id is None
        assert created_expense.title == expense_data.title
        assert created_expense.amount == Decimal("24.99")
        assert created_expense.currency == expense_data.currency
        assert created_expense.expense_date == expense_data.expense_date
        assert created_expense.description == expense_data.description
        assert created_expense.source == expense_data.source
    finally:
        db_session.close()


# Tests that the service returns expenses for a specific user.
# This test exists to verify that the service retrieves user-scoped expenses and returns response schemas.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the requested user's expenses are returned.
def test_service_get_expenses_returns_user_expense_responses(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    user_expense_data = ExpenseCreate(
        user_id=user_id,
        category_id=None,
        title="Lidl groceries",
        amount=Decimal("24.99"),
        currency="EUR",
        expense_date=date(2026, 5, 7),
        description="Milk, bread and fruits",
        source="manual",
    )

    other_user_expense_data = ExpenseCreate(
        user_id=other_user_id,
        category_id=None,
        title="Train ticket",
        amount=Decimal("12.50"),
        currency="EUR",
        expense_date=date(2026, 5, 8),
        description="Munich transport",
        source="manual",
    )

    try:
        expenses_service.create_expense(
            db_session=db_session,
            expense_data=user_expense_data,
        )
        expenses_service.create_expense(
            db_session=db_session,
            expense_data=other_user_expense_data,
        )

        # Act
        expenses = expenses_service.get_expenses(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert len(expenses) == 1
        assert isinstance(expenses[0], ExpenseResponse)
        assert expenses[0].user_id == user_id
        assert expenses[0].category_id is None
        assert expenses[0].title == user_expense_data.title
        assert expenses[0].amount == Decimal("24.99")
        assert expenses[0].currency == user_expense_data.currency
        assert expenses[0].expense_date == user_expense_data.expense_date
        assert expenses[0].description == user_expense_data.description
        assert expenses[0].source == user_expense_data.source
    finally:
        db_session.close()