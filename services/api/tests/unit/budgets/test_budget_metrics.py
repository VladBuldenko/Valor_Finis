from decimal import Decimal

import pytest

from app.modules.budgets.budget_metrics import calculate_budget_metrics
from app.modules.budgets.budget_period import PERIOD_ACTIVE, PERIOD_ENDED, PERIOD_NOT_STARTED


# ---------------------------------------------------------------------------
# Risk status - active
# ---------------------------------------------------------------------------


# Tests (A) that a low projected utilization is reported healthy.
# This test exists to verify the <=90% healthy threshold.
# Parameters:
# - None.
# Returns:
# - None. The test passes if risk_status is healthy.
def test_calculate_budget_metrics_active_healthy() -> None:
    # Act - (100/20)*30 = 150 projected against a 600 limit -> 25%
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("600"), spent=Decimal("100"),
        period_state=PERIOD_ACTIVE, days_in_period=30, days_elapsed=20,
    )

    # Assert
    assert metrics.risk_status == "healthy"


# Tests (B) that a projected utilization strictly between 90% and 100% is
# reported watch.
# Parameters:
# - None.
# Returns:
# - None. The test passes if risk_status is watch.
def test_calculate_budget_metrics_active_watch() -> None:
    # Act - (95/10)*10 = 95 projected against a 100 limit -> 95%
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("100"), spent=Decimal("95"),
        period_state=PERIOD_ACTIVE, days_in_period=10, days_elapsed=10,
    )

    # Assert
    assert metrics.risk_status == "watch"


# Tests (C) that a projected utilization above 100% is reported at_risk.
# Parameters:
# - None.
# Returns:
# - None. The test passes if risk_status is at_risk.
def test_calculate_budget_metrics_active_at_risk() -> None:
    # Act - (450/10)*30 = 1350 projected against a 600 limit
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("600"), spent=Decimal("450"),
        period_state=PERIOD_ACTIVE, days_in_period=30, days_elapsed=10,
    )

    # Assert
    assert metrics.risk_status == "at_risk"


# Tests (D) that an already-exceeded budget always reports exceeded,
# regardless of what the projection would otherwise say.
# This test exists to verify risk rule A's top priority: a calm projection
# must never override an actual, already-realized overspend.
# Parameters:
# - None.
# Returns:
# - None. The test passes if risk_status is exceeded and allowance is zero.
def test_calculate_budget_metrics_active_already_exceeded_wins_over_projection() -> None:
    # Act - spent already exceeds the limit even though the pace projection
    # over the full period would look calm (low daily average).
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("100"), spent=Decimal("150"),
        period_state=PERIOD_ACTIVE, days_in_period=30, days_elapsed=29,
    )

    # Assert
    assert metrics.risk_status == "exceeded"
    assert metrics.daily_spending_allowance == Decimal("0.00")


# Tests (E) that exactly 90% projected utilization is healthy, not watch.
# Parameters:
# - None.
# Returns:
# - None. The test passes if risk_status is healthy at exactly 90%.
def test_calculate_budget_metrics_exactly_90_percent_is_healthy() -> None:
    # Act - (45/10)*20 = 90 projected against a 100 limit -> exactly 90%
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("100"), spent=Decimal("45"),
        period_state=PERIOD_ACTIVE, days_in_period=20, days_elapsed=10,
    )

    # Assert
    assert metrics.projected_spending == Decimal("90.00")
    assert metrics.risk_status == "healthy"


# Tests (F) that exactly 100% projected utilization is watch, not at_risk.
# Parameters:
# - None.
# Returns:
# - None. The test passes if risk_status is watch at exactly 100%.
def test_calculate_budget_metrics_exactly_100_percent_is_watch() -> None:
    # Act - (50/10)*20 = 100 projected against a 100 limit -> exactly 100%
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("100"), spent=Decimal("50"),
        period_state=PERIOD_ACTIVE, days_in_period=20, days_elapsed=10,
    )

    # Assert
    assert metrics.projected_spending == Decimal("100.00")
    assert metrics.risk_status == "watch"


