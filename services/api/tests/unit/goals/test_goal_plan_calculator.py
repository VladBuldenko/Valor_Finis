from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.calendar_period import MONTH, next_period_start
from app.modules.goals import goal_plan_calculator as calc
from app.modules.goals.goal_plan_calculator import HORIZON_MONTHS, build_goal_plan

# VF-GOALS-PLANNING-001: the pure planning arithmetic. No database, no clock:
# every date is injected, so the schedule, rounding, edge cases and bounds are
# exact and repeatable. The independent oracle for the schedule is the shared
# calendar helper (next_period_start), iterated.

TODAY = date(2026, 11, 16)
D = Decimal


def plan(
    *,
    target="2000.00",
    tracked="0.00",
    linked="0.00",
    target_date=None,
    contribution=None,
    status="active",
    as_of=TODAY,
):
    return build_goal_plan(
        goal_id=uuid4(),
        currency="EUR",
        goal_status=status,
        target_amount=D(target),
        tracked_amount=D(tracked),
        linked_amount=D(linked),
        target_date=target_date,
        monthly_contribution=None if contribution is None else D(contribution),
        as_of=as_of,
    )


def oracle_installments(as_of: date, target_date: date) -> list[date]:
    # The documented schedule, built with the shared helper and no arithmetic of our own.
    dates: list[date] = []
    current = as_of

    while current <= target_date:
        dates.append(current)
        current = next_period_start(MONTH, current)

    return dates


class TestRemainingAmount:
    def test_remaining_is_target_minus_current_exactly(self):
        assert calc.remaining_amount(D("2000.00"), D("500.00")) == D("1500.00")
        assert calc.remaining_amount(D("0.10"), D("0.07")) == D("0.03")  # no float drift
        assert str(calc.remaining_amount(D("1000.00"), D("0.00"))) == "1000.00"

    def test_funded_and_overfunded_goals_have_zero_remaining_never_negative(self):
        assert calc.remaining_amount(D("500.00"), D("500.00")) == D("0.00")
        assert calc.remaining_amount(D("500.00"), D("650.25")) == D("0.00")
        assert str(calc.remaining_amount(D("500.00"), D("650.25"))) == "0.00"
        assert calc.overfunded_amount(D("500.00"), D("650.25")) == D("150.25")
        assert calc.overfunded_amount(D("500.00"), D("500.00")) == D("0.00")
        assert calc.overfunded_amount(D("500.00"), D("100.00")) == D("0.00")


class TestSchedule:
    @pytest.mark.parametrize(
        ("as_of", "target", "expected"),
        [
            (date(2026, 11, 16), date(2026, 11, 16), 1),  # target today
            (date(2026, 11, 16), date(2026, 11, 30), 1),  # later this month: only today
            (date(2026, 11, 16), date(2026, 12, 1), 2),  # the 1st of next month is on time
            (date(2026, 11, 16), date(2026, 11, 15), 0),  # in the past
            (date(2026, 11, 16), date(2027, 2, 28), 4),  # Nov 16, Dec 1, Jan 1, Feb 1
            (date(2026, 12, 31), date(2027, 1, 1), 2),  # year transition
            (date(2026, 12, 31), date(2026, 12, 31), 1),
            (date(2028, 1, 31), date(2028, 2, 29), 2),  # leap day target, Feb 1 counts
            (date(2028, 2, 29), date(2028, 3, 1), 2),  # from the leap day itself
            (date(2027, 1, 31), date(2027, 2, 27), 2),  # non-leap February
            (date(2026, 11, 1), date(2026, 11, 1), 1),  # as_of on a 1st: one installment, not two
            (date(2026, 11, 1), date(2026, 12, 1), 2),
        ],
    )
    def test_installment_count_cases(self, as_of, target, expected):
        assert calc.installment_count(as_of, target) == expected

    def test_count_and_dates_agree_with_the_calendar_helper_over_a_sweep(self):
        # every as_of in a leap-year-spanning window against targets across year ends
        for offset in range(0, 800, 7):
            as_of = date(2027, 6, 1) + timedelta(days=offset)

            for target_offset in range(-3, 900, 11):
                target = as_of + timedelta(days=target_offset)
                expected = oracle_installments(as_of, target)

                assert calc.installment_count(as_of, target) == len(expected), (as_of, target)

                for number, expected_date in enumerate(expected[:30], start=1):
                    assert calc.installment_date(as_of, number) == expected_date

    def test_first_installment_is_today_and_the_rest_are_first_of_month(self):
        assert calc.installment_date(TODAY, 1) == TODAY
        assert calc.installment_date(TODAY, 2) == date(2026, 12, 1)
        assert calc.installment_date(TODAY, 3) == date(2027, 1, 1)
        assert calc.installment_date(date(2027, 12, 20), 2) == date(2028, 1, 1)

        with pytest.raises(ValueError):
            calc.installment_date(TODAY, 0)


