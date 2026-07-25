from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.receipts import receipt_service
from app.modules.receipts.receipt_errors import (
    ReceiptExpenseNotFoundError,
    ReceiptNotFoundError,
)
from app.modules.receipts.receipt_schemas import (
    ReceiptCreate,
    ReceiptResponse,
    ReceiptUpdate,
)


router = APIRouter(
    prefix="/receipts",
    tags=["Receipts"],
)


# Creates a new receipt through the API.
# This function exists to receive validated HTTP input
# and delegate receipt creation to the service layer.
# Parameters:
# - receipt_data: validated request body containing receipt metadata.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - ReceiptResponse containing the saved receipt.
@router.post(
    "",
    response_model=ReceiptResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_receipt(
    receipt_data: ReceiptCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> ReceiptResponse:
    return receipt_service.create_receipt(
        db_session=db_session,
        receipt_data=receipt_data,
        user_id=current_user.id,
    )


# Returns all receipts owned by the authenticated user.
# This function exists to expose user-scoped receipt data through the API.
# Parameters:
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - List of ReceiptResponse objects.
@router.get(
    "",
    response_model=list[ReceiptResponse],
)
def get_receipts(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> list[ReceiptResponse]:
    return receipt_service.get_receipts(
        db_session=db_session,
        user_id=current_user.id,
    )


# Returns a single receipt owned by the authenticated user.
# This function exists to expose one receipt through the API
# while preserving user data isolation.
# Parameters:
# - receipt_id: requested receipt identifier from the URL path.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - ReceiptResponse object.
# Raises:
# - HTTPException 404 when the receipt does not exist or belongs to another user.
@router.get(
    "/{receipt_id}",
    response_model=ReceiptResponse,
)
def get_receipt_by_id(
    receipt_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> ReceiptResponse:
    try:
        return receipt_service.get_receipt_by_id(
            db_session=db_session,
            receipt_id=receipt_id,
            user_id=current_user.id,
        )
    except ReceiptNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt not found.",
        ) from error


# Updates a receipt owned by the authenticated user.
# This function exists to receive partial receipt updates
# and delegate business rules to the service layer.
# Parameters:
# - receipt_id: requested receipt identifier from the URL path.
# - receipt_data: validated partial receipt update data.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - ReceiptResponse containing the updated receipt.
# Raises:
# - HTTPException 404 when the receipt does not exist or belongs to another user.
# - HTTPException 404 when the linked expense does not exist or belongs to another user.
@router.patch(
    "/{receipt_id}",
    response_model=ReceiptResponse,
)
def update_receipt(
    receipt_id: UUID,
    receipt_data: ReceiptUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> ReceiptResponse:
    try:
        return receipt_service.update_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            receipt_data=receipt_data,
            user_id=current_user.id,
        )
    except ReceiptNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt not found.",
        ) from error
    except ReceiptExpenseNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Linked expense not found.",
        ) from error


# Deletes a receipt owned by the authenticated user.
# This function exists to remove receipt metadata through the API
# while preserving user data isolation.
# Parameters:
# - receipt_id: requested receipt identifier from the URL path.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - None.
# Raises:
# - HTTPException 404 when the receipt does not exist or belongs to another user.
@router.delete(
    "/{receipt_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_receipt(
    receipt_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> None:
    try:
        receipt_service.delete_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            user_id=current_user.id,
        )
    except ReceiptNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt not found.",
        ) from error