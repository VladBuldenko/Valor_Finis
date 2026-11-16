from datetime import date, timedelta
from decimal import Decimal
from typing import Optional
from uuid import uuid4

import pytest

from app.modules.analytics.analytics_schemas import IncomeExpenseTrendBucket
from app.modules.goals.goal_history_calculator import build_goal_history_comparison

# VF-GOALS-PLANNING-002A: the pure comparison of a required installment with the
# recorded history of completed months. Buckets are built directly (the shape
# the income/expense trend returns); the database path is covered by the
# integration tests.

AS_OF = date(2026, 11, 16)
GOAL_ID = uuid4()
ALWAYS = ["budgets_not_modelled", "goal_commitments_not_modelled"]


def _bucket(
    month: int,
    income: str = "3000.00",
    expense: str = "2400.00",
    income_count: Optional[int] = None,
    expense_count: Optional[int] = None,
    unresolved_income: int = 0,
    unresolved_expense: int = 0,
) -> IncomeExpenseTrendBucket:
    income_total, expense_total = Decimal(income), Decimal(expense)
    start = date(2026, month, 1)
    end = date(2026, month + 1, 1) - timedelta(days=1)

    return IncomeExpenseTrendBucket(
        income_total=income_total,
        expense_total=expense_total,
        net_flow=income_total - expense_total,
        savings_rate_percent=None,
        income_count=(1 if income_total else 0) if income_count is None else income_count,
        expense_count=(1 if expense_total else 0) if expense_count is None else expense_count,
        unresolved_income_count=unresolved_income,
        unresolved_expense_count=unresolved_expense,
        period_start=start,
        period_end=end,
        effective_end=end,
        is_complete=True,
    )


def _compare(buckets, required: Optional[str] = "450.00", goal_currency: str = "EUR", base_currency: str = "EUR"):
    return build_goal_history_comparison(
        goal_id=GOAL_ID,
        goal_currency=goal_currency,
        base_currency=base_currency,
        required_per_installment=None if required is None else Decimal(required),
        buckets=buckets,
        as_of=AS_OF,
    )


THREE = [_bucket(8), _bucket(9), _bucket(10)]


class TestComparableHistory:
    def test_the_documented_example(self) -> None:
        result = _compare(THREE)

        assert result.status == "comparable"
        assert result.average_monthly_income == Decimal("3000.00")
        assert result.average_monthly_expenses == Decimal("2400.00")
        assert result.average_monthly_net_flow == Decimal("600.00")
        assert result.required_per_installment == Decimal("450.00")
        assert result.historical_difference == Decimal("150.00")
        assert result.difference_direction == "surplus"
        assert result.months_used == 3
        assert result.limitations == ALWAYS
        assert (result.analysis_period_start, result.analysis_period_end) == (date(2026, 8, 1), date(2026, 10, 31))
        assert [m.included_in_average for m in result.months] == [True, True, True]

    def test_the_average_is_an_exact_decimal_sum_over_months_used(self) -> None:
        # 100.00 + 100.00 + 100.01 = 300.01; / 3 = 100.00333... -> 100.00
        result = _compare([_bucket(8, "1100.00", "1000.00"), _bucket(9, "1100.00", "1000.00"), _bucket(10, "1100.01", "1000.00")])

        assert result.average_monthly_net_flow == Decimal("100.00")
        assert all(isinstance(value, Decimal) for value in (result.average_monthly_income, result.average_monthly_expenses, result.average_monthly_net_flow, result.historical_difference))

    @pytest.mark.parametrize(
        ("nets", "expected"),
        [
            (("0.01", "0.00"), "0.00"),  # 0.005 -> half-even rounds to the even cent
            (("0.03", "0.00"), "0.02"),  # 0.015 -> 0.02
            (("0.02", "0.01"), "0.02"),  # 0.015 -> 0.02
            (("0.04", "0.01"), "0.02"),  # 0.025 -> 0.02
        ],
    )
    def test_rounding_is_half_even_to_the_cent(self, nets, expected) -> None:
        # Income 100.00 less an expense chosen to leave the given net.
        buckets = [_bucket(m, "100.00", str(Decimal("100.00") - Decimal(net))) for m, net in zip((9, 10), nets)]

        assert _compare(buckets).average_monthly_net_flow == Decimal(expected)

    def test_a_sum_that_float_arithmetic_would_get_wrong_is_exact(self) -> None:
        buckets = [_bucket(m, "0.30", "0.10") for m in (8, 9, 10)]  # float: 0.3 - 0.1 = 0.19999999999999998

        result = _compare(buckets, required="0.20")

        assert result.average_monthly_net_flow == Decimal("0.20")
        assert result.historical_difference == Decimal("0.00")
        assert result.difference_direction == "equal"

    def test_positive_zero_and_negative_net_flow(self) -> None:
        positive = _compare(THREE, required="600.01")
        zero_net = _compare([_bucket(m, "2000.00", "2000.00") for m in (8, 9, 10)], required="0.00")
        negative = _compare([_bucket(m, "2000.00", "2300.00") for m in (8, 9, 10)], required="100.00")

        assert (positive.historical_difference, positive.difference_direction) == (Decimal("-0.01"), "shortfall")
        assert (zero_net.average_monthly_net_flow, zero_net.historical_difference, zero_net.difference_direction) == (Decimal("0.00"), Decimal("0.00"), "equal")
        assert (negative.average_monthly_net_flow, negative.historical_difference, negative.difference_direction) == (Decimal("-300.00"), Decimal("-400.00"), "shortfall")
        assert negative.status == "comparable"

    def test_a_negative_net_flow_is_not_clamped_when_compared_with_a_zero_requirement(self) -> None:
        result = _compare([_bucket(m, "1000.00", "1250.00") for m in (8, 9, 10)], required="0.00")

        assert result.historical_difference == Decimal("-250.00")