class TestRequiredInstallment:
    def test_rounds_up_to_the_cent_and_is_never_short(self):
        # 100.00 over 3 = 33.333... -> 33.34
        result = plan(target="100.00", target_date=date(2027, 1, 20))  # Nov 16, Dec 1, Jan 1
        assert result.installment_count == 3
        assert result.required_per_installment == D("33.34")
        assert str(result.required_per_installment) == "33.34"

    def test_exact_division_is_not_rounded_up(self):
        result = plan(target="100.00", target_date=date(2027, 2, 20))  # 4 installments
        assert result.installment_count == 4
        assert result.required_per_installment == D("25.00")

    @pytest.mark.parametrize(
        ("remaining", "count"),
        [("100.00", 3), ("1000.00", 7), ("0.01", 5), ("0.05", 3), ("9999999999.99", 13), ("1.00", 1), ("123.45", 11)],
    )
    def test_is_the_smallest_cent_amount_that_covers_the_remainder(self, remaining, count):
        cents = int(D(remaining) * 100)
        per = calc._from_cents(calc._ceil_div(cents, count))

        assert per * count >= D(remaining)
        assert (per - D("0.01")) * count < D(remaining)

    def test_uses_the_ledger_sum_of_tracked_and_linked_progress(self):
        result = plan(target="1000.00", tracked="300.00", linked="200.00", target_date=date(2027, 1, 20))

        assert result.current_amount == D("500.00")
        assert result.remaining_amount == D("500.00")
        assert result.tracked_amount == D("300.00")
        assert result.linked_amount == D("200.00")
        assert result.required_per_installment == D("166.67")  # 500 / 3 rounded up

    def test_target_today_means_one_installment_today_for_the_whole_remainder(self):
        result = plan(target="800.00", tracked="100.00", target_date=TODAY)

        assert result.plan_status == "ready"
        assert (result.installment_count, result.required_per_installment) == (1, D("700.00"))
        assert result.first_installment_date == result.last_installment_date == TODAY

    def test_target_later_this_month_is_still_one_installment_today(self):
        result = plan(target="800.00", target_date=date(2026, 11, 30))

        assert (result.installment_count, result.last_installment_date) == (1, TODAY)

    def test_last_installment_is_the_first_of_the_target_month(self):
        result = plan(target="800.00", target_date=date(2027, 3, 31))

        assert result.first_installment_date == TODAY
        assert result.last_installment_date == date(2027, 3, 1)
        assert result.installment_count == 5

    def test_leap_year_and_year_end_targets(self):
        leap = plan(target="600.00", target_date=date(2028, 2, 29), as_of=date(2027, 12, 20))
        assert (leap.installment_count, leap.last_installment_date) == (3, date(2028, 2, 1))  # Dec 20, Jan 1, Feb 1

        year_end = plan(target="300.00", target_date=date(2027, 1, 1), as_of=date(2026, 12, 31))
        assert (year_end.installment_count, year_end.required_per_installment) == (2, D("150.00"))


class TestPlanStatus:
    def test_ready_with_a_future_target_date(self):
        assert plan(target_date=date(2027, 6, 30)).plan_status == "ready"

    def test_no_target_date_gives_progress_but_no_required_installment(self):
        result = plan(tracked="500.00")

        assert result.plan_status == "no_target_date"
        assert result.remaining_amount == D("1500.00")
        assert result.installment_count is None
        assert result.required_per_installment is None
        assert result.first_installment_date is None and result.last_installment_date is None

    def test_target_date_in_the_past(self):
        result = plan(target_date=date(2026, 11, 15))

        assert result.plan_status == "target_date_passed"
        assert result.required_per_installment is None
        assert result.remaining_amount == D("2000.00")

    def test_funded_goal_needs_nothing_even_with_a_past_date(self):
        funded = plan(target="500.00", tracked="500.00", target_date=date(2026, 1, 1))

        assert funded.plan_status == "already_funded"
        assert funded.remaining_amount == D("0.00")
        assert funded.required_per_installment is None

    def test_overfunded_goal(self):
        result = plan(target="500.00", tracked="400.00", linked="250.00", target_date=date(2027, 6, 1))

        assert result.plan_status == "already_funded"
        assert result.current_amount == D("650.00")
        assert result.remaining_amount == D("0.00")
        assert result.overfunded_amount == D("150.00")

    def test_archived_goal_is_never_planned(self):
        result = plan(target="1000.00", status="archived", target_date=date(2027, 6, 1), contribution="50.00")

        assert result.plan_status == "archived"
        assert result.required_per_installment is None
        assert result.remaining_amount == D("1000.00")
        assert result.what_if is not None and result.what_if.outcome == "not_applicable"

    def test_completed_status_is_planned_like_any_goal(self):
        assert plan(status="completed", target_date=date(2027, 6, 1)).plan_status == "ready"

    def test_no_progress_yet(self):
        result = plan(target="1200.00", target_date=date(2027, 10, 20))  # Nov 16 + 11 first-of-months = 12

        assert result.current_amount == D("0.00")
        assert (result.installment_count, result.required_per_installment) == (12, D("100.00"))

    def test_tracked_only_and_linked_goals_are_reported_separately(self):
        tracked_only = plan(tracked="250.00")
        linked = plan(linked="250.00")

        assert (tracked_only.tracked_amount, tracked_only.linked_amount) == (D("250.00"), D("0.00"))
        assert (linked.tracked_amount, linked.linked_amount) == (D("0.00"), D("250.00"))
        assert tracked_only.current_amount == linked.current_amount == D("250.00")


