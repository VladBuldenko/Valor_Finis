import uuid
from pathlib import Path
from typing import BinaryIO, Dict, Optional, Set

from fastapi import UploadFile

from app.core.app_config import settings
from app.modules.receipts.receipt_errors import (
    ReceiptFileEmptyError,
    ReceiptFileStorageError,
    ReceiptFileTooLargeError,
    ReceiptFileTypeNotAllowedError,
)


ALLOWED_RECEIPT_FILE_TYPES: Dict[str, Set[str]] = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "application/pdf": {".pdf"},
}

FILE_READ_CHUNK_SIZE = 1024 * 1024


# Returns a validated lowercase extension for an uploaded receipt file.
# This function exists to ensure that the MIME type and file extension
# match one of the supported receipt formats.
# Parameters:
# - filename: original uploaded filename.
# - content_type: MIME type supplied for the uploaded file.
# Returns:
# - Validated lowercase file extension.
# Raises:
# - ReceiptFileTypeNotAllowedError when the file type is unsupported.
def validate_receipt_file_type(
    filename: Optional[str],
    content_type: Optional[str],
) -> str:
    if filename is None or content_type is None:
        raise ReceiptFileTypeNotAllowedError()

    normalized_content_type = content_type.strip().lower()
    file_extension = Path(filename).suffix.lower()

    allowed_extensions = ALLOWED_RECEIPT_FILE_TYPES.get(
        normalized_content_type,
    )

    if (
        allowed_extensions is None
        or file_extension not in allowed_extensions
    ):
        raise ReceiptFileTypeNotAllowedError()

    return file_extension


# Writes receipt content to the destination file in chunks.
# This function exists to avoid loading the complete uploaded file
# into application memory.
# Parameters:
# - source_file: binary stream containing uploaded file data.
# - destination_path: local path where the file must be stored.
# - max_file_size_bytes: maximum allowed receipt file size.
# Returns:
# - Total number of bytes written.
# Raises:
# - ReceiptFileEmptyError when the uploaded file contains no data.
# - ReceiptFileTooLargeError when the file exceeds the configured limit.
def write_receipt_file(
    source_file: BinaryIO,
    destination_path: Path,
    max_file_size_bytes: int,
) -> int:
    total_size = 0

    with destination_path.open("wb") as destination_file:
        while True:
            chunk = source_file.read(FILE_READ_CHUNK_SIZE)

            if not chunk:
                break

            total_size += len(chunk)

            if total_size > max_file_size_bytes:
                raise ReceiptFileTooLargeError()

            destination_file.write(chunk)

    if total_size == 0:
        raise ReceiptFileEmptyError()

    return total_size


# Removes a partially stored receipt file without raising another error.
# This function exists to clean up incomplete files after validation
# or filesystem failures.
# Parameters:
# - file_path: path of the partially stored file.
# Returns:
# - None.
def remove_partial_file(file_path: Path) -> None:
    try:
        file_path.unlink(missing_ok=True)
    except OSError:
        pass


# Saves an uploaded receipt file in local storage.
# This function exists to validate and persist receipt files while keeping
# filesystem operations outside routers and repositories.
# Parameters:
# - uploaded_file: receipt file received through FastAPI.
# - user_id: authenticated user identifier.
# Returns:
# - Internal path of the stored receipt file.
# Raises:
# - ReceiptFileTypeNotAllowedError for unsupported files.
# - ReceiptFileEmptyError for empty files.
# - ReceiptFileTooLargeError for oversized files.
# - ReceiptFileStorageError for unexpected filesystem failures.
def save_receipt_file(
    uploaded_file: UploadFile,
    user_id: uuid.UUID,
) -> str:
    file_extension = validate_receipt_file_type(
        filename=uploaded_file.filename,
        content_type=uploaded_file.content_type,
    )

    upload_root = Path(settings.receipt_upload_dir)
    user_upload_directory = upload_root / str(user_id)

    stored_filename = f"{uuid.uuid4()}{file_extension}"
    destination_path = user_upload_directory / stored_filename

    try:
        user_upload_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        uploaded_file.file.seek(0)

        write_receipt_file(
            source_file=uploaded_file.file,
            destination_path=destination_path,
            max_file_size_bytes=settings.receipt_max_file_size_bytes,
        )
    except (
        ReceiptFileEmptyError,
        ReceiptFileTooLargeError,
    ):
        remove_partial_file(destination_path)
        raise
    except OSError as error:
        remove_partial_file(destination_path)
        raise ReceiptFileStorageError() from error

    return destination_path.as_posix()


# Deletes a receipt file from local storage.
# This function exists to remove stored files when a later database
# operation fails or explicit cleanup is required.
# Parameters:
# - storage_path: internal path of the stored receipt file.
# Returns:
# - None.
# Raises:
# - ReceiptFileStorageError when the file cannot be removed.
def delete_receipt_file(storage_path: str) -> None:
    file_path = Path(storage_path)

    try:
        file_path.unlink(missing_ok=True)
    except OSError as error:
        raise ReceiptFileStorageError() from error