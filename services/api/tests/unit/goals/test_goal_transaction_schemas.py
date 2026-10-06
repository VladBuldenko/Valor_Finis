from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.modules.goals.goal_transaction_schemas import (
    GoalTransactionCreate,
    GoalTransactionResponse,
)


# Tests that a contribution request is accepted.
# Parameters:
# - None.
# Returns:
# - None. The test passes if GoalTransactionCreate is created successfully.
def test_goal_transaction_create_accepts_contribution() -> None:
    # Act
    transaction = GoalTransactionCreate(type="contribution", amount=Decimal("100.00"))

    # Assert
    assert transaction.type == "contribution"
    assert transaction.amount == Decimal("100.00")
    assert transaction.description is None


# Tests that a withdrawal request is accepted.
# Parameters:
# - None.
# Returns:
# - None. The test passes if GoalTransactionCreate is created successfully.
def test_goal_transaction_create_accepts_withdrawal() -> None:
    # Act
    transaction = GoalTransactionCreate(type="withdrawal", amount=Decimal("50.00"))

    # Assert
    assert transaction.type == "withdrawal"
    assert transaction.amount == Decimal("50.00")


# Tests that a description is accepted and preserved.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the description is stored unchanged.
def test_goal_transaction_create_accepts_description() -> None:
    # Act
    transaction = GoalTransactionCreate(
        type="contribution",
        amount=Decimal("10.00"),
        description="Payday transfer",
    )

    # Assert
    assert transaction.description == "Payday transfer"


# Tests that opening_balance is rejected by the public request schema.
# This test exists because opening_balance is reserved for migration/system
# backfill (VF-016) - a client must never be able to create one.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_transaction_create_rejects_opening_balance() -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        GoalTransactionCreate(type="opening_balance", amount=Decimal("100.00"))


# Tests that an unrecognized type value is rejected.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_transaction_create_rejects_unknown_type() -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        GoalTransactionCreate(type="refund", amount=Decimal("100.00"))


# Tests that a zero amount is rejected.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_transaction_create_rejects_zero_amount() -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        GoalTransactionCreate(type="contribution", amount=Decimal("0.00"))


# Tests that a negative amount is rejected.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_transaction_create_rejects_negative_amount() -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        GoalTransactionCreate(type="withdrawal", amount=Decimal("-10.00"))


# Tests that an amount exceeding the allowed digit count is rejected.
# This test exists to verify max_digits=12 is enforced, matching the
# NUMERIC(12,2) database column.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_transaction_create_rejects_excessive_digits() -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        GoalTransactionCreate(type="contribution", amount=Decimal("1234567890123.00"))


# Tests that an amount exceeding the allowed decimal places is rejected.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_transaction_create_rejects_excessive_decimal_places() -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        GoalTransactionCreate(type="contribution", amount=Decimal("10.001"))


# Tests that a description longer than 255 characters is rejected.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_transaction_create_rejects_description_over_max_length() -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        GoalTransactionCreate(
            type="contribution",
            amount=Decimal("10.00"),
            description="x" * 256,
        )


# Tests that extra fields are rejected.
# This test exists to verify user_id/goal_id/type=opening_balance cannot be
# smuggled in through additional request fields.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_transaction_create_rejects_extra_fields() -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        GoalTransactionCreate(
            type="contribution",
            amount=Decimal("10.00"),
            user_id="00000000-0000-0000-0000-000000000000",
        )


# Tests that effective_date and client_request_id are optional and default
# to None, so requests from older clients stay valid (VF-020B3).
# Parameters:
# - None.
# Returns:
# - None. The test passes if both fields default to None.
def test_goal_transaction_create_runtime_fields_are_optional() -> None:
    # Act
    transaction = GoalTransactionCreate(type="contribution", amount=Decimal("10.00"))

    # Assert
    assert transaction.effective_date is None
    assert transaction.client_request_id is None


# Tests that an ISO calendar date and a UUID key are accepted (VF-020B3).
# Parameters:
# - None.
# Returns:
# - None. The test passes if both values are parsed.
def test_goal_transaction_create_accepts_effective_date_and_client_request_id() -> None:
    # Arrange
    key = uuid4()

    # Act
    transaction = GoalTransactionCreate(
        type="withdrawal",
        amount=Decimal("10.00"),
        effective_date="2026-10-05",
        client_request_id=str(key),
    )

    # Assert
    assert transaction.effective_date == date(2026, 10, 5)
    assert transaction.client_request_id == key


# Tests that effective_date accepts only a pure calendar date: datetime
# strings (even at midnight or with an offset), datetime objects, numeric
# timestamps and non-ISO strings are rejected, so no timezone can shift the
# recorded day (VF-020B3).
# Parameters:
# - value: rejected effective_date input.
# Returns:
# - None. The test passes if ValidationError is raised.
@pytest.mark.parametrize(
    "value",
    [
        "2026-10-05T00:00:00",
        "2026-10-05T00:00:00Z",
        "2026-10-05T23:30:00-05:00",
        datetime(2026, 10, 5, tzinfo=timezone.utc),
        1759622400,
        "05.10.2026",
        "2026-1-5",
        "2026-13-01",
    ],
)
def test_goal_transaction_create_rejects_non_date_effective_date(value) -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        GoalTransactionCreate(type="contribution", amount=Decimal("10.00"), effective_date=value)


# Tests that a client can never choose the transaction currency: it is
# always copied from the goal, and the field is rejected (VF-020B3).
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_transaction_create_rejects_client_currency() -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        GoalTransactionCreate(type="contribution", amount=Decimal("10.00"), currency="USD")


# Tests that a malformed client_request_id is rejected.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_transaction_create_rejects_malformed_client_request_id() -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        GoalTransactionCreate(
            type="contribution", amount=Decimal("10.00"), client_request_id="not-a-uuid",
        )


# Tests that the response serializes a row written before VF-020B3 whose
# currency, effective_date and client_request_id are all NULL.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the response holds None for all three.
def test_goal_transaction_response_serializes_legacy_null_fields() -> None:
    # Arrange
    legacy_row = SimpleNamespace(
        id=uuid4(),
        goal_id=uuid4(),
        user_id=uuid4(),
        type="opening_balance",
        amount=Decimal("200.00"),
        description=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        currency=None,
        effective_date=None,
        client_request_id=None,
    )

    # Act
    response = GoalTransactionResponse.model_validate(legacy_row)
    payload = response.model_dump(mode="json")

    # Assert
    assert payload["currency"] is None
    assert payload["effective_date"] is None
    assert payload["client_request_id"] is None


# Tests that the response exposes the runtime fields of a row written since
# VF-020B3.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the three fields are serialized.
def test_goal_transaction_response_exposes_runtime_fields() -> None:
    # Arrange
    key = UUID("5f0c6a8e-3d2b-4c1a-9e7f-2b8d4a6c1e90")
    row = SimpleNamespace(
        id=uuid4(),
        goal_id=uuid4(),
        user_id=uuid4(),
        type="contribution",
        amount=Decimal("10.00"),
        description=None,
        created_at=datetime(2026, 10, 5, 22, 30, tzinfo=timezone.utc),
        currency="USD",
        effective_date=date(2026, 10, 5),
        client_request_id=key,
    )

    # Act
    payload = GoalTransactionResponse.model_validate(row).model_dump(mode="json")

    # Assert
    assert payload["currency"] == "USD"
    assert payload["effective_date"] == "2026-10-05"
    assert payload["client_request_id"] == str(key)
