from datetime import date, timedelta
from types import SimpleNamespace
from typing import Optional

import pytest

from app.modules.budgets.budget_period import (
    PERIOD_ACTIVE,
    PERIOD_ENDED,
    PERIOD_NOT_STARTED,
    next_period_start,
    resolve_current_window,
    resolve_period,
)


def make_budget(
    start_date: date,
    end_date: Optional[date] = None,
    period: str = "monthly",
) -> SimpleNamespace:
    return SimpleNamespace(start_date=start_date, end_date=end_date, period=period)


# ---------------------------------------------------------------------------
# Calendar boundaries — resolve_period
# ---------------------------------------------------------------------------


# Tests that a monthly period resolves to the same window regardless of
# where in the month as_of falls.
# This test exists to confirm monthly windows are calendar-aligned, not
# anchored to the reference date itself.
# Parameters:
# - None.
# Returns:
# - None. The test passes if mid-month, first-day, and last-day all resolve
#   to the same period window.
def test_resolve_period_monthly_same_window_regardless_of_day() -> None:
    # Arrange
    mid_month = date(2026, 9, 15)
    first_day = date(2026, 9, 1)
    last_day = date(2026, 9, 30)

    # Act
    windows = [resolve_period("monthly", d) for d in (mid_month, first_day, last_day)]

    # Assert
    for window in windows:
        assert window.period_start == date(2026, 9, 1)
        assert window.period_end == date(2026, 9, 30)


# Tests that monthly period_end correctly reflects each month's length,
# including a non-leap and a leap February.
# This test exists because month-length correctness must come from
# calendar.monthrange, not hand-computed constants.
# Parameters:
# - None.
# Returns:
# - None. The test passes if each month's period_end matches its true
#   last day.
@pytest.mark.parametrize(
    "as_of,expected_end",
    [
        (date(2026, 1, 10), date(2026, 1, 31)),
        (date(2026, 4, 10), date(2026, 4, 30)),
        (date(2026, 2, 10), date(2026, 2, 28)),
        (date(2028, 2, 10), date(2028, 2, 29)),
    ],
)
def test_resolve_period_monthly_month_lengths(as_of: date, expected_end: date) -> None:
    # Act
    window = resolve_period("monthly", as_of)

    # Assert
    assert window.period_end == expected_end


# Tests that a weekly period starts on Monday whether as_of is that Monday
# or the following Sunday.
# This test exists to confirm the weekly window is Monday-Sunday regardless
# of which day of the week as_of falls on.
# Parameters:
# - None.
# Returns:
# - None. The test passes if both a Monday as_of and a Sunday as_of resolve
#   to the same Monday-start window.
def test_resolve_period_weekly_monday_and_sunday_same_window() -> None:
    # Arrange
    monday = date(2026, 9, 14)
    sunday = date(2026, 9, 20)

    # Act
    monday_window = resolve_period("weekly", monday)
    sunday_window = resolve_period("weekly", sunday)

    # Assert
    assert monday_window.period_start == date(2026, 9, 14)
    assert monday_window.period_end == date(2026, 9, 20)
    assert sunday_window == monday_window


# Tests that a weekly window spanning a month boundary resolves correctly.
# This test exists because month-boundary arithmetic is where off-by-one
# errors in hand-rolled date math tend to appear.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the window runs 2026-08-31 to 2026-09-06.
def test_resolve_period_weekly_spans_month_boundary() -> None:
    # Act
    window = resolve_period("weekly", date(2026, 8, 31))

    # Assert
    assert window.period_start == date(2026, 8, 31)
    assert window.period_end == date(2026, 9, 6)


# Tests that a weekly window spanning a year boundary resolves correctly.
# This test exists because year-boundary arithmetic is a second place
# off-by-one errors tend to appear.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the window runs 2026-12-28 to 2027-01-03.
def test_resolve_period_weekly_spans_year_boundary() -> None:
    # Act
    window = resolve_period("weekly", date(2026, 12, 28))

    # Assert
    assert window.period_start == date(2026, 12, 28)
    assert window.period_end == date(2027, 1, 3)


# Tests that a yearly period always resolves to Jan 1-Dec 31 of as_of's
# year, and that a leap year spans 366 days.
# This test exists to confirm yearly windows are calendar-year-aligned and
# that leap years are handled without hand-computed day counts.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the window bounds and leap-year day count
#   are correct.
def test_resolve_period_yearly_bounds_and_leap_year_length() -> None:
    # Act
    window = resolve_period("yearly", date(2026, 6, 1))
    leap_window = resolve_period("yearly", date(2028, 6, 1))

    # Assert
    assert window.period_start == date(2026, 1, 1)
    assert window.period_end == date(2026, 12, 31)
    assert (leap_window.period_end - leap_window.period_start).days + 1 == 366


