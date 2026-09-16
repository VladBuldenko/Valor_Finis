from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.analytics.analytics_schemas import (
    BudgetStatusItem,
    CategorySummaryItem,
    GoalProgressItem,
    MonthlySummaryResponse,
)
from app.modules.budgets import budget_metrics, budget_version_repository
from app.modules.budgets import budget_repository as budgets_repository
from app.modules.budgets.budget_period import (
    PERIOD_ENDED,
    PERIOD_NOT_STARTED,
    CurrentWindow,
    resolve_current_window,
)
from app.modules.budgets.budgets_models import BudgetModel
from app.modules.categories import repository as categories_repository
from app.modules.expenses import expenses_repository
from app.modules.goals import goal_repository as goals_repository


UNCATEGORIZED_CATEGORY_NAME = "Uncategorized"


# Builds a category id to category name lookup map for the authenticated user.
# This function exists to avoid repeating category name search logic
# inside analytics calculations.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter categories.
# Returns:
# - Dictionary where key is category UUID and value is category name.
def build_category_name_map(
    db_session: Session,
    user_id: UUID,
) -> dict[UUID, str]:
    categories = categories_repository.get_categories(
        db_session=db_session,
        user_id=user_id,
    )

    return {
        category.id: category.name
        for category in categories
    }


# Returns a readable category name by category id.
# This function exists to keep fallback category naming consistent
# across different analytics responses.
# Parameters:
# - category_id: optional category UUID from expense or budget.
# - category_name_map: dictionary with category UUID to category name mapping.
# Returns:
# - Category name or Uncategorized when category_id is missing or unknown.
def get_category_name(
    category_id: Optional[UUID],
    category_name_map: dict[UUID, str],
) -> str:
    if category_id is None:
        return UNCATEGORIZED_CATEGORY_NAME

    return category_name_map.get(category_id, UNCATEGORIZED_CATEGORY_NAME)


# Calculates total spending and expense count for the authenticated user
# within a selected year and month.
# This function exists to provide a monthly dashboard summary.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter expenses.
# - year: selected year used to filter expenses.
# - month: selected month used to filter expenses.
# Returns:
# - MonthlySummaryResponse with total spent and expenses count for the selected month.
def get_monthly_summary(
    db_session: Session,
    user_id: UUID,
    year: int,
    month: int,
) -> MonthlySummaryResponse:
    expenses = expenses_repository.get_expenses(
        db_session=db_session,
        user_id=user_id,
    )

    monthly_expenses = [
        expense
        for expense in expenses
        if expense.expense_date.year == year
        and expense.expense_date.month == month
    ]

    total_spent = sum(
        (expense.amount for expense in monthly_expenses),
        Decimal("0"),
    )

    return MonthlySummaryResponse(
        total_spent=total_spent,
        expenses_count=len(monthly_expenses),
    )


