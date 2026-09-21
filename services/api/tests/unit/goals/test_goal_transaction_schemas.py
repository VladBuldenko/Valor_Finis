from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.goals.goal_transaction_schemas import GoalTransactionCreate


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
