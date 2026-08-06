from typing import Type

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from app.core.exception_handlers import (
    DOMAIN_ERROR_RESPONSES,
    handle_domain_error,
    register_exception_handlers,
)
from app.modules.budgets.budget_errors import (
    BudgetAlreadyExistsError,
    BudgetNotFoundError,
)
from app.modules.categories.errors import (
    CategoryAlreadyExistsError,
    CategoryDefaultDeletionNotAllowedError,
    CategoryDefaultModificationNotAllowedError,
    CategoryNotFoundError,
)
from app.modules.expenses.expenses_errors import ExpenseNotFoundError
from app.modules.goals.goal_errors import (
    GoalInvalidAmountError,
    GoalNotFoundError,
)
from app.modules.receipts.receipt_errors import (
    ReceiptAlreadyConfirmedError,
    ReceiptConfirmationDataMissingError,
    ReceiptConfirmationNotAllowedError,
    ReceiptExpenseNotFoundError,
    ReceiptFileEmptyError,
    ReceiptFileStorageError,
    ReceiptFileTooLargeError,
    ReceiptFileTypeNotAllowedError,
    ReceiptNotFoundError,
    ReceiptOcrFileNotFoundError,
    ReceiptOcrProcessingError,
    ReceiptProcessingNotAllowedError,
)


# Tests that every domain error has the expected HTTP mapping.
# This test exists to protect API status codes and error messages
# from accidental changes.
# Parameters:
# - error_type: domain exception class.
# - expected_status_code: expected HTTP response status.
# - expected_detail: expected API error message.
# Returns:
# - None.
@pytest.mark.parametrize(
    (
        "error_type",
        "expected_status_code",
        "expected_detail",
    ),
    [
        (
            CategoryAlreadyExistsError,
            status.HTTP_409_CONFLICT,
            "Category with this name already exists for this user.",
        ),
        (
            CategoryNotFoundError,
            status.HTTP_404_NOT_FOUND,
            "Category not found.",
        ),
        (
            CategoryDefaultModificationNotAllowedError,
            status.HTTP_409_CONFLICT,
            "Default category cannot be modified.",
        ),
        (
            CategoryDefaultDeletionNotAllowedError,
            status.HTTP_409_CONFLICT,
            "Default category cannot be deleted.",
        ),
        (
            ExpenseNotFoundError,
            status.HTTP_404_NOT_FOUND,
            "Expense not found.",
        ),
        (
            BudgetAlreadyExistsError,
            status.HTTP_409_CONFLICT,
            (
                "Budget with this name, period, and start date "
                "already exists for this user."
            ),
        ),
        (
            BudgetNotFoundError,
            status.HTTP_404_NOT_FOUND,
            "Budget not found.",
        ),
        (
            GoalNotFoundError,
            status.HTTP_404_NOT_FOUND,
            "Goal not found.",
        ),
        (
            GoalInvalidAmountError,
            status.HTTP_400_BAD_REQUEST,
            "current_amount must be less than or equal to target_amount.",
        ),
        (
            ReceiptNotFoundError,
            status.HTTP_404_NOT_FOUND,
            "Receipt not found.",
        ),
        (
            ReceiptExpenseNotFoundError,
            status.HTTP_404_NOT_FOUND,
            "Linked expense not found.",
        ),
        (
            ReceiptFileEmptyError,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Receipt file is empty.",
        ),
        (
            ReceiptFileTypeNotAllowedError,
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Receipt file type is not supported.",
        ),
        (
            ReceiptFileTooLargeError,
            status.HTTP_413_CONTENT_TOO_LARGE,
            "Receipt file is too large.",
        ),
        (
            ReceiptFileStorageError,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Receipt file could not be stored.",
        ),
        (
            ReceiptProcessingNotAllowedError,
            status.HTTP_409_CONFLICT,
            "Receipt cannot be processed in its current status.",
        ),
        (
            ReceiptOcrFileNotFoundError,
            status.HTTP_404_NOT_FOUND,
            "Receipt file not found.",
        ),
        (
            ReceiptOcrProcessingError,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Receipt OCR processing failed.",
        ),
        (
            ReceiptConfirmationNotAllowedError,
            status.HTTP_409_CONFLICT,
            "Receipt cannot be confirmed in its current status.",
        ),
        (
            ReceiptConfirmationDataMissingError,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Required receipt confirmation data is missing.",
        ),
        (
            ReceiptAlreadyConfirmedError,
            status.HTTP_409_CONFLICT,
            "Receipt has already been confirmed.",
        ),
    ],
)
def test_domain_error_has_expected_http_response(
    error_type: Type[Exception],
    expected_status_code: int,
    expected_detail: str,
) -> None:
    # Act
    actual_status_code, actual_detail = DOMAIN_ERROR_RESPONSES[
        error_type
    ]

    # Assert
    assert actual_status_code == expected_status_code
    assert actual_detail == expected_detail


# Tests that every configured domain error is registered on FastAPI.
# This test exists to ensure that mapped exceptions are actually handled
# by the application.
# Parameters:
# - None.
# Returns:
# - None.
def test_register_exception_handlers_registers_all_domain_errors() -> None:
    # Arrange
    test_app = FastAPI()

    # Act
    register_exception_handlers(test_app)

    # Assert
    for error_type in DOMAIN_ERROR_RESPONSES:
        assert (
            test_app.exception_handlers[error_type]
            is handle_domain_error
        )


# Tests the complete FastAPI exception handling flow.
# This test exists to verify that a raised domain error becomes
# a consistent HTTP JSON response.
# Parameters:
# - None.
# Returns:
# - None.
def test_registered_domain_error_handler_returns_json_response() -> None:
    # Arrange
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/test-domain-error")
    def raise_domain_error() -> None:
        raise BudgetNotFoundError

    client = TestClient(test_app)

    # Act
    response = client.get("/test-domain-error")

    # Assert
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {
        "detail": "Budget not found.",
    }