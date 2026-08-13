from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.modules.receipts import receipt_ocr_service
from app.modules.receipts.receipt_errors import (
    ReceiptFileStorageError,
    ReceiptOcrFileNotFoundError,
    ReceiptOcrProcessingError,
)


# Verifies that OCR text is extracted and normalized for an existing file.
# This test exists to confirm successful provider delegation
# and whitespace normalization.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the OCR provider.
# Returns:
# - None.
def test_extract_receipt_text_returns_normalized_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_file_path = tmp_path / "receipt.jpg"
    receipt_file_path.write_bytes(b"receipt-image-content")

    extracted_text = "\n  LIDL\nTOTAL 24.99 EUR  \n"
    expected_text = "LIDL\nTOTAL 24.99 EUR"

    ocr_provider_mock = MagicMock()
    ocr_provider_mock.extract_text.return_value = extracted_text

    monkeypatch.setattr(
        receipt_ocr_service,
        "receipt_ocr_provider",
        ocr_provider_mock,
    )

    result = receipt_ocr_service.extract_receipt_text(
        storage_path=receipt_file_path.as_posix(),
    )

    assert result == expected_text

    ocr_provider_mock.extract_text.assert_called_once_with(
        file_path=receipt_file_path,
    )


# Verifies that OCR processing fails when the stored file does not exist.
# This test exists to prevent provider calls for missing receipt files.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the OCR provider.
# Returns:
# - None.
def test_extract_receipt_text_raises_when_file_not_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_file_path = tmp_path / "missing-receipt.jpg"

    ocr_provider_mock = MagicMock()

    monkeypatch.setattr(
        receipt_ocr_service,
        "receipt_ocr_provider",
        ocr_provider_mock,
    )

    with pytest.raises(ReceiptOcrFileNotFoundError):
        receipt_ocr_service.extract_receipt_text(
            storage_path=missing_file_path.as_posix(),
        )

    ocr_provider_mock.extract_text.assert_not_called()


# Verifies that an empty OCR result is rejected.
# This test exists to prevent receipts from being marked as processed
# without usable extracted text.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the OCR provider.
# Returns:
# - None.
def test_extract_receipt_text_rejects_empty_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_file_path = tmp_path / "receipt.jpg"
    receipt_file_path.write_bytes(b"receipt-image-content")

    ocr_provider_mock = MagicMock()
    ocr_provider_mock.extract_text.return_value = "   \n\t   "

    monkeypatch.setattr(
        receipt_ocr_service,
        "receipt_ocr_provider",
        ocr_provider_mock,
    )

    with pytest.raises(ReceiptOcrProcessingError):
        receipt_ocr_service.extract_receipt_text(
            storage_path=receipt_file_path.as_posix(),
        )

    ocr_provider_mock.extract_text.assert_called_once_with(
        file_path=receipt_file_path,
    )


# Verifies that a receipt-specific OCR error is propagated unchanged.
# This test exists to preserve domain errors raised by the OCR provider.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the OCR provider.
# Returns:
# - None.
def test_extract_receipt_text_propagates_ocr_processing_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_file_path = tmp_path / "receipt.jpg"
    receipt_file_path.write_bytes(b"receipt-image-content")

    processing_error = ReceiptOcrProcessingError()

    ocr_provider_mock = MagicMock()
    ocr_provider_mock.extract_text.side_effect = processing_error

    monkeypatch.setattr(
        receipt_ocr_service,
        "receipt_ocr_provider",
        ocr_provider_mock,
    )

    with pytest.raises(ReceiptOcrProcessingError) as error_info:
        receipt_ocr_service.extract_receipt_text(
            storage_path=receipt_file_path.as_posix(),
        )

    assert error_info.value is processing_error


# Verifies that unexpected provider errors are converted into domain errors.
# This test exists to prevent provider implementation details
# from escaping the OCR infrastructure layer.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the OCR provider.
# Returns:
# - None.
def test_extract_receipt_text_wraps_unexpected_provider_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_file_path = tmp_path / "receipt.jpg"
    receipt_file_path.write_bytes(b"receipt-image-content")

    provider_error = RuntimeError("OCR provider is unavailable.")

    ocr_provider_mock = MagicMock()
    ocr_provider_mock.extract_text.side_effect = provider_error

    monkeypatch.setattr(
        receipt_ocr_service,
        "receipt_ocr_provider",
        ocr_provider_mock,
    )

    with pytest.raises(ReceiptOcrProcessingError) as error_info:
        receipt_ocr_service.extract_receipt_text(
            storage_path=receipt_file_path.as_posix(),
        )

    assert error_info.value.__cause__ is provider_error


# Verifies that the placeholder provider rejects OCR processing.
# This test exists to make unconfigured OCR behavior explicit.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# Returns:
# - None.
def test_unconfigured_ocr_provider_raises_processing_error(
    tmp_path: Path,
) -> None:
    receipt_file_path = tmp_path / "receipt.jpg"
    receipt_file_path.write_bytes(b"receipt-image-content")

    provider = receipt_ocr_service.UnconfiguredReceiptOcrProvider()

    with pytest.raises(ReceiptOcrProcessingError):
        provider.extract_text(
            file_path=receipt_file_path,
        )

# Verifies that OCR can process a receipt materialized
# from a non-local storage provider.
# This test exists to keep OCR independent from
# the receipt storage implementation.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace storage materialization
#   and the OCR provider.
# Returns:
# - None.
def test_extract_receipt_text_uses_materialized_storage_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_file_path = (
        tmp_path / "receipt.jpg"
    )

    receipt_file_path.write_bytes(
        b"remote-receipt-content",
    )

    materialize_mock = MagicMock(
        return_value=nullcontext(
            receipt_file_path,
        ),
    )

    monkeypatch.setattr(
        receipt_ocr_service.receipt_storage_service,
        "materialize_receipt_file",
        materialize_mock,
    )

    ocr_provider_mock = MagicMock()
    ocr_provider_mock.extract_text.return_value = (
        "  LIDL\nTOTAL 42.50 EUR  "
    )

    monkeypatch.setattr(
        receipt_ocr_service,
        "receipt_ocr_provider",
        ocr_provider_mock,
    )

    result = receipt_ocr_service.extract_receipt_text(
        storage_path=(
            "supabase://receipts/"
            "user-id/receipt-id.jpg"
        ),
    )

    assert result == (
        "LIDL\nTOTAL 42.50 EUR"
    )

    materialize_mock.assert_called_once_with(
        storage_path=(
            "supabase://receipts/"
            "user-id/receipt-id.jpg"
        ),
    )

    ocr_provider_mock.extract_text.assert_called_once_with(
        file_path=receipt_file_path,
    )


# Verifies that storage failures are converted into OCR processing errors.
# This test exists to keep receipt processing independent
# from storage-provider implementation errors.
# Parameters:
# - monkeypatch: pytest fixture used to replace storage materialization.
# Returns:
# - None.
def test_extract_receipt_text_wraps_storage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_error = ReceiptFileStorageError()

    materialize_mock = MagicMock(
        side_effect=storage_error,
    )

    monkeypatch.setattr(
        receipt_ocr_service.receipt_storage_service,
        "materialize_receipt_file",
        materialize_mock,
    )

    with pytest.raises(
        ReceiptOcrProcessingError,
    ) as error_info:
        receipt_ocr_service.extract_receipt_text(
            storage_path=(
                "supabase://receipts/"
                "user-id/receipt-id.jpg"
            ),
        )

    assert error_info.value.__cause__ is storage_error