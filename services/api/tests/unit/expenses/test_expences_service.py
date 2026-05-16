from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from app.modules.expenses import expenses_service
from app.modules.expenses.expenses_schemas import ExpenseCreate, ExpenseResponse


# Tests that the service creates a new expense through the repository layer.
# This test exists to verify that the service passes database session and expense data correctly.
# Parameters:
# - None.
# Returns:
# - None. The test passes if an ExpenseResponse object is returned.
def test_service_create_expense_creates_expense() -> None:
    # Arrange
    db_session = MagicMock()

    expense_data = ExpenseCreate(
        amount=Decimal("24.99"),
        category="food",
        description="Lidl groceries",
        date=date(2026, 5, 7),
    )

    # Act
    created_expense = expenses_service.create_expense(db_session, expense_data)

    # Assert
    assert isinstance(created_expense, ExpenseResponse)
    assert created_expense.amount == Decimal("24.99")
    assert created_expense.category == "food"


# Tests that the service returns expenses through the repository layer.
# This test exists to verify that the service retrieves expense data using the provided database session.
# Parameters:
# - None.
# Returns:
# - None. The test passes if expenses are returned as a list.
def test_service_get_expenses_returns_expenses() -> None:
    # Arrange
    db_session = MagicMock()

    # Act
    expenses = expenses_service.get_expenses(db_session)

    # Assert
    assert isinstance(expenses, list)