class TestWhatIf:
    def test_no_what_if_unless_a_contribution_is_given(self):
        assert plan(target_date=date(2027, 6, 1)).what_if is None

    def test_completion_date_follows_the_same_schedule(self):
        result = plan(target="450.00", contribution="100.00")  # 5 installments

        assert result.what_if.outcome == "reaches_target"
        assert result.what_if.installments_needed == 5
        assert result.what_if.estimated_completion_date == date(2027, 3, 1)  # Nov 16, Dec 1, Jan 1, Feb 1, Mar 1
        assert result.what_if.monthly_contribution == D("100.00")

    def test_a_contribution_covering_everything_finishes_today(self):
        result = plan(target="300.00", tracked="100.00", contribution="9999999999.99")

        assert (result.what_if.installments_needed, result.what_if.estimated_completion_date) == (1, TODAY)

    def test_exact_multiples_do_not_need_an_extra_installment(self):
        assert plan(target="300.00", contribution="100.00").what_if.installments_needed == 3
        assert plan(target="300.01", contribution="100.00").what_if.installments_needed == 4

    def test_zero_contribution_has_no_date(self):
        what_if = plan(target="300.00", contribution="0.00").what_if

        assert what_if.outcome == "no_contribution"
        assert (what_if.installments_needed, what_if.estimated_completion_date) == (None, None)

    def test_tiny_contributions_are_bounded_not_looped(self):
        # 10,000,000.00 at 0.01 per installment would be 10^9 installments
        what_if = plan(target="10000000.00", contribution="0.01").what_if

        assert what_if.outcome == "not_reachable_within_horizon"
        assert what_if.installments_needed is None and what_if.estimated_completion_date is None

    def test_the_horizon_boundary_is_exact(self):
        # installment k is k-1 months after the first: 601 installments are still inside the horizon
        inside = plan(target=f"{HORIZON_MONTHS + 1}.00", contribution="1.00").what_if
        outside = plan(target=f"{HORIZON_MONTHS + 2}.00", contribution="1.00").what_if

        assert inside.outcome == "reaches_target" and inside.installments_needed == HORIZON_MONTHS + 1
        assert inside.estimated_completion_date == date(2076, 11, 1)
        assert outside.outcome == "not_reachable_within_horizon"

    def test_calendar_exhaustion_is_not_a_crash(self):
        what_if = plan(target="500.00", contribution="1.00", as_of=date(9999, 6, 1)).what_if

        assert what_if.outcome == "not_reachable_within_horizon"

    def test_funded_goal(self):
        assert plan(target="500.00", tracked="700.00", contribution="50.00").what_if.outcome == "already_funded"

    def test_compares_with_the_target_date(self):
        on_time = plan(target="300.00", contribution="100.00", target_date=date(2027, 1, 1)).what_if
        late = plan(target="300.00", contribution="100.00", target_date=date(2026, 12, 31)).what_if
        no_date = plan(target="300.00", contribution="100.00").what_if
        passed = plan(target="300.00", contribution="100.00", target_date=date(2026, 11, 1)).what_if

        assert on_time.estimated_completion_date == date(2027, 1, 1) and on_time.on_or_before_target_date is True
        assert late.on_or_before_target_date is False
        assert no_date.on_or_before_target_date is None
        assert passed.outcome == "reaches_target" and passed.on_or_before_target_date is None

    def test_year_and_leap_year_transitions(self):
        across_year = plan(target="300.00", contribution="100.00", as_of=date(2026, 12, 15)).what_if
        leap = plan(target="300.00", contribution="100.00", as_of=date(2028, 1, 31)).what_if

        assert across_year.estimated_completion_date == date(2027, 2, 1)
        assert leap.estimated_completion_date == date(2028, 3, 1)  # Jan 31, Feb 1, Mar 1

    def test_more_than_two_decimals_is_refused_never_rounded(self):
        with pytest.raises(ValueError):
            plan(target="300.00", contribution="10.005")


def test_every_amount_has_exactly_two_decimal_places():
    result = plan(target="1000.00", tracked="333.33", target_date=date(2027, 4, 20), contribution="77.77")

    for value in (
        result.target_amount,
        result.current_amount,
        result.remaining_amount,
        result.overfunded_amount,
        result.required_per_installment,
        result.what_if.monthly_contribution,
    ):
        assert value == value.quantize(D("0.01")), value
        assert value.as_tuple().exponent == -2, value
