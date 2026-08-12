import uuid
from io import BytesIO
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock
import httpx

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.modules.receipts import receipt_storage_service
from app.modules.receipts.receipt_errors import (
    ReceiptFileEmptyError,
    ReceiptFileStorageError,
    ReceiptFileTooLargeError,
    ReceiptFileTypeNotAllowedError,
)


# Creates an UploadFile instance for receipt storage unit tests.
# This helper exists to build realistic in-memory file uploads
# without starting the FastAPI application.
# Parameters:
# - filename: original uploaded filename.
# - content_type: MIME type of the uploaded file.
# - content: binary file content.
# Returns:
# - UploadFile instance backed by an in-memory byte stream.
def build_upload_file(
    filename: str,
    content_type: str,
    content: bytes,
) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers(
            {
                "content-type": content_type,
            }
        ),
    )


# Verifies that supported receipt file types return normalized extensions.
# This test exists to confirm valid MIME type and extension combinations.
# Parameters:
# - filename: uploaded filename.
# - content_type: uploaded MIME type.
# - expected_extension: normalized extension expected from validation.
# Returns:
# - None.
@pytest.mark.parametrize(
    (
        "filename",
        "content_type",
        "expected_extension",
    ),
    [
        ("receipt.jpg", "image/jpeg", ".jpg"),
        ("receipt.jpeg", "image/jpeg", ".jpeg"),
        ("receipt.JPG", "image/jpeg", ".jpg"),
        ("receipt.png", "image/png", ".png"),
        ("receipt.pdf", "application/pdf", ".pdf"),
        ("receipt.PDF", " application/pdf ", ".pdf"),
    ],
)
def test_validate_receipt_file_type_accepts_supported_types(
    filename: str,
    content_type: str,
    expected_extension: str,
) -> None:
    result = receipt_storage_service.validate_receipt_file_type(
        filename=filename,
        content_type=content_type,
    )

    assert result == expected_extension


# Verifies that missing or unsupported file type data is rejected.
# This test exists to prevent invalid MIME type and extension combinations.
# Parameters:
# - filename: uploaded filename or None.
# - content_type: uploaded MIME type or None.
# Returns:
# - None.
@pytest.mark.parametrize(
    (
        "filename",
        "content_type",
    ),
    [
        (None, "image/jpeg"),
        ("receipt.jpg", None),
        ("receipt", "image/jpeg"),
        ("receipt.exe", "application/octet-stream"),
        ("receipt.png", "image/jpeg"),
        ("receipt.pdf", "image/png"),
        ("receipt.jpg", "application/pdf"),
    ],
)
def test_validate_receipt_file_type_rejects_unsupported_types(
    filename: Optional[str],
    content_type: Optional[str],
) -> None:
    with pytest.raises(ReceiptFileTypeNotAllowedError):
        receipt_storage_service.validate_receipt_file_type(
            filename=filename,
            content_type=content_type,
        )


# Verifies that binary receipt content is written to the destination.
# This test exists to confirm chunked file writing and byte counting.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# Returns:
# - None.
def test_write_receipt_file_writes_content(
    tmp_path: Path,
) -> None:
    file_content = b"receipt-image-content"
    source_file = BytesIO(file_content)
    destination_path = tmp_path / "receipt.jpg"

    result = receipt_storage_service.write_receipt_file(
        source_file=source_file,
        destination_path=destination_path,
        max_file_size_bytes=1024,
    )

    assert result == len(file_content)
    assert destination_path.exists()
    assert destination_path.read_bytes() == file_content


# Verifies that a zero-byte receipt file is rejected.
# This test exists to prevent empty files from being accepted as receipts.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# Returns:
# - None.
def test_write_receipt_file_rejects_empty_file(
    tmp_path: Path,
) -> None:
    destination_path = tmp_path / "empty-receipt.jpg"

    with pytest.raises(ReceiptFileEmptyError):
        receipt_storage_service.write_receipt_file(
            source_file=BytesIO(b""),
            destination_path=destination_path,
            max_file_size_bytes=1024,
        )


