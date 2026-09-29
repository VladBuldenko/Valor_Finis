from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.accounts.account_transfer_schemas import (
    AccountTransferCreate,
    AccountTransferResponse,
)


def _valid_payload(**overrides) -> dict:
    payload = {
        "client_request_id": str(uuid4()),
        "source_account_id": str(uuid4()),
        "destination_account_id": str(uuid4()),
        "amount": "300.00",
        "transfer_date": "2026-10-15",
        "description": "Move to savings",
    }
    payload.update(overrides)
    return payload


# Tests that a complete valid create request parses with Decimal money and
# a date, and that description is optional.
# Parameters:
# - None.
# Returns:
# - None. The test passes if both payloads validate.
def test_account_transfer_create_valid_request() -> None:
    parsed = AccountTransferCreate.model_validate(_valid_payload())

    assert parsed.amount == Decimal("300.00")
    assert isinstance(parsed.amount, Decimal)
    assert parsed.transfer_date == date(2026, 10, 15)
    assert parsed.description == "Move to savings"

    without_description = _valid_payload()
    del without_description["description"]
    assert AccountTransferCreate.model_validate(without_description).description is None


# Tests that invalid amounts are rejected: zero, negative, more than 12
# digits, and more than 2 decimal places.
# Parameters:
# - amount: the invalid amount string under test.
# Returns:
# - None. The test passes if validation fails.
@pytest.mark.parametrize(
    "amount",
    ["0", "0.00", "-1.00", "12345678901.00", "1.001"],
)
def test_account_transfer_create_invalid_amount_rejected(amount: str) -> None:
    with pytest.raises(ValidationError):
        AccountTransferCreate.model_validate(_valid_payload(amount=amount))


# Tests that the largest representable NUMERIC(12,2) amount is accepted.
# Parameters:
# - None.
# Returns:
# - None. The test passes if validation succeeds.
def test_account_transfer_create_max_amount_accepted() -> None:
    parsed = AccountTransferCreate.model_validate(_valid_payload(amount="9999999999.99"))

    assert parsed.amount == Decimal("9999999999.99")


# Tests that a description longer than 500 characters is rejected, and
# exactly 500 is accepted.
# Parameters:
# - None.
# Returns:
# - None. The test passes if only the over-long description fails.
def test_account_transfer_create_description_length() -> None:
    AccountTransferCreate.model_validate(_valid_payload(description="x" * 500))

    with pytest.raises(ValidationError):
        AccountTransferCreate.model_validate(_valid_payload(description="x" * 501))


# Tests that a transfer from an Account to itself is rejected by the schema.
# Parameters:
# - None.
# Returns:
# - None. The test passes if validation fails.
def test_account_transfer_create_same_account_rejected() -> None:
    account_id = str(uuid4())

    with pytest.raises(ValidationError):
        AccountTransferCreate.model_validate(
            _valid_payload(source_account_id=account_id, destination_account_id=account_id)
        )


# Tests that client_request_id is required.
# Parameters:
# - None.
# Returns:
# - None. The test passes if validation fails.
def test_account_transfer_create_requires_client_request_id() -> None:
    payload = _valid_payload()
    del payload["client_request_id"]

    with pytest.raises(ValidationError):
        AccountTransferCreate.model_validate(payload)


# Tests that every server-owned field is rejected rather than silently
# accepted (extra="forbid").
# Parameters:
# - field_name: the server-owned field under test.
# - value: a plausible client-supplied value.
# Returns:
# - None. The test passes if validation fails.
@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("user_id", str(uuid4())),
        ("currency", "EUR"),
        ("status", "posted"),
        ("planned_date", "2026-10-15"),
        ("effective_date", "2026-10-15"),
        ("posted_at", "2026-10-15T10:00:00Z"),
        ("kind", "transfer"),
    ],
)
def test_account_transfer_create_server_owned_fields_rejected(
    field_name: str, value: str,
) -> None:
    with pytest.raises(ValidationError):
        AccountTransferCreate.model_validate(_valid_payload(**{field_name: value}))


def _response_values(**overrides) -> dict:
    values = {
        "id": uuid4(),
        "user_id": uuid4(),
        "client_request_id": uuid4(),
        "source_account_id": uuid4(),
        "destination_account_id": uuid4(),
        "amount": Decimal("300.00"),
        "currency": "EUR",
        "status": "planned",
        "planned_date": date(2026, 10, 15),
        "effective_date": None,
        "description": None,
        "posted_at": None,
        "created_at": datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return values


# Tests the planned and immediately posted response shapes, Decimal string
# serialization, and that there is no transfer_date field.
# Parameters:
# - None.
# Returns:
# - None. The test passes if both shapes serialize as expected.
def test_account_transfer_response_shapes() -> None:
    planned = AccountTransferResponse(**_response_values()).model_dump(mode="json")

    assert planned["status"] == "planned"
    assert planned["planned_date"] == "2026-10-15"
    assert planned["effective_date"] is None
    assert planned["posted_at"] is None
    assert planned["amount"] == "300.00"
    assert "transfer_date" not in planned

    posted = AccountTransferResponse(
        **_response_values(
            status="posted",
            planned_date=None,
            effective_date=date(2026, 9, 28),
            posted_at=datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc),
        )
    ).model_dump(mode="json")

    assert posted["status"] == "posted"
    assert posted["planned_date"] is None
    assert posted["effective_date"] == "2026-09-28"
    assert posted["posted_at"] is not None
    assert "transfer_date" not in posted


# Tests that the response rejects a status outside planned/posted.
# Parameters:
# - None.
# Returns:
# - None. The test passes if validation fails.
def test_account_transfer_response_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        AccountTransferResponse(**_response_values(status="cancelled"))
