import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.receipts.receipt_errors import ReceiptNotFoundError
from app.modules.receipts.receipt_models import ReceiptModel
from app.modules.receipts.receipt_schemas import ReceiptCreate, ReceiptUpdate


# Creates a new receipt in the database.
# This function exists to persist receipt metadata for the authenticated user.
# Parameters:
# - db_session: active SQLAlchemy session.
# - receipt_data: validated receipt creation data.
# - user_id: authenticated user identifier.
# Returns:
# - Saved ReceiptModel instance.
def create_receipt(
    db_session: Session,
    receipt_data: ReceiptCreate,
    user_id: uuid.UUID,
) -> ReceiptModel:
    receipt = ReceiptModel(
        user_id=user_id,
        file_url=receipt_data.file_url,
        storage_path=receipt_data.storage_path,
        status="uploaded",
    )

    db_session.add(receipt)
    db_session.commit()
    db_session.refresh(receipt)

    return receipt


# Returns all receipts that belong to the authenticated user.
# This function exists to keep receipt data isolated per user.
# Parameters:
# - db_session: active SQLAlchemy session.
# - user_id: authenticated user identifier.
# Returns:
# - List of ReceiptModel instances owned by the user.
def get_receipts(
    db_session: Session,
    user_id: uuid.UUID,
) -> list[ReceiptModel]:
    return (
        db_session.query(ReceiptModel)
        .filter(ReceiptModel.user_id == user_id)
        .order_by(ReceiptModel.created_at.desc())
        .all()
    )


# Returns a single receipt by id and user id.
# This function exists to enforce receipt ownership at the database access layer.
# Parameters:
# - db_session: active SQLAlchemy session.
# - receipt_id: requested receipt identifier.
# - user_id: authenticated user identifier.
# Returns:
# - ReceiptModel instance owned by the user.
# Raises:
# - ReceiptNotFoundError when the receipt does not exist or belongs to another user.
def get_receipt_by_id(
    db_session: Session,
    receipt_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ReceiptModel:
    receipt: Optional[ReceiptModel] = (
        db_session.query(ReceiptModel)
        .filter(
            ReceiptModel.id == receipt_id,
            ReceiptModel.user_id == user_id,
        )
        .first()
    )

    if receipt is None:
        raise ReceiptNotFoundError()

    return receipt


# Updates an existing receipt owned by the authenticated user.
# This function exists to persist OCR results, status changes, or expense linkage.
# Parameters:
# - db_session: active SQLAlchemy session.
# - receipt_id: receipt identifier.
# - receipt_data: validated partial receipt update data.
# - user_id: authenticated user identifier.
# Returns:
# - Updated ReceiptModel instance.
# Raises:
# - ReceiptNotFoundError when the receipt does not exist or belongs to another user.
def update_receipt(
    db_session: Session,
    receipt_id: uuid.UUID,
    receipt_data: ReceiptUpdate,
    user_id: uuid.UUID,
) -> ReceiptModel:
    receipt = get_receipt_by_id(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    update_data = receipt_data.model_dump(exclude_unset=True)

    for field_name, field_value in update_data.items():
        setattr(receipt, field_name, field_value)

    db_session.commit()
    db_session.refresh(receipt)

    return receipt


# Deletes a receipt owned by the authenticated user.
# This function exists to remove receipt metadata while preserving user data isolation.
# Parameters:
# - db_session: active SQLAlchemy session.
# - receipt_id: receipt identifier.
# - user_id: authenticated user identifier.
# Returns:
# - None.
# Raises:
# - ReceiptNotFoundError when the receipt does not exist or belongs to another user.
def delete_receipt(
    db_session: Session,
    receipt_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    receipt = get_receipt_by_id(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    db_session.delete(receipt)
    db_session.commit()