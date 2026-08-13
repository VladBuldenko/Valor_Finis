import uuid

from sqlalchemy.orm import Session
from fastapi import UploadFile

from app.modules.expenses.expenses_errors import ExpenseNotFoundError
from app.modules.expenses import expenses_repository
from app.modules.receipts import (
    receipt_ocr_service,
    receipt_parser_service,
    receipt_repository,
    receipt_storage_service,
    receipt_storage_service,
)
from app.modules.receipts.receipt_errors import (
    ReceiptExpenseNotFoundError,
    ReceiptFileStorageError,
    ReceiptOcrFileNotFoundError,
    ReceiptOcrProcessingError,
    ReceiptProcessingNotAllowedError,
    ReceiptAlreadyConfirmedError,
    ReceiptConfirmationDataMissingError,
    ReceiptConfirmationNotAllowedError,
)
from app.modules.receipts.receipt_models import ReceiptModel
from app.modules.receipts.receipt_schemas import (
    ReceiptConfirmRequest,
    ReceiptConfirmResponse,
    ReceiptCreate,
    ReceiptResponse,
    ReceiptUpdate,
)
from app.modules.expenses import expenses_service
from app.modules.expenses.expenses_schemas import ExpenseCreate


PROCESSABLE_RECEIPT_STATUSES = (
    "uploaded",
    "failed",
)
# Converts a ReceiptModel instance into a ReceiptResponse schema.
# This function exists to keep database models separated from API response schemas.
# Parameters:
# - receipt: SQLAlchemy receipt model instance.
# Returns:
# - ReceiptResponse schema.
def map_receipt_to_response(receipt: ReceiptModel) -> ReceiptResponse:
    return ReceiptResponse.model_validate(receipt)


# Creates a new receipt for the authenticated user.
# This function exists to apply receipt creation business logic before persistence.
# Parameters:
# - db_session: active SQLAlchemy session.
# - receipt_data: validated receipt creation data.
# - user_id: authenticated user identifier.
# Returns:
# - ReceiptResponse containing the saved receipt.
def create_receipt(
    db_session: Session,
    receipt_data: ReceiptCreate,
    user_id: uuid.UUID,
) -> ReceiptResponse:
    receipt = receipt_repository.create_receipt(
        db_session=db_session,
        receipt_data=receipt_data,
        user_id=user_id,
    )

    return map_receipt_to_response(receipt)

# Saves an uploaded receipt file and creates its database record.
# This function exists to coordinate receipt file storage
# and receipt metadata persistence.
# Parameters:
# - db_session: active SQLAlchemy session.
# - uploaded_file: receipt file received through the API.
# - user_id: authenticated user identifier.
# Returns:
# - ReceiptResponse containing the created receipt.
def upload_receipt(
    db_session: Session,
    uploaded_file: UploadFile,
    user_id: uuid.UUID,
) -> ReceiptResponse:
    storage_path = receipt_storage_service.save_receipt_file(
        uploaded_file=uploaded_file,
        user_id=user_id,
    )

    receipt_data = ReceiptCreate(
        storage_path=storage_path,
    )

    try:
        return create_receipt(
            db_session=db_session,
            receipt_data=receipt_data,
            user_id=user_id,
        )
    except Exception:
        try:
            receipt_storage_service.delete_receipt_file(
                storage_path=storage_path,
            )
        except ReceiptFileStorageError:
            pass

        raise

