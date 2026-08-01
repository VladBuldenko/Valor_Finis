from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.db.database_session import get_db_session
from app.modules.auth.auth_dependencies import get_current_user
from app.modules.auth.auth_schemas import CurrentUser
from app.modules.receipts import receipt_service
from app.modules.receipts.receipt_errors import (
    ReceiptExpenseNotFoundError,
    ReceiptFileEmptyError,
    ReceiptFileStorageError,
    ReceiptFileTooLargeError,
    ReceiptFileTypeNotAllowedError,
    ReceiptNotFoundError,
    ReceiptOcrFileNotFoundError,
    ReceiptOcrProcessingError,
    ReceiptProcessingNotAllowedError,
    ReceiptAlreadyConfirmedError,
    ReceiptConfirmationDataMissingError,
    ReceiptConfirmationNotAllowedError,
)
from app.modules.receipts.receipt_schemas import (
    ReceiptCreate,
    ReceiptResponse,
    ReceiptUpdate,
    ReceiptConfirmRequest,
    ReceiptConfirmResponse,
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
# - HTTPException 422 when the uploaded file is empty.
# - HTTPException 413 when the uploaded file exceeds the size limit.
# - HTTPException 415 when the uploaded file type is unsupported.
# - HTTPException 500 when the file cannot be stored.
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
    try:
        return receipt_service.upload_receipt(
            db_session=db_session,
            uploaded_file=file,
            user_id=current_user.id,
        )
    except ReceiptFileEmptyError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Receipt file is empty.",
        ) from error
    except ReceiptFileTooLargeError as error:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Receipt file is too large.",
        ) from error
    except ReceiptFileTypeNotAllowedError as error:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Receipt file type is not supported.",
        ) from error
    except ReceiptFileStorageError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Receipt file could not be stored.",
        ) from error

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
# - HTTPException 404 when the receipt or stored file cannot be found.
# - HTTPException 409 when receipt processing is not allowed.
# - HTTPException 422 when OCR processing fails.
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
    try:
        return receipt_service.process_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            user_id=current_user.id,
        )
    except ReceiptNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt not found.",
        ) from error
    except ReceiptOcrFileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt file not found.",
        ) from error
    except ReceiptProcessingNotAllowedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Receipt cannot be processed in its current status.",
        ) from error
    except ReceiptOcrProcessingError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Receipt OCR processing failed.",
        ) from error
    
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
# - HTTPException 404 when the receipt cannot be found.
# - HTTPException 409 when confirmation is not allowed.
# - HTTPException 422 when required confirmation data is missing.
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
    try:
        return receipt_service.confirm_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            confirmation_data=confirmation_data,
            user_id=current_user.id,
        )
    except ReceiptNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt not found.",
        ) from error
    except ReceiptAlreadyConfirmedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Receipt has already been confirmed.",
        ) from error
    except ReceiptConfirmationNotAllowedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Receipt cannot be confirmed in its current status.",
        ) from error
    except ReceiptConfirmationDataMissingError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Required receipt confirmation data is missing.",
        ) from error

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