# Calculates spending grouped by category for the authenticated user.
# This function exists to show where the user's money goes.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter expenses and categories.
# Returns:
# - List of CategorySummaryItem objects grouped by category_id.
def get_category_summary(
    db_session: Session,
    user_id: UUID,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> list[CategorySummaryItem]:
    expenses = expenses_repository.get_expenses(
        db_session=db_session,
        user_id=user_id,
    )

    if year is not None and month is not None:
        expenses = [
            expense
            for expense in expenses
            if expense.expense_date.year == year
            and expense.expense_date.month == month
        ]

    category_name_map = build_category_name_map(
        db_session=db_session,
        user_id=user_id,
    )

    category_totals: dict[Optional[UUID], Decimal] = defaultdict(
        lambda: Decimal("0")
    )
    category_counts: dict[Optional[UUID], int] = defaultdict(int)

    for expense in expenses:
        category_totals[expense.category_id] += expense.amount
        category_counts[expense.category_id] += 1

    return [
        CategorySummaryItem(
            category_id=category_id,
            category_name=get_category_name(
                category_id=category_id,
                category_name_map=category_name_map,
            ),
            total_spent=total_spent,
            expenses_count=category_counts[category_id],
        )
        for category_id, total_spent in category_totals.items()
    ]


# Resolves the calendar window a budget's status should be reported against.
# This function exists because resolve_current_window (budget_period.py)
# anchors both period_state and the calendar window to the same as_of,
# which only makes sense while a budget is active. For a not-yet-started or
# already-ended budget, "the calendar period containing as_of" has no
# relationship to the budget's actual activation window - so this function
# re-anchors the window (only) to the date that actually represents the
# period that matters: the first period for not_started, the final period
# for ended. period_state itself must still come from the real as_of.
# Parameters:
# - budget: the budget to resolve a window for.
# - lifecycle: resolve_current_window(budget, as_of) - authoritative for
#   period_state.
# - as_of: the real reference date.
# Returns:
# - CurrentWindow with period/effective bounds appropriate to report status
#   against; period_state is not meaningful on this return value, use
#   lifecycle.period_state instead.
def _resolve_status_window(
    budget: BudgetModel,
    lifecycle: CurrentWindow,
    as_of: date,
) -> CurrentWindow:
    if lifecycle.period_state == PERIOD_NOT_STARTED:
        return resolve_current_window(budget, budget.start_date)

    if lifecycle.period_state == PERIOD_ENDED:
        return resolve_current_window(budget, budget.end_date)

    return lifecycle


# Calculates current-calendar-period budget status for each configured
# budget of the authenticated user.
# This function exists to show spent, remaining, and exceeded amounts for
# the period a budget is actually in right now, resolving historical
# limit/category configuration from BudgetVersion rather than the budget's
# current values.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter budgets and expenses.
# - as_of: reference date the status is calculated as of. The caller (the
#   router) is responsible for defaulting this to today - this function
#   stays a pure, deterministic function of its arguments.
# Returns:
# - List of BudgetStatusItem objects with spending status by budget.
def get_budget_status(
    db_session: Session,
    user_id: UUID,
    as_of: date,
) -> list[BudgetStatusItem]:
    expenses = expenses_repository.get_expenses(
        db_session=db_session,
        user_id=user_id,
    )
    budgets = budgets_repository.get_budgets(
        db_session=db_session,
        user_id=user_id,
    )
    category_name_map = build_category_name_map(
        db_session=db_session,
        user_id=user_id,
    )

    budget_status: list[BudgetStatusItem] = []

    for budget in budgets:
        lifecycle = resolve_current_window(budget, as_of)
        window = _resolve_status_window(budget, lifecycle, as_of)

        # Authoritative for limit_amount/category_id: never trust the
        # budget's current values for a historical/current period once a
        # version exists for it.
        version = budget_version_repository.resolve_version_for_period(
            db_session=db_session,
            budget_id=budget.id,
            period_start=window.period_start,
            period_end=window.period_end,
        )

        if lifecycle.period_state == PERIOD_NOT_STARTED:
            spent = Decimal("0")
        else:
            expense_cutoff = min(window.effective_end, as_of)
            spent = Decimal("0")

            for expense in expenses:
                # Currency correctness: only same-currency expenses can be
                # summed against this budget's limit. No FX conversion
                # exists yet (that is a later slice) and fake-converting
                # would misrepresent the real amount, so a mismatched
                # expense is excluded the same way an out-of-category or
                # out-of-period expense already is.
                if expense.currency != budget.currency:
                    continue

                if (
                    version.category_id is not None
                    and expense.category_id != version.category_id
                ):
                    continue

                if expense.expense_date < window.effective_start:
                    continue

                if expense.expense_date > expense_cutoff:
                    continue

                spent += expense.amount

        remaining = max(version.limit_amount - spent, Decimal("0"))
        exceeded_amount = max(spent - version.limit_amount, Decimal("0"))
        utilization_percent = (
            spent / version.limit_amount * Decimal("100")
        ).quantize(Decimal("0.01"))

        # Pure current-period pace/risk metrics (VF-014B4). window.days_elapsed
        # is only meaningful for an active budget - budget_metrics normalizes
        # the not_started/ended cases itself per its documented rules rather
        # than trusting the re-anchored helper window's raw value for those.
        metrics = budget_metrics.calculate_budget_metrics(
            limit_amount=version.limit_amount,
            spent=spent,
            period_state=lifecycle.period_state,
            days_in_period=window.days_in_period,
            days_elapsed=window.days_elapsed,
        )

        budget_status.append(
            BudgetStatusItem(
                budget_id=budget.id,
                budget_name=budget.name,
                category_id=version.category_id,
                category_name=get_category_name(
                    category_id=version.category_id,
                    category_name_map=category_name_map,
                ),
                period=budget.period,
                period_start=window.period_start,
                period_end=window.period_end,
                effective_start=window.effective_start,
                effective_end=window.effective_end,
                period_state=lifecycle.period_state,
                is_partial_period=window.is_partial_period,
                limit_amount=version.limit_amount,
                spent=spent,
                remaining=remaining,
                exceeded_amount=exceeded_amount,
                utilization_percent=utilization_percent,
                is_exceeded=spent > version.limit_amount,
                days_in_period=metrics.days_in_period,
                days_elapsed=metrics.days_elapsed,
                days_remaining=metrics.days_remaining,
                average_daily_spending=metrics.average_daily_spending,
                daily_spending_allowance=metrics.daily_spending_allowance,
                projected_spending=metrics.projected_spending,
                projected_surplus=metrics.projected_surplus,
                projected_deficit=metrics.projected_deficit,
                risk_status=metrics.risk_status,
            )
        )

    return budget_status


# Calculates progress for each financial goal of the authenticated user.
# This function exists to show how much money is already saved
# and how much is still needed for each goal.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter goals.
# Returns:
# - List of GoalProgressItem objects with goal progress information.
def get_goal_progress(
    db_session: Session,
    user_id: UUID,
) -> list[GoalProgressItem]:
    goals = goals_repository.get_goals(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        GoalProgressItem(
            goal_id=goal.id,
            name=goal.name,
            target_amount=goal.target_amount,
            current_amount=goal.current_amount,
            remaining_amount=max(
                goal.target_amount - goal.current_amount,
                Decimal("0"),
            ),
            progress_percent=(
                goal.current_amount / goal.target_amount * Decimal("100")
            ).quantize(Decimal("0.01")),
            status=goal.status,
            target_date=goal.target_date,
        )
        for goal in goals
    ]