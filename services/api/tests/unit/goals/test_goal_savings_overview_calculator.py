import calendar
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from app.modules.analytics.analytics_schemas import IncomeExpenseTrendBucket
from app.modules.goals.goal_plan_calculator import build_goal_plan
from app.modules.goals.goal_savings_overview_calculator import HORIZON_MONTHS, build_goal_savings_overview
from app.modules.goals.goal_schemas import GoalResponse

# VF-GOALS-PLANNING-002B: the pure combination of every planned Goal's
# installment into a bounded monthly schedule, compared with recorded history.
# Goals and buckets are built directly (the shapes the service hands in); the
# database path is covered by the integration tests.

AS_OF = date(2026, 11, 16)
ALWAYS = ["budgets_not_modelled", "goal_commitments_not_modelled", "future_obligations_not_modelled"]
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _goal(
    name: str = "Goal",
    *,
    target: str = "1000.00",
    tracked: str = "0.00",
    linked: str = "0.00",
    target_date: Optional[date] = date(2027, 3, 31),
    currency: str = "EUR",
    status: str = "active",
    rank: Optional[int] = 1,
) -> GoalResponse:
    tracked_amount, linked_amount = Decimal(tracked), Decimal(linked)

    return GoalResponse(
        id=uuid4(),
        user_id=uuid4(),
        name=name,
        target_amount=Decimal(target),
        current_amount=tracked_amount + linked_amount,
        priority_rank=rank,
        tracked_amount=tracked_amount,
        linked_amount=linked_amount,
        allocations=[],
        currency=currency,
        target_date=target_date,
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )


def _bucket(year: int, month: int, income: str = "3000.00", expense: str = "2400.00", unresolved_expense: int = 0) -> IncomeExpenseTrendBucket:
    income_total, expense_total = Decimal(income), Decimal(expense)
    end = date(year, month, calendar.monthrange(year, month)[1])

    return IncomeExpenseTrendBucket(
        income_total=income_total,
        expense_total=expense_total,
        net_flow=income_total - expense_total,
        savings_rate_percent=None,
        income_count=1 if income_total else 0,
        expense_count=1 if expense_total else 0,
        unresolved_income_count=0,
        unresolved_expense_count=unresolved_expense,
        period_start=date(year, month, 1),
        period_end=end,
        effective_end=end,
        is_complete=True,
    )


# August, September and October 2026: the completed months before AS_OF.
HISTORY = [_bucket(2026, 8), _bucket(2026, 9), _bucket(2026, 10)]  # net 600.00 each


def _overview(goals, history=HISTORY, base: str = "EUR", as_of: date = AS_OF):
    return build_goal_savings_overview(goals=goals, base_currency=base, history_buckets=history, as_of=as_of)


def _totals(overview) -> list[str]:
    return [str(month.total_required) for month in overview.months]


