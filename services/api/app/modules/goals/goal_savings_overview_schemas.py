from datetime import date
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.goals.goal_history_schemas import GoalHistoryDifferenceDirection, GoalHistoryMonth


# Combined Goal savings overview (VF-GOALS-PLANNING-002B): read-only and
# advisory. It adds up the HYPOTHETICAL required installments the existing Goal
# plan (VF-GOALS-PLANNING-001) calculates for each planned Goal, month by month
# for a bounded window, and sets them next to the user's RECORDED history
# (VF-GOALS-PLANNING-002A). It never schedules, reserves or moves money, and it
# never says a contribution is affordable.

# Why a Goal is not part of the numeric totals.
# - archived / completed: only active Goals are planned.
# - already_funded: nothing remains to fund (reached or overfunded).
# - no_target_date / target_date_passed: UNPLANNED, not "zero savings needed";
#   the Goal needs a (future) target date before an installment exists.
# - other_currency: the Goal is not in the user's base currency; nothing is
#   converted, so it is left out and the total is incomplete.
GoalSavingsExclusionReason = Literal[
    "archived",
    "completed",
    "already_funded",
    "no_target_date",
    "target_date_passed",
    "other_currency",
]

# What the history comparison produced.
# - comparable: a usable historical average and at least one planned Goal.
# - insufficient_data: planned Goals exist, but the recorded history is too
#   thin or unresolved to average safely.
# - no_planned_goals: there is no installment to compare.
GoalSavingsComparisonStatus = Literal[
    "comparable",
    "insufficient_data",
    "no_planned_goals",
]

# Why the overview should be read with care. The last three codes are always
# present; the others describe this particular situation.
# - unresolved_currency_data / fewer_than_two_active_months /
#   months_without_activity_excluded: history data quality (as in 002A).
# - other_currency_goals_excluded: the total leaves out Goals in another
#   currency, so it is incomplete.
# - goals_without_target_date / goals_with_passed_target_date: active Goals
#   that are unplanned.
# - budgets_not_modelled: Budget limits are not treated as spending.
# - goal_commitments_not_modelled: existing reservations and active allocation
#   rules are neither subtracted nor counted as future contributions.
# - future_obligations_not_modelled: future recurring bills and other
#   obligations are not modelled.
GoalSavingsLimitation = Literal[
    "unresolved_currency_data",
    "fewer_than_two_active_months",
    "months_without_activity_excluded",
    "other_currency_goals_excluded",
    "goals_without_target_date",
    "goals_with_passed_target_date",
    "budgets_not_modelled",
    "goal_commitments_not_modelled",
    "future_obligations_not_modelled",
]


class GoalSavingsPlannedGoal(BaseModel):
    """One Goal that contributes a required installment, in display (priority) order."""

    goal_id: UUID
    name: str
    priority_rank: Optional[int] = Field(default=None, description="1 = highest.")
    target_date: date
    remaining_amount: Decimal
    installment_count: int = Field(ge=1, description="Installments from as_of to target_date.")
    required_per_installment: Decimal = Field(description="The Goal plan's own installment, rounded up to the cent.")
    first_installment_date: date
    last_installment_date: date
    continues_after_window: bool = Field(
        description="True when installments continue after the last month of the overview window.",
    )


class GoalSavingsContribution(BaseModel):
    """One planned Goal's hypothetical installment in one month."""

    goal_id: UUID
    amount: Decimal


class GoalSavingsMonth(BaseModel):
    """One calendar month of the planning window."""

    period_start: date = Field(description="First day of the calendar month.")
    period_end: date = Field(description="Last day of the calendar month.")
    installment_date: date = Field(
        description="The date of this month's installments: as_of for the current month, else the 1st.",
    )
    total_required: Decimal = Field(description="Sum of the planned Goals' installments in this month.")
    planned_goal_count: int = Field(ge=0, description="Goals with an installment in this month.")
    contributions: list[GoalSavingsContribution] = Field(description="Goal-level breakdown, in display order.")
    historical_difference: Optional[Decimal] = Field(
        default=None,
        description="average_monthly_net_flow - total_required for THIS month; set only when the comparison is comparable and a Goal has an installment in this month.",
    )
    difference_direction: Optional[GoalHistoryDifferenceDirection] = None


class GoalSavingsExclusions(BaseModel):
    """How many Goals are not part of the numeric totals, by reason."""

    archived: int = Field(ge=0)
    completed: int = Field(ge=0)
    already_funded: int = Field(ge=0)
    no_target_date: int = Field(ge=0)
    target_date_passed: int = Field(ge=0)
    other_currency: int = Field(ge=0)
    other_currencies: list[str] = Field(description="The distinct currencies of the other_currency Goals, sorted.")


class GoalSavingsHistory(BaseModel):
    """The recorded history the months are compared with (the same rules as 002A)."""

    status: GoalSavingsComparisonStatus
    analysis_period_start: date = Field(description="First day of the oldest analysed month.")
    analysis_period_end: date = Field(description="Last day of the newest completed month.")
    months: list[GoalHistoryMonth] = Field(description="Exactly three completed months, oldest first.")
    months_used: int = Field(ge=0)
    average_monthly_income: Optional[Decimal] = None
    average_monthly_expenses: Optional[Decimal] = None
    average_monthly_net_flow: Optional[Decimal] = None


class GoalSavingsOverviewResponse(BaseModel):
    """
    Read-only overview of the user's combined Goal savings requirements.

    What:
        For a bounded window of calendar months starting with the current one,
        the combined hypothetical installment of every planned Goal, which
        Goals contribute, which Goals are left out and why, and how each
        month compares with the recorded average monthly net flow.

    Why:
        Each Goal is judged on its own in the Goal plan; this shows what they
        add up to, because every Goal may look reasonable alone while the
        combination exceeds recorded history. Every installment is the Goal
        plan's own calculation (the schedule is unchanged: one installment
        today, one on the 1st of each following month, none after the target
        date, so a Goal stops contributing once its target date is reached).
        Only Goals in the base currency are added up; nothing is converted, and
        other-currency Goals are reported as excluded, which makes the total
        incomplete. Tracked progress and linked reservations are existing
        progress, never a new monthly expense; target amounts are never
        summed. These are hypothetical required installments, not scheduled
        payments: nothing is transferred or reserved, and enabled allocation
        rules are not counted as future contributions. Budgets, recurring
        bills and other obligations are not modelled. All amounts have 2
        decimal places; the arithmetic is exact.
    """

    as_of: date = Field(description="The server date the overview was worked out for.")
    base_currency: str = Field(description="The currency every figure here is expressed in.")
    horizon_months: int = Field(description="Number of calendar months in the window, including the current one.")
    is_total_complete: bool = Field(
        description="False when Goals in another currency were left out of the totals.",
    )
    planned_goals: list[GoalSavingsPlannedGoal] = Field(description="In display (priority) order.")
    months: list[GoalSavingsMonth] = Field(description="Exactly horizon_months months, current month first.")
    exclusions: GoalSavingsExclusions
    history: GoalSavingsHistory
    limitations: list[GoalSavingsLimitation]