# Tests (G) that projected utilization just above 100% is at_risk.
# Parameters:
# - None.
# Returns:
# - None. The test passes if risk_status is at_risk just past 100%.
def test_calculate_budget_metrics_projection_above_100_percent() -> None:
    # Act - (51/10)*20 = 102 projected against a 100 limit -> 102%
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("100"), spent=Decimal("51"),
        period_state=PERIOD_ACTIVE, days_in_period=20, days_elapsed=10,
    )

    # Assert
    assert metrics.projected_spending == Decimal("102.00")
    assert metrics.risk_status == "at_risk"


# ---------------------------------------------------------------------------
# Lifecycle states
# ---------------------------------------------------------------------------


# Tests (H) not_started day/spending/projection/risk normalization.
# This test exists to lock in the explicit not_started overrides: zero
# elapsed, full days remaining, a nonzero allowance derived from the full
# window, and a null (not zero) projection.
# Parameters:
# - None.
# Returns:
# - None. The test passes if all not_started fields match the documented rules.
def test_calculate_budget_metrics_not_started() -> None:
    # Act
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("300"), spent=Decimal("0"),
        period_state=PERIOD_NOT_STARTED, days_in_period=30, days_elapsed=0,
    )

    # Assert
    assert metrics.days_elapsed == 0
    assert metrics.days_remaining == 30
    assert metrics.average_daily_spending == Decimal("0.00")
    assert metrics.daily_spending_allowance == Decimal("10.00")
    assert metrics.projected_spending is None
    assert metrics.projected_surplus is None
    assert metrics.projected_deficit is None
    assert metrics.risk_status == "healthy"


# Tests (I) an ended, under-budget period reports its final actual spend
# as the projection, healthy risk, and zero allowance/remaining days.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ended-under-budget fields match spec.
def test_calculate_budget_metrics_ended_under_budget() -> None:
    # Act
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("500"), spent=Decimal("300"),
        period_state=PERIOD_ENDED, days_in_period=10, days_elapsed=999,
    )

    # Assert
    assert metrics.days_elapsed == 10
    assert metrics.days_remaining == 0
    assert metrics.average_daily_spending == Decimal("30.00")
    assert metrics.daily_spending_allowance == Decimal("0.00")
    assert metrics.projected_spending == Decimal("300.00")
    assert metrics.projected_surplus == Decimal("200.00")
    assert metrics.projected_deficit == Decimal("0.00")
    assert metrics.risk_status == "healthy"


# Tests (J) an ended, exceeded period reports exceeded risk and a nonzero
# projected deficit equal to the real overspend.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ended-exceeded fields match spec.
def test_calculate_budget_metrics_ended_exceeded() -> None:
    # Act
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("500"), spent=Decimal("600"),
        period_state=PERIOD_ENDED, days_in_period=10, days_elapsed=999,
    )

    # Assert
    assert metrics.projected_spending == Decimal("600.00")
    assert metrics.projected_surplus == Decimal("0.00")
    assert metrics.projected_deficit == Decimal("100.00")
    assert metrics.risk_status == "exceeded"


# ---------------------------------------------------------------------------
# Partial periods and active-day edges
# ---------------------------------------------------------------------------


# Tests (K) that a partial first period uses the partial window length for
# every day-based calculation, not the full calendar month.
# Parameters:
# - None.
# Returns:
# - None. The test passes if projection uses the 15-day partial window.
def test_calculate_budget_metrics_partial_first_period() -> None:
    # Arrange - budget activated Sept 16, effective window Sept 16-30 = 15
    # days; as_of Sept 20 -> elapsed 5, remaining 11 (per the task's own
    # worked example).
    # Act
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("300"), spent=Decimal("50"),
        period_state=PERIOD_ACTIVE, days_in_period=15, days_elapsed=5,
    )

    # Assert
    assert metrics.days_in_period == 15
    assert metrics.days_elapsed == 5
    assert metrics.days_remaining == 11
    assert metrics.average_daily_spending == Decimal("10.00")
    assert metrics.projected_spending == Decimal("150.00")  # (50/5)*15


