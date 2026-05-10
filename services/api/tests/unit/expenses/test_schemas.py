from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.expenses.schemas import ExpenseCreate


# Tests that valid expense input is accepted by the schema.
# This test exists to confirm that correct user expense data passes validation.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ExpenseCreate is created successfully.
def test_expense_create_accepts_valid_data() -> None:
    # Arrange
    amount = Decimal("24.99")
    category = "food"
    description = "Lidl groceries"
    expense_date = date(2026, 5, 7)

    # Act
    expense = ExpenseCreate(
        amount=amount,
        category=category,
        description=description,
        date=expense_date,
    )

    # Assert
    assert expense.amount == amount
    assert expense.category == category
    assert expense.description == description
    assert expense.date == expense_date


# Tests that zero amount is rejected by the schema.
# This test exists because expense amount must always be greater than zero.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_expense_create_rejects_zero_amount() -> None:
    # Arrange
    invalid_data = {
        "amount": Decimal("0"),
        "category": "food",
        "description": "Invalid expense",
        "date": date(2026, 5, 7),
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        ExpenseCreate(**invalid_data)


# Tests that negative amount is rejected by the schema.
# This test exists because negative expenses are not valid spending records.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_expense_create_rejects_negative_amount() -> None:
    # Arrange
    invalid_data = {
        "amount": Decimal("-10"),
        "category": "food",
        "description": "Invalid expense",
        "date": date(2026, 5, 7),
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        ExpenseCreate(**invalid_data)


# Tests that empty category is rejected by the schema.
# This test exists because every expense must belong to a category.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_expense_create_rejects_empty_category() -> None:
    # Arrange
    invalid_data = {
        "amount": Decimal("24.99"),
        "category": "",
        "description": "Lidl groceries",
        "date": date(2026, 5, 7),
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        ExpenseCreate(**invalid_data)


# Tests that missing date is rejected by the schema.
# This test exists because every expense must have a date.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_expense_create_rejects_missing_date() -> None:
    # Arrange
    invalid_data: dict[str, Any] = {
        "amount": Decimal("24.99"),
        "category": "food",
        "description": "Lidl groceries",
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        ExpenseCreate(**invalid_data)