from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from app.modules.future_obligations.future_obligation_models import FutureObligationModel
from app.modules.future_obligations.future_obligation_projection import (
    HORIZON_MONTHS,
    build_upcoming_obligations,
    window_end_for,
)

# VF-GOALS-PLANNING-002C1: the pure upcoming-bills projection. Obligations are built
# directly (the shape the repository returns); the database path is covered by the
# integration tests.

AS_OF = date(2026, 11, 16)


def _ob(
    name: str = "Bill",
    *,
    schedule: str = "monthly",
    amount: str = "100.00",
    currency: str = "EUR",
    first: date = date(2026, 11, 20),
    final: Optional[date] = None,
    status: str = "active",
) -> FutureObligationModel:
    return FutureObligationModel(
        id=uuid4(),
        user_id=uuid4(),
        name=name,
        schedule=schedule,
        amount=Decimal(amount),
        currency=currency,
        first_due_date=first,
        final_due_date=final,
        status=status,
    )


def _project(obligations, base: str = "EUR", as_of: date = AS_OF):
    return build_upcoming_obligations(obligations, base, as_of)


def _totals(response) -> list[str]:
    return [str(month.base_currency_total) for month in response.months]


class TestWindow:
    def test_twelve_calendar_months_starting_with_the_current_one(self) -> None:
        response = _project([])

        assert response.horizon_months == HORIZON_MONTHS == 12 == len(response.months)
        assert response.window_start == date(2026, 11, 1)
        assert response.window_end == date(2027, 10, 31)
        assert response.months[0].period_start == date(2026, 11, 1)
        assert response.months[0].period_end == date(2026, 11, 30)
        assert response.months[2].period_start == date(2027, 1, 1)  # across the year end
        assert response.months[11].period_end == date(2027, 10, 31)
        assert response.window_end == window_end_for(AS_OF)

    def test_an_empty_projection_is_all_zero_and_complete(self) -> None:
        response = _project([])

        assert set(_totals(response)) == {"0.00"}
        assert response.base_currency_window_total == Decimal("0.00")
        assert response.is_base_total_complete is True
        assert response.excluded_currencies == [] and response.totals_by_currency == []
        assert all(m.occurrence_count == 0 and m.occurrences == [] for m in response.months)

    def test_leap_february_and_december_boundaries(self) -> None:
        response = _project([], as_of=date(2027, 12, 20))
        leap = _project([], as_of=date(2027, 11, 5))

        assert response.months[0].period_end == date(2027, 12, 31)
        assert response.months[2].period_start == date(2028, 2, 1)
        assert response.months[2].period_end == date(2028, 2, 29)  # leap year
        assert leap.months[3].period_end == date(2028, 2, 29)
        assert _project([], as_of=date(2026, 2, 10)).months[0].period_end == date(2026, 2, 28)

    def test_the_last_day_of_a_month_is_still_that_month(self) -> None:
        response = _project([_ob(first=date(2026, 12, 31))], as_of=date(2026, 11, 30))

        assert response.months[0].period_start == date(2026, 11, 1)
        assert [m.occurrence_count for m in response.months[:3]] == [0, 1, 1]


class TestCurrentMonthRule:
    def test_due_dates_before_today_are_excluded_and_today_is_included(self) -> None:
        earlier = _ob("Earlier", first=date(2026, 5, 10))  # due the 10th: already past this month
        today = _ob("Today", first=date(2026, 5, 16))  # due the 16th: today
        later = _ob("Later", first=date(2026, 5, 25))

        response = _project([earlier, today, later])
        current = response.months[0]

        assert [o.name for o in current.occurrences] == ["Today", "Later"]
        # The one that already passed this month is due again next month.
        assert [o.name for o in response.months[1].occurrences] == ["Earlier", "Today", "Later"]

    def test_a_monthly_obligation_started_long_ago_gives_only_upcoming_dates(self) -> None:
        response = _project([_ob(first=date(2020, 1, 20))])

        assert response.months[0].occurrences[0].due_date == date(2026, 11, 20)
        assert min(o.due_date for m in response.months for o in m.occurrences) >= AS_OF
        assert sum(m.occurrence_count for m in response.months) == 12

    def test_a_past_one_time_obligation_contributes_nothing(self) -> None:
        response = _project([_ob(schedule="one_time", first=date(2026, 11, 15))])

        assert sum(m.occurrence_count for m in response.months) == 0

    def test_a_one_time_obligation_today_and_in_a_later_month(self) -> None:
        today = _ob("Today", schedule="one_time", first=AS_OF)
        later = _ob("Later", schedule="one_time", first=date(2027, 3, 31), amount="250.50")

        response = _project([today, later])

        assert [m.occurrence_count for m in response.months] == [1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0]
        assert response.months[4].occurrences[0].due_date == date(2027, 3, 31)


