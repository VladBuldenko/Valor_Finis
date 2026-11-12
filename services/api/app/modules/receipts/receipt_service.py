import logging
import uuid

from pydantic import ValidationError
from sqlalchemy.orm import Session
from fastapi import UploadFile

from app.modules.receipts import (
    receipt_ocr_service,
    receipt_parser_service,
    receipt_repository,
    receipt_storage_service,
    receipt_storage_service,
)
from app.modules.receipts.receipt_errors import (
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


logger = logging.getLogger(__name__)


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
    # The row is locked for the status check AND the move to "processing"
    # (committed together below), so two simultaneous process requests for
    # one receipt cannot both pass the check: the second waits, then sees
    # "processing" and is rejected instead of running OCR twice.
    receipt = receipt_repository.get_receipt_by_id_for_update(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    if receipt.status not in PROCESSABLE_RECEIPT_STATUSES:
        raise ReceiptProcessingNotAllowedError()

    storage_path = receipt.storage_path

    if not storage_path:
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
        # storage_path is client-writable, so OCR only ever reads a file
        # inside this user's own storage area; any other path is treated
        # exactly like a missing file (failed + "Receipt file not found").
        if not receipt_storage_service.is_receipt_storage_path_owned_by(
            storage_path=storage_path,
            user_id=user_id,
        ):
            raise ReceiptOcrFileNotFoundError()

        extracted_text = receipt_ocr_service.extract_receipt_text(
            storage_path=storage_path,
        )

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
    except Exception:
        # Any failure after "processing" was committed (OCR errors, but also
        # a result the database refuses) must leave the receipt "failed",
        # the only non-processable state a retry can start from. Otherwise
        # it would stay "processing" with no way forward.
        db_session.rollback()

        try:
            receipt_repository.update_receipt(
                db_session=db_session,
                receipt_id=receipt_id,
                receipt_data=ReceiptUpdate(
                    status="failed",
                ),
                user_id=user_id,
            )
        except Exception:
            db_session.rollback()
            logger.error("receipt_processing_failed_state_not_saved")

        raise

    return map_receipt_to_response(processed_receipt)

# Confirms a processed receipt and creates a linked expense, optionally
# linked to an Account.
# This function exists to atomically convert verified receipt data
# into an expense and prevent partial database writes.
#
# Serialization (VF-017I): the receipt row is locked FIRST
# (get_receipt_by_id_for_update) and only then checked for
# confirmability, so a concurrent second confirmation of the same receipt
# waits for this transaction, re-reads the committed row, and is rejected
# as already confirmed -- never two Expenses, never two Account debits.
#
# Account linkage is passed straight through ExpenseCreate.account_id;
# expenses_service.create_expense stays the sole authority on Account
# ownership, archived status, exact currency match, Account row locking,
# and the debit AccountTransaction projection. Lock order is therefore
# Receipt -> Account (create_expense resolves FX before locking the
# Account, so no Account lock is held across FX network I/O).
#
# Atomicity: create_expense(commit=False) and update_receipt(commit=False)
# only flush; the single commit below covers the Expense, its optional
# AccountTransaction, and the receipt update. Any failure rolls all of
# them back and releases both locks.
# Parameters:
# - db_session: active SQLAlchemy session.
# - receipt_id: receipt identifier.
# - confirmation_data: optional user corrections for OCR-detected values,
#   plus an optional account_id for the created Expense.
# - user_id: authenticated user identifier.
# Returns:
# - ReceiptConfirmResponse containing the confirmed receipt
#   and created expense (with its derived account_id).
# Raises:
# - ReceiptNotFoundError when the receipt does not belong to the user.
# - ReceiptAlreadyConfirmedError when the receipt was already confirmed.
# - ReceiptConfirmationNotAllowedError when the receipt is not processed.
# - ReceiptConfirmationDataMissingError when required expense data is missing.
# - Any error raised by expenses_service.create_expense (e.g.
#   AccountNotFoundError, AccountArchivedError,
#   ExpenseAccountCurrencyMismatchError, CategoryNotFoundError, FX
#   errors), after rolling back.
def confirm_receipt(
    db_session: Session,
    receipt_id: uuid.UUID,
    confirmation_data: ReceiptConfirmRequest,
    user_id: uuid.UUID,
) -> ReceiptConfirmResponse:
    receipt = receipt_repository.get_receipt_by_id_for_update(
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

    try:
        expense_data = ExpenseCreate(
            category_id=confirmation_data.category_id,
            title=title,
            amount=amount,
            currency=currency,
            expense_date=expense_date,
            description=confirmation_data.description,
            source="receipt",
            account_id=confirmation_data.account_id,
        )
    except ValidationError as error:
        # A stored detected value the Expense rules refuse (for example a
        # malformed currency written through PATCH) is not usable data: the
        # user is asked to supply it, instead of the request failing as a 500.
        raise ReceiptConfirmationDataMissingError() from error

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
            # storage_path is client-writable: only a file inside this
            # user's own storage area is ever removed. A foreign or
            # out-of-area path is left untouched; the receipt row is still
            # deleted.
            if receipt_storage_service.is_receipt_storage_path_owned_by(
                storage_path=receipt.storage_path,
                user_id=user_id,
            ):
                receipt_storage_service.delete_receipt_file(
                    storage_path=receipt.storage_path,
                )
            else:
                logger.warning(
                    "receipt_delete_skipped_foreign_storage_path"
                )

        db_session.commit()
    except Exception:
        db_session.rollback()
        raise