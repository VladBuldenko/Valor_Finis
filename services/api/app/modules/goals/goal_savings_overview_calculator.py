from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, Sequence, Tuple

from app.core.calendar_period import MONTH, next_period_start
from app.modules.analytics.analytics_schemas import IncomeExpenseTrendBucket
from app.modules.goals.goal_history_calculator import difference_direction_of, summarize_history
from app.modules.goals.goal_plan_calculator import build_goal_plan
from app.modules.goals.goal_plan_schemas import GoalPlanResponse
from app.modules.goals.goal_savings_overview_schemas import (
    GoalSavingsComparisonStatus,
    GoalSavingsContribution,
    GoalSavingsExclusionReason,
    GoalSavingsExclusions,
    GoalSavingsHistory,
    GoalSavingsLimitation,
    GoalSavingsMonth,
    GoalSavingsOverviewResponse,
    GoalSavingsPlannedGoal,
)
from app.modules.goals.goal_schemas import GoalResponse

# Combined Goal savings overview (VF-GOALS-PLANNING-002B): pure, deterministic
# arithmetic with no database, clock or HTTP access.
#
# THE RULES
# - Each Goal is judged by the EXISTING Goal plan (build_goal_plan), so there is
#   no second installment calculation. The schedule is that plan's: installment
#   1 is as_of, the following ones the 1st of each next calendar month, none
#   after the target date. A Goal therefore contributes in window month k (0 =
#   the current month) exactly when k < its installment_count.
# - A Goal is planned only when it is active, in the base currency, has
#   something left to fund and a target date that is today or later. Every other
#   Goal is excluded with one reason (see GoalSavingsExclusionReason). A Goal
#   without a future target date is UNPLANNED, never "zero savings needed".
# - The window is HORIZON_MONTHS calendar months starting with the current one.
# - month total = exact sum of the planned Goals' installments in that month
#   (each already a 2-decimal amount), so nothing is rounded here.
# - The comparison uses the shared history summary (the 002A rules). The
#   difference of a month is average_monthly_net_flow - that month's total, and
#   only for a month in which some Goal has an installment.
# Target amounts, tracked progress and linked reservations are never summed into
# monthly totals, and nothing is converted between currencies.

HORIZON_MONTHS = 12

_ZERO = Decimal("0.00")


# The first day of the calendar month that is `offset` months after as_of's month.
def _month_start(as_of: date, offset: int) -> date:
    current = date(as_of.year, as_of.month, 1)

    for _ in range(offset):
        current = next_period_start(MONTH, current)

    return current


# Classifies one Goal: (reason it is excluded, or None) and, when planned, its plan.
def _plan_or_reason(
    goal: GoalResponse, base_currency: str, as_of: date
) -> Tuple[Optional[GoalSavingsExclusionReason], Optional[GoalPlanResponse]]:
    if goal.status == "archived":
        return "archived", None

    if goal.status == "completed":
        return "completed", None

    plan = build_goal_plan(
        goal_id=goal.id,
        currency=goal.currency,
        goal_status=goal.status,
        target_amount=goal.target_amount,
        tracked_amount=goal.tracked_amount,
        linked_amount=goal.linked_amount,
        target_date=goal.target_date,
        monthly_contribution=None,
        as_of=as_of,
    )

    if plan.plan_status == "already_funded":
        return "already_funded", None

    if plan.plan_status == "no_target_date":
        return "no_target_date", None

    if plan.plan_status == "target_date_passed":
        return "target_date_passed", None

    if goal.currency != base_currency:
        return "other_currency", None

    return None, plan