# Verifies that receipt content exceeding the configured limit is rejected.
# This test exists to prevent oversized files from being fully stored.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# Returns:
# - None.
def test_write_receipt_file_rejects_oversized_file(
    tmp_path: Path,
) -> None:
    destination_path = tmp_path / "large-receipt.jpg"

    with pytest.raises(ReceiptFileTooLargeError):
        receipt_storage_service.write_receipt_file(
            source_file=BytesIO(b"12345"),
            destination_path=destination_path,
            max_file_size_bytes=4,
        )


# Verifies that a valid uploaded receipt is stored in the user's directory.
# This test exists to confirm path generation, directory creation,
# safe filename generation, and file content persistence.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to override application settings.
# Returns:
# - None.
def test_save_receipt_file_stores_file_for_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    file_content = b"valid-receipt-image"

    uploaded_file = build_upload_file(
        filename="original-receipt.jpg",
        content_type="image/jpeg",
        content=file_content,
    )

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_upload_dir",
        str(tmp_path),
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_max_file_size_mb",
        1,
    )

    result = receipt_storage_service.save_receipt_file(
        uploaded_file=uploaded_file,
        user_id=user_id,
    )

    stored_path = Path(result)
    expected_user_directory = tmp_path / str(user_id)

    assert stored_path.exists()
    assert stored_path.parent == expected_user_directory
    assert stored_path.suffix == ".jpg"
    assert stored_path.name != uploaded_file.filename
    assert stored_path.read_bytes() == file_content


# Verifies that unsupported uploads are rejected before directory creation.
# This test exists to avoid creating filesystem data for invalid files.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to override application settings.
# Returns:
# - None.
def test_save_receipt_file_rejects_unsupported_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()

    uploaded_file = build_upload_file(
        filename="receipt.txt",
        content_type="text/plain",
        content=b"invalid receipt",
    )

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_upload_dir",
        str(tmp_path),
    )

    with pytest.raises(ReceiptFileTypeNotAllowedError):
        receipt_storage_service.save_receipt_file(
            uploaded_file=uploaded_file,
            user_id=user_id,
        )

    assert not (tmp_path / str(user_id)).exists()


# Verifies that an empty upload does not leave a partial file.
# This test exists to keep local storage clean after file validation failure.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to override application settings.
# Returns:
# - None.
def test_save_receipt_file_removes_empty_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()

    uploaded_file = build_upload_file(
        filename="empty-receipt.jpg",
        content_type="image/jpeg",
        content=b"",
    )

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_upload_dir",
        str(tmp_path),
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_max_file_size_mb",
        1,
    )

    with pytest.raises(ReceiptFileEmptyError):
        receipt_storage_service.save_receipt_file(
            uploaded_file=uploaded_file,
            user_id=user_id,
        )

    user_directory = tmp_path / str(user_id)

    assert user_directory.exists()
    assert list(user_directory.iterdir()) == []


# Verifies that an oversized upload does not leave a partial file.
# This test exists to remove incomplete files after size validation failure.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to override application settings.
# Returns:
# - None.
def test_save_receipt_file_removes_oversized_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()

    uploaded_file = build_upload_file(
        filename="large-receipt.jpg",
        content_type="image/jpeg",
        content=b"file-content",
    )

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_upload_dir",
        str(tmp_path),
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_max_file_size_mb",
        0,
    )

    with pytest.raises(ReceiptFileTooLargeError):
        receipt_storage_service.save_receipt_file(
            uploaded_file=uploaded_file,
            user_id=user_id,
        )

    user_directory = tmp_path / str(user_id)

    assert user_directory.exists()
    assert list(user_directory.iterdir()) == []


# Verifies that unexpected filesystem errors are converted into domain errors.
# This test exists to prevent raw OSError details from escaping the storage layer.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace filesystem writing.
# Returns:
# - None.
def test_save_receipt_file_wraps_filesystem_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()

    uploaded_file = build_upload_file(
        filename="receipt.jpg",
        content_type="image/jpeg",
        content=b"receipt-content",
    )

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_upload_dir",
        str(tmp_path),
    )

    write_receipt_file_mock = MagicMock(
        side_effect=OSError("Filesystem failure"),
    )

    monkeypatch.setattr(
        receipt_storage_service,
        "write_receipt_file",
        write_receipt_file_mock,
    )

    with pytest.raises(ReceiptFileStorageError) as error_info:
        receipt_storage_service.save_receipt_file(
            uploaded_file=uploaded_file,
            user_id=user_id,
        )

    assert isinstance(error_info.value.__cause__, OSError)

    write_receipt_file_mock.assert_called_once()


