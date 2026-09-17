from datetime import date
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MonthlySummaryResponse(BaseModel):
    """
    Schema for a high-level spending summary.

    What:
        Represents total spending and number of expenses.

    Why:
        Provides a simple dashboard overview for web and mobile clients.
    """

    total_spent: Decimal = Field(
        ...,
        description=(
            "Total spending in base_currency (VF-014B5D), summed from each "
            "resolved Expense's base_amount - never the original mixed-"
            "currency amount. Excludes unresolved legacy Expenses; see "
            "unresolved_expenses_count."
        ),
        examples=["250.75"],
    )

    expenses_count: int = Field(
        ...,
        ge=0,
        description=(
            "Number of resolved Expense records included in total_spent."
        ),
        examples=[12],
    )

    base_currency: str = Field(
        ...,
        description=(
            "The authoritative base currency (VF-014B5B) total_spent is "
            "denominated in, from the user's financial settings - never "
            "derived from whichever Expense happens to appear first."
        ),
        examples=["EUR"],
    )

    unresolved_expenses_count: int = Field(
        ...,
        ge=0,
        description=(
            "Number of matching legacy unresolved Expenses (base_amount is "
            "NULL) excluded from total_spent. Not counted as zero-valued - "
            "this makes incomplete legacy data explicit rather than silent. "
            "expenses_count + unresolved_expenses_count is the total number "
            "of matching Expenses for the period."
        ),
        examples=[0],
    )


class CategorySummaryItem(BaseModel):
    """
    Schema for spending summary grouped by category.

    What:
        Represents total spending and expense count for one category.

    Why:
        Helps the user understand where money is spent.
    """

    category_id: Optional[UUID] = Field(
        default=None,
        description="Category identifier. Null means uncategorized expenses.",
    )

    category_name: str = Field(
        ...,
        description="Human-readable category name.",
        examples=["Food"],
    )

    total_spent: Decimal = Field(
        ...,
        description=(
            "Total spending in base_currency (VF-014B5D) for this category, "
            "summed from each resolved Expense's base_amount - never the "
            "original mixed-currency amount. 0 when every matching Expense "
            "in this category is unresolved; see unresolved_expenses_count."
        ),
        examples=["120.50"],
    )

    expenses_count: int = Field(
        ...,
        ge=0,
        description=(
            "Number of resolved expenses in this category included in "
            "total_spent."
        ),
        examples=[5],
    )

    base_currency: str = Field(
        ...,
        description=(
            "The authoritative base currency (VF-014B5B) total_spent is "
            "denominated in, from the user's financial settings."
        ),
        examples=["EUR"],
    )

    unresolved_expenses_count: int = Field(
        ...,
        ge=0,
        description=(
            "Number of matching legacy unresolved Expenses (base_amount is "
            "NULL) in this category, excluded from total_spent. A category "
            "whose matching Expenses are all unresolved is still returned - "
            "with total_spent=0, expenses_count=0, and this field > 0 - "
            "rather than silently omitted."
        ),
        examples=[0],
    )