# Processes a stored receipt through the configured OCR provider.
# This function exists to coordinate receipt status transitions,
# OCR text extraction, and persistence of the processing result.
# Parameters:
# - db_session: active SQLAlchemy session.
# - receipt_id: receipt identifier.
# - user_id: authenticated user identifier.
# Returns:
# - ReceiptResponse containing the processed receipt.
# Raises:
# - ReceiptNotFoundError when the receipt does not belong to the user.
# - ReceiptProcessingNotAllowedError when the current status cannot be processed.
# - ReceiptOcrFileNotFoundError when no local receipt file is available.
# - ReceiptOcrProcessingError when OCR processing fails.
def process_receipt(
    db_session: Session,
    receipt_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ReceiptResponse:
    receipt = receipt_repository.get_receipt_by_id(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    if receipt.status not in PROCESSABLE_RECEIPT_STATUSES:
        raise ReceiptProcessingNotAllowedError()

    if not receipt.storage_path:
        raise ReceiptOcrFileNotFoundError()

    receipt_repository.update_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        receipt_data=ReceiptUpdate(
            status="processing",
        ),
        user_id=user_id,
    )

    try:
        extracted_text = receipt_ocr_service.extract_receipt_text(
            storage_path=receipt.storage_path,
        )
    except (
        ReceiptOcrFileNotFoundError,
        ReceiptOcrProcessingError,
    ):
        receipt_repository.update_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            receipt_data=ReceiptUpdate(
                status="failed",
            ),
            user_id=user_id,
        )

        raise

    parsed_data = receipt_parser_service.parse_receipt_text(
        ocr_text=extracted_text,
    )

    processed_receipt = receipt_repository.update_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        receipt_data=ReceiptUpdate(
            status="processed",
            ocr_text=extracted_text,
            merchant_detected=parsed_data.merchant_detected,
            total_amount_detected=parsed_data.total_amount_detected,
            currency_detected=parsed_data.currency_detected,
            purchase_date_detected=parsed_data.purchase_date_detected,
        ),
        user_id=user_id,
    )

    return map_receipt_to_response(processed_receipt)

# Confirms a processed receipt and creates a linked expense.
# This function exists to atomically convert verified receipt data
# into an expense and prevent partial database writes.
# Parameters:
# - db_session: active SQLAlchemy session.
# - receipt_id: receipt identifier.
# - confirmation_data: optional user corrections for OCR-detected values.
# - user_id: authenticated user identifier.
# Returns:
# - ReceiptConfirmResponse containing the confirmed receipt
#   and created expense.
# Raises:
# - ReceiptNotFoundError when the receipt does not belong to the user.
# - ReceiptAlreadyConfirmedError when the receipt was already confirmed.
# - ReceiptConfirmationNotAllowedError when the receipt is not processed.
# - ReceiptConfirmationDataMissingError when required expense data is missing.
def confirm_receipt(
    db_session: Session,
    receipt_id: uuid.UUID,
    confirmation_data: ReceiptConfirmRequest,
    user_id: uuid.UUID,
) -> ReceiptConfirmResponse:
    receipt = receipt_repository.get_receipt_by_id(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    if receipt.status == "confirmed" or receipt.expense_id is not None:
        raise ReceiptAlreadyConfirmedError()

    if receipt.status != "processed":
        raise ReceiptConfirmationNotAllowedError()

    title = (
        confirmation_data.title
        or receipt.merchant_detected
    )
    amount = (
        confirmation_data.amount
        or receipt.total_amount_detected
    )
    currency = (
        confirmation_data.currency
        or receipt.currency_detected
    )
    expense_date = (
        confirmation_data.expense_date
        or receipt.purchase_date_detected
    )

    if (
        title is None
        or amount is None
        or currency is None
        or expense_date is None
    ):
        raise ReceiptConfirmationDataMissingError()

    expense_data = ExpenseCreate(
        category_id=confirmation_data.category_id,
        title=title,
        amount=amount,
        currency=currency,
        expense_date=expense_date,
        description=confirmation_data.description,
        source="receipt",
    )

    try:
        created_expense = expenses_service.create_expense(
            db_session=db_session,
            expense_data=expense_data,
            user_id=user_id,
            commit=False,
        )

        confirmed_receipt_model = receipt_repository.update_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            receipt_data=ReceiptUpdate(
                expense_id=created_expense.id,
                status="confirmed",
            ),
            user_id=user_id,
            commit=False,
        )

        db_session.commit()
        db_session.refresh(confirmed_receipt_model)
    except Exception:
        db_session.rollback()
        raise

    return ReceiptConfirmResponse(
        receipt=map_receipt_to_response(
            confirmed_receipt_model,
        ),
        expense=created_expense,
    )

