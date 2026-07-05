from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.expenses.expenses_schemas import ExpenseCreate


# Tests that valid expense input is accepted by the schema.
# This test exists to confirm that correct user expense data passes validation.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ExpenseCreate is created successfully.
def test_expense_create_accepts_valid_data() -> None:
    # Arrange
    user_id = uuid4()
    amount = Decimal("24.99")
    description = "Milk, bread and fruits"
    expense_date = date(2026, 5, 7)

    # Act
    expense = ExpenseCreate(
        user_id=user_id,
        category_id=None,
        title="Lidl groceries",
        amount=amount,
        currency="EUR",
        expense_date=expense_date,
        description=description,
        source="manual",
    )

    # Assert
    assert expense.user_id == user_id
    assert expense.category_id is None
    assert expense.title == "Lidl groceries"
    assert expense.amount == amount
    assert expense.currency == "EUR"
    assert expense.expense_date == expense_date
    assert expense.description == description
    assert expense.source == "manual"

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