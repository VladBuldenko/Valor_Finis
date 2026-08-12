import uuid
from pathlib import Path
from typing import BinaryIO, Dict, Optional, Set, Tuple
from urllib.parse import quote

import httpx
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

SUPABASE_STORAGE_SCHEME = "supabase://"

SUPABASE_STORAGE_TIMEOUT_SECONDS = 10.0


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
# into application memory when local storage is used.
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
            chunk = source_file.read(
                FILE_READ_CHUNK_SIZE,
            )

            if not chunk:
                break

            total_size += len(chunk)

            if total_size > max_file_size_bytes:
                raise ReceiptFileTooLargeError()

            destination_file.write(chunk)

    if total_size == 0:
        raise ReceiptFileEmptyError()

    return total_size


# Reads receipt content in validated chunks.
# This function exists to validate receipt size before sending
# the file to remote storage.
# Parameters:
# - source_file: binary stream containing uploaded file data.
# - max_file_size_bytes: maximum allowed receipt file size.
# Returns:
# - Complete validated receipt file content.
# Raises:
# - ReceiptFileEmptyError when the uploaded file contains no data.
# - ReceiptFileTooLargeError when the file exceeds the configured limit.
def read_receipt_file_content(
    source_file: BinaryIO,
    max_file_size_bytes: int,
) -> bytes:
    total_size = 0
    chunks = []

    while True:
        chunk = source_file.read(
            FILE_READ_CHUNK_SIZE,
        )

        if not chunk:
            break

        total_size += len(chunk)

        if total_size > max_file_size_bytes:
            raise ReceiptFileTooLargeError()

        chunks.append(chunk)

    if total_size == 0:
        raise ReceiptFileEmptyError()

    return b"".join(chunks)


# Removes a partially stored local receipt file without raising another error.
# This function exists to clean up incomplete files after validation
# or filesystem failures.
# Parameters:
# - file_path: path of the partially stored file.
# Returns:
# - None.
def remove_partial_file(
    file_path: Path,
) -> None:
    try:
        file_path.unlink(
            missing_ok=True,
        )
    except OSError:
        pass


# Returns configured Supabase Storage server credentials.
# This function exists to keep remote storage configuration access
# isolated from upload and delete operations.
# Parameters:
# - None.
# Returns:
# - Tuple containing normalized Supabase URL and secret key.
# Raises:
# - ReceiptFileStorageError when required storage credentials are missing.
def get_supabase_storage_credentials() -> Tuple[str, str]:
    supabase_url = settings.supabase_url
    supabase_secret_key = settings.supabase_secret_key

    if not supabase_url or not supabase_secret_key:
        raise ReceiptFileStorageError()

    return (
        supabase_url.rstrip("/"),
        supabase_secret_key,
    )


# Builds the internal path stored for a Supabase receipt object.
# This function exists to preserve the storage provider and bucket
# together with the object path.
# Parameters:
# - bucket: Supabase Storage bucket name.
# - object_path: object path inside the bucket.
# Returns:
# - Internal Supabase storage path.
def build_supabase_storage_path(
    bucket: str,
    object_path: str,
) -> str:
    return (
        f"{SUPABASE_STORAGE_SCHEME}"
        f"{bucket}/{object_path}"
    )


# Parses an internal Supabase storage path.
# This function exists to resolve the bucket and object path
# independently from the currently configured storage driver.
# Parameters:
# - storage_path: stored receipt path.
# Returns:
# - Tuple containing bucket and object path when the path belongs
#   to Supabase Storage, otherwise None.
# Raises:
# - ReceiptFileStorageError when a Supabase path is malformed.
def parse_supabase_storage_path(
    storage_path: str,
) -> Optional[Tuple[str, str]]:
    if not storage_path.startswith(
        SUPABASE_STORAGE_SCHEME,
    ):
        return None

    path_without_scheme = storage_path[
        len(SUPABASE_STORAGE_SCHEME):
    ]

    bucket, separator, object_path = (
        path_without_scheme.partition("/")
    )

    if (
        not separator
        or not bucket
        or not object_path
    ):
        raise ReceiptFileStorageError()

    return (
        bucket,
        object_path,
    )


