import calendar
from datetime import date
from typing import Optional

# Future obligations (VF-GOALS-PLANNING-002C1): the deterministic calendar
# recurrence, pure (no database, clock or HTTP) so every rule is unit-testable.
#
# THE RULES
# - A one-time obligation has exactly one due date: first_due_date.
# - A monthly obligation is due once in every calendar month from the month of
#   first_due_date, on the ANCHOR DAY: the day of the month of first_due_date.
# - In a month that is shorter than the anchor day the due date is CLAMPED to
#   the last day of that month (the 31st becomes the 30th, the 28th or, in a
#   leap year, the 29th). The anchor is never overwritten, so the next long
#   month is due on the anchor day again: there is no accumulated drift.
# - A monthly obligation stops after final_due_date (inclusive), when given.
# - The due date of any month is computed DIRECTLY from the anchor, never by
#   stepping from the previous occurrence, so past months cost nothing and
#   cannot introduce drift.
# Money is not touched here.

SCHEDULE_ONE_TIME = "one_time"
SCHEDULE_MONTHLY = "monthly"

# The accepted range of a due date. Wide enough for any real obligation, narrow
# enough that month arithmetic can never run off the calendar.
MIN_DUE_DATE = date(2000, 1, 1)
MAX_DUE_DATE = date(2100, 12, 31)


# Absolute month number, so months can be compared and differenced.
def month_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


# The (year, month) of an absolute month number.
def year_and_month(index: int) -> tuple[int, int]:
    return index // 12, index % 12 + 1


# The due date of the anchor day in a month, clamped to the month's last day.
def clamped_due_date(anchor_day: int, year: int, month: int) -> date:
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


# Why a schedule combination is not valid, or None when it is.
# Used for the request (create) and for the resulting state of an update.
def schedule_shape_error(
    schedule: str,
    first_due_date: date,
    final_due_date: Optional[date],
) -> Optional[str]:
    if schedule == SCHEDULE_ONE_TIME and final_due_date is not None:
        return "A one-time obligation has a single due date and cannot have a final due date."

    if final_due_date is not None and final_due_date < first_due_date:
        return "The final due date cannot be before the first due date."

    return None


# The due date of an obligation in one calendar month, or None when it has none.
# Parameters:
# - schedule / first_due_date / final_due_date: the obligation.
# - year, month: the calendar month asked about.
# Returns:
# - The due date in that month, or None when the month is before the first due
#   date, after the final due date, or (one-time) not the month of the due date.
# This ignores "today": whether a date is still upcoming is the caller's rule.
def due_date_in_month(
    schedule: str,
    first_due_date: date,
    final_due_date: Optional[date],
    year: int,
    month: int,
) -> Optional[date]:
    months_after_first = month_index(year, month) - month_index(first_due_date.year, first_due_date.month)

    if months_after_first < 0:
        return None

    if schedule == SCHEDULE_ONE_TIME:
        return first_due_date if months_after_first == 0 else None

    due_date = clamped_due_date(first_due_date.day, year, month)

    if final_due_date is not None and due_date > final_due_date:
        return None

    return due_date


# The first due date on or after `as_of`, or None when none remains.
# This function exists for the list view ("next due"). It is O(1): it looks at
# the month of as_of (or of the first due date, if later) and at most the
# following one.
def next_due_date(
    schedule: str,
    first_due_date: date,
    final_due_date: Optional[date],
    as_of: date,
) -> Optional[date]:
    if schedule == SCHEDULE_ONE_TIME:
        return first_due_date if first_due_date >= as_of else None

    start_index = max(
        month_index(as_of.year, as_of.month),
        month_index(first_due_date.year, first_due_date.month),
    )

    for index in (start_index, start_index + 1):
        year, month = year_and_month(index)
        due_date = due_date_in_month(schedule, first_due_date, final_due_date, year, month)

        if due_date is None:
            # Past the final due date: every later month is too.
            return None

        if due_date >= as_of:
            return due_date

    return None
