from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.income.income_schemas import IncomeCreate, IncomeResponse, IncomeUpdate


def _valid_create_kwargs(**overrides):
    kwargs = dict(
        amount=Decimal("2500.00"),
        currency="EUR",
        received_at=date(2026, 5, 7),
        source="salary",
    )
    kwargs.update(overrides)
    return kwargs


# Tests that currency is normalized to uppercase.
# Parameters:
# - None.
# Returns:
# - None. The test passes if lowercase input is normalized to uppercase.
def test_income_create_normalizes_currency_to_uppercase() -> None:
    income = IncomeCreate(**_valid_create_kwargs(currency="eur"))
    assert income.currency == "EUR"


# Tests that a non-alphabetic currency code is rejected.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised.
def test_income_create_rejects_non_alphabetic_currency() -> None:
    with pytest.raises(ValidationError):
        IncomeCreate(**_valid_create_kwargs(currency="12E"))


# Tests that a zero amount is rejected.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised.
def test_income_create_rejects_zero_amount() -> None:
    with pytest.raises(ValidationError):
        IncomeCreate(**_valid_create_kwargs(amount=Decimal("0.00")))


# Tests that a negative amount is rejected.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised.
def test_income_create_rejects_negative_amount() -> None:
    with pytest.raises(ValidationError):
        IncomeCreate(**_valid_create_kwargs(amount=Decimal("-10.00")))


# Tests that an invalid source is rejected.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised.
def test_income_create_rejects_invalid_source() -> None:
    with pytest.raises(ValidationError):
        IncomeCreate(**_valid_create_kwargs(source="lottery"))


# Tests that all five closed-set source values are accepted.
# Parameters:
# - None.
# Returns:
# - None. The test passes if every value validates successfully.
def test_income_create_accepts_all_valid_sources() -> None:
    for source in ("salary", "freelance", "refund", "gift", "other"):
        income = IncomeCreate(**_valid_create_kwargs(source=source))
        assert income.source == source


# Tests that IncomeCreate rejects a client-supplied user_id.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised.
def test_income_create_rejects_user_id_field() -> None:
    with pytest.raises(ValidationError):
        IncomeCreate(**_valid_create_kwargs(), user_id="11111111-1111-1111-1111-111111111111")


# Tests that IncomeCreate rejects injected FX snapshot fields.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised.
def test_income_create_rejects_injected_fx_fields() -> None:
    with pytest.raises(ValidationError):
        IncomeCreate(**_valid_create_kwargs(), base_amount=Decimal("2500.00"))


# Tests that IncomeCreate rejects an account_id field.
# This test exists as the schema-level regression for the VF-017C
# architectural rule: account_id must not exist in the public Income
# contract until VF-017D makes the link actually affect Account balance.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised.
def test_income_create_rejects_account_id_field() -> None:
    with pytest.raises(ValidationError):
        IncomeCreate(
            **_valid_create_kwargs(),
            account_id="11111111-1111-1111-1111-111111111111",
        )


# Tests that IncomeUpdate requires at least one field.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised for an empty
#   payload.
def test_income_update_requires_at_least_one_field() -> None:
    with pytest.raises(ValidationError):
        IncomeUpdate()


# Tests that IncomeUpdate rejects an explicit null for a required field.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised.
def test_income_update_rejects_null_amount() -> None:
    with pytest.raises(ValidationError):
        IncomeUpdate(amount=None)


# Tests that IncomeUpdate allows an explicit null for description (clears
# an existing note).
# Parameters:
# - None.
# Returns:
# - None. The test passes if the update validates with description=None.
def test_income_update_allows_null_description() -> None:
    update = IncomeUpdate(description=None, source="gift")
    assert update.description is None


# Tests that IncomeUpdate allows a partial update of just source.
# Parameters:
# - None.
# Returns:
# - None. The test passes if only source is set.
def test_income_update_allows_partial_source_update() -> None:
    update = IncomeUpdate(source="freelance")
    assert update.source == "freelance"
    assert "amount" not in update.model_fields_set


# Tests that IncomeResponse round-trips FX snapshot fields.
# Parameters:
# - None.
# Returns:
# - None. The test passes if all five FX fields are present on the
#   response.
def test_income_response_includes_fx_snapshot() -> None:
    from datetime import datetime
    from uuid import uuid4

    response = IncomeResponse(
        id=uuid4(),
        user_id=uuid4(),
        amount=Decimal("2500.00"),
        currency="EUR",
        received_at=date(2026, 5, 7),
        source="salary",
        description=None,
        base_amount=Decimal("2500.00"),
        base_currency="EUR",
        fx_rate=Decimal("1.00000000"),
        fx_rate_date=date(2026, 5, 7),
        fx_source="identity",
        created_at=datetime(2026, 5, 7),
        updated_at=datetime(2026, 5, 7),
    )
    assert response.base_amount == Decimal("2500.00")
    assert response.fx_source == "identity"
