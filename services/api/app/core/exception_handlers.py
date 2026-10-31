from typing import Dict, Tuple, Type

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.utils import is_body_allowed_for_status_code
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.api_errors import (
    INTERNAL_SERVER_ERROR_CODE,
    VALIDATION_ERROR_CODE,
    resolve_http_error_code,
)

from app.modules.accounts.account_errors import (
    AccountArchivedError,
    AccountCurrencyImmutableError,
    AccountDeletionNotAllowedError,
    AccountNotFoundError,
    AccountReferencedByGoalAllocationError,
    AccountReferencedByPlannedTransferError,
    AccountReferencedByRuleError,
)
from app.modules.accounts.account_transfer_errors import (
    AccountTransferAlreadyPostedError,
    AccountTransferCurrencyMismatchError,
    AccountTransferEffectiveDateInFutureError,
    AccountTransferIdempotencyConflictError,
    AccountTransferNotFoundError,
)
from app.modules.budgets.budget_errors import (
    BudgetAlreadyExistsError,
    BudgetImmutableFieldError,
    BudgetNotFoundError,
    BudgetReferencedByRuleError,
    BudgetRetroactiveDeactivationError,
)
from app.modules.categories.errors import (
    CategoryAlreadyExistsError,
    CategoryDefaultDeletionNotAllowedError,
    CategoryDefaultModificationNotAllowedError,
    CategoryInUseByBudgetError,
    CategoryNotFoundError,
)
from app.modules.expenses.expenses_errors import (
    ExpenseAccountCurrencyMismatchError,
    ExpenseNotFoundError,
)
from app.modules.fx.fx_errors import (
    FxFutureDatedNotSupportedError,
    FxProviderUnavailableError,
    FxRateUnavailableError,
)
from app.modules.financial_rules.financial_rule_errors import (
    FinancialRuleActivationNotAvailableError,
    FinancialRuleAlreadyExistsError,
    FinancialRuleCurrencyMismatchError,
    FinancialRuleDeletionNotAllowedError,
    FinancialRuleInvalidFieldsError,
    FinancialRuleInvalidTransitionError,
    FinancialRuleNotFoundError,
    RuleAlertNotFoundError,
    RuleProposalNotFoundError,
    RuleProposalStaleError,
    FinancialRuleSubjectArchivedError,
)
from app.modules.goals.goal_errors import (
    GoalAccountCurrencyMismatchError,
    GoalArchivedError,
    GoalCurrencyImmutableError,
    GoalDeletionNotAllowedError,
    GoalInsufficientFundsError,
    GoalLinkedTransactionDateError,
    GoalNotFoundError,
    GoalPartitionInsufficientFundsError,
    GoalPriorityGoalArchivedError,
    GoalPrioritySetStaleError,
    GoalReferencedByRuleError,
    GoalReservationCapacityError,
    GoalTransactionEffectiveDateInFutureError,
    GoalTransactionIdempotencyConflictError,
)
from app.modules.income.income_errors import (
    IncomeAccountCurrencyMismatchError,
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
    AccountReferencedByPlannedTransferError: (
        status.HTTP_409_CONFLICT,
        "Account is referenced by planned transfers. Delete them first.",
    ),
    AccountReferencedByGoalAllocationError: (
        status.HTTP_409_CONFLICT,
        "Account is referenced by Goal reservations and cannot be deleted or have its currency changed.",
    ),
    FinancialRuleNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Financial rule not found.",
    ),
    RuleAlertNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Rule alert not found.",
    ),
    RuleProposalNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Rule proposal not found.",
    ),
    RuleProposalStaleError: (
        status.HTTP_409_CONFLICT,
        "The proposal can no longer be confirmed and was cancelled (stale). Nothing was written.",
    ),
    FinancialRuleAlreadyExistsError: (
        status.HTTP_409_CONFLICT,
        "A rule of this type already exists for this subject.",
    ),
    FinancialRuleInvalidTransitionError: (
        status.HTTP_409_CONFLICT,
        "This status change is not allowed from the rule's current status.",
    ),
    FinancialRuleActivationNotAvailableError: (
        status.HTTP_409_CONFLICT,
        "This rule type cannot be enabled yet.",
    ),
    FinancialRuleDeletionNotAllowedError: (
        status.HTTP_409_CONFLICT,
        "Only draft or disabled rules can be deleted.",
    ),
    FinancialRuleSubjectArchivedError: (
        status.HTTP_409_CONFLICT,
        "The rule's Account or Goal is archived.",
    ),
    FinancialRuleCurrencyMismatchError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "The source Account and every target Goal must use the same currency.",
    ),
    AccountReferencedByRuleError: (
        status.HTTP_409_CONFLICT,
        "Account is referenced by a financial rule and cannot be deleted or have its currency changed.",
    ),
    GoalReferencedByRuleError: (
        status.HTTP_409_CONFLICT,
        "Goal is referenced by a financial rule and cannot be deleted or have its currency changed.",
    ),
    BudgetReferencedByRuleError: (
        status.HTTP_409_CONFLICT,
        "Budget is referenced by a financial rule and cannot be deleted.",
    ),
    AccountTransferNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Account transfer not found.",
    ),
    AccountTransferIdempotencyConflictError: (
        status.HTTP_409_CONFLICT,
        "client_request_id has already been used for a different transfer.",
    ),
    AccountTransferCurrencyMismatchError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Transfer source and destination accounts must use the same currency.",
    ),
    AccountTransferAlreadyPostedError: (
        status.HTTP_409_CONFLICT,
        "Account transfer has already been posted.",
    ),
    AccountTransferEffectiveDateInFutureError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Transfer effective date cannot be in the future.",
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
    ExpenseAccountCurrencyMismatchError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Expense currency must match the account's currency to link them.",
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
    GoalPartitionInsufficientFundsError: (
        status.HTTP_409_CONFLICT,
        "Withdrawal exceeds the goal amount reserved against this account.",
    ),
    GoalReservationCapacityError: (
        status.HTTP_409_CONFLICT,
        "Reservation exceeds the Account's reservable capacity.",
    ),
    GoalLinkedTransactionDateError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Linked goal transactions are dated today; effective_date must be omitted or equal to today.",
    ),
    GoalAccountCurrencyMismatchError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Goal and Account currencies must match.",
    ),
    GoalPriorityGoalArchivedError: (
        status.HTTP_409_CONFLICT,
        "Archived goals cannot be ranked.",
    ),
    GoalPrioritySetStaleError: (
        status.HTTP_409_CONFLICT,
        "Goal list is out of date. Reload goals and try again.",
    ),
    GoalArchivedError: (
        status.HTTP_409_CONFLICT,
        "Archived goal cannot receive contributions.",
    ),
    GoalCurrencyImmutableError: (
        status.HTTP_409_CONFLICT,
        "Goal currency cannot be changed after transaction history exists.",
    ),
    GoalDeletionNotAllowedError: (
        status.HTTP_409_CONFLICT,
        "Goal with transaction history cannot be deleted. Archive it instead.",
    ),
    GoalTransactionIdempotencyConflictError: (
        status.HTTP_409_CONFLICT,
        "client_request_id has already been used for a different goal transaction.",
    ),
    GoalTransactionEffectiveDateInFutureError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Goal transaction effective date cannot be in the future.",
    ),
    IncomeNotFoundError: (
        status.HTTP_404_NOT_FOUND,
        "Income not found.",
    ),
    IncomeFutureDatedNotSupportedError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "A foreign-currency income cannot be dated in the future.",
    ),
    IncomeAccountCurrencyMismatchError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Income currency must match the account's currency to link them.",
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