class BudgetStatusItem(BaseModel):
    """
    Schema for budget usage status.

    What:
        Represents how much was spent against a configured budget.

    Why:
        Helps the user see remaining budget and exceeded amounts.
    """

    budget_id: UUID = Field(
        ...,
        description="Budget identifier.",
    )

    budget_name: str = Field(
        ...,
        description="Human-readable budget name.",
        examples=["Monthly groceries"],
    )

    category_id: Optional[UUID] = Field(
        default=None,
        description=(
            "Category identifier scoping this budget, resolved from the "
            "BudgetVersion applicable to the current period."
        ),
    )

    category_name: str = Field(
        ...,
        description="Human-readable category name or Uncategorized.",
        examples=["Food"],
    )

    period: Literal["weekly", "monthly", "yearly"] = Field(
        ...,
        description="Recurrence unit this budget resets on.",
        examples=["monthly"],
    )

    period_start: date = Field(
        ...,
        description="Inclusive start of the calendar period this status covers.",
        examples=["2026-09-01"],
    )

    period_end: date = Field(
        ...,
        description="Inclusive end of the calendar period this status covers.",
        examples=["2026-09-30"],
    )

    effective_start: date = Field(
        ...,
        description=(
            "period_start clamped to the budget's activation date - where "
            "spending is actually counted from."
        ),
        examples=["2026-09-01"],
    )

    effective_end: date = Field(
        ...,
        description=(
            "period_end clamped to the budget's deactivation date, if any."
        ),
        examples=["2026-09-30"],
    )

    period_state: Literal["not_started", "active", "ended"] = Field(
        ...,
        description="Whether the budget's activation window has started/ended.",
        examples=["active"],
    )

    is_partial_period: bool = Field(
        ...,
        description=(
            "True when the budget's activation or deactivation date clips "
            "this calendar period."
        ),
        examples=[False],
    )

    limit_amount: Decimal = Field(
        ...,
        description=(
            "Limit in effect for this period, resolved from BudgetVersion "
            "history rather than the budget's current value."
        ),
        examples=["400.00"],
    )

    spent: Decimal = Field(
        ...,
        description="Amount already spent within the budget period.",
        examples=["250.00"],
    )

    remaining: Decimal = Field(
        ...,
        description="Amount still available before exceeding the budget.",
        examples=["150.00"],
    )

    exceeded_amount: Decimal = Field(
        ...,
        description="Amount by which the budget was exceeded.",
        examples=["0.00"],
    )

    utilization_percent: Decimal = Field(
        ...,
        description=(
            "spent / limit_amount * 100. Not clamped - an exceeded budget "
            "can read above 100."
        ),
        examples=["62.50"],
    )

    is_exceeded: bool = Field(
        ...,
        description="Shows whether spending is greater than the budget limit.",
        examples=[False],
    )

    days_in_period: int = Field(
        ...,
        description=(
            "Length of the effective budget window, inclusive. A partial "
            "first/final period uses the partial length, not the full "
            "calendar month/week/year."
        ),
        examples=[30],
    )

    days_elapsed: int = Field(
        ...,
        description=(
            "Effective days counted so far. 0 for not_started; equals "
            "days_in_period for ended."
        ),
        examples=[16],
    )

    days_remaining: int = Field(
        ...,
        description=(
            "Effective spending days left. For an active budget this "
            "includes today (days_in_period - days_elapsed + 1) - today is "
            "both an elapsed day and still a day the user may spend on."
        ),
        examples=[15],
    )

    average_daily_spending: Decimal = Field(
        ...,
        description="spent divided by the days that produced it.",
        examples=["15.63"],
    )

    daily_spending_allowance: Decimal = Field(
        ...,
        description=(
            "Remaining budget divided across remaining spending days. "
            "0.00 once a budget is exceeded or has ended."
        ),
        examples=["10.00"],
    )

    projected_spending: Optional[Decimal] = Field(
        default=None,
        description=(
            "Simple current-period linear pace projection "
            "(spent / days_elapsed * days_in_period). Never capped at "
            "limit_amount. Null for not_started (no observed pace yet). "
            "This is a current-period pace estimate, not a historical "
            "forecast - see VF-015 for pattern-aware forecasting."
        ),
        examples=["580.00"],
    )

    projected_surplus: Optional[Decimal] = Field(
        default=None,
        description=(
            "max(limit_amount - projected_spending, 0). Null exactly when "
            "projected_spending is null."
        ),
        examples=["20.00"],
    )

    projected_deficit: Optional[Decimal] = Field(
        default=None,
        description=(
            "max(projected_spending - limit_amount, 0). Null exactly when "
            "projected_spending is null."
        ),
        examples=["0.00"],
    )

    risk_status: Literal["healthy", "watch", "at_risk", "exceeded"] = Field(
        ...,
        description=(
            "Deterministic pace-based status: exceeded (spent > limit) "
            "always wins; otherwise healthy for not_started/ended, and for "
            "active budgets, projected utilization <=90% is healthy, "
            ">90-100% is watch, >100% is at_risk."
        ),
        examples=["healthy"],
    )