# Builds the overview.
# Parameters:
# - goals: the user's Goals with their ledger-derived tracked/linked amounts.
# - base_currency: the currency of the recorded history and of every total.
# - history_buckets: the completed months, oldest first (at least one).
# - as_of: the server date.
# Returns:
# - GoalSavingsOverviewResponse.
def build_goal_savings_overview(
    goals: Sequence[GoalResponse],
    base_currency: str,
    history_buckets: Sequence[IncomeExpenseTrendBucket],
    as_of: date,
) -> GoalSavingsOverviewResponse:
    # Display order is the Goals' priority (1 = highest); the sort is stable, so
    # Goals without a rank keep the order they were given in.
    ordered = sorted(goals, key=lambda goal: (goal.priority_rank is None, goal.priority_rank or 0))

    counts: dict[GoalSavingsExclusionReason, int] = {
        "archived": 0,
        "completed": 0,
        "already_funded": 0,
        "no_target_date": 0,
        "target_date_passed": 0,
        "other_currency": 0,
    }
    other_currencies: set[str] = set()
    planned: list[GoalSavingsPlannedGoal] = []
    installments: list[Tuple[GoalSavingsPlannedGoal, Decimal, int]] = []

    for goal in ordered:
        reason, plan = _plan_or_reason(goal, base_currency, as_of)

        if reason is not None:
            counts[reason] += 1

            if reason == "other_currency":
                other_currencies.add(goal.currency)

            continue

        # A "ready" plan always carries every installment field.
        if (
            plan is None
            or plan.required_per_installment is None
            or plan.installment_count is None
            or plan.first_installment_date is None
            or plan.last_installment_date is None
            or goal.target_date is None
        ):
            raise ValueError("A ready Goal plan must carry its installment fields.")

        item = GoalSavingsPlannedGoal(
            goal_id=goal.id,
            name=goal.name,
            priority_rank=goal.priority_rank,
            target_date=goal.target_date,
            remaining_amount=plan.remaining_amount,
            installment_count=plan.installment_count,
            required_per_installment=plan.required_per_installment,
            first_installment_date=plan.first_installment_date,
            last_installment_date=plan.last_installment_date,
            continues_after_window=plan.installment_count > HORIZON_MONTHS,
        )
        planned.append(item)
        installments.append((item, plan.required_per_installment, plan.installment_count))

    summary = summarize_history(history_buckets)

    comparison_status: GoalSavingsComparisonStatus
    average_net: Optional[Decimal] = None

    if not planned:
        comparison_status = "no_planned_goals"
    elif not summary.usable or summary.average_net is None:
        comparison_status = "insufficient_data"
    else:
        comparison_status = "comparable"
        average_net = summary.average_net

    months: list[GoalSavingsMonth] = []

    for offset in range(HORIZON_MONTHS):
        start = _month_start(as_of, offset)
        contributions = [
            GoalSavingsContribution(goal_id=item.goal_id, amount=amount)
            for item, amount, count in installments
            if offset < count
        ]
        total = sum((entry.amount for entry in contributions), _ZERO)
        difference: Optional[Decimal] = None

        if average_net is not None and contributions:
            difference = average_net - total

        months.append(
            GoalSavingsMonth(
                period_start=start,
                period_end=next_period_start(MONTH, start) - timedelta(days=1),
                installment_date=as_of if offset == 0 else start,
                total_required=total,
                planned_goal_count=len(contributions),
                contributions=contributions,
                historical_difference=difference,
                difference_direction=None if difference is None else difference_direction_of(difference),
            )
        )

    limitations: list[GoalSavingsLimitation] = []

    if planned:
        limitations.extend(summary.data_limitations)

    if counts["other_currency"] > 0:
        limitations.append("other_currency_goals_excluded")

    if counts["no_target_date"] > 0:
        limitations.append("goals_without_target_date")

    if counts["target_date_passed"] > 0:
        limitations.append("goals_with_passed_target_date")

    limitations.extend(
        [
            "budgets_not_modelled",
            "goal_commitments_not_modelled",
            "future_obligations_not_modelled",
        ]
    )

    return GoalSavingsOverviewResponse(
        as_of=as_of,
        base_currency=base_currency,
        horizon_months=HORIZON_MONTHS,
        is_total_complete=counts["other_currency"] == 0,
        planned_goals=planned,
        months=months,
        exclusions=GoalSavingsExclusions(
            archived=counts["archived"],
            completed=counts["completed"],
            already_funded=counts["already_funded"],
            no_target_date=counts["no_target_date"],
            target_date_passed=counts["target_date_passed"],
            other_currency=counts["other_currency"],
            other_currencies=sorted(other_currencies),
        ),
        history=GoalSavingsHistory(
            status=comparison_status,
            analysis_period_start=summary.analysis_period_start,
            analysis_period_end=summary.analysis_period_end,
            months=summary.months,
            months_used=summary.months_used,
            average_monthly_income=summary.average_income,
            average_monthly_expenses=summary.average_expenses,
            average_monthly_net_flow=summary.average_net,
        ),
        limitations=limitations,
    )
