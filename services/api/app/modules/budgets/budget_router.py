from fastapi import APIRouter, status

from app.modules.budgets import budget_service
from app.modules.budgets.budget_schemas import BudgetCreate, BudgetResponse


router = APIRouter(
    prefix="/budgets",
    tags=["Budgets"],
)


# Creates a new budget limit through the API.
# This function exists to expose budget limit creation to mobile and web clients.
# Parameters:
# - budget_data: validated request body containing budget limit details.
# Returns:
# - BudgetResponse object with generated id and created_at timestamp.
@router.post(
    "",
    response_model=BudgetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_budget(budget_data: BudgetCreate) -> BudgetResponse:
    return budget_service.create_budget(budget_data)


# Returns all budget limits through the API.
# This function exists to expose budget limits to mobile and web clients.
# Parameters:
# - None.
# Returns:
# - List of BudgetResponse objects.
@router.get(
    "",
    response_model=list[BudgetResponse],
    status_code=status.HTTP_200_OK,
)
def get_budgets() -> list[BudgetResponse]:
    return budget_service.get_budgets()