class GoalProgressItem(BaseModel):
    """
    Schema for financial goal progress.

    What:
        Represents saved amount, remaining amount, and progress percentage.

    Why:
        Helps the user understand how close they are to reaching a goal.
    """

    goal_id: UUID = Field(
        ...,
        description="Financial goal identifier.",
    )

    name: str = Field(
        ...,
        description="Financial goal name.",
        examples=["Vacation"],
    )

    target_amount: Decimal = Field(
        ...,
        description="Target amount required to complete the goal.",
        examples=["2000.00"],
    )

    current_amount: Decimal = Field(
        ...,
        description="Amount already saved toward the goal.",
        examples=["500.00"],
    )

    remaining_amount: Decimal = Field(
        ...,
        description="Amount still needed to reach the goal.",
        examples=["1500.00"],
    )

    progress_percent: Decimal = Field(
        ...,
        description="Goal completion percentage from 0 to 100.",
        examples=["25.00"],
    )

    status: str = Field(
        ...,
        description="Current goal status.",
        examples=["active"],
    )

    target_date: Optional[date] = Field(
        default=None,
        description="Optional target date for reaching the goal.",
        examples=["2026-12-31"],
    )


class SpendingTrendBucket(BaseModel):
    """
    Schema for one calendar bucket in a spending trend series (VF-015B).

    What:
        Base-currency spending totals for one day/week/month bucket.

    Why:
        Lets a client render a continuous historical series without
        reconstructing missing dates itself - every requested calendar
        bucket is always present, including buckets with no Expenses.
    """

    period_start: date = Field(
        ...,
        description="Inclusive calendar start of this bucket.",
        examples=["2026-09-01"],
    )

    period_end: date = Field(
        ...,
        description=(
            "Inclusive calendar end of this bucket (full period length, "
            "regardless of whether the period has completed)."
        ),
        examples=["2026-09-30"],
    )

    effective_end: date = Field(
        ...,
        description="min(period_end, as_of) - where spending is actually counted through.",
        examples=["2026-09-17"],
    )

    is_complete: bool = Field(
        ...,
        description="True when period_end is before as_of - i.e. this bucket's period has fully elapsed.",
        examples=[False],
    )

    total_spent: Decimal = Field(
        ...,
        description=(
            "Base-currency total for this bucket, summed from each resolved "
            "Expense's persisted base_amount (VF-014B5D) - never the "
            "original mixed-currency amount, never recomputed from fx_rate. "
            "0.00 for a bucket with no resolved Expenses, including one "
            "with no Expenses at all."
        ),
        examples=["100.00"],
    )

    expenses_count: int = Field(
        ...,
        ge=0,
        description="Number of resolved Expenses included in total_spent.",
        examples=[2],
    )

    unresolved_expenses_count: int = Field(
        ...,
        ge=0,
        description=(
            "Number of matching legacy unresolved Expenses (base_amount is "
            "NULL), or resolved Expenses whose persisted base_currency no "
            "longer matches the user's current base_currency, excluded from "
            "total_spent. Never treated as zero-valued."
        ),
        examples=[0],
    )


class PeriodOverPeriodComparison(BaseModel):
    """
    Schema for a comparison between the two most recent COMPLETE buckets in
    a spending trend series (VF-015B).

    What:
        Absolute/percentage change and direction between two fully-elapsed
        calendar periods.

    Why:
        Comparing an in-progress (incomplete) current period against a full
        previous one would always read as "down" purely because the current
        period hasn't finished yet - this only ever compares two periods
        that have both fully elapsed.
    """

    current_period_start: date = Field(..., examples=["2026-08-01"])
    current_period_end: date = Field(..., examples=["2026-08-31"])
    previous_period_start: date = Field(..., examples=["2026-07-01"])
    previous_period_end: date = Field(..., examples=["2026-07-31"])

    current_total_spent: Decimal = Field(..., examples=["150.00"])
    previous_total_spent: Decimal = Field(..., examples=["100.00"])

    absolute_change: Decimal = Field(
        ...,
        description="current_total_spent - previous_total_spent.",
        examples=["50.00"],
    )

    percent_change: Optional[Decimal] = Field(
        default=None,
        description=(
            "((current - previous) / previous) * 100. Null when "
            "previous_total_spent is 0 - percentage change is mathematically "
            "undefined there, never reported as infinity, 100, or 0."
        ),
        examples=["50.00"],
    )

    direction: Literal["up", "down", "unchanged"] = Field(
        ...,
        description="up when absolute_change > 0, down when < 0, unchanged when exactly 0.",
        examples=["up"],
    )


