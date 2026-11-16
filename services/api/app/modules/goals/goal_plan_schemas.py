from datetime import date
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# Goal Planning preview (VF-GOALS-PLANNING-001): read-only and advisory.
# Nothing here is stored, scheduled or reserved, and nothing here says a plan
# is affordable: free cash flow is not modelled.

# Why the plan looks the way it does for this Goal right now.
# - archived: a retired Goal takes no contributions, so there is nothing to plan.
# - already_funded: remaining_amount is zero (reached or overfunded).
# - no_target_date: progress is shown, no required installment can be computed.
# - target_date_passed: the target date is before today.
# - ready: a target date today or later, so a required installment exists.
GoalPlanStatus = Literal[
    "archived",
    "already_funded",
    "no_target_date",
    "target_date_passed",
    "ready",
]

# What the hypothetical monthly contribution leads to.
# - reaches_target: a bounded, estimated completion date exists.
# - no_contribution: the amount is zero, so no date can be calculated.
# - not_reachable_within_horizon: it would take longer than horizon_months.
# - already_funded: nothing remains to fund.
# - not_applicable: the Goal is archived and takes no contributions.
GoalPlanWhatIfOutcome = Literal[
    "reaches_target",
    "no_contribution",
    "not_reachable_within_horizon",
    "already_funded",
    "not_applicable",
]


class GoalPlanRequest(BaseModel):
    """
    Optional hypothetical input for a Goal plan preview.

    What:
        monthly_contribution is the amount the user wants to try, per
        installment of the documented schedule. Omit it for the plan alone.

    Why:
        Invalid input is rejected with 422 (negative, more than 2 decimals,
        more than 12 digits, not a number, NaN or Infinity) so the
        calculation only ever sees a finite, exact, non-negative amount. Zero is accepted and
        answered with no_contribution. The upper bound matches the Goal
        target_amount column, so a large value is safe by construction.
    """

    model_config = ConfigDict(extra="forbid")

    monthly_contribution: Optional[Decimal] = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
        allow_inf_nan=False,
        description="Hypothetical amount contributed on each installment date.",
        examples=["150.00"],
    )


class GoalPlanWhatIf(BaseModel):
    """The estimate for the hypothetical monthly_contribution. Never a guarantee."""

    monthly_contribution: Decimal = Field(examples=["150.00"])
    outcome: GoalPlanWhatIfOutcome
    installments_needed: Optional[int] = Field(
        default=None,
        description="Installments (including today's) needed; null when no date can be calculated.",
    )
    estimated_completion_date: Optional[date] = Field(
        default=None,
        description="Date of the last needed installment on the documented schedule; null when none can be calculated.",
    )
    on_or_before_target_date: Optional[bool] = Field(
        default=None,
        description="Whether the estimated date is on or before target_date; null without a usable target date or estimate.",
    )


class GoalPlanResponse(BaseModel):
    """
    Read-only planning preview of one Goal.

    What:
        Progress, the remaining amount, the required installment up to the
        target date and an optional what-if estimate, all computed on the
        backend from the Goal's ledger-derived amounts.

    Why:
        current_amount is the SAME ledger-derived value every Goal response
        carries (tracked_amount + linked_amount); there is no second balance
        source. tracked_amount is progress with no claim on any Account;
        linked_amount is money reserved against Accounts. Neither is a
        bank transfer.

        Schedule (the one documented assumption): the first hypothetical
        installment is as_of (the server's today); the following ones fall on
        the first day of each next calendar month; only installments on or
        before target_date count. All amounts have 2 decimal places and the
        required installment is rounded UP to the cent.
    """

    goal_id: UUID
    currency: str
    goal_status: Literal["active", "completed", "archived"]
    as_of: date = Field(description="The server date the plan was worked out for.")

    target_amount: Decimal
    current_amount: Decimal
    tracked_amount: Decimal
    linked_amount: Decimal
    remaining_amount: Decimal = Field(description="max(target_amount - current_amount, 0).")
    overfunded_amount: Decimal = Field(description="max(current_amount - target_amount, 0).")

    target_date: Optional[date] = None
    plan_status: GoalPlanStatus

    installment_count: Optional[int] = Field(
        default=None,
        description="Installments from as_of to target_date on the schedule; set only when plan_status is ready.",
    )
    required_per_installment: Optional[Decimal] = Field(
        default=None,
        description="remaining_amount spread over installment_count, rounded UP to the cent; set only when plan_status is ready.",
    )
    first_installment_date: Optional[date] = None
    last_installment_date: Optional[date] = None

    horizon_months: int = Field(description="Longest projection the what-if will consider, in months.")
    what_if: Optional[GoalPlanWhatIf] = None
