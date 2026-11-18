from datetime import date
from typing import Optional

import pytest

from app.modules.future_obligations.future_obligation_schedule import (
    clamped_due_date,
    due_date_in_month,
    next_due_date,
    schedule_shape_error,
)

# VF-GOALS-PLANNING-002C1: the deterministic calendar recurrence, pure. The anchor day
# is the day of the first due date; short months clamp to their last day and the
# anchor is never changed, so there is no drift.

ONE = "one_time"
MONTHLY = "monthly"


def _dates(first: date, months: list[tuple[int, int]], final: Optional[date] = None) -> list[Optional[date]]:
    return [due_date_in_month(MONTHLY, first, final, year, month) for year, month in months]


class TestClamping:
    @pytest.mark.parametrize(
        "anchor, year, month, expected",
        [
            (31, 2026, 1, date(2026, 1, 31)),
            (31, 2026, 2, date(2026, 2, 28)),
            (31, 2028, 2, date(2028, 2, 29)),  # leap year
            (31, 2026, 4, date(2026, 4, 30)),
            (30, 2026, 2, date(2026, 2, 28)),
            (30, 2028, 2, date(2028, 2, 29)),
            (30, 2026, 4, date(2026, 4, 30)),
            (29, 2026, 2, date(2026, 2, 28)),  # not a leap year
            (29, 2028, 2, date(2028, 2, 29)),  # leap day exists
            (29, 2100, 2, date(2100, 2, 28)),  # 2100 is not a leap year
            (28, 2026, 2, date(2026, 2, 28)),
            (1, 2026, 12, date(2026, 12, 1)),
        ],
    )
    def test_the_anchor_day_is_clamped_to_the_last_day_of_a_short_month(self, anchor: int, year: int, month: int, expected: date) -> None:
        assert clamped_due_date(anchor, year, month) == expected


class TestMonthlyRecurrence:
    def test_day_31_clamps_in_short_months_and_returns_to_31_with_no_drift(self) -> None:
        first = date(2026, 1, 31)
        months = [(2026, m) for m in range(1, 13)]

        assert _dates(first, months) == [
            date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30),
            date(2026, 5, 31), date(2026, 6, 30), date(2026, 7, 31), date(2026, 8, 31),
            date(2026, 9, 30), date(2026, 10, 31), date(2026, 11, 30), date(2026, 12, 31),
        ]

    def test_day_30_and_day_29(self) -> None:
        thirty = _dates(date(2026, 1, 30), [(2026, 1), (2026, 2), (2026, 3), (2026, 4)])
        twenty_nine = _dates(date(2027, 1, 29), [(2027, 1), (2027, 2), (2027, 3)])

        assert thirty == [date(2026, 1, 30), date(2026, 2, 28), date(2026, 3, 30), date(2026, 4, 30)]
        assert twenty_nine == [date(2027, 1, 29), date(2027, 2, 28), date(2027, 3, 29)]

    def test_leap_february_uses_the_29th_and_the_next_year_does_not(self) -> None:
        first = date(2027, 12, 31)

        assert _dates(first, [(2027, 12), (2028, 1), (2028, 2), (2028, 3)]) == [
            date(2027, 12, 31), date(2028, 1, 31), date(2028, 2, 29), date(2028, 3, 31),
        ]
        assert due_date_in_month(MONTHLY, first, None, 2029, 2) == date(2029, 2, 28)

    def test_a_first_due_date_that_is_itself_the_29th_of_february(self) -> None:
        first = date(2028, 2, 29)

        assert _dates(first, [(2028, 2), (2028, 3), (2029, 2), (2032, 2)]) == [
            date(2028, 2, 29), date(2028, 3, 29), date(2029, 2, 28), date(2032, 2, 29),
        ]

    def test_the_date_comes_from_the_anchor_not_from_the_previous_occurrence(self) -> None:
        # Asking for March directly gives the 31st even though February clamps.
        assert due_date_in_month(MONTHLY, date(2026, 1, 31), None, 2026, 3) == date(2026, 3, 31)

    def test_nothing_before_the_first_due_date(self) -> None:
        first = date(2026, 6, 15)

        assert _dates(first, [(2026, 5), (2025, 12), (2026, 6)]) == [None, None, date(2026, 6, 15)]

    def test_crosses_year_ends(self) -> None:
        assert _dates(date(2026, 11, 15), [(2026, 12), (2027, 1), (2027, 2)]) == [
            date(2026, 12, 15), date(2027, 1, 15), date(2027, 2, 15),
        ]

    def test_the_final_due_date_is_inclusive_and_stops_later_months(self) -> None:
        first, final = date(2026, 1, 15), date(2026, 3, 15)

        assert _dates(first, [(2026, 1), (2026, 3), (2026, 4)], final) == [date(2026, 1, 15), date(2026, 3, 15), None]

    def test_a_clamped_due_date_before_or_on_the_final_due_date(self) -> None:
        first = date(2026, 1, 31)

        assert due_date_in_month(MONTHLY, first, date(2026, 2, 28), 2026, 2) == date(2026, 2, 28)  # inclusive
        assert due_date_in_month(MONTHLY, first, date(2026, 2, 27), 2026, 2) is None
        # March's due date is the 31st, after a final date of the 30th.
        assert due_date_in_month(MONTHLY, first, date(2026, 3, 30), 2026, 3) is None

    def test_a_final_due_date_in_the_first_month_gives_a_single_occurrence(self) -> None:
        first = date(2026, 5, 10)

        assert _dates(first, [(2026, 5), (2026, 6)], final=date(2026, 5, 10)) == [date(2026, 5, 10), None]


