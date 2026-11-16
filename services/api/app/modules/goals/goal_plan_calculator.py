from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from app.core.calendar_period import MONTH, next_period_start
from app.modules.goals.goal_plan_schemas import (
    GoalPlanResponse,
    GoalPlanStatus,
    GoalPlanWhatIf,
)

# Goal Planning (VF-GOALS-PLANNING-001): pure, deterministic arithmetic with no
# database, clock or HTTP access, so every rule below is unit-testable.
#
# THE SCHEDULE (the single documented assumption)
# - installment 1 is as_of (today);
# - installment k > 1 is the first day of the calendar month k-1 months after
#   as_of's month (the calendar helper next_period_start handles December and
#   leap years);
# - only installments on or before the target date count.
# Everything is advisory: no transaction, reservation or payment is created,
# and nothing here claims a plan is affordable.
#
# MONEY
# All amounts are Decimal with 2 decimal places (the ledger's precision, for
# every currency). The arithmetic runs on integer cents so division and
# rounding are exact: no float, and no dependence on the Decimal context.

# The longest what-if projection: 50 years of monthly installments. A tiny
# contribution therefore ends in "not reachable", never in a long loop.
HORIZON_MONTHS = 600

_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


# Converts a 2-decimal Decimal amount to integer cents.
# Raises ValueError for an amount with more precision, so a bad input can
# never be silently rounded.
def _to_cents(amount: Decimal) -> int:
    scaled = amount * 100

    if scaled != scaled.to_integral_value():
        raise ValueError("amount has more than 2 decimal places")

    return int(scaled)


# Converts integer cents back to a Decimal with exactly 2 decimal places.
def _from_cents(cents: int) -> Decimal:
    return (Decimal(cents) / 100).quantize(_CENT)


# remaining = max(target - current, 0): an overfunded Goal has zero remaining,
# never a negative amount.
def remaining_amount(target_amount: Decimal, current_amount: Decimal) -> Decimal:
    return max(target_amount - current_amount, _ZERO).quantize(_CENT)


# How much the Goal is over its target (zero when not overfunded).
def overfunded_amount(target_amount: Decimal, current_amount: Decimal) -> Decimal:
    return max(current_amount - target_amount, _ZERO).quantize(_CENT)


# The number of installments from as_of up to and including target_date.
# 0 when target_date is before as_of; 1 when it is as_of itself or any later
# day of the same month; then one more for each following month whose first
# day is on or before target_date.
def installment_count(as_of: date, target_date: date) -> int:
    if target_date < as_of:
        return 0

    return 1 + (target_date.year * 12 + target_date.month) - (as_of.year * 12 + as_of.month)


# The date of installment `number` (1 = as_of), by repeatedly applying the
# shared calendar helper. Callers keep `number` within the horizon.
def installment_date(as_of: date, number: int) -> date:
    if number < 1:
        raise ValueError("installment numbers start at 1")

    current = as_of

    for _ in range(number - 1):
        current = next_period_start(MONTH, current)

    return current


# Ceiling division on non-negative integers.
def _ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


# Works out the what-if estimate for a hypothetical per-installment amount.
def _what_if(
    *,
    monthly_contribution: Decimal,
    remaining_cents: int,
    goal_status: str,
    plan_status: GoalPlanStatus,
    target_date: Optional[date],
    as_of: date,
) -> GoalPlanWhatIf:
    def result(outcome, installments=None, completion=None, on_time=None) -> GoalPlanWhatIf:
        return GoalPlanWhatIf(
            monthly_contribution=monthly_contribution.quantize(_CENT),
            outcome=outcome,
            installments_needed=installments,
            estimated_completion_date=completion,
            on_or_before_target_date=on_time,
        )

    if goal_status == "archived":
        return result("not_applicable")

    if remaining_cents == 0:
        return result("already_funded")

    contribution_cents = _to_cents(monthly_contribution)

    if contribution_cents == 0:
        return result("no_contribution")

    installments = _ceil_div(remaining_cents, contribution_cents)

    # installment k happens k-1 months after the first one.
    if installments - 1 > HORIZON_MONTHS:
        return result("not_reachable_within_horizon")

    try:
        completion = installment_date(as_of, installments)
    except ValueError:
        # The calendar ran out (year 9999): no meaningful date.
        return result("not_reachable_within_horizon")

    on_time: Optional[bool] = None

    if target_date is not None and plan_status != "target_date_passed":
        on_time = completion <= target_date

    return result("reaches_target", installments, completion, on_time)


# Builds the whole plan from a Goal's ledger-derived amounts.
# Parameters:
# - tracked_amount / linked_amount: the Goal's two ledger partitions; their sum is
#   the Goal's current_amount (the only balance source).
# - monthly_contribution: optional hypothetical amount (>= 0, 2 decimals).
# - as_of: the server date, resolved once by the caller.
def build_goal_plan(
    *,
    goal_id: UUID,
    currency: str,
    goal_status: str,
    target_amount: Decimal,
    tracked_amount: Decimal,
    linked_amount: Decimal,
    target_date: Optional[date],
    monthly_contribution: Optional[Decimal],
    as_of: date,
) -> GoalPlanResponse:
    current_amount = tracked_amount + linked_amount
    remaining = remaining_amount(target_amount, current_amount)
    remaining_cents = _to_cents(remaining)

    if goal_status == "archived":
        plan_status: GoalPlanStatus = "archived"
    elif remaining_cents == 0:
        plan_status = "already_funded"
    elif target_date is None:
        plan_status = "no_target_date"
    elif target_date < as_of:
        plan_status = "target_date_passed"
    else:
        plan_status = "ready"

    count: Optional[int] = None
    per_installment: Optional[Decimal] = None
    first_date: Optional[date] = None
    last_date: Optional[date] = None

    if plan_status == "ready" and target_date is not None:
        count = installment_count(as_of, target_date)
        per_installment = _from_cents(_ceil_div(remaining_cents, count))
        first_date = as_of
        # The last installment is today when the target is this month, else the
        # first day of the target's month (always on or before target_date).
        last_date = as_of if count == 1 else date(target_date.year, target_date.month, 1)

    what_if = (
        _what_if(
            monthly_contribution=monthly_contribution,
            remaining_cents=remaining_cents,
            goal_status=goal_status,
            plan_status=plan_status,
            target_date=target_date,
            as_of=as_of,
        )
        if monthly_contribution is not None
        else None
    )

    return GoalPlanResponse(
        goal_id=goal_id,
        currency=currency,
        goal_status=goal_status,
        as_of=as_of,
        target_amount=target_amount,
        current_amount=current_amount,
        tracked_amount=tracked_amount,
        linked_amount=linked_amount,
        remaining_amount=remaining,
        overfunded_amount=overfunded_amount(target_amount, current_amount),
        target_date=target_date,
        plan_status=plan_status,
        installment_count=count,
        required_per_installment=per_installment,
        first_installment_date=first_date,
        last_installment_date=last_date,
        horizon_months=HORIZON_MONTHS,
        what_if=what_if,
    )