# Saves an uploaded receipt file in local storage.
# This function exists to preserve the existing local development
# storage implementation separately from remote storage.
# Parameters:
# - uploaded_file: receipt file received through FastAPI.
# - user_id: authenticated user identifier.
# - file_extension: validated receipt file extension.
# Returns:
# - Local internal path of the stored receipt file.
# Raises:
# - ReceiptFileEmptyError for empty files.
# - ReceiptFileTooLargeError for oversized files.
# - ReceiptFileStorageError for unexpected filesystem failures.
def save_receipt_file_locally(
    uploaded_file: UploadFile,
    user_id: uuid.UUID,
    file_extension: str,
) -> str:
    upload_root = Path(
        settings.receipt_upload_dir,
    )

    user_upload_directory = (
        upload_root / str(user_id)
    )

    stored_filename = (
        f"{uuid.uuid4()}{file_extension}"
    )

    destination_path = (
        user_upload_directory / stored_filename
    )

    try:
        user_upload_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        uploaded_file.file.seek(0)

        write_receipt_file(
            source_file=uploaded_file.file,
            destination_path=destination_path,
            max_file_size_bytes=(
                settings.receipt_max_file_size_bytes
            ),
        )
    except (
        ReceiptFileEmptyError,
        ReceiptFileTooLargeError,
    ):
        remove_partial_file(
            destination_path,
        )
        raise
    except OSError as error:
        remove_partial_file(
            destination_path,
        )

        raise ReceiptFileStorageError() from error

    return destination_path.as_posix()


# Saves an uploaded receipt file in Supabase Storage.
# This function exists to persist production receipt files
# outside the application container filesystem.
# Parameters:
# - uploaded_file: receipt file received through FastAPI.
# - user_id: authenticated user identifier.
# - file_extension: validated receipt file extension.
# Returns:
# - Internal Supabase storage path.
# Raises:
# - ReceiptFileEmptyError for empty files.
# - ReceiptFileTooLargeError for oversized files.
# - ReceiptFileStorageError when Supabase Storage cannot save the file.
def save_receipt_file_to_supabase(
    uploaded_file: UploadFile,
    user_id: uuid.UUID,
    file_extension: str,
) -> str:
    supabase_url, supabase_secret_key = (
        get_supabase_storage_credentials()
    )

    bucket = settings.receipt_storage_bucket

    if not bucket:
        raise ReceiptFileStorageError()

    stored_filename = (
        f"{uuid.uuid4()}{file_extension}"
    )

    object_path = (
        f"{user_id}/{stored_filename}"
    )

    encoded_bucket = quote(
        bucket,
        safe="",
    )

    encoded_object_path = quote(
        object_path,
        safe="/",
    )

    upload_url = (
        f"{supabase_url}"
        f"/storage/v1/object/"
        f"{encoded_bucket}/"
        f"{encoded_object_path}"
    )

    content_type = uploaded_file.content_type

    if content_type is None:
        raise ReceiptFileTypeNotAllowedError()

    normalized_content_type = (
        content_type.strip().lower()
    )

    try:
        uploaded_file.file.seek(0)

        file_content = read_receipt_file_content(
            source_file=uploaded_file.file,
            max_file_size_bytes=(
                settings.receipt_max_file_size_bytes
            ),
        )
    except (
        ReceiptFileEmptyError,
        ReceiptFileTooLargeError,
    ):
        raise
    except OSError as error:
        raise ReceiptFileStorageError() from error

    try:
        response = httpx.post(
            upload_url,
            headers={
                "apikey": supabase_secret_key,
                "Content-Type": normalized_content_type,
                "x-upsert": "false",
            },
            content=file_content,
            timeout=SUPABASE_STORAGE_TIMEOUT_SECONDS,
        )

        response.raise_for_status()
    except httpx.HTTPError as error:
        raise ReceiptFileStorageError() from error

    return build_supabase_storage_path(
        bucket=bucket,
        object_path=object_path,
    )