# Tests (L) that a partial final period (already ended mid-month) uses the
# partial window length for average_daily_spending.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the partial 10-day window drives the average.
def test_calculate_budget_metrics_partial_final_period() -> None:
    # Act - budget ended on day 10 of what would have been a 30-day month
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("100"), spent=Decimal("40"),
        period_state=PERIOD_ENDED, days_in_period=10, days_elapsed=999,
    )

    # Assert
    assert metrics.days_in_period == 10
    assert metrics.average_daily_spending == Decimal("4.00")


# Tests (M) the first active day of a period (days_elapsed=1).
# This test exists to verify no division-by-zero and correct pace math on
# the very first day.
# Parameters:
# - None.
# Returns:
# - None. The test passes if day-1 metrics are well-defined.
def test_calculate_budget_metrics_first_active_day() -> None:
    # Act
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("300"), spent=Decimal("30"),
        period_state=PERIOD_ACTIVE, days_in_period=30, days_elapsed=1,
    )

    # Assert
    assert metrics.days_remaining == 30
    assert metrics.average_daily_spending == Decimal("30.00")
    assert metrics.projected_spending == Decimal("900.00")  # (30/1)*30


# Tests (N) the final active day of a period (days_elapsed==days_in_period,
# so days_remaining is exactly 1, per the intentional today-counts-twice
# overlap).
# Parameters:
# - None.
# Returns:
# - None. The test passes if the last day still reports 1 remaining day.
def test_calculate_budget_metrics_final_active_day() -> None:
    # Act
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("300"), spent=Decimal("290"),
        period_state=PERIOD_ACTIVE, days_in_period=30, days_elapsed=30,
    )

    # Assert
    assert metrics.days_remaining == 1
    assert metrics.daily_spending_allowance == Decimal("10.00")


# ---------------------------------------------------------------------------
# Zero spend, precision, and rounding
# ---------------------------------------------------------------------------


# Tests (O) that zero spend produces zero average/projection, not an error.
# Parameters:
# - None.
# Returns:
# - None. The test passes if all spend-derived fields are zero.
def test_calculate_budget_metrics_zero_spent() -> None:
    # Act
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("100"), spent=Decimal("0"),
        period_state=PERIOD_ACTIVE, days_in_period=30, days_elapsed=10,
    )

    # Assert
    assert metrics.average_daily_spending == Decimal("0.00")
    assert metrics.projected_spending == Decimal("0.00")
    assert metrics.projected_surplus == Decimal("100.00")
    assert metrics.projected_deficit == Decimal("0.00")
    assert metrics.risk_status == "healthy"


# Tests (P) that every monetary field is a Decimal, never a float, even
# with inputs that do not divide evenly.
# Parameters:
# - None.
# Returns:
# - None. The test passes if all monetary fields are Decimal instances.
def test_calculate_budget_metrics_decimal_precision_no_float() -> None:
    # Act
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("100"), spent=Decimal("33.33"),
        period_state=PERIOD_ACTIVE, days_in_period=7, days_elapsed=3,
    )

    # Assert
    assert isinstance(metrics.average_daily_spending, Decimal)
    assert isinstance(metrics.daily_spending_allowance, Decimal)
    assert isinstance(metrics.projected_spending, Decimal)
    assert isinstance(metrics.projected_surplus, Decimal)
    assert isinstance(metrics.projected_deficit, Decimal)


