from datetime import date, datetime
from decimal import Decimal

from app.modules.expenses import repository
from app.modules.expenses.schemas import ExpenseCreate, ExpenseResponse


# Resets the in-memory expense repository state before each test.
# This helper exists to keep repository tests independent from each other.
# Parameters:
# - None.
# Returns:
# - None.
def reset_repository_state() -> None:
    repository.expenses_storage.clear()
    repository.next_expense_id = 1


# Tests that the repository creates a new expense successfully.
# This test exists to verify that expense data can be stored in memory.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the created expense contains expected data.
def test_create_expense_creates_new_expense() -> None:
    # Arrange
    reset_repository_state()

    expense_data = ExpenseCreate(
        amount=Decimal("24.99"),
        category="food",
        description="Lidl groceries",
        date=date(2026, 5, 7),
    )

    # Act
    created_expense = repository.create_expense(expense_data)

    # Assert
    assert isinstance(created_expense, ExpenseResponse)
    assert created_expense.amount == Decimal("24.99")
    assert created_expense.category == "food"
    assert created_expense.description == "Lidl groceries"
    assert created_expense.date == date(2026, 5, 7)


# Tests that the repository generates an auto-incremented expense ID.
# This test exists to verify that each created expense receives a unique identifier.
# Parameters:
# - None.
# Returns:
# - None. The test passes if expense IDs are generated in sequence.
def test_create_expense_generates_incremental_id() -> None:
    # Arrange
    reset_repository_state()

    first_expense = ExpenseCreate(
        amount=Decimal("10.00"),
        category="food",
        description="First expense",
        date=date(2026, 5, 7),
    )

    second_expense = ExpenseCreate(
        amount=Decimal("20.00"),
        category="cafe",
        description="Second expense",
        date=date(2026, 5, 8),
    )

    # Act
    created_first_expense = repository.create_expense(first_expense)
    created_second_expense = repository.create_expense(second_expense)

    # Assert
    assert created_first_expense.id == 1
    assert created_second_expense.id == 2


# Tests that the repository adds creation timestamp to a new expense.
# This test exists to verify that created_at is generated automatically.
# Parameters:
# - None.
# Returns:
# - None. The test passes if created_at is a datetime value.
def test_create_expense_generates_created_at_timestamp() -> None:
    # Arrange
    reset_repository_state()

    expense_data = ExpenseCreate(
        amount=Decimal("24.99"),
        category="food",
        description="Lidl groceries",
        date=date(2026, 5, 7),
    )

    # Act
    created_expense = repository.create_expense(expense_data)

    # Assert
    assert isinstance(created_expense.created_at, datetime)


# Tests that the repository returns all saved expenses.
# This test exists to verify that stored expenses can be retrieved.
# Parameters:
# - None.
# Returns:
# - None. The test passes if get_expenses returns previously created expenses.
def test_get_expenses_returns_saved_expenses() -> None:
    # Arrange
    reset_repository_state()

    expense_data = ExpenseCreate(
        amount=Decimal("24.99"),
        category="food",
        description="Lidl groceries",
        date=date(2026, 5, 7),
    )

    created_expense = repository.create_expense(expense_data)

    # Act
    expenses = repository.get_expenses()

    # Assert
    assert len(expenses) == 1
    assert expenses[0] == created_expense