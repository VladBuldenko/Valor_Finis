from datetime import date

import pytest

from app.core.calendar_period import (
    resolve_period_bounds,
    resolve_recent_periods,
)


# ---------------------------------------------------------------------------
# resolve_period_bounds
# ---------------------------------------------------------------------------


# Tests that a day bucket is a single calendar date.
# Parameters:
# - None.
# Returns:
# - None. The test passes if period_start == period_end == as_of.
def test_resolve_period_bounds_day() -> None:
    # Act
    bucket = resolve_period_bounds("day", date(2026, 9, 17))

    # Assert
    assert bucket.period_start == date(2026, 9, 17)
    assert bucket.period_end == date(2026, 9, 17)


# Tests that a week bucket runs Monday through Sunday regardless of which
# weekday as_of falls on.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the bucket spans the correct Monday-Sunday.
def test_resolve_period_bounds_week_monday_to_sunday() -> None:
    # Act - Thursday 2026-09-17
    bucket = resolve_period_bounds("week", date(2026, 9, 17))

    # Assert
    assert bucket.period_start == date(2026, 9, 14)  # Monday
    assert bucket.period_end == date(2026, 9, 20)  # Sunday


# Tests that a month bucket runs the 1st through the last day of the month.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the bucket spans the full calendar month.
def test_resolve_period_bounds_month() -> None:
    # Act
    bucket = resolve_period_bounds("month", date(2026, 9, 17))

    # Assert
    assert bucket.period_start == date(2026, 9, 1)
    assert bucket.period_end == date(2026, 9, 30)


# Tests February in a non-leap year resolves to 28 days.
# Parameters:
# - None.
# Returns:
# - None. The test passes if period_end is Feb 28.
def test_resolve_period_bounds_month_february_non_leap_year() -> None:
    # Act
    bucket = resolve_period_bounds("month", date(2026, 2, 10))

    # Assert
    assert bucket.period_end == date(2026, 2, 28)


# Tests February in a leap year resolves to 29 days.
# Parameters:
# - None.
# Returns:
# - None. The test passes if period_end is Feb 29.
def test_resolve_period_bounds_month_february_leap_year() -> None:
    # Act - 2028 is a leap year
    bucket = resolve_period_bounds("month", date(2028, 2, 10))

    # Assert
    assert bucket.period_end == date(2028, 2, 29)


# Tests that December resolves within the same year, not rolling into the
# next one.
# Parameters:
# - None.
# Returns:
# - None. The test passes if period_end is Dec 31 of the same year.
def test_resolve_period_bounds_month_december() -> None:
    # Act
    bucket = resolve_period_bounds("month", date(2026, 12, 15))

    # Assert
    assert bucket.period_start == date(2026, 12, 1)
    assert bucket.period_end == date(2026, 12, 31)


# Tests that an unsupported period raises.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValueError is raised.
def test_resolve_period_bounds_unsupported_period_raises() -> None:
    # Act / Assert
    with pytest.raises(ValueError):
        resolve_period_bounds("year", date(2026, 9, 17))


# ---------------------------------------------------------------------------
# resolve_recent_periods
# ---------------------------------------------------------------------------


# Tests that a single requested period returns exactly the bucket
# containing as_of.
# Parameters:
# - None.
# Returns:
# - None. The test passes if exactly one bucket, containing as_of, is returned.
def test_resolve_recent_periods_count_one() -> None:
    # Act
    periods = resolve_recent_periods("month", date(2026, 9, 17), count=1)

    # Assert
    assert len(periods) == 1
    assert periods[0].period_start == date(2026, 9, 1)
    assert periods[0].period_end == date(2026, 9, 30)


# Tests that monthly buckets are chronologically ordered oldest-first and
# correctly cross a December -> January year boundary.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the returned buckets are Nov/Dec/Jan/Feb in order.
def test_resolve_recent_periods_month_crosses_year_boundary() -> None:
    # Act - as_of is Feb 2026, walking back 4 months
    periods = resolve_recent_periods("month", date(2026, 2, 10), count=4)

    # Assert
    assert [p.period_start for p in periods] == [
        date(2025, 11, 1),
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
    ]
    assert periods[-1].period_end == date(2026, 2, 28)


# Tests that weekly buckets walk back in exact 7-day steps and stay ordered,
# oldest first, ending with the week containing as_of.
# Parameters:
# - None.
# Returns:
# - None. The test passes if each bucket starts exactly 7 days before the next.
def test_resolve_recent_periods_week_steps_of_seven_days() -> None:
    # Act - as_of is Thursday 2026-09-17, whose own week starts Monday 09-14
    periods = resolve_recent_periods("week", date(2026, 9, 17), count=3)

    # Assert
    assert [p.period_start for p in periods] == [
        date(2026, 8, 31),
        date(2026, 9, 7),
        date(2026, 9, 14),
    ]
    assert periods[-1].period_end == date(2026, 9, 20)


# Tests that daily buckets are consecutive single-day windows, oldest
# first, ending with as_of itself.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the buckets are three consecutive dates.
def test_resolve_recent_periods_day_consecutive_dates() -> None:
    # Act
    periods = resolve_recent_periods("day", date(2026, 9, 17), count=3)

    # Assert
    assert [p.period_start for p in periods] == [
        date(2026, 9, 15),
        date(2026, 9, 16),
        date(2026, 9, 17),
    ]
    for bucket in periods:
        assert bucket.period_start == bucket.period_end


# Tests that count < 1 raises rather than silently returning an empty list.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValueError is raised.
def test_resolve_recent_periods_count_below_one_raises() -> None:
    # Act / Assert
    with pytest.raises(ValueError):
        resolve_recent_periods("month", date(2026, 9, 17), count=0)
