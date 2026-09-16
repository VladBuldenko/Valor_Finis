from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.modules.budgets.budget_period import PERIOD_ENDED, PERIOD_NOT_STARTED

RISK_HEALTHY = "healthy"
RISK_WATCH = "watch"
RISK_AT_RISK = "at_risk"
RISK_EXCEEDED = "exceeded"

_TWO_PLACES = Decimal("0.01")
_WATCH_THRESHOLD_PERCENT = Decimal("90")
_FULL_UTILIZATION_PERCENT = Decimal("100")


@dataclass(frozen=True)
class BudgetMetrics:
    """
    Deterministic current-period pace metrics for a single budget.

    What:
        days/spending-pace/projection/risk figures derived from an
        already-resolved budget period and spend total.

    Why:
        Answers "at my current pace, how am I doing" as a simple linear
        projection over the current period only - see calculate_budget_metrics
        for the explicit limitation of this approach.

    Fields:
        days_in_period: length of the effective budget window (partial
            first/final periods use the partial length, not the full
            calendar month/week/year).
        days_elapsed: effective days counted so far. For not_started this
            is 0; for ended this equals days_in_period.
        days_remaining: effective spending days left, INCLUSIVE of today
            for an active budget (see calculate_budget_metrics).
        average_daily_spending: spent divided by the days that produced it.
        daily_spending_allowance: remaining budget divided across remaining
            spending days - "how much can I spend per day from now on."
        projected_spending: linear current-pace projection over the full
            effective period. Never capped at limit_amount. None when there
            is no observed pace yet (not_started).
        projected_surplus/projected_deficit: limit_amount vs
            projected_spending, never negative. Both None exactly when
            projected_spending is None.
        risk_status: one of "healthy", "watch", "at_risk", "exceeded".
    """

    days_in_period: int
    days_elapsed: int
    days_remaining: int
    average_daily_spending: Decimal
    daily_spending_allowance: Decimal
    projected_spending: Optional[Decimal]
    projected_surplus: Optional[Decimal]
    projected_deficit: Optional[Decimal]
    risk_status: str


# Calculates deterministic current-period pace metrics for a budget.
# This function exists to keep the day/pace/projection/risk arithmetic
# pure and independently testable, separate from data loading and B1/B2
# window and version resolution, which stay in analytics_service.py.
#
# FORECAST LIMITATION: projected_spending is a simple linear current-period
# pace projection (spent / days_elapsed * days_in_period). It is NOT a
# historical forecast - it uses no prior periods, no moving averages, no
# spending-pattern history. It can overreact when a large recurring
# expense lands early in a period (e.g. rent paid on day 1 of a 30-day
# month projects as if that happened every day). Improving this with
# historical data is explicitly deferred to VF-015 Analytics & Forecasting
# v2 - do not "fix" it here.
#
# Parameters:
# - limit_amount: the limit in effect for this period (from BudgetVersion,
#   never the budget's live value directly - the caller is responsible for
#   that resolution).
# - spent: already currency/category/period-filtered spend for this period.
# - period_state: one of budget_period.PERIOD_NOT_STARTED/PERIOD_ACTIVE/
#   PERIOD_ENDED.
# - days_in_period: length of the effective window (B1's
#   CurrentWindow.days_in_period), valid for all three lifecycle states.
# - days_elapsed: B1's raw CurrentWindow.days_elapsed for the window used
#   to resolve this status. Only meaningful for period_state == active;
#   ignored (and replaced per the documented not_started/ended rules) for
#   the other two states, since B1's anchored-window helper values are not
#   directly usable there.
# Returns:
# - BudgetMetrics with all derived fields for this period/state.
def calculate_budget_metrics(
    limit_amount: Decimal,
    spent: Decimal,
    period_state: str,
    days_in_period: int,
    days_elapsed: int,
) -> BudgetMetrics:
    is_exceeded = spent > limit_amount
    projected_spending_raw: Optional[Decimal] = None

    if period_state == PERIOD_NOT_STARTED:
        elapsed = 0
        remaining_days = days_in_period
        average_daily_spending = Decimal("0.00")
        daily_spending_allowance = (limit_amount / days_in_period).quantize(_TWO_PLACES)
        projected_spending: Optional[Decimal] = None
        projected_surplus: Optional[Decimal] = None
        projected_deficit: Optional[Decimal] = None

    elif period_state == PERIOD_ENDED:
        elapsed = days_in_period
        remaining_days = 0
        average_daily_spending = (spent / days_in_period).quantize(_TWO_PLACES)
        daily_spending_allowance = Decimal("0.00")
        # The period is finished, so actual spending is authoritative -
        # there is nothing left to project.
        projected_spending_raw = spent
        projected_spending = spent.quantize(_TWO_PLACES)
        projected_surplus = max(limit_amount - projected_spending_raw, Decimal("0")).quantize(_TWO_PLACES)
        projected_deficit = max(projected_spending_raw - limit_amount, Decimal("0")).quantize(_TWO_PLACES)

    else:
        # Active. days_elapsed >= 1 always holds here: an active budget has
        # by definition already reached its effective_start.
        elapsed = days_elapsed
        # The overlap is intentional: today is both an elapsed day and
        # still a day the user may spend on, so +1 keeps today in both counts.
        remaining_days = days_in_period - days_elapsed + 1
        average_daily_spending = (spent / elapsed).quantize(_TWO_PLACES)

        if is_exceeded:
            daily_spending_allowance = Decimal("0.00")
        else:
            budget_remaining = max(limit_amount - spent, Decimal("0"))
            daily_spending_allowance = (budget_remaining / remaining_days).quantize(_TWO_PLACES)

        # Simple current-pace linear projection - never capped at
        # limit_amount. See the FORECAST LIMITATION note above.
        projected_spending_raw = (spent / elapsed) * days_in_period
        projected_spending = projected_spending_raw.quantize(_TWO_PLACES)
        projected_surplus = max(limit_amount - projected_spending_raw, Decimal("0")).quantize(_TWO_PLACES)
        projected_deficit = max(projected_spending_raw - limit_amount, Decimal("0")).quantize(_TWO_PLACES)

    # Risk status: evaluated in this exact priority order. An already-
    # exceeded budget always wins regardless of lifecycle state. The 90%/
    # 100% thresholds are a fixed, deterministic product rule - not a
    # statistical confidence model.
    if is_exceeded:
        risk_status = RISK_EXCEEDED
    elif period_state == PERIOD_NOT_STARTED:
        risk_status = RISK_HEALTHY
    elif period_state == PERIOD_ENDED:
        risk_status = RISK_HEALTHY
    else:
        projected_utilization_percent = (
            projected_spending_raw / limit_amount * Decimal("100")
        )
        if projected_utilization_percent > _FULL_UTILIZATION_PERCENT:
            risk_status = RISK_AT_RISK
        elif projected_utilization_percent > _WATCH_THRESHOLD_PERCENT:
            risk_status = RISK_WATCH
        else:
            risk_status = RISK_HEALTHY

    return BudgetMetrics(
        days_in_period=days_in_period,
        days_elapsed=elapsed,
        days_remaining=remaining_days,
        average_daily_spending=average_daily_spending,
        daily_spending_allowance=daily_spending_allowance,
        projected_spending=projected_spending,
        projected_surplus=projected_surplus,
        projected_deficit=projected_deficit,
        risk_status=risk_status,
    )
