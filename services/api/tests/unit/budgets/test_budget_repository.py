from datetime import date, datetime
from decimal import Decimal

from app.modules.budgets import budget_repository
from app.modules.budgets.budget_schemas import BudgetCreate, BudgetResponse


# Resets the in-memory budget repository state before each test.
# This helper exists to keep repository tests independent from each other.
# Parameters:
# - None.
# Returns:
# - None.
def reset_repository_state() -> None:
    budget_repository.budgets_storage.clear()
    budget_repository.next_budget_id = 1

# Tests that the repository creates a new budget limit successfully.
# This test exists to verify that budget data can be stored in memory.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the created budget contains expected data.
def test_create_budget_creates_new_budget() -> None:

    # Arrange
    reset_repository_state()

    budget_data = BudgetCreate(
        category="food",
        monthly_limit=Decimal("400"),
        month=date(2026, 5, 1),
    )

    # Act
    created_budget = budget_repository.create_budget(budget_data)

    # Assert
    assert isinstance(created_budget, BudgetResponse)
    assert created_budget.category == "food"
    assert created_budget.monthly_limit == Decimal("400")
    assert created_budget.month == date(2026, 5, 1)


# Tests that the repository generates an auto-incremented budget ID.
# This test exists to verify that each created budget receives a unique identifier.
# Parameters:
# - None.
# Returns:
# - None. The test passes if budget IDs are generated in sequence.
def test_create_budget_generates_incremental_id() -> None:
    # Arrange
    reset_repository_state()

    first_budget = BudgetCreate(
        category="food",
        monthly_limit=Decimal("400"),
        month=date(2026, 5, 1),
    )

    second_budget = BudgetCreate(
        category="cafe",
        monthly_limit=Decimal("150"),
        month=date(2026, 5, 1),
    )

    # Act
    created_first_budget = budget_repository.create_budget(first_budget)
    created_second_budget = budget_repository.create_budget(second_budget)

    # Assert
    assert created_first_budget.id == 1
    assert created_second_budget.id == 2


# Tests that the repository adds creation timestamp to a new budget.
# This test exists to verify that created_at is generated automatically.
# Parameters:
# - None.
# Returns:
# - None. The test passes if created_at is a datetime value.
def test_create_budget_generates_created_at_timestamp() -> None:
    # Arrange
    reset_repository_state()

    budget_data = BudgetCreate(
        category="food",
        monthly_limit=Decimal("400"),
        month=date(2026, 5, 1),
    )

    # Act
    created_budget = budget_repository.create_budget(budget_data)

    # Assert
    assert isinstance(created_budget.created_at, datetime)


# Tests that the repository returns all saved budget limits.
# This test exists to verify that stored budgets can be retrieved.
# Parameters:
# - None.
# Returns:
# - None. The test passes if get_budgets returns previously created budgets.
def test_get_budgets_returns_saved_budgets() -> None:
    # Arrange
    reset_repository_state()

    budget_data = BudgetCreate(
        category="food",
        monthly_limit=Decimal("400"),
        month=date(2026, 5, 1),
    )

    created_budget = budget_repository.create_budget(budget_data)

    # Act
    budgets = budget_repository.get_budgets()

    # Assert
    assert len(budgets) == 1
    assert budgets[0] == created_budget