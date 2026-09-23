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


# Tests that IncomeCreate accepts an optional account_id field.
# This test exists as the schema-level regression for the VF-017D
# architectural rule: account_id is now a legitimate, optional linkage
# field on IncomeCreate (unlike VF-017C, where it did not exist at all).
# It is still never persisted directly on IncomeModel - see
# income_repository.create_income, which whitelists real columns only.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the field round-trips as a UUID and is
#   None when omitted.
def test_income_create_accepts_optional_account_id_field() -> None:
    income = IncomeCreate(
        **_valid_create_kwargs(),
        account_id="11111111-1111-1111-1111-111111111111",
    )
    assert str(income.account_id) == "11111111-1111-1111-1111-111111111111"

    unlinked = IncomeCreate(**_valid_create_kwargs())
    assert unlinked.account_id is None


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


# Tests IncomeUpdate.account_id's three-state PATCH semantics: absent
# means unchanged, a UUID means attach/move, explicit null means detach.
# This test exists to prove account_id is deliberately excluded from the
# "cannot be null" validation every other field here is subject to -
# unlike amount/currency/received_at/source, null is a meaningful, valid
# value for account_id (VF-017D).
# Parameters:
# - None.
# Returns:
# - None. The test passes if all three states are distinguishable via
#   model_fields_set and the field's resulting value.
def test_income_update_account_id_three_state_semantics() -> None:
    absent = IncomeUpdate(source="gift")
    assert "account_id" not in absent.model_fields_set

    attach = IncomeUpdate(account_id="11111111-1111-1111-1111-111111111111")
    assert "account_id" in attach.model_fields_set
    assert attach.account_id is not None

    detach = IncomeUpdate(account_id=None)
    assert "account_id" in detach.model_fields_set
    assert detach.account_id is None


# Tests that IncomeUpdate accepts account_id alone (a pure attach/detach/
# move PATCH with no other field) as a valid, non-empty payload.
# Parameters:
# - None.
# Returns:
# - None. The test passes if construction succeeds.
def test_income_update_account_id_alone_is_valid_payload() -> None:
    update = IncomeUpdate(account_id="11111111-1111-1111-1111-111111111111")
    assert update.model_fields_set == {"account_id"}


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
