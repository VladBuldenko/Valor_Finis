from datetime import date
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# Goal history comparison (VF-GOALS-PLANNING-002A): read-only and advisory.
# It sets the Goal plan's required installment next to the user's RECORDED
# income and expenses of the last completed months. It never says the
# installment is affordable and never reserves, schedules or moves money.

# - comparable: a historical average and a required installment exist in the
#   same currency, so historical_difference is set.
# - insufficient_data: too little (or unresolved) history to average safely.
# - currency_mismatch: the Goal's currency is not the user's base currency, in
#   which the recorded history is expressed; no figure is converted.
# - no_required_installment: the Goal plan has no required installment (for
#   example no target date, already funded, or archived).
GoalHistoryComparisonStatus = Literal[
    "comparable",
    "insufficient_data",
    "currency_mismatch",
    "no_required_installment",
]

# Why the comparison should be read with care. The two "not modelled" codes are
# always present; the others describe this particular history.
# - unresolved_currency_data: some Income/Expense in the analysed months has no
#   base-currency amount, so no average is shown.
# - fewer_than_two_active_months: fewer than two completed months have both
#   recorded Income and recorded Expenses, so no average is shown.
# - months_without_activity_excluded: an average is shown, but a month without
#   both recorded Income and Expenses was left out rather than counted as zero.
# - budgets_not_modelled: Budget limits are not treated as spending.
# - goal_commitments_not_modelled: existing Goal reservations and active
#   allocation rules are not subtracted.
GoalHistoryLimitation = Literal[
    "unresolved_currency_data",
    "fewer_than_two_active_months",
    "months_without_activity_excluded",
    "budgets_not_modelled",
    "goal_commitments_not_modelled",
]

# Surplus: recorded average is above the required installment; shortfall: below.
GoalHistoryDifferenceDirection = Literal["surplus", "equal", "shortfall"]


class GoalHistoryMonth(BaseModel):
    """One completed calendar month of recorded income and expenses."""

    period_start: date
    period_end: date
    income_total: Decimal = Field(description="Resolved Income in the base currency.")
    expense_total: Decimal = Field(description="Resolved Expenses in the base currency.")
    net_flow: Decimal = Field(description="income_total - expense_total; may be negative.")
    income_count: int = Field(ge=0)
    expense_count: int = Field(ge=0)
    unresolved_income_count: int = Field(ge=0)
    unresolved_expense_count: int = Field(ge=0)
    has_activity: bool = Field(
        description="True when the month has both recorded Income and recorded Expenses.",
    )
    included_in_average: bool = Field(
        description="True when this month contributes to the averages.",
    )


class GoalHistoryComparisonResponse(BaseModel):
    """
    Read-only comparison of a Goal's required installment with recorded history.

    What:
        The last three COMPLETED calendar months of recorded Income and
        Expenses (the current, incomplete month is never included), their
        averages, the Goal plan's required installment and, when everything is
        comparable, the difference.

    Why:
        Every figure comes from the same backend analytics (Income and
        Expense records only, base-currency amounts only) and the same Goal
        plan calculation the rest of the app uses. Account balances,
        opening balances, Transfers and Goal transactions are never read, so
        none of them can count as income or expenses. Averages cover only
        months with recorded activity; a month without records is excluded,
        never counted as zero. This is recorded past activity, not a forecast
        and not a guarantee that a contribution is affordable. All amounts
        have 2 decimal places.
    """

    goal_id: UUID
    as_of: date = Field(description="The server date the comparison was worked out for.")
    goal_currency: str
    base_currency: str = Field(description="The currency the recorded history is expressed in.")

    status: GoalHistoryComparisonStatus
    limitations: list[GoalHistoryLimitation]

    analysis_period_start: date = Field(description="First day of the oldest analysed month.")
    analysis_period_end: date = Field(description="Last day of the newest completed month.")
    months: list[GoalHistoryMonth] = Field(description="Exactly three completed months, oldest first.")
    months_used: int = Field(ge=0, description="Months that contribute to the averages (0 when none are shown).")

    average_monthly_income: Optional[Decimal] = Field(
        default=None,
        description="Sum of included months' income / months_used, rounded half-even to the cent.",
    )
    average_monthly_expenses: Optional[Decimal] = Field(default=None)
    average_monthly_net_flow: Optional[Decimal] = Field(
        default=None,
        description="Sum of included months' net flow / months_used, rounded once (may differ by one cent from income - expenses).",
    )

    required_per_installment: Optional[Decimal] = Field(
        default=None,
        description="The Goal plan's required installment, in goal_currency; null when the plan has none.",
    )
    historical_difference: Optional[Decimal] = Field(
        default=None,
        description="average_monthly_net_flow - required_per_installment; set only when status is comparable.",
    )
    difference_direction: Optional[GoalHistoryDifferenceDirection] = None