class TestMultipleGoalsAndPriorities:
    def test_installments_are_added_per_month_and_each_goal_stops_after_its_target_date(self) -> None:
        # as_of 2026-11-16: installments Nov 16, Dec 1, Jan 1, Feb 1, Mar 1.
        long_goal = _goal("Long", target="1000.00", target_date=date(2027, 3, 31), rank=1)  # 5 installments -> 200.00
        short_goal = _goal("Short", target="600.00", target_date=date(2026, 12, 20), rank=2)  # 2 installments -> 300.00

        overview = _overview([long_goal, short_goal])

        assert [str(g.required_per_installment) for g in overview.planned_goals] == ["200.00", "300.00"]
        assert [g.installment_count for g in overview.planned_goals] == [5, 2]
        assert _totals(overview) == ["500.00", "500.00", "200.00", "200.00", "200.00"] + ["0.00"] * 7
        assert [m.planned_goal_count for m in overview.months] == [2, 2, 1, 1, 1] + [0] * 7

    def test_a_goal_completing_before_another_lowers_the_later_months_only(self) -> None:
        first = _goal("Ends early", target="400.00", target_date=date(2026, 12, 31), rank=1)  # 2 x 200.00
        second = _goal("Ends late", target="900.00", target_date=date(2027, 2, 28), rank=2)  # 4 x 225.00

        overview = _overview([first, second])
        by_month = [{c.goal_id: str(c.amount) for c in m.contributions} for m in overview.months[:5]]

        assert by_month[0] == {first.id: "200.00", second.id: "225.00"}
        assert by_month[1] == {first.id: "200.00", second.id: "225.00"}
        assert by_month[2] == {second.id: "225.00"}
        assert by_month[3] == {second.id: "225.00"}
        assert by_month[4] == {}

    def test_display_order_is_the_goal_priority_whatever_order_the_goals_arrive_in(self) -> None:
        low = _goal("Low", rank=3)
        high = _goal("High", rank=1)
        middle = _goal("Middle", rank=2)

        overview = _overview([low, high, middle])

        assert [g.name for g in overview.planned_goals] == ["High", "Middle", "Low"]
        assert [c.goal_id for c in overview.months[0].contributions] == [high.id, middle.id, low.id]

    def test_a_month_s_total_is_exactly_the_sum_of_its_contributions_and_each_goal_counts_once(self) -> None:
        goals = [_goal(f"G{n}", target=f"{n * 100 + 33}.33", rank=n) for n in range(1, 5)]

        overview = _overview(goals)

        for month in overview.months:
            assert month.total_required == sum((c.amount for c in month.contributions), Decimal("0.00"))
            assert len({c.goal_id for c in month.contributions}) == len(month.contributions)
            assert month.planned_goal_count == len(month.contributions)

    def test_the_installment_is_the_goal_plan_s_own_not_a_second_calculation(self) -> None:
        goal = _goal(target="1234.56", tracked="100.00", linked="23.45", target_date=date(2027, 6, 30))

        plan = build_goal_plan(
            goal_id=goal.id,
            currency="EUR",
            goal_status="active",
            target_amount=goal.target_amount,
            tracked_amount=goal.tracked_amount,
            linked_amount=goal.linked_amount,
            target_date=goal.target_date,
            monthly_contribution=None,
            as_of=AS_OF,
        )
        item = _overview([goal]).planned_goals[0]

        assert item.required_per_installment == plan.required_per_installment
        assert item.installment_count == plan.installment_count
        assert item.remaining_amount == plan.remaining_amount
        assert (item.first_installment_date, item.last_installment_date) == (plan.first_installment_date, plan.last_installment_date)


class TestExactDecimalArithmetic:
    def test_installments_round_up_to_the_cent_and_totals_add_exactly(self) -> None:
        thirds = _goal("Thirds", target="100.00", target_date=date(2027, 1, 20), rank=1)  # 3 installments -> 33.34
        other = _goal("Other", target="10.01", target_date=date(2027, 1, 20), rank=2)  # 3 installments -> 3.34

        overview = _overview([thirds, other])

        assert [str(g.required_per_installment) for g in overview.planned_goals] == ["33.34", "3.34"]
        assert _totals(overview)[:3] == ["36.68", "36.68", "36.68"]
        assert all(isinstance(m.total_required, Decimal) for m in overview.months)

    def test_every_amount_has_two_decimal_places(self) -> None:
        overview = _overview([_goal(target="999.99", target_date=date(2027, 2, 1))])

        for month in overview.months:
            assert month.total_required.as_tuple().exponent == -2
        assert overview.planned_goals[0].required_per_installment.as_tuple().exponent == -2

    def test_a_per_goal_rounding_surplus_is_not_hidden(self) -> None:
        # 100.00 / 3 installments rounds up to 33.34, so three installments add 100.02:
        # the month totals report the installments as planned, not the remainder.
        overview = _overview([_goal(target="100.00", target_date=date(2027, 1, 20))])

        assert sum((m.total_required for m in overview.months), Decimal("0.00")) == Decimal("100.02")


class TestProgressIsNotAMonthlyObligation:
    def test_tracked_and_linked_progress_reduce_what_remains_and_are_counted_once(self) -> None:
        goal = _goal(target="1000.00", tracked="300.00", linked="200.00", target_date=date(2027, 3, 31))  # remaining 500.00 / 5

        overview = _overview([goal])

        assert overview.planned_goals[0].remaining_amount == Decimal("500.00")
        assert overview.planned_goals[0].required_per_installment == Decimal("100.00")
        assert _totals(overview)[:5] == ["100.00"] * 5

    def test_target_amounts_and_reservations_are_never_summed_as_monthly_obligations(self) -> None:
        goals = [_goal(f"G{n}", target="1000.00", linked="400.00", rank=n, target_date=date(2027, 3, 31)) for n in (1, 2)]

        overview = _overview(goals)

        assert all(m.total_required <= Decimal("240.00") for m in overview.months)  # 2 x (600.00 / 5)
        assert overview.months[0].total_required == Decimal("240.00")


