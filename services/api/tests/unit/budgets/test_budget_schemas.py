from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.budgets.budget_schemas import BudgetCreate


# Tests that valid budget input is accepted by the schema.
# This test exists to confirm that correct budget limit data passes validation.
# Parameters:
# - None.
# Returns:
# - None. The test passes if BudgetCreate is created successfully.
def test_budget_create_accepts_valid_data() -> None:
    # Arrange
    category = "food"
    monthly_limit = Decimal("400")
    budget_month = date(2026, 5, 1)

    # Act
    budget = BudgetCreate(
        category=category,
        monthly_limit=monthly_limit,
        month=budget_month,
    )

    # Assert
    assert budget.category == category
    assert budget.monthly_limit == monthly_limit
    assert budget.month == budget_month


# Tests that zero monthly limit is rejected by the schema.
# This test exists because budget limit must always be greater than zero.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_budget_create_rejects_zero_monthly_limit() -> None:
    # Arrange
    invalid_data = {
        "category": "food",
        "monthly_limit": Decimal("0"),
        "month": date(2026, 5, 1),
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        BudgetCreate(**invalid_data)


# Tests that negative monthly limit is rejected by the schema.
# This test exists because negative budget limits are not valid.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_budget_create_rejects_negative_monthly_limit() -> None:
    # Arrange
    invalid_data = {
        "category": "food",
        "monthly_limit": Decimal("-400"),
        "month": date(2026, 5, 1),
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        BudgetCreate(**invalid_data)


# Tests that empty category is rejected by the schema.
# This test exists because every budget limit must belong to a category.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_budget_create_rejects_empty_category() -> None:
    # Arrange
    invalid_data = {
        "category": "",
        "monthly_limit": Decimal("400"),
        "month": date(2026, 5, 1),
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        BudgetCreate(**invalid_data)


# Tests that missing month is rejected by the schema.
# This test exists because every budget limit must have an active month.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_budget_create_rejects_missing_month() -> None:
    # Arrange
    invalid_data: dict[str, Any] = {
        "category": "food",
        "monthly_limit": Decimal("400"),
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        BudgetCreate(**invalid_data)