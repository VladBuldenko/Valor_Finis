from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Optional, Sequence
from uuid import UUID

from app.modules.analytics.analytics_schemas import IncomeExpenseTrendBucket
from app.modules.goals.goal_history_schemas import (
    GoalHistoryComparisonResponse,
    GoalHistoryComparisonStatus,
    GoalHistoryDifferenceDirection,
    GoalHistoryLimitation,
    GoalHistoryMonth,
)

# Goal history comparison (VF-GOALS-PLANNING-002A): pure, deterministic
# arithmetic with no database, clock or HTTP access.
#
# THE RULES
# - The months are the completed calendar months handed in by the caller (the
#   income/expense trend with the in-progress month already dropped).
# - A month "has activity" when it has at least one resolved Income AND one
#   resolved Expense. A month without activity is excluded from the averages;
#   missing records are not proof of zero income or zero spending.
# - Any unresolved Income/Expense (no base-currency amount) in ANY analysed
#   month makes the history unusable: the totals would silently omit records.
# - The history is usable with >= MIN_ACTIVE_MONTHS active months and no
#   unresolved records. Only then are averages shown.
# - average = exact Decimal sum / months_used, rounded half-even to the cent
#   (the project's rounding). No float.
# - difference = average_monthly_net_flow - required_per_installment, only when
#   the Goal currency equals the base currency.
# Budgets, Goal reservations and allocation rules are not modelled (see the
# schema's limitation codes).

MIN_ACTIVE_MONTHS = 2

_CENT = Decimal("0.01")


def _average(total: Decimal, months_used: int) -> Decimal:
    return (total / Decimal(months_used)).quantize(_CENT, rounding=ROUND_HALF_EVEN)


def difference_direction_of(difference: Decimal) -> GoalHistoryDifferenceDirection:
    if difference > 0:
        return "surplus"

    if difference < 0:
        return "shortfall"

    return "equal"


# The recorded history of the completed months, summarised once for every
# feature that compares it with a planned contribution (the single Goal
# comparison and, since VF-GOALS-PLANNING-002B, the combined savings overview).
# Only the data-quality limitations are listed here; the two "not modelled"
# codes belong to the callers' responses.
@dataclass(frozen=True)
class HistorySummary:
    months: list[GoalHistoryMonth]
    usable: bool
    months_used: int
    average_income: Optional[Decimal]
    average_expenses: Optional[Decimal]
    average_net: Optional[Decimal]
    data_limitations: list[GoalHistoryLimitation]
    analysis_period_start: date
    analysis_period_end: date


# Applies the rules above to the completed months (oldest first, at least one).
def summarize_history(buckets: Sequence[IncomeExpenseTrendBucket]) -> HistorySummary:
    has_unresolved = any(
        bucket.unresolved_income_count > 0 or bucket.unresolved_expense_count > 0
        for bucket in buckets
    )
    active = [bucket.income_count > 0 and bucket.expense_count > 0 for bucket in buckets]
    active_count = sum(active)
    usable = not has_unresolved and active_count >= MIN_ACTIVE_MONTHS

    months = [
        GoalHistoryMonth(
            period_start=bucket.period_start,
            period_end=bucket.period_end,
            income_total=bucket.income_total,
            expense_total=bucket.expense_total,
            net_flow=bucket.net_flow,
            income_count=bucket.income_count,
            expense_count=bucket.expense_count,
            unresolved_income_count=bucket.unresolved_income_count,
            unresolved_expense_count=bucket.unresolved_expense_count,
            has_activity=is_active,
            included_in_average=usable and is_active,
        )
        for bucket, is_active in zip(buckets, active)
    ]
    included = [bucket for bucket, is_active in zip(buckets, active) if usable and is_active]

    average_income: Optional[Decimal] = None
    average_expenses: Optional[Decimal] = None
    average_net: Optional[Decimal] = None

    if included:
        average_income = _average(sum((b.income_total for b in included), Decimal("0.00")), len(included))
        average_expenses = _average(sum((b.expense_total for b in included), Decimal("0.00")), len(included))
        average_net = _average(sum((b.net_flow for b in included), Decimal("0.00")), len(included))

    limitations: list[GoalHistoryLimitation] = []

    if has_unresolved:
        limitations.append("unresolved_currency_data")

    if active_count < MIN_ACTIVE_MONTHS:
        limitations.append("fewer_than_two_active_months")

    if usable and active_count < len(buckets):
        limitations.append("months_without_activity_excluded")

    return HistorySummary(
        months=months,
        usable=usable,
        months_used=len(included),
        average_income=average_income,
        average_expenses=average_expenses,
        average_net=average_net,
        data_limitations=limitations,
        analysis_period_start=buckets[0].period_start,
        analysis_period_end=buckets[-1].period_end,
    )


# Builds the comparison of the Goal plan's required installment with the
# recorded history of the completed months.
# Parameters:
# - goal_id / goal_currency: the Goal.
# - base_currency: the currency the buckets are expressed in.
# - required_per_installment: the Goal plan's installment, or None when the
#   plan has none (any status other than ready).
# - buckets: the completed months, oldest first (at least one).
# - as_of: the server date, echoed back.
# Returns:
# - GoalHistoryComparisonResponse.
def build_goal_history_comparison(
    goal_id: UUID,
    goal_currency: str,
    base_currency: str,
    required_per_installment: Optional[Decimal],
    buckets: Sequence[IncomeExpenseTrendBucket],
    as_of: date,
) -> GoalHistoryComparisonResponse:
    summary = summarize_history(buckets)
    limitations: list[GoalHistoryLimitation] = [
        *summary.data_limitations,
        "budgets_not_modelled",
        "goal_commitments_not_modelled",
    ]

    status: GoalHistoryComparisonStatus
    difference: Optional[Decimal] = None

    if required_per_installment is None:
        status = "no_required_installment"
    elif goal_currency != base_currency:
        status = "currency_mismatch"
    elif not summary.usable or summary.average_net is None:
        status = "insufficient_data"
    else:
        status = "comparable"
        difference = summary.average_net - required_per_installment

    return GoalHistoryComparisonResponse(
        goal_id=goal_id,
        as_of=as_of,
        goal_currency=goal_currency,
        base_currency=base_currency,
        status=status,
        limitations=limitations,
        analysis_period_start=summary.analysis_period_start,
        analysis_period_end=summary.analysis_period_end,
        months=summary.months,
        months_used=summary.months_used,
        average_monthly_income=summary.average_income,
        average_monthly_expenses=summary.average_expenses,
        average_monthly_net_flow=summary.average_net,
        required_per_installment=required_per_installment,
        historical_difference=difference,
        difference_direction=None if difference is None else difference_direction_of(difference),
    )
