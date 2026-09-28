from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.receipts.receipt_schemas import ReceiptConfirmRequest, ReceiptUpdate

# VF-API-01: receipt inputs that can become an Expense amount/description
# use the same limits as ExpenseCreate - amount NUMERIC(12,2) (max 12
# digits, 2 of them decimal) and description VARCHAR(500) - so
# confirm_receipt never builds an ExpenseCreate that would be rejected
# inside the service. Financial values are Decimals built from strings.

MAX_VALID_AMOUNT = Decimal("9999999999.99")


# Returns the Pydantic error types raised for a single invalid field.
# Parameters:
# - error_info: pytest ExceptionInfo wrapping a ValidationError.
# Returns:
# - Set of error "type" values.
def _error_types(error_info) -> set:
    return {error["type"] for error in error_info.value.errors()}


# Tests that ReceiptConfirmRequest accepts the largest NUMERIC(12,2) amount.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the amount is accepted unchanged.
def test_receipt_confirm_request_accepts_amount_at_numeric_limit() -> None:
    request = ReceiptConfirmRequest(amount=MAX_VALID_AMOUNT)

    assert request.amount == MAX_VALID_AMOUNT


# Tests that ReceiptConfirmRequest rejects a corrected amount with more
# digits than NUMERIC(12,2) can store.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError reports a digit-limit error.
def test_receipt_confirm_request_rejects_amount_exceeding_numeric_digits() -> None:
    with pytest.raises(ValidationError) as error_info:
        ReceiptConfirmRequest(amount=Decimal("10000000000.00"))

    assert _error_types(error_info) & {"decimal_max_digits", "decimal_whole_digits"}


# Tests that ReceiptConfirmRequest rejects a corrected amount with more than
# 2 decimal places.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError reports a decimal-places error.
def test_receipt_confirm_request_rejects_amount_with_more_than_two_decimal_places() -> None:
    with pytest.raises(ValidationError) as error_info:
        ReceiptConfirmRequest(amount=Decimal("1.001"))

    assert "decimal_max_places" in _error_types(error_info)


# Tests that ReceiptConfirmRequest accepts a 500-character description.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the description is accepted unchanged.
def test_receipt_confirm_request_accepts_description_at_max_length() -> None:
    description = "x" * 500

    request = ReceiptConfirmRequest(description=description)

    assert request.description == description


# Tests that ReceiptConfirmRequest rejects a description longer than the
# expense description column (VARCHAR(500)).
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError reports a length error.
def test_receipt_confirm_request_rejects_description_over_max_length() -> None:
    with pytest.raises(ValidationError) as error_info:
        ReceiptConfirmRequest(description="x" * 501)

    assert "string_too_long" in _error_types(error_info)


# Tests that omitted/null corrections keep their existing meaning (fall
# back to OCR data / no description).
# Parameters:
# - None.
# Returns:
# - None. The test passes if null amount and description are accepted.
def test_receipt_confirm_request_keeps_null_semantics() -> None:
    request = ReceiptConfirmRequest.model_validate({"amount": None, "description": None})

    assert request.amount is None
    assert request.description is None


# Tests that ReceiptUpdate accepts the largest NUMERIC(12,2) detected total.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the amount is accepted unchanged.
def test_receipt_update_accepts_total_amount_detected_at_numeric_limit() -> None:
    update = ReceiptUpdate(total_amount_detected=MAX_VALID_AMOUNT)

    assert update.total_amount_detected == MAX_VALID_AMOUNT


# Tests that ReceiptUpdate rejects a detected total with more digits than
# NUMERIC(12,2) can store.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError reports a digit-limit error.
def test_receipt_update_rejects_total_amount_detected_exceeding_numeric_digits() -> None:
    with pytest.raises(ValidationError) as error_info:
        ReceiptUpdate(total_amount_detected=Decimal("10000000000.00"))

    assert _error_types(error_info) & {"decimal_max_digits", "decimal_whole_digits"}


# Tests that ReceiptUpdate rejects a detected total with more than 2
# decimal places - such a stored value would later reach ExpenseCreate
# during confirmation.
# Parameters:
# - None.
# Returns:
# - None. The test passes if ValidationError reports a decimal-places error.
def test_receipt_update_rejects_total_amount_detected_with_more_than_two_decimal_places() -> None:
    with pytest.raises(ValidationError) as error_info:
        ReceiptUpdate(total_amount_detected=Decimal("1.001"))

    assert "decimal_max_places" in _error_types(error_info)