class TestWhichGoalsAreExcluded:
    def test_funded_overfunded_archived_and_completed_goals_add_nothing(self) -> None:
        goals = [
            _goal("Funded", target="500.00", tracked="500.00", rank=1),
            _goal("Overfunded", target="500.00", tracked="650.00", rank=2),
            _goal("Archived", status="archived", rank=None),
            _goal("Completed with room", status="completed", rank=3),
            _goal("Planned", target="500.00", rank=4, target_date=date(2026, 11, 30)),
        ]

        overview = _overview(goals)

        assert overview.exclusions.already_funded == 2
        assert overview.exclusions.archived == 1
        assert overview.exclusions.completed == 1
        assert [g.name for g in overview.planned_goals] == ["Planned"]
        assert _totals(overview)[0] == "500.00"

    def test_goals_without_a_target_date_and_overdue_goals_are_unplanned_not_zero(self) -> None:
        goals = [
            _goal("Undated", target_date=None, rank=1),
            _goal("Overdue", target_date=date(2026, 11, 15), rank=2),
            _goal("Due today", target_date=AS_OF, rank=3, target="250.00"),
        ]

        overview = _overview(goals)

        assert overview.exclusions.no_target_date == 1
        assert overview.exclusions.target_date_passed == 1
        assert [g.name for g in overview.planned_goals] == ["Due today"]
        assert overview.planned_goals[0].installment_count == 1
        assert _totals(overview)[:2] == ["250.00", "0.00"]
        assert "goals_without_target_date" in overview.limitations
        assert "goals_with_passed_target_date" in overview.limitations

    def test_no_goals_at_all(self) -> None:
        overview = _overview([])

        assert overview.planned_goals == []
        assert len(overview.months) == HORIZON_MONTHS
        assert set(_totals(overview)) == {"0.00"}
        assert overview.history.status == "no_planned_goals"
        assert overview.is_total_complete is True
        assert overview.limitations == ALWAYS
        assert all(m.historical_difference is None for m in overview.months)

    def test_only_excluded_goals_is_not_a_zero_requirement(self) -> None:
        overview = _overview([_goal(target_date=None)])

        assert overview.history.status == "no_planned_goals"
        assert all(m.historical_difference is None and m.planned_goal_count == 0 for m in overview.months)


class TestMixedCurrencies:
    def test_goals_in_other_currencies_are_excluded_never_added_or_converted(self) -> None:
        eur = _goal("Eur", target="500.00", rank=1, target_date=date(2026, 11, 30))
        usd = _goal("Usd", target="900.00", rank=2, currency="USD", target_date=date(2026, 11, 30))
        gbp = _goal("Gbp", target="700.00", rank=3, currency="GBP", target_date=date(2026, 11, 30))

        overview = _overview([eur, usd, gbp])

        assert [g.name for g in overview.planned_goals] == ["Eur"]
        assert overview.months[0].total_required == Decimal("500.00")
        assert overview.exclusions.other_currency == 2
        assert overview.exclusions.other_currencies == ["GBP", "USD"]
        assert overview.is_total_complete is False
        assert "other_currency_goals_excluded" in overview.limitations
        assert overview.base_currency == "EUR"

    def test_an_other_currency_goal_that_needs_nothing_does_not_make_the_total_incomplete(self) -> None:
        usd_funded = _goal("Usd funded", target="100.00", tracked="100.00", currency="USD")
        usd_undated = _goal("Usd undated", currency="USD", target_date=None)
        usd_archived = _goal("Usd archived", currency="USD", status="archived", rank=None)

        overview = _overview([usd_funded, usd_undated, usd_archived])

        assert overview.is_total_complete is True
        assert overview.exclusions.other_currency == 0
        assert overview.exclusions.other_currencies == []
        assert (overview.exclusions.already_funded, overview.exclusions.no_target_date, overview.exclusions.archived) == (1, 1, 1)

    def test_the_base_currency_decides_which_goals_count(self) -> None:
        eur = _goal("Eur", currency="EUR", target_date=date(2026, 11, 30))
        usd = _goal("Usd", currency="USD", target="300.00", target_date=date(2026, 11, 30), rank=2)

        overview = _overview([eur, usd], base="USD")

        assert [g.name for g in overview.planned_goals] == ["Usd"]
        assert overview.exclusions.other_currencies == ["EUR"]