# Stable public error code for every entry of DOMAIN_ERROR_RESPONSES. Codes are
# part of the API contract (docs/api-contract.md, section 13): written out
# explicitly, never derived from a class name or a message, and never renamed or
# reused. A new mapped domain error needs a new entry here; the registry test
# fails otherwise.
DOMAIN_ERROR_CODES: Dict[Type[Exception], str] = {
    AccountNotFoundError: "account_not_found",
    AccountCurrencyImmutableError: "account_currency_immutable",
    AccountDeletionNotAllowedError: "account_deletion_not_allowed",
    AccountArchivedError: "account_archived",
    AccountReferencedByPlannedTransferError: "account_referenced_by_planned_transfer",
    AccountReferencedByGoalAllocationError: "account_referenced_by_goal_allocation",
    FinancialRuleNotFoundError: "financial_rule_not_found",
    RuleAlertNotFoundError: "rule_alert_not_found",
    RuleProposalNotFoundError: "rule_proposal_not_found",
    RuleProposalStaleError: "rule_proposal_stale",
    FinancialRuleAlreadyExistsError: "financial_rule_already_exists",
    FinancialRuleInvalidTransitionError: "financial_rule_invalid_transition",
    FinancialRuleActivationNotAvailableError: "financial_rule_activation_not_available",
    FinancialRuleDeletionNotAllowedError: "financial_rule_deletion_not_allowed",
    FinancialRuleSubjectArchivedError: "financial_rule_subject_archived",
    FinancialRuleCurrencyMismatchError: "financial_rule_currency_mismatch",
    AccountReferencedByRuleError: "account_referenced_by_rule",
    GoalReferencedByRuleError: "goal_referenced_by_rule",
    BudgetReferencedByRuleError: "budget_referenced_by_rule",
    AccountTransferNotFoundError: "account_transfer_not_found",
    AccountTransferIdempotencyConflictError: "account_transfer_idempotency_conflict",
    AccountTransferCurrencyMismatchError: "account_transfer_currency_mismatch",
    AccountTransferAlreadyPostedError: "account_transfer_already_posted",
    AccountTransferEffectiveDateInFutureError: "account_transfer_effective_date_in_future",
    CategoryAlreadyExistsError: "category_already_exists",
    CategoryNotFoundError: "category_not_found",
    CategoryDefaultModificationNotAllowedError: "category_default_modification_not_allowed",
    CategoryDefaultDeletionNotAllowedError: "category_default_deletion_not_allowed",
    CategoryInUseByBudgetError: "category_in_use_by_budget",
    ExpenseNotFoundError: "expense_not_found",
    ExpenseAccountCurrencyMismatchError: "expense_account_currency_mismatch",
    FxProviderUnavailableError: "fx_provider_unavailable",
    FxRateUnavailableError: "fx_rate_unavailable",
    FxFutureDatedNotSupportedError: "fx_future_dated_not_supported",
    BudgetAlreadyExistsError: "budget_already_exists",
    BudgetNotFoundError: "budget_not_found",
    BudgetImmutableFieldError: "budget_immutable_field",
    BudgetRetroactiveDeactivationError: "budget_retroactive_deactivation",
    GoalNotFoundError: "goal_not_found",
    GoalInsufficientFundsError: "goal_insufficient_funds",
    GoalPartitionInsufficientFundsError: "goal_partition_insufficient_funds",
    GoalReservationCapacityError: "goal_reservation_capacity_exceeded",
    GoalLinkedTransactionDateError: "goal_linked_transaction_date_invalid",
    GoalAccountCurrencyMismatchError: "goal_account_currency_mismatch",
    GoalPriorityGoalArchivedError: "goal_priority_goal_archived",
    GoalPrioritySetStaleError: "goal_priority_set_stale",
    GoalArchivedError: "goal_archived",
    GoalCurrencyImmutableError: "goal_currency_immutable",
    GoalDeletionNotAllowedError: "goal_deletion_not_allowed",
    GoalTransactionIdempotencyConflictError: "goal_transaction_idempotency_conflict",
    GoalTransactionEffectiveDateInFutureError: "goal_transaction_effective_date_in_future",
    IncomeNotFoundError: "income_not_found",
    IncomeFutureDatedNotSupportedError: "income_future_dated_not_supported",
    IncomeAccountCurrencyMismatchError: "income_account_currency_mismatch",
    ReceiptNotFoundError: "receipt_not_found",
    ReceiptExpenseNotFoundError: "receipt_expense_not_found",
    ReceiptFileEmptyError: "receipt_file_empty",
    ReceiptFileTypeNotAllowedError: "receipt_file_type_not_allowed",
    ReceiptFileTooLargeError: "receipt_file_too_large",
    ReceiptFileStorageError: "receipt_file_storage_failed",
    ReceiptProcessingNotAllowedError: "receipt_processing_not_allowed",
    ReceiptOcrFileNotFoundError: "receipt_ocr_file_not_found",
    ReceiptOcrProcessingError: "receipt_ocr_processing_failed",
    ReceiptConfirmationNotAllowedError: "receipt_confirmation_not_allowed",
    ReceiptConfirmationDataMissingError: "receipt_confirmation_data_missing",
    ReceiptAlreadyConfirmedError: "receipt_already_confirmed",
}

