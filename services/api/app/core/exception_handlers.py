from typing import Dict, Tuple, Type

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.modules.accounts.account_errors import (
    AccountArchivedError,
    AccountCurrencyImmutableError,
    AccountDeletionNotAllowedError,
    AccountNotFoundError,
)
from app.modules.budgets.budget_errors import (
    BudgetAlreadyExistsError,
    BudgetImmutableFieldError,
    BudgetNotFoundError,
    BudgetRetroactiveDeactivationError,
)
from app.modules.categories.errors import (
    CategoryAlreadyExistsError,
    CategoryDefaultDeletionNotAllowedError,
    CategoryDefaultModificationNotAllowedError,
    CategoryInUseByBudgetError,
    CategoryNotFoundError,
)
from app.modules.expenses.expenses_errors import ExpenseNotFoundError
from app.modules.fx.fx_errors import (
    FxFutureDatedNotSupportedError,
    FxProviderUnavailableError,
    FxRateUnavailableError,
)
from app.modules.goals.goal_errors import (
    GoalCurrencyImmutableError,
    GoalDeletionNotAllowedError,
    GoalInsufficientFundsError,
    GoalNotFoundError,
)
from app.modules.income.income_errors import (
    IncomeFutureDatedNotSupportedError,
    IncomeNotFoundError,
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
    AccountNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Account not found.",
    ),
    AccountCurrencyImmutableError: (
        status.HTTP_409_CONFLICT,
        "Account currency cannot be changed after transaction history exists.",
    ),
    AccountDeletionNotAllowedError: (
        status.HTTP_409_CONFLICT,
        "Account with transaction history cannot be deleted. Archive it instead.",
    ),
    AccountArchivedError: (
        status.HTTP_409_CONFLICT,
        "Archived account cannot receive new transactions.",
    ),
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
    CategoryInUseByBudgetError: (
        status.HTTP_409_CONFLICT,
        "Category is referenced by a budget and cannot be deleted. Hide it instead.",
    ),
    ExpenseNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Expense not found.",
    ),
    FxProviderUnavailableError: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Currency conversion is temporarily unavailable. Please try again shortly.",
    ),
    FxRateUnavailableError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "This currency cannot be converted for the given date.",
    ),
    FxFutureDatedNotSupportedError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "A foreign-currency expense cannot be dated in the future.",
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
    BudgetImmutableFieldError: (
        status.HTTP_409_CONFLICT,
        (
            "Budget currency cannot be changed. Period and start date "
            "cannot be changed after the first period completes."
        ),
    ),
    BudgetRetroactiveDeactivationError: (
        status.HTTP_409_CONFLICT,
        "Budget end date cannot be set to a date before today.",
    ),
    GoalNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Goal not found.",
    ),
    GoalInsufficientFundsError: (
        status.HTTP_409_CONFLICT,
        "Withdrawal exceeds the current goal balance.",
    ),
    GoalCurrencyImmutableError: (
        status.HTTP_409_CONFLICT,
        "Goal currency cannot be changed after transaction history exists.",
    ),
    GoalDeletionNotAllowedError: (
        status.HTTP_409_CONFLICT,
        "Goal with transaction history cannot be deleted. Archive it instead.",
    ),
    IncomeNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Income not found.",
    ),
    IncomeFutureDatedNotSupportedError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "A foreign-currency income cannot be dated in the future.",
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