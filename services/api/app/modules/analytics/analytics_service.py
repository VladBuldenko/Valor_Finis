from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core import calendar_period
from app.modules.analytics.analytics_schemas import (
    BudgetStatusItem,
    CategorySummaryItem,
    GoalProgressItem,
    MonthlySummaryResponse,
    PeriodOverPeriodComparison,
    SpendingTrendBucket,
    SpendingTrendResponse,
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
from app.modules.financial_settings import financial_settings_service
from app.modules.goals import goal_repository as goals_repository


BUCKET_AMOUNT_DECIMAL_PLACES = Decimal("0.00")
PERCENT_CHANGE_DECIMAL_PLACES = Decimal("0.01")


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


# Calculates total base-currency spending and expense count for the
# authenticated user within a selected year and month.
# This function exists to provide a monthly dashboard summary.
#
# VF-014B5D: sums each resolved Expense's base_amount (backend-resolved
# base-currency truth, VF-014B5C), never the original expense.amount -
# mixed-currency original amounts must never be summed directly (e.g. 100
# EUR + 100 USD is never reported as 200). A legacy Expense with no FX
# snapshot yet (base_amount is None) is excluded from total_spent rather
# than treated as zero, and separately counted in
# unresolved_expenses_count so incomplete historical data is visible
# rather than silently hidden. A resolved Expense whose persisted
# base_currency does not match the user's current base_currency (not
# reachable today since base_currency mutation is not exposed, but not
# guaranteed by the schema either) is treated the same way: excluded from
# the total and counted as unresolved, rather than summed as if it were
# in the right currency or silently dropped.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter expenses.
# - year: selected year used to filter expenses.
# - month: selected month used to filter expenses.
# Returns:
# - MonthlySummaryResponse with base-currency total spent, resolved
#   expenses count, the user's base currency, and the unresolved count.
def get_monthly_summary(
    db_session: Session,
    user_id: UUID,
    year: int,
    month: int,
) -> MonthlySummaryResponse:
    base_currency = financial_settings_service.get_base_currency(
        db_session=db_session,
        user_id=user_id,
    )

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

    total_spent = Decimal("0")
    expenses_count = 0
    unresolved_expenses_count = 0

    for expense in monthly_expenses:
        if expense.base_amount is None or expense.base_currency != base_currency:
            unresolved_expenses_count += 1
            continue

        total_spent += expense.base_amount
        expenses_count += 1

    return MonthlySummaryResponse(
        total_spent=total_spent,
        expenses_count=expenses_count,
        base_currency=base_currency,
        unresolved_expenses_count=unresolved_expenses_count,
    )


# Calculates base-currency spending grouped by category for the
# authenticated user.
# This function exists to show where the user's money goes.
#
# VF-014B5D: sums each resolved Expense's base_amount, never the original
# expense.amount - see get_monthly_summary's docstring for the full
# resolved/unresolved/incompatible-currency rationale, which applies
# identically here, per category. A category whose matching Expenses are
# all unresolved (or all incompatible-currency) is still returned - never
# silently omitted - with total_spent=0, expenses_count=0, and
# unresolved_expenses_count > 0, so incomplete historical data stays
# visible per category too.
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
    base_currency = financial_settings_service.get_base_currency(
        db_session=db_session,
        user_id=user_id,
    )

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
    category_resolved_counts: dict[Optional[UUID], int] = defaultdict(int)
    category_unresolved_counts: dict[Optional[UUID], int] = defaultdict(int)

    for expense in expenses:
        category_id = expense.category_id
        # Touch category_totals for every matching expense (resolved or
        # not) so a category is registered - and therefore returned below
        # - even when none of its expenses are resolved.
        category_totals.setdefault(category_id, Decimal("0"))

        if expense.base_amount is None or expense.base_currency != base_currency:
            category_unresolved_counts[category_id] += 1
            continue

        category_totals[category_id] += expense.base_amount
        category_resolved_counts[category_id] += 1

    return [
        CategorySummaryItem(
            category_id=category_id,
            category_name=get_category_name(
                category_id=category_id,
                category_name_map=category_name_map,
            ),
            total_spent=total_spent,
            expenses_count=category_resolved_counts[category_id],
            unresolved_expenses_count=category_unresolved_counts[category_id],
            base_currency=base_currency,
        )
        for category_id, total_spent in category_totals.items()
    ]


# Builds the comparison between the two most recent COMPLETE buckets in a
# chronologically-ordered spending trend series.
# This function exists to keep the "never compare an in-progress period
# against a finished one" rule (VF-015B) in one place, since it's easy to
# get wrong by comparing the last two buckets positionally instead of the
# last two that have actually finished.
# Parameters:
# - buckets: chronologically ordered (oldest first) SpendingTrendBucket list.
# Returns:
# - PeriodOverPeriodComparison, or None when fewer than two complete
#   buckets exist in the series.
def _build_period_over_period(
    buckets: list[SpendingTrendBucket],
) -> Optional[PeriodOverPeriodComparison]:
    complete_buckets = [bucket for bucket in buckets if bucket.is_complete]

    if len(complete_buckets) < 2:
        return None

    previous_bucket, current_bucket = complete_buckets[-2], complete_buckets[-1]

    absolute_change = current_bucket.total_spent - previous_bucket.total_spent

    if previous_bucket.total_spent == 0:
        # Percentage change is mathematically undefined against a zero
        # base - never reported as infinity, 100, or 0.
        percent_change = None
    else:
        percent_change = (
            (current_bucket.total_spent - previous_bucket.total_spent)
            / previous_bucket.total_spent
            * Decimal("100")
        ).quantize(PERCENT_CHANGE_DECIMAL_PLACES)

    if absolute_change > 0:
        direction = "up"
    elif absolute_change < 0:
        direction = "down"
    else:
        direction = "unchanged"

    return PeriodOverPeriodComparison(
        current_period_start=current_bucket.period_start,
        current_period_end=current_bucket.period_end,
        previous_period_start=previous_bucket.period_start,
        previous_period_end=previous_bucket.period_end,
        current_total_spent=current_bucket.total_spent,
        previous_total_spent=previous_bucket.total_spent,
        absolute_change=absolute_change,
        percent_change=percent_change,
        direction=direction,
    )


# Calculates a bounded historical base-currency spending time series for the
# authenticated user (VF-015B).
# This function exists to answer "how has my spending moved over time,"
# distinct from Budget Status (per-Budget, original-currency, current-
# period-only) and from monthly/category summary (single period only).
#
# Every requested calendar bucket is emitted, including one with no
# Expenses at all (total_spent 0.00) - a client must never need to
# reconstruct missing dates. Each bucket sums resolved Expenses' persisted
# base_amount (VF-014B5C/B5D) - never the original mixed-currency amount,
# never recomputed from fx_rate, never re-fetched from a provider. A
# legacy unresolved Expense (base_amount is None), or a resolved Expense
# whose persisted base_currency no longer matches the user's current base
# currency, is excluded from the total and counted separately - identical
# to the monthly/category summary rule.
#
# effective_end = min(period_end, as_of) is used as the inclusive upper
# bound for every bucket, uniformly - this is what keeps a future-dated
# Expense from leaking into the current (incomplete) bucket without any
# special-casing: for a complete bucket effective_end already equals
# period_end, so the same filter is exactly right for both cases.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter expenses.
# - period: one of "day", "week", "month".
# - count: number of buckets to return. Must be >= 1; upper-bound
#   validation is the router's responsibility (VF-015B keeps this function
#   a pure, deterministic function of its arguments, matching
#   get_budget_status's as_of convention).
# - as_of: reference date the series ends on. The caller (the router) is
#   responsible for defaulting this to today.
# Returns:
# - SpendingTrendResponse with `count` chronologically ordered buckets and
#   an optional period_over_period comparison.
def get_spending_trend(
    db_session: Session,
    user_id: UUID,
    period: str,
    count: int,
    as_of: date,
) -> SpendingTrendResponse:
    base_currency = financial_settings_service.get_base_currency(
        db_session=db_session,
        user_id=user_id,
    )

    calendar_periods = calendar_period.resolve_recent_periods(
        period=period,
        as_of=as_of,
        count=count,
    )

    expenses = expenses_repository.get_expenses_in_date_range(
        db_session=db_session,
        user_id=user_id,
        start_date=calendar_periods[0].period_start,
        end_date=calendar_periods[-1].period_end,
    )

    buckets: list[SpendingTrendBucket] = []

    for window in calendar_periods:
        effective_end = min(window.period_end, as_of)
        is_complete = window.period_end < as_of

        total_spent = BUCKET_AMOUNT_DECIMAL_PLACES
        expenses_count = 0
        unresolved_expenses_count = 0

        for expense in expenses:
            if expense.expense_date < window.period_start:
                continue

            if expense.expense_date > effective_end:
                # Excludes anything after this bucket's completed range,
                # and - for the current, incomplete bucket, where
                # effective_end == as_of - excludes future-dated Expenses.
                continue

            if expense.base_amount is None or expense.base_currency != base_currency:
                unresolved_expenses_count += 1
                continue

            total_spent += expense.base_amount
            expenses_count += 1

        buckets.append(
            SpendingTrendBucket(
                period_start=window.period_start,
                period_end=window.period_end,
                effective_end=effective_end,
                is_complete=is_complete,
                total_spent=total_spent,
                expenses_count=expenses_count,
                unresolved_expenses_count=unresolved_expenses_count,
            )
        )

    return SpendingTrendResponse(
        base_currency=base_currency,
        period=period,
        count=count,
        as_of=as_of,
        buckets=buckets,
        period_over_period=_build_period_over_period(buckets),
    )


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