class TestRecurrence:
    def test_day_31_clamps_inside_the_window_and_is_not_drifted(self) -> None:
        response = _project([_ob(first=date(2026, 1, 31))], as_of=date(2026, 11, 1))
        dates = [m.occurrences[0].due_date for m in response.months]

        assert dates == [
            date(2026, 11, 30), date(2026, 12, 31), date(2027, 1, 31), date(2027, 2, 28),
            date(2027, 3, 31), date(2027, 4, 30), date(2027, 5, 31), date(2027, 6, 30),
            date(2027, 7, 31), date(2027, 8, 31), date(2027, 9, 30), date(2027, 10, 31),
        ]

    def test_the_29th_in_a_leap_february(self) -> None:
        response = _project([_ob(first=date(2027, 1, 29))], as_of=date(2027, 12, 1))

        assert response.months[2].occurrences[0].due_date == date(2028, 2, 29)

    def test_the_final_due_date_stops_the_recurrence_inclusive(self) -> None:
        response = _project([_ob(first=date(2026, 11, 20), final=date(2027, 1, 20))])

        assert [m.occurrence_count for m in response.months] == [1, 1, 1] + [0] * 9
        assert response.months[2].occurrences[0].due_date == date(2027, 1, 20)

    def test_at_most_one_occurrence_per_obligation_per_month(self) -> None:
        obligations = [_ob(f"B{n}", first=date(2026, 1, n + 1)) for n in range(10)]

        for month in _project(obligations).months:
            ids = [o.obligation_id for o in month.occurrences]

            assert len(ids) == len(set(ids)) == month.occurrence_count


class TestStatusAndOrdering:
    def test_archived_obligations_contribute_nothing(self) -> None:
        response = _project([_ob("Kept"), _ob("Archived", status="archived")])

        assert {o.name for m in response.months for o in m.occurrences} == {"Kept"}

    def test_occurrences_are_ordered_by_due_date_then_name_then_id(self) -> None:
        a = _ob("Beta", first=date(2026, 11, 25))
        b = _ob("Alpha", first=date(2026, 11, 25))
        c = _ob("Zeta", first=date(2026, 11, 18))

        names = [o.name for o in _project([a, b, c]).months[0].occurrences]

        assert names == ["Zeta", "Alpha", "Beta"]

    def test_each_occurrence_carries_its_obligation_amount_and_currency(self) -> None:
        bill = _ob("Rent", amount="950.00", first=date(2026, 11, 20))

        item = _project([bill]).months[0].occurrences[0]

        assert (item.obligation_id, item.name, item.schedule, str(item.amount), item.currency) == (
            bill.id, "Rent", "monthly", "950.00", "EUR",
        )


class TestExactArithmetic:
    def test_decimal_sums_are_exact_not_float(self) -> None:
        # 0.10 + 0.20 is 0.30000000000000004 in binary floating point.
        response = _project([_ob("A", amount="0.10"), _ob("B", amount="0.20")])

        assert response.months[0].base_currency_total == Decimal("0.30")
        assert str(response.months[0].base_currency_total) == "0.30"

    def test_many_small_amounts_and_the_window_total(self) -> None:
        obligations = [_ob(f"B{n}", amount="0.01") for n in range(100)]

        response = _project(obligations)

        assert response.months[0].base_currency_total == Decimal("1.00")
        assert response.base_currency_window_total == Decimal("12.00")

    def test_large_amounts_and_two_decimal_places(self) -> None:
        response = _project([_ob("Big", amount="9999999999.99", first=date(2026, 11, 20))])

        assert response.months[0].base_currency_total == Decimal("9999999999.99")
        assert all(m.base_currency_total.as_tuple().exponent == -2 for m in response.months)

    def test_window_total_is_the_sum_of_the_monthly_totals(self) -> None:
        response = _project([_ob("A", amount="12.34"), _ob("B", schedule="one_time", amount="500.01", first=date(2027, 2, 1))])

        assert response.base_currency_window_total == sum((m.base_currency_total for m in response.months), Decimal("0.00"))
        assert response.base_currency_window_total == Decimal("148.08") + Decimal("500.01")


class TestMixedCurrencies:
    def test_currencies_are_never_added_together(self) -> None:
        eur = _ob("Eur", amount="100.00", currency="EUR")
        usd = _ob("Usd", amount="40.00", currency="USD")
        gbp = _ob("Gbp", amount="7.50", currency="GBP")

        response = _project([eur, usd, gbp])
        current = response.months[0]

        assert current.base_currency_total == Decimal("100.00")
        assert [(t.currency, str(t.total), t.occurrence_count) for t in current.totals_by_currency] == [
            ("EUR", "100.00", 1), ("GBP", "7.50", 1), ("USD", "40.00", 1),
        ]
        assert current.occurrence_count == 3
        assert response.excluded_currencies == ["GBP", "USD"]
        assert response.is_base_total_complete is False

    def test_whole_window_totals_per_currency(self) -> None:
        response = _project([_ob(amount="10.00", currency="USD"), _ob(amount="5.00", currency="EUR")])

        assert [(t.currency, str(t.total), t.occurrence_count) for t in response.totals_by_currency] == [
            ("EUR", "60.00", 12), ("USD", "120.00", 12),
        ]
        assert response.base_currency_window_total == Decimal("60.00")

    def test_a_base_currency_that_has_no_occurrence_totals_zero(self) -> None:
        response = _project([_ob(currency="USD")])

        assert response.months[0].base_currency_total == Decimal("0.00")
        assert response.excluded_currencies == ["USD"]
        assert response.is_base_total_complete is False

    def test_a_foreign_currency_outside_the_window_does_not_flag_the_total(self) -> None:
        response = _project([_ob("Far", schedule="one_time", currency="USD", first=date(2029, 1, 1))])

        assert response.excluded_currencies == []
        assert response.is_base_total_complete is True

    def test_the_base_currency_decides_what_is_included(self) -> None:
        response = _project([_ob(currency="EUR"), _ob(currency="USD")], base="USD")

        assert response.base_currency == "USD"
        assert response.excluded_currencies == ["EUR"]
        assert response.months[0].base_currency_total == Decimal("100.00")
