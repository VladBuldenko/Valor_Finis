from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.expenses.expenses_schemas import ExpenseCreate, ExpenseResponse, ExpenseUpdate


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


# --- VF-API-01: schema limits match the expenses table ---------------------
# amount is NUMERIC(12,2) (max 12 digits, 2 of them decimal, so at most 10
# before the decimal point) and description is VARCHAR(500). Financial
# values are Decimals built from strings, never floats.

MAX_VALID_AMOUNT = Decimal("9999999999.99")


# Builds valid ExpenseCreate input with selected fields overridden.
# Parameters:
# - overrides: field values replacing the defaults.
# Returns:
# - A dict accepted by ExpenseCreate unless an override is invalid.
def _expense_create_data(**overrides) -> dict:
    data = {
        "category_id": None,
        "title": "Lidl groceries",
        "amount": Decimal("24.99"),
        "currency": "EUR",
        "expense_date": date(2026, 5, 7),
        "description": None,
        "source": "manual",
    }
    data.update(overrides)
    return data


# Returns the Pydantic error types raised for a single invalid field.
# Parameters:
# - error_info: pytest ExceptionInfo wrapping a ValidationError.
# Returns:
# - Set of error "type" values.
def _error_types(error_info) -> set:
    return {error["type"] for error in error_info.value.errors()}


# Tests that ExpenseCreate accepts the largest NUMERIC(12,2) amount.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the amount is accepted unchanged.
def test_expense_create_accepts_amount_at_numeric_limit() -> None:
    expense = ExpenseCreate(**_expense_create_data(amount=MAX_VALID_AMOUNT))

    assert expense.amount == MAX_VALID_AMOUNT


# Tests that ExpenseCreate rejects an amount with more digits than
# NUMERIC(12,2) can store.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError reports a digit-limit error.
def test_expense_create_rejects_amount_exceeding_numeric_digits() -> None:
    with pytest.raises(ValidationError) as error_info:
        ExpenseCreate(**_expense_create_data(amount=Decimal("10000000000.00")))

    assert _error_types(error_info) & {"decimal_max_digits", "decimal_whole_digits"}


# Tests that ExpenseCreate rejects an amount with more than 2 decimal
# places instead of letting the database round it.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError reports a decimal-places error.
def test_expense_create_rejects_amount_with_more_than_two_decimal_places() -> None:
    with pytest.raises(ValidationError) as error_info:
        ExpenseCreate(**_expense_create_data(amount=Decimal("1.001")))

    assert "decimal_max_places" in _error_types(error_info)


# Tests that ExpenseCreate accepts a description of exactly 500 characters.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the description is accepted unchanged.
def test_expense_create_accepts_description_at_max_length() -> None:
    description = "x" * 500

    expense = ExpenseCreate(**_expense_create_data(description=description))

    assert expense.description == description


# Tests that ExpenseCreate rejects a description longer than VARCHAR(500).
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError reports a length error.
def test_expense_create_rejects_description_over_max_length() -> None:
    with pytest.raises(ValidationError) as error_info:
        ExpenseCreate(**_expense_create_data(description="x" * 501))

    assert "string_too_long" in _error_types(error_info)


# Tests that ExpenseUpdate accepts the largest NUMERIC(12,2) amount.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the amount is accepted unchanged.
def test_expense_update_accepts_amount_at_numeric_limit() -> None:
    update = ExpenseUpdate(amount=MAX_VALID_AMOUNT)

    assert update.amount == MAX_VALID_AMOUNT


# Tests that ExpenseUpdate rejects an amount with more digits than
# NUMERIC(12,2) can store.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError reports a digit-limit error.
def test_expense_update_rejects_amount_exceeding_numeric_digits() -> None:
    with pytest.raises(ValidationError) as error_info:
        ExpenseUpdate(amount=Decimal("10000000000.00"))

    assert _error_types(error_info) & {"decimal_max_digits", "decimal_whole_digits"}


# Tests that ExpenseUpdate rejects an amount with more than 2 decimal
# places.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError reports a decimal-places error.
def test_expense_update_rejects_amount_with_more_than_two_decimal_places() -> None:
    with pytest.raises(ValidationError) as error_info:
        ExpenseUpdate(amount=Decimal("1.001"))

    assert "decimal_max_places" in _error_types(error_info)


# Tests that ExpenseUpdate accepts a description of exactly 500 characters.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the description is accepted unchanged.
def test_expense_update_accepts_description_at_max_length() -> None:
    description = "x" * 500

    update = ExpenseUpdate(description=description)

    assert update.description == description


# Tests that ExpenseUpdate rejects a description longer than VARCHAR(500).
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError reports a length error.
def test_expense_update_rejects_description_over_max_length() -> None:
    with pytest.raises(ValidationError) as error_info:
        ExpenseUpdate(description="x" * 501)

    assert "string_too_long" in _error_types(error_info)


# Tests that an explicit description=None is still accepted on update,
# which is how a client clears an existing note.
# Parameters:
# - None.
# Returns:
# - None. The test passes if description is set (in model_fields_set) to None.
def test_expense_update_accepts_explicit_null_description() -> None:
    update = ExpenseUpdate.model_validate({"description": None})

    assert update.description is None
    assert "description" in update.model_fields_set