class SpendingTrendResponse(BaseModel):
    """
    Schema for a bounded historical spending time series (VF-015B).

    What:
        A day/week/month series of base-currency spending buckets ending
        with the period containing as_of, plus a comparison between the two
        most recent complete buckets.

    Why:
        Historical spending analytics, distinct from Budget Status
        (per-Budget, original-currency-matched, current-period-only) and
        from monthly/category summary (single-period only). Never performs
        FX/network calls - reads only already-persisted base_amount.
    """

    base_currency: str = Field(
        ...,
        description="The user's authoritative base currency (VF-014B5B), from financial settings.",
        examples=["EUR"],
    )

    period: Literal["day", "week", "month"] = Field(
        ...,
        description="The calendar bucket size requested.",
        examples=["month"],
    )

    count: int = Field(
        ...,
        ge=1,
        description="Number of buckets returned.",
        examples=[6],
    )

    as_of: date = Field(
        ...,
        description="Server reference date the series was resolved against.",
        examples=["2026-09-17"],
    )

    buckets: list[SpendingTrendBucket] = Field(
        ...,
        description="Chronologically ordered (oldest first), always exactly `count` buckets.",
    )

    period_over_period: Optional[PeriodOverPeriodComparison] = Field(
        default=None,
        description="Null when fewer than two complete buckets exist in the returned series.",
    )


class CategoryTrendItem(BaseModel):
    """
    Schema for one category's historical spending trend (VF-015C).

    What:
        A day/week/month bucket series and period-over-period comparison,
        scoped to a single category (or Uncategorized).

    Why:
        Reuses SpendingTrendBucket and PeriodOverPeriodComparison exactly
        as-is - a category's trend has identical bucket/comparison
        semantics to the overall spending trend, just scoped to one
        category's Expenses.
    """

    category_id: Optional[UUID] = Field(
        default=None,
        description="Category identifier. Null means Uncategorized.",
    )

    category_name: str = Field(
        ...,
        description=(
            "Human-readable category name, or \"Uncategorized\" when "
            "category_id is null. A category deleted after an Expense was "
            "recorded against it - Expense.category_id is set NULL by the "
            "database - has no recoverable historical name: those "
            "Expenses appear under Uncategorized from that point on, not "
            "under the deleted category's former name."
        ),
        examples=["Food"],
    )

    buckets: list[SpendingTrendBucket] = Field(
        ...,
        description="Chronologically ordered (oldest first), always exactly `count` buckets.",
    )

    period_over_period: Optional[PeriodOverPeriodComparison] = Field(
        default=None,
        description="Null when fewer than two complete buckets exist for this category.",
    )


class CategoryTrendResponse(BaseModel):
    """
    Schema for bounded historical spending trends grouped by category
    (VF-015C).

    What:
        A day/week/month series per category, each with its own
        period-over-period comparison.

    Why:
        Answers "how has spending in each category moved over time,"
        distinct from Category Summary (single period only) and Spending
        Trend (not broken down by category).
    """

    base_currency: str = Field(
        ...,
        description="The user's authoritative base currency (VF-014B5B), from financial settings.",
        examples=["EUR"],
    )

    period: Literal["day", "week", "month"] = Field(
        ...,
        description="The calendar bucket size requested.",
        examples=["month"],
    )

    count: int = Field(
        ...,
        ge=1,
        description="Number of buckets returned per category.",
        examples=[6],
    )

    as_of: date = Field(
        ...,
        description="Server reference date the series was resolved against.",
        examples=["2026-09-17"],
    )

    categories: list[CategoryTrendItem] = Field(
        ...,
        description=(
            "Categories with at least one matching Expense in the "
            "requested range (present even if every matching Expense is "
            "unresolved/incompatible-currency), ordered by category_name "
            "case-insensitive ascending with category_id as a "
            "deterministic tie-breaker. When category_id was supplied and "
            "owned by the caller, contains exactly that one category, "
            "even with zero matching Expenses."
        ),
    )


