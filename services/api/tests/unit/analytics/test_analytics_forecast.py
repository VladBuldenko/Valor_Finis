from decimal import Decimal

from app.modules.analytics.analytics_forecast import calculate_spending_forecast


# ---------------------------------------------------------------------------
# Pure math - linear_run_rate
# ---------------------------------------------------------------------------


# Tests day-1-of-month projection: intentionally simple and explainable,
# not dampened even though it extrapolates a single day across the whole
# month.
# Parameters:
# - None.
# Returns:
# - None. The test passes if projected_spending == 100 * 30.
def test_calculate_spending_forecast_day_one() -> None:
    # Act
    result = calculate_spending_forecast(
        spent_to_date=Decimal("100.00"), days_elapsed=1, days_in_month=30,
        data_complete=True,
    )

    # Assert
    assert result.forecast_status == "available"
    assert result.average_daily_spending == Decimal("100.00")
    assert result.projected_spending == Decimal("3000.00")


# Tests a middle-of-month projection using the task's own worked example,
# and proves projected_spending is computed from the full-precision daily
# rate, never from the already-quantized average_daily_spending display
# value - the two diverge by 10 cents for this exact input.
# Parameters:
# - None.
# Returns:
# - None. The test passes only if projected_spending == 1033.33, not the
#   1033.23 a naive (rounded-then-multiplied) implementation would give.
def test_calculate_spending_forecast_does_not_multiply_rounded_average() -> None:
    # Act
    result = calculate_spending_forecast(
        spent_to_date=Decimal("100.00"), days_elapsed=3, days_in_month=31,
        data_complete=True,
    )

    # Assert
    assert result.average_daily_spending == Decimal("33.33")
    assert result.projected_spending == Decimal("1033.33")
    # The naive (wrong) calculation a display-value-based implementation
    # would produce - explicitly proven different from the correct result.
    naive_wrong_result = (Decimal("33.33") * 31).quantize(Decimal("0.01"))
    assert naive_wrong_result == Decimal("1033.23")
    assert result.projected_spending != naive_wrong_result


# Tests that on the last day of the month, the projection equals actual
# spend exactly, after money quantization - even though the intermediate
# full-precision division/multiplication round-trip is not bit-exact for
# a non-evenly-divisible amount.
# Parameters:
# - None.
# Returns:
# - None. The test passes if projected_spending == spent_to_date exactly.
def test_calculate_spending_forecast_last_day_equals_actual() -> None:
    # Act - 1000.00 / 31 is a repeating decimal, days_elapsed == days_in_month
    result = calculate_spending_forecast(
        spent_to_date=Decimal("1000.00"), days_elapsed=31, days_in_month=31,
        data_complete=True,
    )

    # Assert
    assert result.projected_spending == Decimal("1000.00")


# Tests zero spending: valid for a linear pace model, not an error state.
# Parameters:
# - None.
# Returns:
# - None. The test passes if both figures are exactly "0.00".
def test_calculate_spending_forecast_zero_spending() -> None:
    # Act
    result = calculate_spending_forecast(
        spent_to_date=Decimal("0.00"), days_elapsed=10, days_in_month=30,
        data_complete=True,
    )

    # Assert
    assert result.forecast_status == "available"
    assert result.average_daily_spending == Decimal("0.00")
    assert result.projected_spending == Decimal("0.00")


# Tests a precision-sensitive Decimal case (repeating-decimal daily rate)
# to prove exact Decimal behavior with no float drift.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the result matches hand-computed exact Decimal
#   arithmetic, and is a genuine Decimal instance throughout.
def test_calculate_spending_forecast_decimal_precision_no_float_drift() -> None:
    # Act - 10.00 / 3 = 3.333... repeating
    result = calculate_spending_forecast(
        spent_to_date=Decimal("10.00"), days_elapsed=3, days_in_month=30,
        data_complete=True,
    )

    # Assert
    assert isinstance(result.average_daily_spending, Decimal)
    assert isinstance(result.projected_spending, Decimal)
    assert result.average_daily_spending == Decimal("3.33")
    # Full precision: (10/3)*30 = 100 exactly, not 3.33*30 = 99.90.
    assert result.projected_spending == Decimal("100.00")


# Tests that incomplete data produces a null forecast regardless of the
# spend/day figures - never a partial or best-effort projection.
# Parameters:
# - None.
# Returns:
# - None. The test passes if both figures are None and status is
#   "incomplete_data".
def test_calculate_spending_forecast_incomplete_data_returns_nulls() -> None:
    # Act
    result = calculate_spending_forecast(
        spent_to_date=Decimal("500.00"), days_elapsed=10, days_in_month=30,
        data_complete=False,
    )

    # Assert
    assert result.forecast_status == "incomplete_data"
    assert result.average_daily_spending is None
    assert result.projected_spending is None
