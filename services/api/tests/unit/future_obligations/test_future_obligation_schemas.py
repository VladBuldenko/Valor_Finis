from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.future_obligations.future_obligation_schemas import (
    FutureObligationCreate,
    FutureObligationUpdate,
)

# VF-GOALS-PLANNING-002C1: request validation. The API rejects invalid amounts, dates
# and schedule combinations before anything reaches the service or the database.


def _create(**over: Any) -> FutureObligationCreate:
    body: dict[str, Any] = {
        "name": "Car insurance",
        "schedule": "monthly",
        "amount": "120.00",
        "first_due_date": "2026-12-31",
    }
    body.update(over)

    return FutureObligationCreate(**body)


def _rejected(**over: Any) -> str:
    with pytest.raises(ValidationError) as caught:
        _create(**over)

    return str(caught.value)


class TestAmount:
    @pytest.mark.parametrize("amount", ["0.01", "1", "120.00", "9999999999.99"])
    def test_valid_amounts(self, amount: str) -> None:
        assert _create(amount=amount).amount > 0

    @pytest.mark.parametrize("amount", ["0", "0.00", "-1.00", "-0.01", "10.005", "abc", "NaN", "Infinity", "-Infinity", "1e400", "99999999999999.99", "", None])
    def test_invalid_amounts_are_rejected(self, amount: Any) -> None:
        with pytest.raises(ValidationError):
            _create(amount=amount)

    def test_a_float_with_binary_noise_is_not_silently_rounded(self) -> None:
        with pytest.raises(ValidationError):
            _create(amount=0.1 + 0.2)


class TestCurrency:
    def test_omitted_means_use_the_base_currency(self) -> None:
        assert _create().currency is None

    def test_normalized_to_uppercase_and_trimmed(self) -> None:
        assert _create(currency=" usd ").currency == "USD"

    @pytest.mark.parametrize("currency", ["EU", "EURO", "E1R", "€€€", "", "  "])
    def test_invalid_currency_codes(self, currency: str) -> None:
        with pytest.raises(ValidationError):
            _create(currency=currency)


class TestName:
    def test_trimmed(self) -> None:
        assert _create(name="  Rent  ").name == "Rent"

    @pytest.mark.parametrize("name", ["", "   ", "x" * 101])
    def test_blank_or_too_long_names_are_rejected(self, name: str) -> None:
        with pytest.raises(ValidationError):
            _create(name=name)

    def test_a_100_character_name_is_accepted(self) -> None:
        assert len(_create(name="x" * 100).name) == 100

    def test_a_blank_description_is_no_description(self) -> None:
        assert _create(description="   ").description is None
        assert _create(description=" Renewal ").description == "Renewal"

    def test_a_description_over_500_characters_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _create(description="x" * 501)


class TestDatesAndSchedule:
    def test_a_one_time_obligation_has_no_final_due_date(self) -> None:
        assert _create(schedule="one_time").final_due_date is None
        assert "single due date" in _rejected(schedule="one_time", final_due_date="2027-01-01")

    def test_a_monthly_obligation_may_end_on_or_after_its_first_due_date(self) -> None:
        assert _create(final_due_date="2026-12-31").final_due_date == date(2026, 12, 31)
        assert _create(final_due_date="2027-06-30").final_due_date == date(2027, 6, 30)

    def test_a_final_due_date_before_the_first_is_rejected(self) -> None:
        assert "before the first due date" in _rejected(final_due_date="2026-12-30")

    @pytest.mark.parametrize("value", ["2026-02-30", "2026-13-01", "2026-00-10", "31/12/2026", "tomorrow", "", None])
    def test_invalid_dates_are_rejected(self, value: Any) -> None:
        with pytest.raises(ValidationError):
            _create(first_due_date=value)

    @pytest.mark.parametrize("value", ["1999-12-31", "2101-01-01"])
    def test_dates_outside_2000_to_2100_are_rejected(self, value: str) -> None:
        with pytest.raises(ValidationError):
            _create(first_due_date=value)
        with pytest.raises(ValidationError):
            _create(final_due_date=value, first_due_date="2026-12-31")

    def test_the_boundary_dates_are_accepted(self) -> None:
        assert _create(first_due_date="2000-01-01").first_due_date == date(2000, 1, 1)
        assert _create(first_due_date="2100-12-31").first_due_date == date(2100, 12, 31)

    def test_a_past_first_due_date_is_accepted(self) -> None:
        assert _create(first_due_date="2020-05-01").first_due_date == date(2020, 5, 1)

    def test_a_leap_day_is_valid_only_in_a_leap_year(self) -> None:
        assert _create(first_due_date="2028-02-29").first_due_date == date(2028, 2, 29)
        with pytest.raises(ValidationError):
            _create(first_due_date="2027-02-29")

    @pytest.mark.parametrize("schedule", ["weekly", "yearly", "daily", "", None])
    def test_only_one_time_and_monthly_exist(self, schedule: Any) -> None:
        with pytest.raises(ValidationError):
            _create(schedule=schedule)


class TestNothingTheClientMustNotSet:
    @pytest.mark.parametrize("field", ["user_id", "status", "id", "next_due_date", "created_at", "client_request_fingerprint", "account_id", "expense_id"])
    def test_unknown_and_server_owned_fields_are_rejected(self, field: str) -> None:
        with pytest.raises(ValidationError):
            _create(**{field: "x"})


class TestUpdate:
    def test_an_empty_update_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FutureObligationUpdate()

    @pytest.mark.parametrize("field", ["name", "amount", "currency", "first_due_date", "status"])
    def test_required_fields_cannot_be_null(self, field: str) -> None:
        with pytest.raises(ValidationError):
            FutureObligationUpdate(**{field: None})

    def test_description_and_final_due_date_can_be_cleared(self) -> None:
        update = FutureObligationUpdate(description=None, final_due_date=None)

        assert update.model_fields_set == {"description", "final_due_date"}
        assert update.description is None and update.final_due_date is None

    def test_the_schedule_kind_cannot_be_changed(self) -> None:
        with pytest.raises(ValidationError):
            FutureObligationUpdate(schedule="one_time")

    def test_field_rules_apply_to_updates_too(self) -> None:
        for bad in ({"amount": "0"}, {"amount": "1.234"}, {"currency": "EU"}, {"name": " "}, {"first_due_date": "2026-02-30"}, {"status": "paused"}, {"final_due_date": "2101-01-01"}):
            with pytest.raises(ValidationError):
                FutureObligationUpdate(**bad)

    def test_valid_values_are_normalized(self) -> None:
        update = FutureObligationUpdate(name=" Rent ", currency="usd", amount="1250.5", status="archived")

        assert (update.name, update.currency, str(update.amount), update.status) == ("Rent", "USD", "1250.5", "archived")
