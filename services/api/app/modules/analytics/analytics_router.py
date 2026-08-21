from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional

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


# Returns spending summary for a selected month through the API.
# This function exists to expose monthly total spending and expense count
# to mobile and web clients.
# Parameters:
# - year: selected year used to filter expenses.
# - month: selected month used to filter expenses.
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
    year: int = Query(
        ...,
        ge=2000,
        le=2100,
        description="Year used to filter monthly expenses.",
        examples=[2026],
    ),
    month: int = Query(
        ...,
        ge=1,
        le=12,
        description="Month used to filter monthly expenses.",
        examples=[7],
    ),
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> MonthlySummaryResponse:
    return analytics_service.get_monthly_summary(
        db_session=db_session,
        user_id=current_user.id,
        year=year,
        month=month,
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
    year: Optional[int] = Query(
        default=None,
        ge=2000,
        le=2100,
        description="Optional year used to filter category expenses.",
        examples=[2026],
    ),
    month: Optional[int] = Query(
        default=None,
        ge=1,
        le=12,
        description="Optional month used to filter category expenses.",
        examples=[8],
    ),
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> list[CategorySummaryItem]:
    if (year is None) != (month is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Year and month must be provided together.",
        )

    return analytics_service.get_category_summary(
        db_session=db_session,
        user_id=current_user.id,
        year=year,
        month=month,
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