# FinancialRuleInvalidFieldsError has its own handler (its message comes from the
# exception), so it is outside DOMAIN_ERROR_RESPONSES and has its code here.
FINANCIAL_RULE_INVALID_FIELDS_CODE = "financial_rule_invalid_fields"


# Converts a domain exception into a consistent HTTP JSON response.
# This function exists to keep HTTP error mapping outside router modules.
# Parameters:
# - request: FastAPI request that produced the exception.
# - error: domain exception raised by the application.
# Returns:
# - JSONResponse with a consistent detail field and a stable code field.
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
            "code": DOMAIN_ERROR_CODES[type(error)],
        },
    )


# Returns a 422 for an invalid financial-rule request. The message is built by
# the rules service from validation text only - never from database
# constraint names or SQL.
async def handle_financial_rule_invalid_fields(
    request: Request,
    error: Exception,
) -> JSONResponse:
    del request

    message = getattr(error, "message", "Invalid financial rule.")

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": message, "code": FINANCIAL_RULE_INVALID_FIELDS_CODE},
    )


# Adds the stable code to every HTTPException response (authentication and
# configuration errors, Starlette's 404/405, router-level errors). Status,
# detail and headers are exactly what FastAPI's default handler produced.
async def handle_http_exception(
    request: Request,
    error: Exception,
) -> Response:
    del request

    http_error = error if isinstance(error, StarletteHTTPException) else None

    if http_error is None:
        raise error

    headers = getattr(http_error, "headers", None)

    if not is_body_allowed_for_status_code(http_error.status_code):
        return Response(status_code=http_error.status_code, headers=headers)

    return JSONResponse(
        status_code=http_error.status_code,
        content={
            "detail": http_error.detail,
            "code": resolve_http_error_code(http_error),
        },
        headers=headers,
    )


# Keeps FastAPI's structured validation `detail` list and adds only the code.
async def handle_request_validation_error(
    request: Request,
    error: Exception,
) -> JSONResponse:
    del request

    errors = error.errors() if isinstance(error, RequestValidationError) else []

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": jsonable_encoder(errors),
            "code": VALIDATION_ERROR_CODE,
        },
    )


# Last-resort handler for an unexpected exception. The body is a fixed message:
# nothing from the exception (text, SQL, traceback, settings) is ever included.
async def handle_unexpected_error(
    request: Request,
    error: Exception,
) -> JSONResponse:
    del request, error

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error.",
            "code": INTERNAL_SERVER_ERROR_CODE,
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
    app.add_exception_handler(
        FinancialRuleInvalidFieldsError,
        handle_financial_rule_invalid_fields,
    )
    app.add_exception_handler(
        StarletteHTTPException,
        handle_http_exception,
    )
    app.add_exception_handler(
        RequestValidationError,
        handle_request_validation_error,
    )
    app.add_exception_handler(
        Exception,
        handle_unexpected_error,
    )
