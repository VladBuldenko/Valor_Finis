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