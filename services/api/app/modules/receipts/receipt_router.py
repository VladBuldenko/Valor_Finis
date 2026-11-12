from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.receipts import receipt_service
from app.modules.receipts.receipt_schemas import (
    ReceiptConfirmRequest,
    ReceiptConfirmResponse,
    ReceiptResponse,
)


router = APIRouter(
    prefix="/receipts",
    tags=["Receipts"],
)

# Receipt lifecycle and financial references are server-owned (VF-MVP-CORE-005A).
# A receipt is created only by POST /receipts/upload, moved forward only by
# POST /receipts/{id}/process and POST /receipts/{id}/confirm, and linked to its
# Expense only by the atomic confirmation. There is deliberately NO public create-
# from-metadata or PATCH route: a client-writable status, expense_id, OCR result or
# file location would let a caller forge states, bypass OCR and confirmation, or
# reset a confirmed receipt and confirm it again (a second Expense and Account debit).
# Calls to those two paths answer 405.


# Uploads a receipt file and creates its database record.
# This function exists to receive multipart receipt uploads
# and delegate validation, storage, and persistence to the service layer.
# Parameters:
# - file: uploaded receipt image or PDF.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - ReceiptResponse containing the created receipt.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.post(
    "/upload",
    response_model=ReceiptResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_receipt(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> ReceiptResponse:
    return receipt_service.upload_receipt(
        db_session=db_session,
        uploaded_file=file,
        user_id=current_user.id,
    )


# Processes an uploaded receipt through OCR.
# This function exists to start receipt text extraction
# and expose the processing result through the API.
# Parameters:
# - receipt_id: receipt identifier from the URL path.
# - current_user: authenticated user resolved from request authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - ReceiptResponse containing the processed receipt.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.post(
    "/{receipt_id}/process",
    response_model=ReceiptResponse,
    status_code=status.HTTP_200_OK,
)
def process_receipt(
    receipt_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> ReceiptResponse:
    return receipt_service.process_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=current_user.id,
    )


# Confirms a processed receipt and creates a linked expense.
# This function exists to convert verified receipt data
# into a persistent expense through one atomic operation.
# Parameters:
# - receipt_id: receipt identifier from the URL path.
# - confirmation_data: optional corrections for OCR-detected values.
# - current_user: authenticated user resolved from authentication data.
# - db_session: active SQLAlchemy session injected by FastAPI.
# Returns:
# - ReceiptConfirmResponse containing the receipt and created expense.
# Raises:
# - Domain exceptions propagated to the global exception handlers.
@router.post(
    "/{receipt_id}/confirm",
    response_model=ReceiptConfirmResponse,
    status_code=status.HTTP_200_OK,
)
def confirm_receipt(
    receipt_id: UUID,
    confirmation_data: ReceiptConfirmRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> ReceiptConfirmResponse:
    return receipt_service.confirm_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        confirmation_data=confirmation_data,
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
    status_code=status.HTTP_200_OK,
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
# - Domain exceptions propagated to the global exception handlers.
@router.get(
    "/{receipt_id}",
    response_model=ReceiptResponse,
    status_code=status.HTTP_200_OK,
)
def get_receipt_by_id(
    receipt_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> ReceiptResponse:
    return receipt_service.get_receipt_by_id(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=current_user.id,
    )


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
# - Domain exceptions propagated to the global exception handlers.
@router.delete(
    "/{receipt_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_receipt(
    receipt_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> None:
    receipt_service.delete_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=current_user.id,
    )