class TestOneTime:
    def test_only_the_month_of_its_due_date(self) -> None:
        first = date(2026, 12, 31)

        assert [due_date_in_month(ONE, first, None, 2026, m) for m in (11, 12)] == [None, date(2026, 12, 31)]
        assert due_date_in_month(ONE, first, None, 2027, 1) is None


class TestNextDueDate:
    def test_one_time_future_today_and_past(self) -> None:
        as_of = date(2026, 11, 16)

        assert next_due_date(ONE, date(2026, 12, 1), None, as_of) == date(2026, 12, 1)
        assert next_due_date(ONE, as_of, None, as_of) == as_of
        assert next_due_date(ONE, date(2026, 11, 15), None, as_of) is None

    def test_monthly_that_started_earlier_returns_only_what_is_still_upcoming(self) -> None:
        first = date(2025, 3, 20)

        assert next_due_date(MONTHLY, first, None, date(2026, 11, 16)) == date(2026, 11, 20)
        assert next_due_date(MONTHLY, first, None, date(2026, 11, 20)) == date(2026, 11, 20)  # due today
        assert next_due_date(MONTHLY, first, None, date(2026, 11, 21)) == date(2026, 12, 20)

    def test_a_first_due_date_in_the_future_is_the_next_one(self) -> None:
        assert next_due_date(MONTHLY, date(2027, 2, 10), None, date(2026, 11, 16)) == date(2027, 2, 10)

    def test_year_end_and_clamped_months(self) -> None:
        first = date(2026, 1, 31)

        assert next_due_date(MONTHLY, first, None, date(2026, 12, 31)) == date(2026, 12, 31)
        assert next_due_date(MONTHLY, first, None, date(2027, 1, 1)) == date(2027, 1, 31)
        assert next_due_date(MONTHLY, first, None, date(2027, 2, 1)) == date(2027, 2, 28)
        assert next_due_date(MONTHLY, first, None, date(2027, 2, 28)) == date(2027, 2, 28)
        assert next_due_date(MONTHLY, first, None, date(2027, 3, 1)) == date(2027, 3, 31)
        assert next_due_date(MONTHLY, date(2027, 12, 15), None, date(2027, 12, 16)) == date(2028, 1, 15)

    def test_none_once_the_final_due_date_has_passed(self) -> None:
        first, final = date(2026, 1, 15), date(2026, 11, 15)

        assert next_due_date(MONTHLY, first, final, date(2026, 11, 15)) == date(2026, 11, 15)
        assert next_due_date(MONTHLY, first, final, date(2026, 11, 16)) is None
        assert next_due_date(MONTHLY, first, final, date(2030, 1, 1)) is None

    def test_a_final_due_date_that_would_cut_a_clamped_month(self) -> None:
        # Due on the 31st; the final date is the 30th, so the March date (the 31st) is gone.
        assert next_due_date(MONTHLY, date(2026, 1, 31), date(2026, 3, 30), date(2026, 3, 1)) is None


class TestScheduleShape:
    def test_valid_and_invalid_combinations(self) -> None:
        assert schedule_shape_error(ONE, date(2026, 12, 1), None) is None
        assert schedule_shape_error(MONTHLY, date(2026, 12, 1), None) is None
        assert schedule_shape_error(MONTHLY, date(2026, 12, 1), date(2026, 12, 1)) is None
        assert "one-time" in (schedule_shape_error(ONE, date(2026, 12, 1), date(2027, 1, 1)) or "")
        assert "before the first" in (schedule_shape_error(MONTHLY, date(2026, 12, 2), date(2026, 12, 1)) or "")
