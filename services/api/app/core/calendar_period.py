from dataclasses import dataclass
from datetime import date, timedelta

# Generic calendar-boundary math with no dependency on any domain module.
# This exists so analytics (VF-015B) can bucket by day/week/month without
# importing from app.modules.budgets - budgets/budget_period.py already has
# equivalent weekly/monthly/yearly boundary functions, but those are
# directly imported by budget_service.py (production code) and directly
# tested by tests/unit/budgets/test_budget_period.py and
# test_budget_service.py. Extracting/refactoring them into this module would
# touch that production call site and several Budget test files for a
# small amount of shared arithmetic - disproportionate churn for this slice.
# This module deliberately duplicates the small, stable amount of month/
# leap-year boundary arithmetic instead, so analytics never depends on the
# budgets module, and budget_period.py and its existing tests stay untouched.

DAY = "day"
WEEK = "week"
MONTH = "month"

SUPPORTED_PERIODS = frozenset({DAY, WEEK, MONTH})


@dataclass(frozen=True)
class CalendarPeriod:
    """A calendar-aligned bucket (inclusive bounds)."""

    period_start: date
    period_end: date


# Returns the start date of the period immediately following period_start.
# This function exists as the single source of day/week/month boundary
# arithmetic for calendar bucketing, so leap-year and year-end handling are
# never duplicated across call sites.
# Parameters:
# - period: one of DAY, WEEK, MONTH.
# - period_start: the inclusive start date of the current period. Must
#   already be aligned to a period boundary (as returned by
#   resolve_period_bounds).
# Returns:
# - The first date of the following period.
# Raises:
# - ValueError: when period is not a supported unit.
def next_period_start(period: str, period_start: date) -> date:
    if period == DAY:
        return period_start + timedelta(days=1)

    if period == WEEK:
        return period_start + timedelta(days=7)

    if period == MONTH:
        if period_start.month == 12:
            return date(period_start.year + 1, 1, 1)
        return date(period_start.year, period_start.month + 1, 1)

    raise ValueError(f"Unsupported period: {period}")


# Returns the start date of the period immediately preceding period_start.
# This function exists to walk backward through calendar buckets (e.g. to
# build a recent-history series) without re-deriving day/week/month
# arithmetic at each call site.
# Parameters:
# - period: one of DAY, WEEK, MONTH.
# - period_start: the inclusive start date of the current period. Must
#   already be aligned to a period boundary.
# Returns:
# - The first date of the preceding period.
# Raises:
# - ValueError: when period is not a supported unit.
def previous_period_start(period: str, period_start: date) -> date:
    if period == DAY:
        return period_start - timedelta(days=1)

    if period == WEEK:
        return period_start - timedelta(days=7)

    if period == MONTH:
        if period_start.month == 1:
            return date(period_start.year - 1, 12, 1)
        return date(period_start.year, period_start.month - 1, 1)

    raise ValueError(f"Unsupported period: {period}")


# Resolves the calendar-aligned bucket (inclusive bounds) containing a
# reference date.
# This function exists as the single source of calendar-boundary math for
# bucketing: day buckets are a single date, week buckets run Monday-Sunday,
# month buckets run the 1st to the last day of the month.
# Parameters:
# - period: one of DAY, WEEK, MONTH.
# - as_of: the reference date to resolve a bucket for.
# Returns:
# - CalendarPeriod with inclusive period_start/period_end.
# Raises:
# - ValueError: when period is not a supported unit.
def resolve_period_bounds(period: str, as_of: date) -> CalendarPeriod:
    if period == DAY:
        period_start = as_of
    elif period == WEEK:
        period_start = as_of - timedelta(days=as_of.weekday())
    elif period == MONTH:
        period_start = date(as_of.year, as_of.month, 1)
    else:
        raise ValueError(f"Unsupported period: {period}")

    period_end = next_period_start(period, period_start) - timedelta(days=1)

    return CalendarPeriod(period_start=period_start, period_end=period_end)


# Resolves the `count` most recent calendar buckets, ending with the bucket
# containing as_of.
# This function exists as the single place that walks backward through
# calendar history, so callers never hand-roll repeated backward iteration.
# Parameters:
# - period: one of DAY, WEEK, MONTH.
# - as_of: the reference date the most recent bucket must contain.
# - count: how many buckets to return. Must be >= 1.
# Returns:
# - list[CalendarPeriod] in chronological order (oldest first), with the
#   last element being the bucket containing as_of.
# Raises:
# - ValueError: when period is not a supported unit, or count < 1.
def resolve_recent_periods(
    period: str,
    as_of: date,
    count: int,
) -> list[CalendarPeriod]:
    if count < 1:
        raise ValueError("count must be >= 1")

    periods = [resolve_period_bounds(period, as_of)]

    for _ in range(count - 1):
        previous_start = previous_period_start(period, periods[-1].period_start)
        periods.append(resolve_period_bounds(period, previous_start))

    periods.reverse()

    return periods
