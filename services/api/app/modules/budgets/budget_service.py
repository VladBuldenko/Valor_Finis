from app.modules.budgets import budget_repository
from app.modules.budgets.budget_schemas import BudgetCreate, BudgetResponse


# Creates a new budget limit using validated budget data.
# This function exists to keep budget business logic separate from API and storage layers.
# Parameters:
# - budget_data: validated budget input data.
# Returns:
# - BudgetResponse object created by the repository.
def create_budget(budget_data: BudgetCreate) -> BudgetResponse:
    return budget_repository.create_budget(budget_data)


# Returns all created budget limits.
# This function exists to provide a clean service layer between router and repository.
# Parameters:
# - None.
# Returns:
# - List of BudgetResponse objects.
def get_budgets() -> list[BudgetResponse]:
    return budget_repository.get_budgets()