from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.budgets.budget_schemas import BudgetCreate


# Tests that valid budget input is accepted by the schema.
# This test exists to confirm that correct budget data passes validation.
# Parameters:
# - None.
# Returns:
# - None. The test passes if BudgetCreate is created successfully.
def test_budget_create_accepts_valid_data() -> None:
    # Arrange
    limit_amount = Decimal("400")
    start_date = date(2026, 5, 1)

    # Act
    budget = BudgetCreate(
        category_id=None,
        name="Food budget",
        limit_amount=limit_amount,
        currency="EUR",
        period="monthly",
        start_date=start_date,
        end_date=None,
    )

    # Assert
    assert budget.category_id is None
    assert budget.name == "Food budget"
    assert budget.limit_amount == limit_amount
    assert budget.currency == "EUR"
    assert budget.period == "monthly"
    assert budget.start_date == start_date
    assert budget.end_date is None


# Tests that user_id is rejected by the budget creation schema.
# This test exists because user_id must come from authentication data,
# not from the client request body.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_budget_create_rejects_user_id_field() -> None:
    # Arrange
    invalid_data = {
        "user_id": uuid4(),
        "category_id": None,
        "name": "Food budget",
        "limit_amount": Decimal("400"),
        "currency": "EUR",
        "period": "monthly",
        "start_date": date(2026, 5, 1),
        "end_date": None,
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        BudgetCreate(**invalid_data)


# Tests that zero limit amount is rejected by the schema.
# This test exists because budget limit must always be greater than zero.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_budget_create_rejects_zero_limit_amount() -> None:
    # Arrange
    invalid_data = {
        "category_id": None,
        "name": "Invalid budget",
        "limit_amount": Decimal("0"),
        "currency": "EUR",
        "period": "monthly",
        "start_date": date(2026, 5, 1),
        "end_date": None,
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        BudgetCreate(**invalid_data)


# Tests that negative limit amount is rejected by the schema.
# This test exists because negative budget limits are not valid.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_budget_create_rejects_negative_limit_amount() -> None:
    # Arrange
    invalid_data = {
        "category_id": None,
        "name": "Invalid budget",
        "limit_amount": Decimal("-400"),
        "currency": "EUR",
        "period": "monthly",
        "start_date": date(2026, 5, 1),
        "end_date": None,
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        BudgetCreate(**invalid_data)


# Tests that empty name is rejected by the schema.
# This test exists because every budget needs a human-readable name.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_budget_create_rejects_empty_name() -> None:
    # Arrange
    invalid_data = {
        "category_id": None,
        "name": "",
        "limit_amount": Decimal("400"),
        "currency": "EUR",
        "period": "monthly",
        "start_date": date(2026, 5, 1),
        "end_date": None,
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        BudgetCreate(**invalid_data)


# Tests that missing start date is rejected by the schema.
# This test exists because every budget must have a start date.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_budget_create_rejects_missing_start_date() -> None:
    # Arrange
    invalid_data: dict[str, Any] = {
        "category_id": None,
        "name": "Food budget",
        "limit_amount": Decimal("400"),
        "currency": "EUR",
        "period": "monthly",
        "end_date": None,
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        BudgetCreate(**invalid_data)


# Tests that currency is normalized to uppercase.
# This test exists to verify that values such as eur and EUR are stored consistently.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the currency value is normalized.
def test_budget_create_normalizes_currency_to_uppercase() -> None:
    # Act
    budget = BudgetCreate(
        category_id=None,
        name="Food budget",
        limit_amount=Decimal("400"),
        currency="eur",
        period="monthly",
        start_date=date(2026, 5, 1),
        end_date=None,
    )

    # Assert
    assert budget.currency == "EUR"


# Tests that end date before start date is rejected by the schema.
# This test exists because a budget period cannot end before it starts.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_budget_create_rejects_end_date_before_start_date() -> None:
    # Arrange
    invalid_data = {
        "category_id": None,
        "name": "Food budget",
        "limit_amount": Decimal("400"),
        "currency": "EUR",
        "period": "monthly",
        "start_date": date(2026, 5, 1),
        "end_date": date(2026, 4, 30),
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        BudgetCreate(**invalid_data)