class TestCalendarBoundaries:
    def test_the_window_is_twelve_calendar_months_starting_with_the_current_one(self) -> None:
        overview = _overview([_goal()])

        assert overview.horizon_months == 12 == len(overview.months)
        assert overview.months[0].period_start == date(2026, 11, 1)
        assert overview.months[0].installment_date == AS_OF
        assert overview.months[1].installment_date == date(2026, 12, 1)
        assert overview.months[2].period_start == date(2027, 1, 1)  # across the year end
        assert overview.months[11].period_start == date(2027, 10, 1)
        assert overview.months[11].period_end == date(2027, 10, 31)

    def test_installments_on_the_last_day_of_a_month_and_the_first_of_the_next(self) -> None:
        as_of = date(2026, 11, 30)
        one = _goal("Today only", target="100.00", target_date=date(2026, 11, 30))
        two = _goal("Plus the 1st", target="100.00", target_date=date(2026, 12, 1), rank=2)

        overview = _overview([one, two], as_of=as_of, history=HISTORY)

        assert [g.installment_count for g in overview.planned_goals] == [1, 2]
        assert [m.planned_goal_count for m in overview.months[:3]] == [2, 1, 0]
        assert overview.months[0].installment_date == as_of
        assert overview.months[1].installment_date == date(2026, 12, 1)

    def test_a_target_date_before_the_next_first_of_the_month_adds_no_further_installment(self) -> None:
        goal = _goal(target="300.00", target_date=date(2026, 11, 30))

        assert _overview([goal]).planned_goals[0].installment_count == 1

    def test_leap_year_february(self) -> None:
        as_of = date(2028, 2, 15)
        until_29th = _goal("Feb 29", target="100.00", target_date=date(2028, 2, 29))
        until_mar_1 = _goal("Mar 1", target="100.00", target_date=date(2028, 3, 1), rank=2)

        overview = _overview([until_29th, until_mar_1], as_of=as_of, history=[_bucket(2028, 1), _bucket(2027, 12), _bucket(2027, 11)])

        assert overview.months[0].period_end == date(2028, 2, 29)
        assert overview.months[1].period_start == date(2028, 3, 1)
        assert [g.installment_count for g in overview.planned_goals] == [1, 2]

    def test_non_leap_february_ends_on_the_28th(self) -> None:
        overview = _overview([_goal()], as_of=date(2027, 2, 10), history=HISTORY)

        assert overview.months[0].period_end == date(2027, 2, 28)

    def test_a_goal_beyond_the_window_contributes_in_every_month_and_says_so(self) -> None:
        far = _goal("Far", target="6000.00", target_date=date(2031, 11, 30), rank=1)
        edge = _goal("Edge", target="1200.00", target_date=date(2027, 10, 31), rank=2)  # exactly 12 installments
        beyond = _goal("Beyond", target="1300.00", target_date=date(2027, 11, 30), rank=3)  # 13 installments

        overview = _overview([far, edge, beyond])
        flags = {g.name: g.continues_after_window for g in overview.planned_goals}

        assert len(overview.months) == 12
        assert flags == {"Far": True, "Edge": False, "Beyond": True}
        assert [m.planned_goal_count for m in overview.months] == [3] * 12