# Verifies that an existing receipt file is deleted.
# This test exists to support cleanup after database or business operation failures.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# Returns:
# - None.
def test_delete_receipt_file_removes_existing_file(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "receipt.jpg"
    file_path.write_bytes(b"receipt-content")

    receipt_storage_service.delete_receipt_file(
        storage_path=file_path.as_posix(),
    )

    assert not file_path.exists()


# Verifies that deleting a missing receipt file is safe.
# This test exists to make cleanup operations idempotent.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# Returns:
# - None.
def test_delete_receipt_file_allows_missing_file(
    tmp_path: Path,
) -> None:
    missing_file_path = tmp_path / "missing-receipt.jpg"

    result = receipt_storage_service.delete_receipt_file(
        storage_path=missing_file_path.as_posix(),
    )

    assert result is None


# Verifies that file deletion errors are converted into domain errors.
# This test exists to prevent raw filesystem exceptions from escaping
# the receipt storage layer.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace Path.unlink.
# Returns:
# - None.
def test_delete_receipt_file_wraps_filesystem_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "receipt.jpg"
    file_path.write_bytes(b"receipt-content")

    unlink_mock = MagicMock(
        side_effect=OSError("Permission denied"),
    )

    monkeypatch.setattr(
        Path,
        "unlink",
        unlink_mock,
    )

    with pytest.raises(ReceiptFileStorageError) as error_info:
        receipt_storage_service.delete_receipt_file(
            storage_path=file_path.as_posix(),
        )

    assert isinstance(error_info.value.__cause__, OSError)

    unlink_mock.assert_called_once_with(
        missing_ok=True,
    )

# Verifies that Supabase storage saves a valid receipt object.
# This test exists to confirm remote object path generation,
# request authentication, and receipt content upload.
# Parameters:
# - monkeypatch: pytest fixture used to override application settings
#   and the HTTP client.
# Returns:
# - None.
def test_save_receipt_file_uploads_file_to_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()

    uploaded_file = build_upload_file(
        filename="receipt.jpg",
        content_type="image/jpeg",
        content=b"receipt-content",
    )

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_storage_driver",
        "supabase",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "supabase_url",
        "https://example.supabase.co",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "supabase_secret_key",
        "test-secret-key",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_storage_bucket",
        "receipts",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_max_file_size_mb",
        1,
    )

    response_mock = MagicMock()

    post_mock = MagicMock(
        return_value=response_mock,
    )

    monkeypatch.setattr(
        receipt_storage_service.httpx,
        "post",
        post_mock,
    )

    result = receipt_storage_service.save_receipt_file(
        uploaded_file=uploaded_file,
        user_id=user_id,
    )

    assert result.startswith(
        f"supabase://receipts/{user_id}/",
    )
    assert result.endswith(
        ".jpg",
    )

    post_mock.assert_called_once()

    call_args = post_mock.call_args

    assert (
        "/storage/v1/object/receipts/"
        f"{user_id}/"
        in call_args.args[0]
    )

    assert call_args.kwargs["headers"] == {
        "apikey": "test-secret-key",
        "Content-Type": "image/jpeg",
        "x-upsert": "false",
    }

    assert (
        call_args.kwargs["content"]
        == b"receipt-content"
    )

    response_mock.raise_for_status.assert_called_once_with()


# Verifies that empty files are rejected before calling Supabase.
# This test exists to keep validation inside the backend storage layer.
# Parameters:
# - monkeypatch: pytest fixture used to override application settings.
# Returns:
# - None.
def test_save_receipt_file_rejects_empty_supabase_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()

    uploaded_file = build_upload_file(
        filename="receipt.jpg",
        content_type="image/jpeg",
        content=b"",
    )

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_storage_driver",
        "supabase",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "supabase_url",
        "https://example.supabase.co",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "supabase_secret_key",
        "test-secret-key",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_storage_bucket",
        "receipts",
    )

    post_mock = MagicMock()

    monkeypatch.setattr(
        receipt_storage_service.httpx,
        "post",
        post_mock,
    )

    with pytest.raises(
        ReceiptFileEmptyError,
    ):
        receipt_storage_service.save_receipt_file(
            uploaded_file=uploaded_file,
            user_id=user_id,
        )

    post_mock.assert_not_called()


