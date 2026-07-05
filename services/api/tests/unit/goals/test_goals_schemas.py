from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.goals.goal_schemas import GoalCreate


# Tests that valid goal input is accepted by the schema.
# This test exists to confirm that correct financial goal data passes validation.
# Parameters:
# - None.
# Returns:
# - None. The test passes if GoalCreate is created successfully.
def test_goal_create_accepts_valid_data() -> None:
    # Arrange
    user_id = uuid4()
    name = "Vacation"
    target_amount = Decimal("2000")
    current_amount = Decimal("500")
    target_date = date(2026, 12, 31)

    # Act
    goal = GoalCreate(
        user_id=user_id,
        name=name,
        target_amount=target_amount,
        current_amount=current_amount,
        currency="EUR",
        target_date=target_date,
        status="active",
    )

    # Assert
    assert goal.user_id == user_id
    assert goal.name == name
    assert goal.target_amount == target_amount
    assert goal.current_amount == current_amount
    assert goal.currency == "EUR"
    assert goal.target_date == target_date
    assert goal.status == "active"


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
        "current_amount": Decimal("500"),
        "deadline": date(2026, 12, 31),
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
        "current_amount": Decimal("500"),
        "deadline": date(2026, 12, 31),
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        GoalCreate(**invalid_data)


# Tests that negative current amount is rejected by the schema.
# This test exists because already saved amount cannot be negative.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_create_rejects_negative_current_amount() -> None:
    # Arrange
    invalid_data = {
        "name": "Vacation",
        "target_amount": Decimal("2000"),
        "current_amount": Decimal("-500"),
        "deadline": date(2026, 12, 31),
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        GoalCreate(**invalid_data)


# Tests that missing deadline is rejected by the schema.
# This test exists because every financial goal must have a deadline.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_goal_create_rejects_missing_deadline() -> None:
    # Arrange
    invalid_data: dict[str, Any] = {
        "name": "Vacation",
        "target_amount": Decimal("2000"),
        "current_amount": Decimal("500"),
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        GoalCreate(**invalid_data)