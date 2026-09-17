from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

# Deterministic current-month spending pace projection (VF-015D).
# This module exists to keep the forecast arithmetic pure and independently
# testable, separate from data loading/FX resolution, mirroring
# budgets/budget_metrics.py's separation of pure math from
# analytics_service.py's data loading and period/version resolution.

FORECAST_AVAILABLE = "available"
FORECAST_INCOMPLETE_DATA = "incomplete_data"

_MONEY_DECIMAL_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class SpendingForecastResult:
    """
    Deterministic linear-run-rate projection for the current calendar month.

    What:
        A current-pace projection of total month spending, derived from
        an already-resolved spent-to-date total and elapsed/total day
        counts.

    Why:
        Answers "at my current pace, what will I spend this month" as the
        simplest possible explainable model - see calculate_spending_forecast
        for its documented limitation, matching budget_metrics.py's own
        FORECAST LIMITATION note for the identical linear-pace approach
        already shipped for Budget Status (VF-014B4).

    Fields:
        forecast_status: "available" when every current-month Expense
            considered has a resolved base-currency amount; "incomplete_data"
            when at least one does not - a projection is never computed from
            known-incomplete monetary data.
        average_daily_spending: spent_to_date / days_elapsed, quantized to
            money precision. None exactly when forecast_status is
            "incomplete_data".
        projected_spending: the linear projection over the full month,
            quantized to money precision. None exactly when
            average_daily_spending is None.
    """

    forecast_status: str
    average_daily_spending: Optional[Decimal]
    projected_spending: Optional[Decimal]


# Calculates the deterministic linear-run-rate spending forecast for the
# current calendar month.
# This function exists to keep the forecast formula pure, independently
# testable, and free of any data-loading/FX/network concern.
#
# FORECAST LIMITATION: this is a simple linear current-month pace
# projection (spent_to_date / days_elapsed * days_in_month). It is NOT a
# historical forecast - it uses no prior months, no moving averages, no
# spending-pattern history. It can overreact when a large expense lands
# early in the month (e.g. rent paid on day 1 projects as if that
# happened every day for the rest of the month). This is intentional and
# not smoothed or dampened - see VF-015A/B4's identical documented
# limitation for Budget Status's own linear projection. A historical-
# baseline or hybrid model is explicitly deferred to a later slice.
#
# Parameters:
# - spent_to_date: already resolved, already base-currency-summed spend
#   for the current month through as_of (the caller's responsibility -
#   this function has no FX/resolution knowledge at all).
# - days_elapsed: inclusive day count from the 1st of the month through
#   as_of. Must be >= 1 - guaranteed by construction since as_of always
#   falls within the month it resolves, never validated defensively here.
# - days_in_month: inclusive total day count in the calendar month.
# - data_complete: False when the caller found any unresolved or
#   incompatible-base_currency Expense in the current month - a forecast
#   is never computed from known-incomplete monetary data, regardless of
#   how much of it happens to be missing.
# Returns:
# - SpendingForecastResult. When data_complete is False,
#   average_daily_spending and projected_spending are both None and
#   forecast_status is "incomplete_data" - spent_to_date itself is still
#   the caller's own concern to report as-is (this function never sees it
#   in that branch).
def calculate_spending_forecast(
    spent_to_date: Decimal,
    days_elapsed: int,
    days_in_month: int,
    data_complete: bool,
) -> SpendingForecastResult:
    if not data_complete:
        return SpendingForecastResult(
            forecast_status=FORECAST_INCOMPLETE_DATA,
            average_daily_spending=None,
            projected_spending=None,
        )

    # Full Decimal precision throughout - raw_average_daily is never
    # quantized before being used to compute raw_projection. Quantizing it
    # first (e.g. displaying "33.33" and then multiplying that by
    # days_in_month) would introduce intermediate rounding drift that has
    # nothing to do with the actual pace; average_daily_spending below is
    # a separate, purely presentational quantization of the same raw value.
    raw_average_daily = spent_to_date / days_elapsed
    raw_projection = raw_average_daily * days_in_month

    return SpendingForecastResult(
        forecast_status=FORECAST_AVAILABLE,
        average_daily_spending=raw_average_daily.quantize(_MONEY_DECIMAL_PLACES),
        projected_spending=raw_projection.quantize(_MONEY_DECIMAL_PLACES),
    )
