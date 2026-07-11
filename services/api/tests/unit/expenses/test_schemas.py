from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.expenses.expenses_schemas import ExpenseCreate, ExpenseResponse


# Tests that valid expense input is accepted by the schema.
# This test exists to confirm that correct expense request data passes validation without user_id.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ExpenseCreate is created successfully.
def test_expense_create_accepts_valid_data_without_user_id() -> None:
    # Arrange
    amount = Decimal("24.99")
    description = "Milk, bread and fruits"
    expense_date = date(2026, 5, 7)

    # Act
    expense = ExpenseCreate(
        category_id=None,
        title="Lidl groceries",
        amount=amount,
        currency="EUR",
        expense_date=expense_date,
        description=description,
        source="manual",
    )

    # Assert
    assert expense.category_id is None
    assert expense.title == "Lidl groceries"
    assert expense.amount == amount
    assert expense.currency == "EUR"
    assert expense.expense_date == expense_date
    assert expense.description == description
    assert expense.source == "manual"


# Tests that user_id is rejected in create request data.
# This test exists because user ownership must come from authentication data, not from request body.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_expense_create_rejects_user_id() -> None:
    # Arrange
    invalid_data = {
        "user_id": uuid4(),
        "category_id": None,
        "title": "Lidl groceries",
        "amount": Decimal("24.99"),
        "currency": "EUR",
        "expense_date": date(2026, 5, 7),
        "description": "Milk, bread and fruits",
        "source": "manual",
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        ExpenseCreate.model_validate(invalid_data)


# Tests that negative amount is rejected by the schema.
# This test exists because negative expenses are not valid spending records.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_expense_create_rejects_negative_amount() -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        ExpenseCreate(
            category_id=None,
            title="Invalid expense",
            amount=Decimal("-10"),
            currency="EUR",
            expense_date=date(2026, 5, 7),
            description="Invalid expense",
            source="manual",
        )


# Tests that zero amount is rejected by the schema.
# This test exists because expense amount must be greater than zero.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_expense_create_rejects_zero_amount() -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        ExpenseCreate(
            category_id=None,
            title="Invalid expense",
            amount=Decimal("0"),
            currency="EUR",
            expense_date=date(2026, 5, 7),
            description="Invalid expense",
            source="manual",
        )


# Tests that empty title is rejected by the schema.
# This test exists because every expense must have a non-empty title.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_expense_create_rejects_empty_title() -> None:
    # Act / Assert
    with pytest.raises(ValidationError):
        ExpenseCreate(
            category_id=None,
            title="",
            amount=Decimal("24.99"),
            currency="EUR",
            expense_date=date(2026, 5, 7),
            description="Milk, bread and fruits",
            source="manual",
        )


# Tests that missing expense_date is rejected by the schema.
# This test exists because every expense must have an expense date.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError is raised.
def test_expense_create_rejects_missing_expense_date() -> None:
    # Arrange
    invalid_data = {
        "category_id": None,
        "title": "Lidl groceries",
        "amount": Decimal("24.99"),
        "currency": "EUR",
        "description": "Milk, bread and fruits",
        "source": "manual",
    }

    # Act / Assert
    with pytest.raises(ValidationError):
        ExpenseCreate.model_validate(invalid_data)


# Tests that ExpenseResponse contains database and ownership fields.
# This test exists because API responses must include id, user_id, created_at, and updated_at.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ExpenseResponse is created with expected values.
def test_expense_response_contains_database_and_user_fields() -> None:
    # Arrange
    expense_id = uuid4()
    user_id = uuid4()
    created_at = datetime(2026, 5, 7, 10, 30, 0)
    updated_at = datetime(2026, 5, 7, 10, 30, 0)

    # Act
    expense = ExpenseResponse(
        id=expense_id,
        user_id=user_id,
        category_id=None,
        title="Lidl groceries",
        amount=Decimal("24.99"),
        currency="EUR",
        expense_date=date(2026, 5, 7),
        description="Milk, bread and fruits",
        source="manual",
        created_at=created_at,
        updated_at=updated_at,
    )

    # Assert
    assert expense.id == expense_id
    assert expense.user_id == user_id
    assert expense.category_id is None
    assert expense.title == "Lidl groceries"
    assert expense.amount == Decimal("24.99")
    assert expense.currency == "EUR"
    assert expense.expense_date == date(2026, 5, 7)
    assert expense.description == "Milk, bread and fruits"
    assert expense.source == "manual"
    assert expense.created_at == created_at
    assert expense.updated_at == updated_at