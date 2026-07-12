from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.analytics import analytics_service
from app.modules.analytics.analytics_schemas import (
    BudgetStatusItem,
    CategorySummaryItem,
    GoalProgressItem,
    MonthlySummaryResponse,
)
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser


router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
)


# Returns spending summary through the API.
# This function exists to expose total spending and expense count
# to mobile and web clients.
# Parameters:
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy database session injected by FastAPI.
# Returns:
# - MonthlySummaryResponse object with total spent and expenses count.
@router.get(
    "/monthly-summary",
    response_model=MonthlySummaryResponse,
    status_code=status.HTTP_200_OK,
)
def get_monthly_summary(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> MonthlySummaryResponse:
    return analytics_service.get_monthly_summary(
        db_session=db_session,
        user_id=current_user.id,
    )


# Returns spending summary grouped by category through the API.
# This function exists to expose category-based spending analytics
# to mobile and web clients.
# Parameters:
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy database session injected by FastAPI.
# Returns:
# - List of CategorySummaryItem objects.
@router.get(
    "/category-summary",
    response_model=list[CategorySummaryItem],
    status_code=status.HTTP_200_OK,
)
def get_category_summary(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> list[CategorySummaryItem]:
    return analytics_service.get_category_summary(
        db_session=db_session,
        user_id=current_user.id,
    )


# Returns budget status through the API.
# This function exists to expose remaining budget and exceeded limits
# to mobile and web clients.
# Parameters:
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy database session injected by FastAPI.
# Returns:
# - List of BudgetStatusItem objects.
@router.get(
    "/budget-status",
    response_model=list[BudgetStatusItem],
    status_code=status.HTTP_200_OK,
)
def get_budget_status(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> list[BudgetStatusItem]:
    return analytics_service.get_budget_status(
        db_session=db_session,
        user_id=current_user.id,
    )


# Returns financial goal progress through the API.
# This function exists to expose goal progress data
# to mobile and web clients.
# Parameters:
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy database session injected by FastAPI.
# Returns:
# - List of GoalProgressItem objects.
@router.get(
    "/goal-progress",
    response_model=list[GoalProgressItem],
    status_code=status.HTTP_200_OK,
)
def get_goal_progress(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> list[GoalProgressItem]:
    return analytics_service.get_goal_progress(
        db_session=db_session,
        user_id=current_user.id,
    )