# Returns all receipts owned by the authenticated user.
# This function exists to expose user-scoped receipt data to the API layer.
# Parameters:
# - db_session: active SQLAlchemy session.
# - user_id: authenticated user identifier.
# Returns:
# - List of ReceiptResponse schemas.
def get_receipts(
    db_session: Session,
    user_id: uuid.UUID,
) -> list[ReceiptResponse]:
    receipts = receipt_repository.get_receipts(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        map_receipt_to_response(receipt)
        for receipt in receipts
    ]


# Returns a single receipt owned by the authenticated user.
# This function exists to expose one user-scoped receipt to the API layer.
# Parameters:
# - db_session: active SQLAlchemy session.
# - receipt_id: requested receipt identifier.
# - user_id: authenticated user identifier.
# Returns:
# - ReceiptResponse schema.
def get_receipt_by_id(
    db_session: Session,
    receipt_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ReceiptResponse:
    receipt = receipt_repository.get_receipt_by_id(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    return map_receipt_to_response(receipt)


# Validates that an expense exists and belongs to the authenticated user.
# This function exists to prevent linking receipts to another user's expenses.
# Parameters:
# - db_session: active SQLAlchemy session.
# - expense_id: requested expense identifier.
# - user_id: authenticated user identifier.
# Returns:
# - None.
# Raises:
# - ReceiptExpenseNotFoundError when the expense does not exist for the user.
def validate_receipt_expense_link(
    db_session: Session,
    expense_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    try:
        expenses_repository.get_expense_by_id(
            db_session=db_session,
            expense_id=expense_id,
            user_id=user_id,
        )
    except ExpenseNotFoundError as error:
        raise ReceiptExpenseNotFoundError() from error


# Updates an existing receipt owned by the authenticated user.
# This function exists to apply receipt update business rules before persistence.
# Parameters:
# - db_session: active SQLAlchemy session.
# - receipt_id: receipt identifier.
# - receipt_data: validated partial receipt update data.
# - user_id: authenticated user identifier.
# Returns:
# - ReceiptResponse schema containing the updated receipt.
def update_receipt(
    db_session: Session,
    receipt_id: uuid.UUID,
    receipt_data: ReceiptUpdate,
    user_id: uuid.UUID,
) -> ReceiptResponse:
    if "expense_id" in receipt_data.model_fields_set and receipt_data.expense_id is not None:
        validate_receipt_expense_link(
            db_session=db_session,
            expense_id=receipt_data.expense_id,
            user_id=user_id,
        )

    receipt = receipt_repository.update_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        receipt_data=receipt_data,
        user_id=user_id,
    )

    return map_receipt_to_response(receipt)


# Deletes a receipt and its stored file for the authenticated user.
# This function exists to coordinate database deletion
# with receipt file cleanup across local or remote storage.
# Parameters:
# - db_session: active SQLAlchemy session.
# - receipt_id: receipt identifier.
# - user_id: authenticated user identifier.
# Returns:
# - None.
# Raises:
# - ReceiptNotFoundError when the receipt does not belong to the user.
# - ReceiptFileStorageError when the stored receipt file cannot be removed.
def delete_receipt(
    db_session: Session,
    receipt_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    receipt = receipt_repository.get_receipt_by_id(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    try:
        receipt_repository.delete_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            user_id=user_id,
            commit=False,
        )

        if receipt.storage_path:
            receipt_storage_service.delete_receipt_file(
                storage_path=receipt.storage_path,
            )

        db_session.commit()
    except Exception:
        db_session.rollback()
        raise