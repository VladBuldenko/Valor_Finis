import uuid

from sqlalchemy.orm import Session

from app.modules.expenses.expenses_errors import ExpenseNotFoundError
from app.modules.expenses import expenses_repository
from app.modules.receipts import receipt_repository
from app.modules.receipts.receipt_errors import ReceiptExpenseNotFoundError
from app.modules.receipts.receipt_models import ReceiptModel
from app.modules.receipts.receipt_schemas import (
    ReceiptCreate,
    ReceiptResponse,
    ReceiptUpdate,
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