from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core import calendar_period
from app.modules.analytics import analytics_forecast
from app.modules.analytics.analytics_schemas import (
    BudgetStatusItem,
    CategorySummaryItem,
    CategoryTrendItem,
    CategoryTrendResponse,
    GoalProgressItem,
    MonthlySummaryResponse,
    PeriodOverPeriodComparison,
    SpendingForecastResponse,
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
from app.modules.goals import goal_transaction_repository


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


# Builds one calendar-bucket series (VF-015B/C) from an already-filtered
# list of Expenses.
# This function exists as the single place that turns "a set of Expenses"
# into "a base-currency bucket series" - both get_spending_trend (the
# user's whole spending) and get_category_trend (one category's spending)
# need exactly this same per-bucket resolved/unresolved-FX/future-date
# logic, and previously diverging copies would be a real correctness risk
# (a fix applied to one and not the other).
#
# effective_end = min(period_end, as_of) is used as the inclusive upper
# bound for every bucket, uniformly - this is what keeps a future-dated
# Expense from leaking into the current (incomplete) bucket without any
# special-casing: for a complete bucket effective_end already equals
# period_end, so the same filter is exactly right for both cases.
# Parameters:
# - calendar_periods: chronologically ordered (oldest first) calendar
#   buckets from calendar_period.resolve_recent_periods.
# - expenses: Expenses already scoped to whatever this series represents
#   (all of the user's Expenses in range, or one category's).
# - base_currency: the user's authoritative base currency.
# - as_of: reference date the series ends on.
# Returns:
# - list[SpendingTrendBucket], one per calendar_periods entry, in the
#   same chronological order.
def _build_spending_trend_buckets(
    calendar_periods: list[calendar_period.CalendarPeriod],
    expenses: list,
    base_currency: str,
    as_of: date,
) -> list[SpendingTrendBucket]:
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

    return buckets


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

    buckets = _build_spending_trend_buckets(
        calendar_periods=calendar_periods,
        expenses=expenses,
        base_currency=base_currency,
        as_of=as_of,
    )

    return SpendingTrendResponse(
        base_currency=base_currency,
        period=period,
        count=count,
        as_of=as_of,
        buckets=buckets,
        period_over_period=_build_period_over_period(buckets),
    )


# Calculates bounded historical base-currency spending trends grouped by
# category for the authenticated user (VF-015C).
# This function exists to answer "how has spending in each category moved
# over time," reusing get_spending_trend's bucket-building and comparison
# logic per category rather than duplicating it.
#
# A single bounded Expense query covers the whole requested range (never
# get_expenses(user_id), never one query per category or per bucket) -
# Expenses are grouped by category_id once, then each category's buckets
# are built from its own pre-filtered subset, so total work stays
# proportional to (buckets x matching Expenses), not
# (buckets x categories x Expenses).
#
# A category appears in the response only when it has at least one
# matching Expense in the requested range - including when every matching
# Expense is unresolved/incompatible-currency, so incomplete legacy data
# is never silently hidden. A category with zero Expenses anywhere in the
# range is never returned, unless it was explicitly requested via
# category_id (in which case it is always returned, with all-zero
# buckets). Expenses whose category was later deleted have
# category_id NULL (enforced by the FK) and appear under Uncategorized -
# VF-015C does not attempt to recover a deleted category's historical name.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter expenses/categories.
# - period: one of "day", "week", "month".
# - count: number of buckets to return per category. Must be >= 1;
#   upper-bound validation is the router's responsibility.
# - as_of: reference date the series ends on. The caller (the router) is
#   responsible for defaulting this to today.
# - category_id: optional. When provided, must be owned by user_id (raises
#   CategoryNotFoundError otherwise, the same convention every other
#   category-ownership check in this codebase uses - this never reveals
#   whether a category owned by a different user exists). When provided,
#   the response contains exactly that one category. Omit for Uncategorized -
#   there is no separate sentinel value for it.
# Returns:
# - CategoryTrendResponse with one CategoryTrendItem per matching category,
#   ordered by category_name (case-insensitive) then category_id.
# Raises:
# - CategoryNotFoundError: category_id is set and not owned by user_id.
def get_category_trend(
    db_session: Session,
    user_id: UUID,
    period: str,
    count: int,
    as_of: date,
    category_id: Optional[UUID] = None,
) -> CategoryTrendResponse:
    base_currency = financial_settings_service.get_base_currency(
        db_session=db_session,
        user_id=user_id,
    )

    if category_id is not None:
        # Ownership/existence check up front - fails before doing any
        # further work, and never distinguishes "doesn't exist" from
        # "belongs to someone else."
        categories_repository.get_category_by_id(
            db_session=db_session,
            category_id=category_id,
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

    if category_id is not None:
        expenses = [expense for expense in expenses if expense.category_id == category_id]

    expenses_by_category_id: dict[Optional[UUID], list] = defaultdict(list)
    for expense in expenses:
        expenses_by_category_id[expense.category_id].append(expense)

    if category_id is not None and category_id not in expenses_by_category_id:
        # A valid, owned category with zero matching Expenses in range is
        # still returned, with all-zero buckets - never omitted.
        expenses_by_category_id[category_id] = []

    category_name_map = build_category_name_map(
        db_session=db_session,
        user_id=user_id,
    )

    ordered_category_ids = sorted(
        expenses_by_category_id.keys(),
        key=lambda candidate_id: (
            get_category_name(candidate_id, category_name_map).casefold(),
            str(candidate_id) if candidate_id is not None else "",
        ),
    )

    categories: list[CategoryTrendItem] = []

    for candidate_id in ordered_category_ids:
        buckets = _build_spending_trend_buckets(
            calendar_periods=calendar_periods,
            expenses=expenses_by_category_id[candidate_id],
            base_currency=base_currency,
            as_of=as_of,
        )

        categories.append(
            CategoryTrendItem(
                category_id=candidate_id,
                category_name=get_category_name(candidate_id, category_name_map),
                buckets=buckets,
                period_over_period=_build_period_over_period(buckets),
            )
        )

    return CategoryTrendResponse(
        base_currency=base_currency,
        period=period,
        count=count,
        as_of=as_of,
        categories=categories,
    )


# Calculates a deterministic current-month spending pace projection for
# the authenticated user (VF-015D).
# This function exists to answer "at my current pace, what will I spend
# this calendar month" - CURRENT-MONTH SPENDING PACE PROJECTION only, not
# a cash-flow/income/savings/net-worth forecast. Loads/resolves data here;
# the actual linear_run_rate formula lives in analytics_forecast.py, kept
# pure and independently testable (mirroring budget_metrics.py's
# separation for Budget Status's identical linear model).
#
# The Expense query is bounded to [period_start, as_of] - not period_end -
# so a future-dated Expense within the same calendar month (allowed for a
# base-currency identity conversion) can never affect the pace; there is
# no need to additionally filter by date in the aggregation loop below,
# unlike Spending/Category Trend's per-bucket effective_end clamping.
#
# Any unresolved (base_amount is None) or incompatible-base_currency
# Expense in range makes the whole forecast unavailable
# (forecast_status="incomplete_data", average_daily_spending and
# projected_spending both null) rather than silently projecting from
# known-incomplete monetary data - spent_to_date/expenses_count/
# unresolved_expenses_count are still always populated regardless.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter expenses.
# - as_of: reference date the forecast covers the calendar month of. The
#   caller (the router) is responsible for defaulting this to today - this
#   function stays a pure, deterministic function of its arguments,
#   matching get_budget_status's as_of convention.
# Returns:
# - SpendingForecastResponse for the calendar month containing as_of.
def get_spending_forecast(
    db_session: Session,
    user_id: UUID,
    as_of: date,
) -> SpendingForecastResponse:
    base_currency = financial_settings_service.get_base_currency(
        db_session=db_session,
        user_id=user_id,
    )

    month_window = calendar_period.resolve_period_bounds(
        period=calendar_period.MONTH,
        as_of=as_of,
    )
    period_start = month_window.period_start
    period_end = month_window.period_end
    days_in_month = (period_end - period_start).days + 1
    days_elapsed = (as_of - period_start).days + 1

    expenses = expenses_repository.get_expenses_in_date_range(
        db_session=db_session,
        user_id=user_id,
        start_date=period_start,
        end_date=as_of,
    )

    spent_to_date = BUCKET_AMOUNT_DECIMAL_PLACES
    expenses_count = 0
    unresolved_expenses_count = 0

    for expense in expenses:
        if expense.base_amount is None or expense.base_currency != base_currency:
            unresolved_expenses_count += 1
            continue

        spent_to_date += expense.base_amount
        expenses_count += 1

    forecast = analytics_forecast.calculate_spending_forecast(
        spent_to_date=spent_to_date,
        days_elapsed=days_elapsed,
        days_in_month=days_in_month,
        data_complete=(unresolved_expenses_count == 0),
    )

    return SpendingForecastResponse(
        base_currency=base_currency,
        method="linear_run_rate",
        forecast_status=forecast.forecast_status,
        period_start=period_start,
        period_end=period_end,
        as_of=as_of,
        days_in_month=days_in_month,
        days_elapsed=days_elapsed,
        spent_to_date=spent_to_date,
        expenses_count=expenses_count,
        unresolved_expenses_count=unresolved_expenses_count,
        average_daily_spending=forecast.average_daily_spending,
        projected_spending=forecast.projected_spending,
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
# current_amount is ledger-derived (VF-016D): the Goal row has no balance
# column at all (VF-016G), so one bulk grouped query fetches every one of
# the user's goal balances up front (the same repository call GoalResponse
# read paths use), never issuing one balance query per Goal no matter how
# many goals the user has.
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

    balances = goal_transaction_repository.get_ledger_balances_for_user(
        db_session=db_session,
        user_id=user_id,
    )

    goal_progress_items = []

    for goal in goals:
        current_amount = balances.get(goal.id, Decimal("0.00"))

        goal_progress_items.append(
            GoalProgressItem(
                goal_id=goal.id,
                name=goal.name,
                target_amount=goal.target_amount,
                current_amount=current_amount,
                remaining_amount=max(
                    goal.target_amount - current_amount,
                    Decimal("0"),
                ),
                progress_percent=(
                    current_amount / goal.target_amount * Decimal("100")
                ).quantize(Decimal("0.01")),
                status=goal.status,
                target_date=goal.target_date,
            )
        )

    return goal_progress_items