from datetime import date
from decimal import Decimal

from app.modules.expenses import repository, service
from app.modules.expenses.schemas import ExpenseCreate, ExpenseResponse


# Resets the in-memory expense repository state before each test.
# This helper exists to keep service tests independent from each other.
# Parameters:
# - None.
# Returns:
# - None.
def reset_repository_state() -> None:
    repository.expenses_storage.clear()
    repository.next_expense_id = 1


# Tests that the service creates a new expense.
# This test exists to verify that the service layer correctly delegates expense creation to the repository.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the created expense contains expected data.
def test_service_create_expense_creates_expense() -> None:
    # Arrange
    reset_repository_state()

    expense_data = ExpenseCreate(
        amount=Decimal("24.99"),
        category="food",
        description="Lidl groceries",
        date=date(2026, 5, 7),
    )

    # Act
    created_expense = service.create_expense(expense_data)

    # Assert
    assert isinstance(created_expense, ExpenseResponse)
    assert created_expense.id == 1
    assert created_expense.amount == Decimal("24.99")
    assert created_expense.category == "food"


# Tests that the service returns all expenses.
# This test exists to verify that the service layer can retrieve expenses through the repository.
# Parameters:
# - None.
# Returns:
# - None. The test passes if returned expenses include previously created expenses.
def test_service_get_expenses_returns_expenses() -> None:
    # Arrange
    reset_repository_state()

    expense_data = ExpenseCreate(
        amount=Decimal("24.99"),
        category="food",
        description="Lidl groceries",
        date=date(2026, 5, 7),
    )

    created_expense = service.create_expense(expense_data)

    # Act
    expenses = service.get_expenses()

    # Assert
    assert len(expenses) == 1
    assert expenses[0] == created_expense