# Saves an uploaded receipt file using the configured storage driver.
# This function exists as the storage abstraction used by receipt
# business logic.
# Parameters:
# - uploaded_file: receipt file received through FastAPI.
# - user_id: authenticated user identifier.
# Returns:
# - Internal path of the stored receipt file.
# Raises:
# - ReceiptFileTypeNotAllowedError for unsupported files.
# - ReceiptFileEmptyError for empty files.
# - ReceiptFileTooLargeError for oversized files.
# - ReceiptFileStorageError when storage fails.
def save_receipt_file(
    uploaded_file: UploadFile,
    user_id: uuid.UUID,
) -> str:
    file_extension = validate_receipt_file_type(
        filename=uploaded_file.filename,
        content_type=uploaded_file.content_type,
    )

    if (
        settings.receipt_storage_driver
        == "supabase"
    ):
        return save_receipt_file_to_supabase(
            uploaded_file=uploaded_file,
            user_id=user_id,
            file_extension=file_extension,
        )

    return save_receipt_file_locally(
        uploaded_file=uploaded_file,
        user_id=user_id,
        file_extension=file_extension,
    )


# Deletes a receipt file from local storage.
# This function exists to isolate filesystem deletion
# from the generic storage dispatcher.
# Parameters:
# - storage_path: local receipt file path.
# Returns:
# - None.
# Raises:
# - ReceiptFileStorageError when the file cannot be removed.
def delete_local_receipt_file(
    storage_path: str,
) -> None:
    file_path = Path(
        storage_path,
    )

    try:
        file_path.unlink(
            missing_ok=True,
        )
    except OSError as error:
        raise ReceiptFileStorageError() from error


# Deletes a receipt file from Supabase Storage.
# This function exists to remove remote receipt objects
# through the Supabase Storage API.
# Parameters:
# - bucket: Supabase Storage bucket name.
# - object_path: object path inside the bucket.
# Returns:
# - None.
# Raises:
# - ReceiptFileStorageError when Supabase Storage deletion fails.
def delete_supabase_receipt_file(
    bucket: str,
    object_path: str,
) -> None:
    supabase_url, supabase_secret_key = (
        get_supabase_storage_credentials()
    )

    encoded_bucket = quote(
        bucket,
        safe="",
    )

    delete_url = (
        f"{supabase_url}"
        f"/storage/v1/object/"
        f"{encoded_bucket}"
    )

    try:
        response = httpx.request(
            method="DELETE",
            url=delete_url,
            headers={
                "apikey": supabase_secret_key,
                "Content-Type": "application/json",
            },
            json={
                "prefixes": [
                    object_path,
                ],
            },
            timeout=SUPABASE_STORAGE_TIMEOUT_SECONDS,
        )

        response.raise_for_status()
    except httpx.HTTPError as error:
        raise ReceiptFileStorageError() from error


# Deletes a receipt file using the provider encoded in its storage path.
# This function exists to keep old local receipt paths usable after
# the configured storage driver changes to Supabase.
# Parameters:
# - storage_path: internal path of the stored receipt file.
# Returns:
# - None.
# Raises:
# - ReceiptFileStorageError when storage deletion fails.
def delete_receipt_file(
    storage_path: str,
) -> None:
    supabase_path = parse_supabase_storage_path(
        storage_path=storage_path,
    )

    if supabase_path is not None:
        bucket, object_path = supabase_path

        delete_supabase_receipt_file(
            bucket=bucket,
            object_path=object_path,
        )

        return

    delete_local_receipt_file(
        storage_path=storage_path,
    )