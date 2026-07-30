import uuid

from sqlalchemy.orm import Session
from fastapi import UploadFile

from app.modules.expenses.expenses_errors import ExpenseNotFoundError
from app.modules.expenses import expenses_repository
from app.modules.receipts import (
    receipt_ocr_service,
    receipt_repository,
    receipt_storage_service,
)
from app.modules.receipts.receipt_errors import (
    ReceiptExpenseNotFoundError,
    ReceiptFileStorageError,
    ReceiptOcrFileNotFoundError,
    ReceiptOcrProcessingError,
    ReceiptProcessingNotAllowedError,
)
from app.modules.receipts.receipt_models import ReceiptModel
from app.modules.receipts.receipt_schemas import (
    ReceiptCreate,
    ReceiptResponse,
    ReceiptUpdate,
)

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

    processed_receipt = receipt_repository.update_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        receipt_data=ReceiptUpdate(
            status="processed",
            ocr_text=extracted_text,
        ),
        user_id=user_id,
    )

    return map_receipt_to_response(processed_receipt)

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


# Deletes a receipt owned by the authenticated user.
# This function exists to remove receipt metadata through the business layer.
# Parameters:
# - db_session: active SQLAlchemy session.
# - receipt_id: receipt identifier.
# - user_id: authenticated user identifier.
# Returns:
# - None.
def delete_receipt(
    db_session: Session,
    receipt_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    receipt_repository.delete_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )