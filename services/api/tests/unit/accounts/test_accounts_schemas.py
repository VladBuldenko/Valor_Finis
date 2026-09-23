from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.accounts.account_schemas import (
    AccountCreate,
    AccountResponse,
    AccountUpdate,
)
from app.modules.accounts.account_transaction_schemas import AccountTransactionCreate


# Tests that currency is normalized to uppercase.
# Parameters:
# - None.
# Returns:
# - None. The test passes if lowercase input is normalized to uppercase.
def test_account_create_normalizes_currency_to_uppercase() -> None:
    account = AccountCreate(name="Wallet", type="cash", currency="eur")
    assert account.currency == "EUR"


# Tests that a non-alphabetic currency code is rejected.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised.
def test_account_create_rejects_non_alphabetic_currency() -> None:
    with pytest.raises(ValidationError):
        AccountCreate(name="Wallet", type="cash", currency="12E")


# Tests that a blank (whitespace-only) name is rejected.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised.
def test_account_create_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        AccountCreate(name="   ", type="cash", currency="EUR")


# Tests that a name with surrounding whitespace is trimmed.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the stored name has no leading/trailing
#   whitespace.
def test_account_create_trims_name() -> None:
    account = AccountCreate(name="  Main Checking  ", type="checking")
    assert account.name == "Main Checking"


# Tests that an invalid account type is rejected.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised.
def test_account_create_rejects_invalid_type() -> None:
    with pytest.raises(ValidationError):
        AccountCreate(name="Card", type="credit_card", currency="EUR")


# Tests that AccountCreate rejects an injected current_balance field.
# This test exists because current_balance is never client-writable.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised.
def test_account_create_rejects_current_balance_field() -> None:
    with pytest.raises(ValidationError):
        AccountCreate(
            name="Wallet",
            type="cash",
            currency="EUR",
            current_balance=Decimal("500"),
        )


# Tests that AccountCreate accepts a signed opening_balance.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the field round-trips exactly.
def test_account_create_accepts_signed_opening_balance() -> None:
    account = AccountCreate(
        name="Wallet", type="cash", currency="EUR", opening_balance=Decimal("-125.50")
    )
    assert account.opening_balance == Decimal("-125.50")


# Tests that AccountUpdate requires at least one field.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised for an empty
#   payload.
def test_account_update_requires_at_least_one_field() -> None:
    with pytest.raises(ValidationError):
        AccountUpdate()


# Tests that AccountUpdate rejects an explicit null for a required field.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised.
def test_account_update_rejects_null_name() -> None:
    with pytest.raises(ValidationError):
        AccountUpdate(name=None)


# Tests that AccountUpdate allows a partial update of just status.
# Parameters:
# - None.
# Returns:
# - None. The test passes if only status is set.
def test_account_update_allows_partial_status_update() -> None:
    update = AccountUpdate(status="archived")
    assert update.status == "archived"
    assert "name" not in update.model_fields_set


# Tests that AccountResponse allows a negative current_balance.
# This test exists because, unlike GoalResponse.current_amount (ge=0),
# an Account is a descriptive financial record, not a payment
# authorization system - a negative balance is a valid, representable
# state.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the response validates with a negative
#   balance.
def test_account_response_allows_negative_current_balance() -> None:
    from datetime import datetime
    from uuid import uuid4

    response = AccountResponse(
        id=uuid4(),
        user_id=uuid4(),
        name="Checking",
        type="checking",
        currency="EUR",
        status="active",
        current_balance=Decimal("-25.00"),
        created_at=datetime(2026, 9, 23),
        updated_at=datetime(2026, 9, 23),
    )
    assert response.current_balance == Decimal("-25.00")


# Tests that AccountTransactionCreate has no kind field at all.
# This test exists to prove opening_balance is structurally unreachable
# through this schema - there is no field for a client to even attempt to
# set it through.
# Parameters:
# - None.
# Returns:
# - None. The test passes if "kind" is rejected as an unknown field.
def test_account_transaction_create_has_no_kind_field() -> None:
    with pytest.raises(ValidationError):
        AccountTransactionCreate(
            kind="opening_balance",
            direction="credit",
            amount=Decimal("100.00"),
            transaction_date="2026-09-23",
        )


# Tests that AccountTransactionCreate rejects a zero amount.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised.
def test_account_transaction_create_rejects_zero_amount() -> None:
    with pytest.raises(ValidationError):
        AccountTransactionCreate(
            direction="credit",
            amount=Decimal("0.00"),
            transaction_date="2026-09-23",
        )


# Tests that AccountTransactionCreate rejects an invalid direction.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a ValidationError is raised.
def test_account_transaction_create_rejects_invalid_direction() -> None:
    with pytest.raises(ValidationError):
        AccountTransactionCreate(
            direction="sideways",
            amount=Decimal("10.00"),
            transaction_date="2026-09-23",
        )