class SpendingForecastResponse(BaseModel):
    """
    Schema for a deterministic current-month spending pace projection
    (VF-015D).

    What:
        A linear-run-rate projection of the authenticated user's total
        base-currency spending for the calendar month containing today,
        built only from already-persisted, already-resolved Expense data.

    Why:
        This is CURRENT-MONTH SPENDING PACE PROJECTION only - it is not a
        cash-flow, income, savings, or net-worth forecast, and it does not
        use historical months, seasonality, or any model beyond the single
        documented linear_run_rate formula. See method below.
    """

    base_currency: str = Field(
        ...,
        description="The user's authoritative base currency (VF-014B5B), from financial settings.",
        examples=["EUR"],
    )

    method: Literal["linear_run_rate"] = Field(
        ...,
        description=(
            "The forecast model used. Always \"linear_run_rate\" today - "
            "spent_to_date / days_elapsed * days_in_month. Exposed "
            "explicitly so a future model can be added later without "
            "implying today's model is more sophisticated than it is."
        ),
        examples=["linear_run_rate"],
    )

    forecast_status: Literal["available", "incomplete_data"] = Field(
        ...,
        description=(
            "\"available\" when every matching current-month Expense has "
            "a resolved base-currency amount - a month with zero Expenses "
            "is \"available\" with a 0.00 projection, which is valid for "
            "a linear pace model. \"incomplete_data\" when at least one "
            "matching Expense is unresolved or persisted against an "
            "incompatible base_currency - a projection is never computed "
            "from known-incomplete monetary data; average_daily_spending "
            "and projected_spending are both null in that case."
        ),
        examples=["available"],
    )

    period_start: date = Field(
        ...,
        description="First calendar day of the month containing as_of.",
        examples=["2026-09-01"],
    )

    period_end: date = Field(
        ...,
        description="Last calendar day of the month containing as_of.",
        examples=["2026-09-30"],
    )

    as_of: date = Field(
        ...,
        description="Server reference date the forecast was resolved against.",
        examples=["2026-09-17"],
    )

    days_in_month: int = Field(
        ...,
        ge=1,
        description="Inclusive total number of calendar days in the month.",
        examples=[30],
    )

    days_elapsed: int = Field(
        ...,
        ge=1,
        description="Inclusive day count from period_start through as_of. Always >= 1.",
        examples=[17],
    )

    spent_to_date: Decimal = Field(
        ...,
        description=(
            "Base-currency spending from period_start through as_of "
            "(inclusive), summed from each resolved Expense's persisted "
            "base_amount (VF-014B5C/B5D) - never the original mixed-"
            "currency amount, never recomputed from fx_rate. Always "
            "populated, even when forecast_status is \"incomplete_data\" - "
            "it reflects resolved spending only in that case."
        ),
        examples=["500.00"],
    )

    expenses_count: int = Field(
        ...,
        ge=0,
        description="Number of resolved Expenses included in spent_to_date.",
        examples=[8],
    )

    unresolved_expenses_count: int = Field(
        ...,
        ge=0,
        description=(
            "Number of matching current-month Expenses excluded from "
            "spent_to_date because they are unresolved (base_amount is "
            "NULL) or persisted against an incompatible base_currency. "
            "Any value > 0 makes forecast_status \"incomplete_data\"."
        ),
        examples=[0],
    )

    average_daily_spending: Optional[Decimal] = Field(
        default=None,
        description=(
            "spent_to_date / days_elapsed, quantized to money precision. "
            "Null exactly when forecast_status is \"incomplete_data\"."
        ),
        examples=["29.41"],
    )

    projected_spending: Optional[Decimal] = Field(
        default=None,
        description=(
            "Linear projection over the full month: computed from the "
            "full-precision daily rate (never from the already-quantized "
            "average_daily_spending value above), then quantized once to "
            "money precision. Never capped, dampened, or smoothed - a "
            "large expense early in the month can make this volatile by "
            "design, matching Budget Status's identical linear model. "
            "Null exactly when forecast_status is \"incomplete_data\"."
        ),
        examples=["882.35"],
    )