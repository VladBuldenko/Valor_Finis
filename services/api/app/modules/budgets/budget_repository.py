from datetime import datetime

from app.modules.budgets.budget_schemas import BudgetCreate, BudgetResponse


budgets_storage: list[BudgetResponse] = []
next_budget_id = 1


# Creates a new budget limit in temporary in-memory storage.
# This function exists to isolate budget storage logic from business logic.
# Parameters:
# - budget_data: validated budget input data.
# Returns:
# - BudgetResponse object with generated id and created_at timestamp.
def create_budget(budget_data: BudgetCreate) -> BudgetResponse:
    global next_budget_id

    budget = BudgetResponse(
        id=next_budget_id,
        category=budget_data.category,
        monthly_limit=budget_data.monthly_limit,
        month=budget_data.month,
        created_at=datetime.utcnow(),
    )

    budgets_storage.append(budget)
    next_budget_id += 1

    return budget


# Returns all budget limits from temporary in-memory storage.
# This function exists to keep budget retrieval logic inside the repository layer.
# Parameters:
# - None.
# Returns:
# - List of BudgetResponse objects.
def get_budgets() -> list[BudgetResponse]:
    return budgets_storage