from datetime import date
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.analytics import analytics_service
from app.modules.analytics.analytics_schemas import (
    BudgetStatusItem,
    CategorySummaryItem,
    CategoryTrendResponse,
    GoalProgressItem,
    MonthlySummaryResponse,
    SpendingForecastResponse,
    SpendingTrendResponse,
)
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser


router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
)


# Default bucket counts when `count` is omitted, and the maximum a client
# may request - bounds the query so a single request can never pull an
# unbounded amount of history. Shared by spending-trend (VF-015B) and
# category-trend (VF-015C), which use identical period/count semantics.
SPENDING_TREND_DEFAULT_COUNTS = {"day": 30, "week": 12, "month": 6}
SPENDING_TREND_MAXIMUM_COUNTS = {"day": 366, "week": 104, "month": 24}


# Resolves the effective bucket count for a trend request, applying the
# per-period default when omitted and rejecting a count above the
# per-period maximum.
# This function exists so spending-trend and category-trend never
# duplicate this validation, which is identical for both endpoints.
# Parameters:
# - period: one of "day", "week", "month".
# - count: the client-supplied count, or None to use the period's default.
# Returns:
# - The resolved count to use.
# Raises:
# - HTTPException 422: when the resolved count exceeds the period's maximum.
def _resolve_trend_count(period: str, count: Optional[int]) -> int:
    resolved_count = count if count is not None else SPENDING_TREND_DEFAULT_COUNTS[period]

    if resolved_count > SPENDING_TREND_MAXIMUM_COUNTS[period]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"count must not exceed {SPENDING_TREND_MAXIMUM_COUNTS[period]} "
                f"for period '{period}'."
            ),
        )

    return resolved_count


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


# Returns a bounded historical base-currency spending time series through
# the API, plus a comparison between the two most recent complete periods.
# This function exists to expose VF-015B spending-trend analytics to mobile
# and web clients - distinct from Budget Status (per-Budget, original-
# currency) and monthly/category summary (single period only).
# Parameters:
# - period: calendar bucket size - "day", "week", or "month".
# - count: number of buckets to return. Defaults and maximum bounds vary
#   by period (see SPENDING_TREND_DEFAULT_COUNTS/SPENDING_TREND_MAXIMUM_COUNTS)
#   so a client can never request an unbounded amount of history.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy database session injected by FastAPI.
# Returns:
# - SpendingTrendResponse with `count` buckets ending at the server's
#   current date, and an optional period_over_period comparison.
# Raises:
# - HTTPException 422: when count exceeds the maximum for the requested period.
@router.get(
    "/spending-trend",
    response_model=SpendingTrendResponse,
    status_code=status.HTTP_200_OK,
)
def get_spending_trend(
    period: Literal["day", "week", "month"] = Query(
        ...,
        description="Calendar bucket size.",
        examples=["month"],
    ),
    count: Optional[int] = Query(
        default=None,
        ge=1,
        description=(
            "Number of buckets to return. Defaults to 30/12/6 for "
            "day/week/month when omitted; maximum 366/104/24 respectively."
        ),
        examples=[6],
    ),
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> SpendingTrendResponse:
    resolved_count = _resolve_trend_count(period=period, count=count)

    return analytics_service.get_spending_trend(
        db_session=db_session,
        user_id=current_user.id,
        period=period,
        count=resolved_count,
        as_of=date.today(),
    )


# Returns bounded historical base-currency spending trends grouped by
# category through the API - each category's own day/week/month bucket
# series plus its own period-over-period comparison.
# This function exists to expose VF-015C category-trend analytics to
# mobile and web clients - distinct from Category Summary (single period
# only) and Spending Trend (not broken down by category).
# Parameters:
# - period: calendar bucket size - "day", "week", or "month".
# - count: number of buckets to return per category. Same defaults/maximums
#   as spending-trend (see _resolve_trend_count).
# - category_id: optional. When provided, must be a category owned by the
#   authenticated user; the response then contains exactly that one
#   category (even with zero matching Expenses). Omit for Uncategorized -
#   there is no separate sentinel value for it in VF-015C.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy database session injected by FastAPI.
# Returns:
# - CategoryTrendResponse with one item per matching category.
# Raises:
# - HTTPException 422: when count exceeds the maximum for the requested period.
# - CategoryNotFoundError: category_id is set and not owned by the caller
#   (mapped centrally to 404 - see app.core.exception_handlers).
@router.get(
    "/category-trend",
    response_model=CategoryTrendResponse,
    status_code=status.HTTP_200_OK,
)
def get_category_trend(
    period: Literal["day", "week", "month"] = Query(
        ...,
        description="Calendar bucket size.",
        examples=["month"],
    ),
    count: Optional[int] = Query(
        default=None,
        ge=1,
        description=(
            "Number of buckets to return per category. Defaults to "
            "30/12/6 for day/week/month when omitted; maximum "
            "366/104/24 respectively."
        ),
        examples=[6],
    ),
    category_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Optional category to scope the trend to. Must be owned by "
            "the authenticated user. Omit for Uncategorized - there is no "
            "separate sentinel value for it."
        ),
    ),
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> CategoryTrendResponse:
    resolved_count = _resolve_trend_count(period=period, count=count)

    return analytics_service.get_category_trend(
        db_session=db_session,
        user_id=current_user.id,
        period=period,
        count=resolved_count,
        as_of=date.today(),
        category_id=category_id,
    )


# Returns a deterministic current-month spending pace projection through
# the API.
# This function exists to expose VF-015D's spending-forecast analytics to
# mobile and web clients - CURRENT-MONTH SPENDING PACE PROJECTION only,
# never a cash-flow/income/savings/net-worth forecast. Always calculated
# against the server's current date - there is no public as_of parameter,
# no history-length parameter, and no forecast-model-selection parameter;
# the current linear_run_rate model is the only one implemented.
# Parameters:
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy database session injected by FastAPI.
# Returns:
# - SpendingForecastResponse for the calendar month containing today.
@router.get(
    "/spending-forecast",
    response_model=SpendingForecastResponse,
    status_code=status.HTTP_200_OK,
)
def get_spending_forecast(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> SpendingForecastResponse:
    return analytics_service.get_spending_forecast(
        db_session=db_session,
        user_id=current_user.id,
        as_of=date.today(),
    )


# Returns budget status through the API.
# This function exists to expose remaining budget and exceeded limits
# to mobile and web clients, calculated against the current calendar
# period each budget is in, always relative to the server's current date.
# The service layer supports an explicit as_of internally (deterministic,
# unit-testable), but that is not exposed publicly here on purpose:
# arbitrary-date/historical-period browsing is out of scope for VF-014B3
# and belongs to VF-015's own, deliberately designed API.
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
        as_of=date.today(),
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