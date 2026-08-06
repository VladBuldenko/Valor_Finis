from typing import Dict, Tuple, Type

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

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


DomainErrorResponse = Tuple[int, str]


DOMAIN_ERROR_RESPONSES: Dict[
    Type[Exception],
    DomainErrorResponse,
] = {
    CategoryAlreadyExistsError: (
        status.HTTP_409_CONFLICT,
        "Category with this name already exists for this user.",
    ),
    CategoryNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Category not found.",
    ),
    CategoryDefaultModificationNotAllowedError: (
        status.HTTP_409_CONFLICT,
        "Default category cannot be modified.",
    ),
    CategoryDefaultDeletionNotAllowedError: (
        status.HTTP_409_CONFLICT,
        "Default category cannot be deleted.",
    ),
    ExpenseNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Expense not found.",
    ),
    BudgetAlreadyExistsError: (
        status.HTTP_409_CONFLICT,
            (
        "Budget with this name, period, and start date "
        "already exists for this user."
        ),
    ),
    BudgetNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Budget not found.",
    ),
    GoalNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Goal not found.",
    ),
    GoalInvalidAmountError: (
    status.HTTP_400_BAD_REQUEST,
    "current_amount must be less than or equal to target_amount.",
    ),
    ReceiptNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Receipt not found.",
    ),
    ReceiptExpenseNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Linked expense not found.",
    ),
    ReceiptFileEmptyError: (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Receipt file is empty.",
    ),
    ReceiptFileTypeNotAllowedError: (
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        "Receipt file type is not supported.",
    ),
    ReceiptFileTooLargeError: (
        status.HTTP_413_CONTENT_TOO_LARGE,
        "Receipt file is too large.",
    ),
    ReceiptFileStorageError: (
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "Receipt file could not be stored.",
    ),
    ReceiptProcessingNotAllowedError: (
        status.HTTP_409_CONFLICT,
        "Receipt cannot be processed in its current status.",
    ),
    ReceiptOcrFileNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Receipt file not found.",
    ),
    ReceiptOcrProcessingError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Receipt OCR processing failed.",
    ),
    ReceiptConfirmationNotAllowedError: (
        status.HTTP_409_CONFLICT,
        "Receipt cannot be confirmed in its current status.",
    ),
    ReceiptConfirmationDataMissingError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Required receipt confirmation data is missing.",
    ),
    ReceiptAlreadyConfirmedError: (
        status.HTTP_409_CONFLICT,
        "Receipt has already been confirmed.",
    ),
}


# Converts a domain exception into a consistent HTTP JSON response.
# This function exists to keep HTTP error mapping outside router modules.
# Parameters:
# - request: FastAPI request that produced the exception.
# - error: domain exception raised by the application.
# Returns:
# - JSONResponse with a consistent detail field.
async def handle_domain_error(
    request: Request,
    error: Exception,
) -> JSONResponse:
    del request

    status_code, detail = DOMAIN_ERROR_RESPONSES[type(error)]

    return JSONResponse(
        status_code=status_code,
        content={
            "detail": detail,
        },
    )


# Registers all domain exception handlers on the FastAPI application.
# This function exists to configure centralized HTTP error handling
# during application startup.
# Parameters:
# - app: FastAPI application instance.
# Returns:
# - None.
def register_exception_handlers(
    app: FastAPI,
) -> None:
    for error_type in DOMAIN_ERROR_RESPONSES:
        app.add_exception_handler(
            error_type,
            handle_domain_error,
        )