from fastapi import APIRouter, status

from app.modules.analytics import analytics_service
from app.modules.analytics.analytics_schemas import (
    BudgetStatusItem,
    CategorySummaryItem,
    GoalProgressItem,
    MonthlySummaryResponse,
)


router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
)


# Returns monthly spending summary through the API.
# This function exists to expose total spending and expense count to mobile and web clients.
# Parameters:
# - None.
# Returns:
# - MonthlySummaryResponse object with total spent and expenses count.
@router.get(
    "/monthly-summary",
    response_model=MonthlySummaryResponse,
    status_code=status.HTTP_200_OK,
)
def get_monthly_summary() -> MonthlySummaryResponse:
    return analytics_service.get_monthly_summary()


# Returns spending summary grouped by category through the API.
# This function exists to expose category-based spending analytics to mobile and web clients.
# Parameters:
# - None.
# Returns:
# - List of CategorySummaryItem objects.
@router.get(
    "/category-summary",
    response_model=list[CategorySummaryItem],
    status_code=status.HTTP_200_OK,
)
def get_category_summary() -> list[CategorySummaryItem]:
    return analytics_service.get_category_summary()


# Returns budget status through the API.
# This function exists to expose remaining budget and exceeded limits to mobile and web clients.
# Parameters:
# - None.
# Returns:
# - List of BudgetStatusItem objects.
@router.get(
    "/budget-status",
    response_model=list[BudgetStatusItem],
    status_code=status.HTTP_200_OK,
)
def get_budget_status() -> list[BudgetStatusItem]:
    return analytics_service.get_budget_status()


# Returns financial goal progress through the API.
# This function exists to expose goal progress data to mobile and web clients.
# Parameters:
# - None.
# Returns:
# - List of GoalProgressItem objects.
@router.get(
    "/goal-progress",
    response_model=list[GoalProgressItem],
    status_code=status.HTTP_200_OK,
)
def get_goal_progress() -> list[GoalProgressItem]:
    return analytics_service.get_goal_progress()