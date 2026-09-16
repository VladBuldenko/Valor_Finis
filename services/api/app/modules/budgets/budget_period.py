from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Protocol

WEEKLY = "weekly"
MONTHLY = "monthly"
YEARLY = "yearly"

PERIOD_NOT_STARTED = "not_started"
PERIOD_ACTIVE = "active"
PERIOD_ENDED = "ended"


class PeriodicBudget(Protocol):
    """
    Structural type for anything with a recurring-budget shape.

    Why:
        Lets resolve_current_window accept both the SQLAlchemy BudgetModel
        and lightweight test doubles (e.g. SimpleNamespace) without a
        runtime dependency on the ORM model.
    """

    start_date: date
    end_date: Optional[date]
    period: str


@dataclass(frozen=True)
class PeriodWindow:
    """The calendar-aligned window (inclusive bounds) containing a reference date."""

    period_start: date
    period_end: date


@dataclass(frozen=True)
class CurrentWindow:
    """
    The calendar period window intersected with a budget's active lifetime.

    Fields:
        period_start/period_end: the full calendar-aligned window (inclusive).
        effective_start/effective_end: the window clamped to the budget's
            start_date/end_date, i.e. the span expenses are actually counted over.
        is_partial_period: True when the budget's lifetime clips either
            calendar boundary (activation mid-period, or deactivation mid-period).
        period_state: whether as_of falls before, during, or after the
            budget's active lifetime.
        days_in_period: length of the effective window, in days (inclusive).
        days_elapsed: how many of those days are on or before as_of, clamped
            to [0, days_in_period].
    """

    period_start: date
    period_end: date
    effective_start: date
    effective_end: date
    is_partial_period: bool
    period_state: str
    days_in_period: int
    days_elapsed: int


# Returns the exclusive start date of the period immediately following the
# given period_start.
# This function exists so period boundaries (and period_end, one day before
# the next start) are always derived from a single source of month/leap-year
# arithmetic rather than hand-computed in multiple places.
# Parameters:
# - period: recurrence unit, one of "weekly", "monthly", "yearly".
# - period_start: the inclusive start date of the current period. Must
#   already be aligned to a period boundary (as returned by resolve_period).
# Returns:
# - The first date of the following period.
# Raises:
# - ValueError: when period is not a supported recurrence unit.
def next_period_start(period: str, period_start: date) -> date:
    if period == WEEKLY:
        return period_start + timedelta(days=7)

    if period == MONTHLY:
        if period_start.month == 12:
            return date(period_start.year + 1, 1, 1)
        return date(period_start.year, period_start.month + 1, 1)

    if period == YEARLY:
        return date(period_start.year + 1, 1, 1)

    raise ValueError(f"Unsupported period: {period}")


# Resolves the calendar-aligned period window (inclusive bounds) containing
# a reference date.
# This function exists as the single source of calendar-boundary math for
# recurring budgets: weekly windows run Monday-Sunday, monthly windows run
# the 1st to the last day of the month, yearly windows run Jan 1-Dec 31.
# Parameters:
# - period: recurrence unit, one of "weekly", "monthly", "yearly".
# - as_of: the reference date to resolve a window for.
# Returns:
# - PeriodWindow with inclusive period_start/period_end.
# Raises:
# - ValueError: when period is not a supported recurrence unit.
def resolve_period(period: str, as_of: date) -> PeriodWindow:
    if period == WEEKLY:
        period_start = as_of - timedelta(days=as_of.weekday())
    elif period == MONTHLY:
        period_start = date(as_of.year, as_of.month, 1)
    elif period == YEARLY:
        period_start = date(as_of.year, 1, 1)
    else:
        raise ValueError(f"Unsupported period: {period}")

    period_end = next_period_start(period, period_start) - timedelta(days=1)
    return PeriodWindow(period_start=period_start, period_end=period_end)


# Resolves the current calendar period for a recurring budget, clamped to
# the budget's active lifetime (start_date/end_date).
# This function exists to answer "what window should this budget's spending
# be measured over right now," including the partial-period case where a
# budget is activated or deactivated mid-period.
# Parameters:
# - budget: anything with start_date, end_date, and period (see PeriodicBudget).
# - as_of: the reference date to resolve the window for.
# Returns:
# - CurrentWindow describing the full and effective bounds, partiality,
#   lifetime state, and elapsed/total day counts.
def resolve_current_window(budget: PeriodicBudget, as_of: date) -> CurrentWindow:
    if as_of < budget.start_date:
        period_state = PERIOD_NOT_STARTED
    elif budget.end_date is not None and as_of > budget.end_date:
        period_state = PERIOD_ENDED
    else:
        period_state = PERIOD_ACTIVE

    window = resolve_period(budget.period, as_of)

    effective_start = max(window.period_start, budget.start_date)
    effective_end = (
        window.period_end
        if budget.end_date is None
        else min(window.period_end, budget.end_date)
    )
    is_partial_period = (
        effective_start != window.period_start or effective_end != window.period_end
    )

    days_in_period = (effective_end - effective_start).days + 1

    if as_of < effective_start:
        days_elapsed = 0
    else:
        days_elapsed = (min(as_of, effective_end) - effective_start).days + 1
        days_elapsed = min(days_elapsed, days_in_period)

    return CurrentWindow(
        period_start=window.period_start,
        period_end=window.period_end,
        effective_start=effective_start,
        effective_end=effective_end,
        is_partial_period=is_partial_period,
        period_state=period_state,
        days_in_period=days_in_period,
        days_elapsed=days_elapsed,
    )