# Tests that consecutive periods never gap or overlap: as_of on the last
# day of a period resolves differently than as_of one day later, and the
# next window's period_start is exactly one day after the prior period_end.
# This test exists because period-boundary continuity is the property every
# downstream spending calculation depends on.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the two windows differ and are contiguous.
def test_resolve_period_monthly_transition_has_no_gap_or_overlap() -> None:
    # Arrange
    last_day = date(2026, 9, 30)
    next_day = date(2026, 10, 1)

    # Act
    current = resolve_period("monthly", last_day)
    following = resolve_period("monthly", next_day)

    # Assert
    assert current != following
    assert following.period_start == current.period_end + timedelta(days=1)
    assert following.period_start == next_period_start("monthly", current.period_start)


# Tests that resolve_period rejects an unsupported period value.
# This test exists because the recurrence unit is otherwise only validated
# by Pydantic/DB constraints — this function must not silently misbehave
# if it is ever called with unvalidated input.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValueError is raised.
def test_resolve_period_rejects_unsupported_period() -> None:
    # Act / Assert
    with pytest.raises(ValueError):
        resolve_period("daily", date(2026, 9, 15))


# ---------------------------------------------------------------------------
# Partial first/last period — resolve_current_window
# ---------------------------------------------------------------------------


# Tests that a budget activated mid-month reports a partial first period
# with the correct effective start, day counts, and partiality flag.
# This test exists to lock in the Part 1 "option D" decision: the period
# stays calendar-aligned, but only days on/after activation count.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the window fields match the documented example.
def test_resolve_current_window_partial_first_period() -> None:
    # Arrange
    budget = make_budget(start_date=date(2026, 9, 15), period="monthly")
    as_of = date(2026, 9, 20)

    # Act
    window = resolve_current_window(budget, as_of)

    # Assert
    assert window.period_start == date(2026, 9, 1)
    assert window.effective_start == date(2026, 9, 15)
    assert window.days_in_period == 16
    assert window.days_elapsed == 6
    assert window.is_partial_period is True


# Tests that a budget activated on the first day of the period is not
# flagged as partial.
# This test exists as the counterpart to the partial-period test above.
# Parameters:
# - None.
# Returns:
# - None. The test passes if is_partial_period is False.
def test_resolve_current_window_full_period_when_activated_on_first_day() -> None:
    # Arrange
    budget = make_budget(start_date=date(2026, 9, 1), period="monthly")

    # Act
    window = resolve_current_window(budget, date(2026, 9, 20))

    # Assert
    assert window.is_partial_period is False
    assert window.effective_start == date(2026, 9, 1)
    assert window.days_in_period == 30


# Tests that a budget deactivated mid-month reports a partial final period
# clamped to end_date.
# This test exists to confirm end_date clamps effective_end the same way
# start_date clamps effective_start.
# Parameters:
# - None.
# Returns:
# - None. The test passes if effective_end and days_in_period match the
#   documented example.
def test_resolve_current_window_partial_final_period() -> None:
    # Arrange
    budget = make_budget(
        start_date=date(2026, 8, 1),
        end_date=date(2026, 9, 10),
        period="monthly",
    )

    # Act
    window = resolve_current_window(budget, date(2026, 9, 8))

    # Assert
    assert window.effective_end == date(2026, 9, 10)
    assert window.days_in_period == 10
    assert window.is_partial_period is True


# Tests the period_state discriminator across a budget's lifetime: before
# activation, during its active window, and after deactivation.
# This test exists because period_state is what downstream analytics use
# to decide whether a budget applies at all on a given as_of date.
# Parameters:
# - None.
# Returns:
# - None. The test passes if each as_of resolves to the correct state.
def test_resolve_current_window_period_state_transitions() -> None:
    # Arrange
    budget = make_budget(
        start_date=date(2026, 9, 15),
        end_date=date(2026, 10, 15),
        period="monthly",
    )

    # Act / Assert
    assert resolve_current_window(budget, date(2026, 9, 1)).period_state == PERIOD_NOT_STARTED
    assert resolve_current_window(budget, date(2026, 9, 20)).period_state == PERIOD_ACTIVE
    assert resolve_current_window(budget, date(2026, 11, 1)).period_state == PERIOD_ENDED


# ---------------------------------------------------------------------------
# next_period_start
# ---------------------------------------------------------------------------


# Tests that next_period_start rejects an unsupported period value.
# This test exists for the same reason as the resolve_period equivalent:
# this function must fail loudly on unvalidated input rather than guess.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValueError is raised.
def test_next_period_start_rejects_unsupported_period() -> None:
    # Act / Assert
    with pytest.raises(ValueError):
        next_period_start("daily", date(2026, 9, 1))