class TestHistoricalComparison:
    def test_the_difference_is_calculated_for_each_month_not_for_goals_running_forever(self) -> None:
        ends_early = _goal("Early", target="800.00", target_date=date(2026, 12, 31), rank=1)  # 2 x 400.00
        runs_on = _goal("Runs on", target="1000.00", target_date=date(2027, 3, 31), rank=2)  # 5 x 200.00

        overview = _overview([ends_early, runs_on])
        differences = [m.historical_difference for m in overview.months[:6]]

        assert overview.history.status == "comparable"
        assert overview.history.average_monthly_net_flow == Decimal("600.00")
        assert differences == [Decimal("0.00"), Decimal("0.00"), Decimal("400.00"), Decimal("400.00"), Decimal("400.00"), None]
        assert [m.difference_direction for m in overview.months[:6]] == ["equal", "equal", "surplus", "surplus", "surplus", None]

    def test_a_shortfall_is_reported_with_its_sign(self) -> None:
        overview = _overview([_goal(target="4000.00", target_date=date(2027, 1, 31))])  # 3 x 1333.34

        assert overview.months[0].historical_difference == Decimal("-733.34")
        assert overview.months[0].difference_direction == "shortfall"

    def test_a_negative_historical_net_flow_makes_every_installment_a_shortfall(self) -> None:
        negative = [_bucket(2026, month, income="1000.00", expense="1500.00") for month in (8, 9, 10)]

        overview = _overview([_goal(target="500.00", target_date=date(2026, 11, 30))], history=negative)

        assert overview.history.average_monthly_net_flow == Decimal("-500.00")
        assert overview.months[0].historical_difference == Decimal("-1000.00")
        assert overview.months[0].difference_direction == "shortfall"

    def test_the_average_uses_the_shared_history_rules(self) -> None:
        # Two active months out of three: the empty month is left out, never counted as zero.
        history = [_bucket(2026, 8, income="0.00", expense="0.00"), _bucket(2026, 9, income="3000.00", expense="2500.00"), _bucket(2026, 10, income="3200.00", expense="2500.00")]

        overview = _overview([_goal()], history=history)

        assert overview.history.status == "comparable"
        assert overview.history.months_used == 2
        assert overview.history.average_monthly_net_flow == Decimal("600.00")
        assert "months_without_activity_excluded" in overview.limitations

    def test_half_even_rounding_of_the_average(self) -> None:
        history = [_bucket(2026, 8, income="3000.00", expense="2999.99"), _bucket(2026, 9, income="3000.00", expense="2999.98"), _bucket(2026, 10, income="3000.00", expense="2999.98")]
        # nets 0.01 + 0.02 + 0.02 = 0.05 / 3 = 0.01666... -> 0.02

        assert _overview([_goal()], history=history).history.average_monthly_net_flow == Decimal("0.02")

    def test_insufficient_history_gives_no_difference_but_still_the_installments(self) -> None:
        thin = [_bucket(2026, 8, income="0.00", expense="0.00"), _bucket(2026, 9, income="0.00", expense="0.00"), _bucket(2026, 10)]

        overview = _overview([_goal(target="500.00", target_date=date(2026, 11, 30))], history=thin)

        assert overview.history.status == "insufficient_data"
        assert overview.history.average_monthly_net_flow is None
        assert overview.months[0].total_required == Decimal("500.00")
        assert all(m.historical_difference is None for m in overview.months)
        assert "fewer_than_two_active_months" in overview.limitations

    def test_unresolved_currency_data_blocks_the_comparison(self) -> None:
        history = [_bucket(2026, 8), _bucket(2026, 9, unresolved_expense=1), _bucket(2026, 10)]

        overview = _overview([_goal()], history=history)

        assert overview.history.status == "insufficient_data"
        assert "unresolved_currency_data" in overview.limitations
        assert all(m.historical_difference is None for m in overview.months)

    def test_history_limitations_are_not_reported_when_there_is_nothing_to_compare(self) -> None:
        thin = [_bucket(2026, 8, income="0.00", expense="0.00")] * 3

        overview = _overview([], history=thin)

        assert overview.limitations == ALWAYS

    def test_an_incomplete_total_still_compares_the_goals_that_are_included(self) -> None:
        eur = _goal("Eur", target="300.00", target_date=date(2026, 11, 30))
        usd = _goal("Usd", target="9999.00", currency="USD", target_date=date(2026, 11, 30), rank=2)

        overview = _overview([eur, usd])

        assert overview.is_total_complete is False
        assert overview.months[0].historical_difference == Decimal("300.00")


class TestLimitationsAndWording:
    def test_the_unmodelled_obligations_are_always_disclosed_last(self) -> None:
        overview = _overview([_goal()])

        assert overview.limitations == ALWAYS

    def test_limitations_are_ordered_data_quality_then_goal_exclusions_then_the_constant_ones(self) -> None:
        thin = [_bucket(2026, 8, income="0.00", expense="0.00")] * 2 + [_bucket(2026, 10)]
        goals = [
            _goal("A", rank=1),
            _goal("Usd", currency="USD", rank=2),
            _goal("Undated", target_date=None, rank=3),
            _goal("Overdue", target_date=date(2026, 1, 1), rank=4),
        ]

        overview = _overview(goals, history=thin)

        assert overview.limitations == [
            "fewer_than_two_active_months",
            "other_currency_goals_excluded",
            "goals_without_target_date",
            "goals_with_passed_target_date",
            *ALWAYS,
        ]