# Tests (Q) that daily_spending_allowance is quantized to exactly 2 decimal
# places even when the division does not terminate at 2dp.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the allowance is rounded to 0.01.
def test_calculate_budget_metrics_daily_allowance_rounding() -> None:
    # Act - remaining 100 / 3 remaining days = 33.333...
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("100"), spent=Decimal("0"),
        period_state=PERIOD_ACTIVE, days_in_period=3, days_elapsed=1,
    )

    # Assert
    assert metrics.daily_spending_allowance == Decimal("33.33")


# Tests (R) that average_daily_spending is quantized to exactly 2 decimal
# places even when the division does not terminate at 2dp.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the average is rounded to 0.01.
def test_calculate_budget_metrics_average_daily_spending_rounding() -> None:
    # Act - 10 / 3 elapsed days = 3.333...
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("100"), spent=Decimal("10"),
        period_state=PERIOD_ACTIVE, days_in_period=30, days_elapsed=3,
    )

    # Assert
    assert metrics.average_daily_spending == Decimal("3.33")


# Tests (S) that projected_surplus is correctly nonzero when the pace
# projects under the limit.
# Parameters:
# - None.
# Returns:
# - None. The test passes if surplus reflects the gap and deficit is zero.
def test_calculate_budget_metrics_projected_surplus() -> None:
    # Act - (100/10)*20 = 200 projected against a 600 limit
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("600"), spent=Decimal("100"),
        period_state=PERIOD_ACTIVE, days_in_period=20, days_elapsed=10,
    )

    # Assert
    assert metrics.projected_spending == Decimal("200.00")
    assert metrics.projected_surplus == Decimal("400.00")
    assert metrics.projected_deficit == Decimal("0.00")


# Tests (T) that projected_deficit is correctly nonzero when the pace
# projects over the limit, and is never reported as a negative surplus.
# Parameters:
# - None.
# Returns:
# - None. The test passes if deficit reflects the overrun and surplus is zero.
def test_calculate_budget_metrics_projected_deficit() -> None:
    # Act - (60/10)*20 = 120 projected against a 100 limit
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("100"), spent=Decimal("60"),
        period_state=PERIOD_ACTIVE, days_in_period=20, days_elapsed=10,
    )

    # Assert
    assert metrics.projected_spending == Decimal("120.00")
    assert metrics.projected_surplus == Decimal("0.00")
    assert metrics.projected_deficit == Decimal("20.00")


# Tests that days_in_period/days_elapsed/days_remaining are never negative,
# across all three lifecycle states.
# Parameters:
# - None.
# Returns:
# - None. The test passes if no day count is ever negative.
@pytest.mark.parametrize(
    "period_state,days_in_period,days_elapsed",
    [
        (PERIOD_NOT_STARTED, 30, 0),
        (PERIOD_ACTIVE, 30, 1),
        (PERIOD_ACTIVE, 30, 30),
        (PERIOD_ENDED, 10, 999),
    ],
)
def test_calculate_budget_metrics_day_counts_never_negative(
    period_state: str, days_in_period: int, days_elapsed: int,
) -> None:
    # Act
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("100"), spent=Decimal("50"),
        period_state=period_state, days_in_period=days_in_period, days_elapsed=days_elapsed,
    )

    # Assert
    assert metrics.days_in_period >= 0
    assert metrics.days_elapsed >= 0
    assert metrics.days_remaining >= 0


# Tests that projected_spending is never capped at limit_amount, even when
# the current pace projects far above it.
# This test exists to lock in the explicit "do not cap" requirement.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the projection exceeds the limit uncapped.
def test_calculate_budget_metrics_projection_not_capped_at_limit() -> None:
    # Act - (300/1)*30 = 9000 against a 600 limit
    metrics = calculate_budget_metrics(
        limit_amount=Decimal("600"), spent=Decimal("300"),
        period_state=PERIOD_ACTIVE, days_in_period=30, days_elapsed=1,
    )

    # Assert
    assert metrics.projected_spending == Decimal("9000.00")
    assert metrics.risk_status == "at_risk"
