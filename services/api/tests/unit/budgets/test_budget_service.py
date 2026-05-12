from datetime import date
from decimal import Decimal

from app.modules.budgets import budget_repository, budget_service
from app.modules.budgets.budget_schemas import BudgetCreate, BudgetResponse


# Resets the in-memory budget repository state before each test.
# This helper exists to keep service tests independent from each other.
# Parameters:
# - None.
# Returns:
# - None.
def reset_repository_state() -> None:
    budget_repository.budgets_storage.clear()
    budget_repository.next_budget_id = 1


# Tests that the service creates a new budget limit.
# This test exists to verify that the service layer correctly delegates budget creation to the repository.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the created budget contains expected data.
def test_service_create_budget_creates_budget() -> None:
    # Arrange
    reset_repository_state()

    budget_data = BudgetCreate(
        category="food",
        monthly_limit=Decimal("400"),
        month=date(2026, 5, 1),
    )

    # Act
    created_budget = budget_service.create_budget(budget_data)

    # Assert
    assert isinstance(created_budget, BudgetResponse)
    assert created_budget.id == 1
    assert created_budget.category == "food"
    assert created_budget.monthly_limit == Decimal("400")


# Tests that the service returns all budget limits.
# This test exists to verify that the service layer can retrieve budgets through the repository.
# Parameters:
# - None.
# Returns:
# - None. The test passes if returned budgets include previously created budgets.
def test_service_get_budgets_returns_budgets() -> None:
    # Arrange
    reset_repository_state()

    budget_data = BudgetCreate(
        category="food",
        monthly_limit=Decimal("400"),
        month=date(2026, 5, 1),
    )

    created_budget = budget_service.create_budget(budget_data)

    # Act
    budgets = budget_service.get_budgets()

    # Assert
    assert len(budgets) == 1
    assert budgets[0] == created_budget