class TestMissingHistory:
    def test_a_month_without_records_is_excluded_not_counted_as_zero(self) -> None:
        result = _compare([_bucket(8, "0.00", "0.00"), _bucket(9, "3000.00", "2400.00"), _bucket(10, "3000.00", "2000.00")])

        # (600 + 1000) / 2 = 800.00 - never / 3 = 533.33
        assert result.status == "comparable"
        assert result.months_used == 2
        assert result.average_monthly_net_flow == Decimal("800.00")
        assert result.average_monthly_income == Decimal("3000.00")
        assert result.limitations == ["months_without_activity_excluded"] + ALWAYS
        assert [m.included_in_average for m in result.months] == [False, True, True]
        assert [m.has_activity for m in result.months] == [False, True, True]

    def test_a_month_with_only_income_or_only_expenses_is_not_active(self) -> None:
        income_only = _bucket(8, "3000.00", "0.00")
        expense_only = _bucket(9, "0.00", "500.00")

        result = _compare([income_only, expense_only, _bucket(10)])

        assert result.status == "insufficient_data"
        assert [m.has_activity for m in result.months] == [False, False, True]
        # The months are still described, so the user can see what exists.
        assert result.months[0].income_total == Decimal("3000.00")
        assert result.months[1].expense_total == Decimal("500.00")

    def test_a_single_active_month_is_not_enough(self) -> None:
        result = _compare([_bucket(8, "0.00", "0.00"), _bucket(9, "0.00", "0.00"), _bucket(10)])

        assert result.status == "insufficient_data"
        assert result.limitations == ["fewer_than_two_active_months"] + ALWAYS
        assert (result.average_monthly_income, result.average_monthly_expenses, result.average_monthly_net_flow) == (None, None, None)
        assert (result.historical_difference, result.difference_direction, result.months_used) == (None, None, 0)
        assert result.required_per_installment == Decimal("450.00")
        assert not any(m.included_in_average for m in result.months)

    def test_no_history_at_all_is_insufficient_not_zero(self) -> None:
        result = _compare([_bucket(m, "0.00", "0.00") for m in (8, 9, 10)])

        assert result.status == "insufficient_data"
        assert result.average_monthly_net_flow is None
        assert result.historical_difference is None

    def test_exactly_two_active_months_is_enough(self) -> None:
        result = _compare([_bucket(8, "0.00", "0.00"), _bucket(9), _bucket(10)])

        assert result.status == "comparable"
        assert result.months_used == 2


class TestUnresolvedCurrencyData:
    @pytest.mark.parametrize("which", ["income", "expense"])
    def test_any_unresolved_record_makes_the_history_unusable(self, which: str) -> None:
        unresolved = {"unresolved_income": 1} if which == "income" else {"unresolved_expense": 1}

        result = _compare([_bucket(8), _bucket(9, **unresolved), _bucket(10)])

        assert result.status == "insufficient_data"
        assert "unresolved_currency_data" in result.limitations
        assert (result.average_monthly_income, result.average_monthly_expenses, result.average_monthly_net_flow, result.historical_difference) == (None, None, None, None)
        assert not any(m.included_in_average for m in result.months)
        # The counts are passed through so the gap is visible.
        assert result.months[1].unresolved_income_count + result.months[1].unresolved_expense_count == 1

    def test_unresolved_data_in_an_otherwise_empty_month_still_blocks(self) -> None:
        result = _compare([_bucket(8, "0.00", "0.00", unresolved_expense=2), _bucket(9), _bucket(10)])

        assert result.status == "insufficient_data"
        assert "unresolved_currency_data" in result.limitations


class TestCurrencyAndRequirement:
    def test_goal_currency_other_than_base_is_never_compared_or_converted(self) -> None:
        result = _compare(THREE, goal_currency="USD", base_currency="EUR")

        assert result.status == "currency_mismatch"
        assert result.historical_difference is None
        assert result.difference_direction is None
        assert (result.goal_currency, result.base_currency) == ("USD", "EUR")
        # The history itself is still described, in the base currency.
        assert result.average_monthly_net_flow == Decimal("600.00")
        assert result.required_per_installment == Decimal("450.00")

    def test_no_required_installment_is_its_own_neutral_state(self) -> None:
        result = _compare(THREE, required=None)

        assert result.status == "no_required_installment"
        assert result.required_per_installment is None
        assert result.historical_difference is None
        assert result.average_monthly_net_flow == Decimal("600.00")

    def test_precedence_requirement_then_currency_then_data(self) -> None:
        empty = [_bucket(m, "0.00", "0.00") for m in (8, 9, 10)]

        assert _compare(empty, required=None, goal_currency="USD").status == "no_required_installment"
        assert _compare(empty, goal_currency="USD").status == "currency_mismatch"
        assert _compare(empty).status == "insufficient_data"
        assert _compare(THREE).status == "comparable"


class TestStructure:
    def test_every_month_is_listed_oldest_first_with_its_figures(self) -> None:
        result = _compare([_bucket(8, "100.00", "40.00"), _bucket(9, "200.00", "50.00"), _bucket(10, "300.00", "60.00")])

        assert [m.period_start for m in result.months] == [date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)]
        assert [m.net_flow for m in result.months] == [Decimal("60.00"), Decimal("150.00"), Decimal("240.00")]
        assert result.goal_id == GOAL_ID and result.as_of == AS_OF

    def test_the_two_not_modelled_limitations_are_always_present(self) -> None:
        for buckets in (THREE, [_bucket(m, "0.00", "0.00") for m in (8, 9, 10)]):
            assert set(ALWAYS) <= set(_compare(buckets).limitations)