# Verifies that oversized files are rejected before calling Supabase.
# This test exists to enforce the configured backend size limit
# independently from Supabase bucket settings.
# Parameters:
# - monkeypatch: pytest fixture used to override application settings.
# Returns:
# - None.
def test_save_receipt_file_rejects_oversized_supabase_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()

    uploaded_file = build_upload_file(
        filename="receipt.jpg",
        content_type="image/jpeg",
        content=b"receipt-content",
    )

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_storage_driver",
        "supabase",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "supabase_url",
        "https://example.supabase.co",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "supabase_secret_key",
        "test-secret-key",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_storage_bucket",
        "receipts",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_max_file_size_mb",
        0,
    )

    post_mock = MagicMock()

    monkeypatch.setattr(
        receipt_storage_service.httpx,
        "post",
        post_mock,
    )

    with pytest.raises(
        ReceiptFileTooLargeError,
    ):
        receipt_storage_service.save_receipt_file(
            uploaded_file=uploaded_file,
            user_id=user_id,
        )

    post_mock.assert_not_called()


# Verifies that Supabase upload failures are converted into domain errors.
# This test exists to prevent HTTP client implementation details
# from escaping the receipt storage layer.
# Parameters:
# - monkeypatch: pytest fixture used to replace the HTTP request.
# Returns:
# - None.
def test_save_receipt_file_wraps_supabase_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()

    uploaded_file = build_upload_file(
        filename="receipt.jpg",
        content_type="image/jpeg",
        content=b"receipt-content",
    )

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_storage_driver",
        "supabase",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "supabase_url",
        "https://example.supabase.co",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "supabase_secret_key",
        "test-secret-key",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_storage_bucket",
        "receipts",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_max_file_size_mb",
        1,
    )

    post_mock = MagicMock(
        side_effect=httpx.ConnectError(
            "Supabase unavailable",
        ),
    )

    monkeypatch.setattr(
        receipt_storage_service.httpx,
        "post",
        post_mock,
    )

    with pytest.raises(
        ReceiptFileStorageError,
    ) as error_info:
        receipt_storage_service.save_receipt_file(
            uploaded_file=uploaded_file,
            user_id=user_id,
        )

    assert isinstance(
        error_info.value.__cause__,
        httpx.ConnectError,
    )


# Verifies that Supabase receipt objects are deleted through Storage API.
# This test exists to confirm remote cleanup for Supabase storage paths.
# Parameters:
# - monkeypatch: pytest fixture used to override settings
#   and replace the HTTP request.
# Returns:
# - None.
def test_delete_receipt_file_removes_supabase_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "supabase_url",
        "https://example.supabase.co",
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "supabase_secret_key",
        "test-secret-key",
    )

    response_mock = MagicMock()

    request_mock = MagicMock(
        return_value=response_mock,
    )

    monkeypatch.setattr(
        receipt_storage_service.httpx,
        "request",
        request_mock,
    )

    storage_path = (
        "supabase://receipts/"
        "user-id/receipt-id.jpg"
    )

    receipt_storage_service.delete_receipt_file(
        storage_path=storage_path,
    )

    request_mock.assert_called_once_with(
        method="DELETE",
        url=(
            "https://example.supabase.co"
            "/storage/v1/object/receipts"
        ),
        headers={
            "apikey": "test-secret-key",
            "Content-Type": "application/json",
        },
        json={
            "prefixes": [
                "user-id/receipt-id.jpg",
            ],
        },
        timeout=(
            receipt_storage_service
            .SUPABASE_STORAGE_TIMEOUT_SECONDS
        ),
    )

    response_mock.raise_for_status.assert_called_once_with()


# Verifies that malformed Supabase storage paths are rejected.
# This test exists to prevent ambiguous remote deletion operations.
# Parameters:
# - None.
# Returns:
# - None.
def test_delete_receipt_file_rejects_invalid_supabase_path() -> None:
    with pytest.raises(
        ReceiptFileStorageError,
    ):
        receipt_storage_service.delete_receipt_file(
            storage_path="supabase://receipts",
        )