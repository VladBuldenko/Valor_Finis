from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.goals.goal_schemas import GoalCreate, GoalResponse, GoalUpdate


# Tests that valid goal input is accepted by the schema.
# This test exists to confirm that correct financial goal data passes validation.
# Parameters:
# - None.
# Returns:
# - None. The test passes if GoalCreate is created successfully.
def test_goal_create_accepts_valid_data() -> None:
    # Arrange
    name = "Vacation"
    target_amount = Decimal("2000")
    target_date = date(2026, 12, 31)

    # Act
    goal = GoalCreate(
        name=name,
        target_amount=target_amount,
        currency="EUR",
        target_date=target_date,
        status="active",
    )

    # Assert
    assert goal.name == name
    assert goal.target_amount == target_amount
    assert goal.currency == "EUR"
    assert goal.target_date == target_date
    assert goal.status == "active"


# Tests that user_id is rejected by the goal creation schema.
# This test exists because user_id must come from authentication data,
# not from the client request body.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_create_rejects_user_id_field() -> None:
    # Arrange
    invalid_data = {
        "user_id": uuid4(),
        "name": "Vacation",
        "target_amount": Decimal("2000"),
        "currency": "EUR",
        "target_date": date(2026, 12, 31),
        "status": "active",
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        GoalCreate(**invalid_data)


# Tests that current_amount is rejected by the goal creation schema.
# This test exists because current_amount is no longer client-writable
# (VF-016C): every new Goal starts at 0 and can only be funded afterward
# through a contribution GoalTransaction.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_create_rejects_current_amount_field() -> None:
    # Arrange
    invalid_data = {
        "name": "Vacation",
        "target_amount": Decimal("2000"),
        "current_amount": Decimal("500"),
        "currency": "EUR",
        "target_date": date(2026, 12, 31),
        "status": "active",
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        GoalCreate(**invalid_data)


# Tests that GoalUpdate rejects a current_amount field.
# This test exists because current_amount is no longer client-writable
# (VF-016C): sending it in a PATCH must fail via extra="forbid", since
# funding only happens through a GoalTransaction.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_update_rejects_current_amount_field() -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        GoalUpdate(current_amount=Decimal("700"))


# Tests that GoalResponse allows current_amount to exceed target_amount.
# This test exists because overfunding is a valid product state (VF-016):
# a response schema must be able to represent it, unlike the removed
# create/update validation rule.
# Parameters:
# - None.
# Returns:
# - None. The test passes if GoalResponse is created successfully.
def test_goal_response_allows_overfunded_current_amount() -> None:
    # Arrange
    now = datetime.now(timezone.utc)

    # Act
    goal = GoalResponse(
        id=uuid4(),
        user_id=uuid4(),
        name="Vacation",
        target_amount=Decimal("1000.00"),
        current_amount=Decimal("1200.00"),
        currency="EUR",
        target_date=None,
        status="active",
        created_at=now,
        updated_at=now,
    )

    # Assert
    assert goal.current_amount == Decimal("1200.00")
    assert goal.current_amount > goal.target_amount


# Tests that empty goal name is rejected by the schema.
# This test exists because every financial goal must have a name.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_create_rejects_empty_name() -> None:
    # Arrange
    invalid_data = {
        "name": "",
        "target_amount": Decimal("2000"),
        "currency": "EUR",
        "target_date": date(2026, 12, 31),
        "status": "active",
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        GoalCreate(**invalid_data)


# Tests that zero target amount is rejected by the schema.
# This test exists because target amount must be greater than zero.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_create_rejects_zero_target_amount() -> None:
    # Arrange
    invalid_data = {
        "name": "Vacation",
        "target_amount": Decimal("0"),
        "currency": "EUR",
        "target_date": date(2026, 12, 31),
        "status": "active",
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        GoalCreate(**invalid_data)


# Tests that target date can be omitted.
# This test exists because target_date is optional for financial goals.
# Parameters:
# - None.
# Returns:
# - None. The test passes if GoalCreate is created with target_date set to None.
def test_goal_create_accepts_missing_target_date() -> None:
    # Act
    goal = GoalCreate(
        name="Vacation",
        target_amount=Decimal("2000"),
        currency="EUR",
        status="active",
    )

    # Assert
    assert goal.target_date is None


# Tests that currency is normalized to uppercase.
# This test exists to verify that values such as eur and EUR are stored consistently.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the currency value is normalized.
def test_goal_create_normalizes_currency_to_uppercase() -> None:
    # Act
    goal = GoalCreate(
        name="Vacation",
        target_amount=Decimal("2000"),
        currency="eur",
        target_date=date(2026, 12, 31),
        status="active",
    )

    # Assert
    assert goal.currency == "EUR"


# Tests that invalid status is rejected by the schema.
# This test exists because goal status must be one of the allowed values.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_create_rejects_invalid_status() -> None:
    # Arrange
    invalid_data = {
        "name": "Vacation",
        "target_amount": Decimal("2000"),
        "currency": "EUR",
        "target_date": date(2026, 12, 31),
        "status": "paused",
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        GoalCreate(**invalid_data)
