from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

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


# Verifies that the Tesseract provider returns text produced by the
# Tesseract OCR engine for a valid receipt image.
# This test exists to confirm successful delegation to pytesseract
# without depending on the real installed Tesseract binary.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary.
# Returns:
# - None.
def test_tesseract_provider_returns_extracted_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (20, 20), color="white").save(receipt_image_path)

    image_to_string_mock = MagicMock(
        return_value="LIDL\nSUMME 24.99 EUR",
    )

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        image_to_string_mock,
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    result = provider.extract_text(
        file_path=receipt_image_path,
    )

    assert result == "LIDL\nSUMME 24.99 EUR"

    image_to_string_mock.assert_called_once()

    call_kwargs = image_to_string_mock.call_args.kwargs

    assert call_kwargs["lang"] == (
        receipt_ocr_service.TESSERACT_OCR_LANGUAGES
    )
    assert call_kwargs["timeout"] == (
        receipt_ocr_service.settings.receipt_ocr_timeout_seconds
    )


# Verifies that Tesseract engine failures are converted into the
# domain-specific OCR processing error.
# This test exists to prevent pytesseract implementation details
# (missing binary, non-zero exit code) from escaping the OCR provider.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary.
# Returns:
# - None.
def test_tesseract_provider_wraps_tesseract_engine_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (20, 20), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        MagicMock(
            side_effect=receipt_ocr_service.pytesseract.TesseractNotFoundError(),
        ),
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with pytest.raises(ReceiptOcrProcessingError):
        provider.extract_text(
            file_path=receipt_image_path,
        )


# Verifies that an unreadable/corrupt image file is rejected
# as an OCR processing error instead of an unhandled PIL exception.
# This test exists to confirm that malformed receipt files
# do not crash the OCR provider.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# Returns:
# - None.
def test_tesseract_provider_wraps_invalid_image_file(
    tmp_path: Path,
) -> None:
    invalid_image_path = tmp_path / "receipt.png"
    invalid_image_path.write_bytes(b"not-a-real-image")

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with pytest.raises(ReceiptOcrProcessingError):
        provider.extract_text(
            file_path=invalid_image_path,
        )


# Verifies that the "tesseract" driver selects the Tesseract OCR provider.
# This test exists to confirm configuration-driven provider selection.
# Parameters:
# - None.
# Returns:
# - None.
def test_select_receipt_ocr_provider_returns_tesseract_provider() -> None:
    provider = receipt_ocr_service.select_receipt_ocr_provider(
        driver="tesseract",
    )

    assert isinstance(
        provider,
        receipt_ocr_service.TesseractReceiptOcrProvider,
    )


# Verifies that the "unconfigured" driver selects the placeholder provider.
# This test exists to confirm that OCR can be explicitly disabled
# through configuration without removing the provider from the codebase.
# Parameters:
# - None.
# Returns:
# - None.
def test_select_receipt_ocr_provider_returns_unconfigured_provider() -> None:
    provider = receipt_ocr_service.select_receipt_ocr_provider(
        driver="unconfigured",
    )

    assert isinstance(
        provider,
        receipt_ocr_service.UnconfiguredReceiptOcrProvider,
    )


# Verifies that an unsupported OCR driver name fails fast.
# This test exists to prevent the application from silently falling back
# to an unexpected OCR provider when misconfigured.
# Parameters:
# - None.
# Returns:
# - None.
def test_select_receipt_ocr_provider_rejects_unsupported_driver() -> None:
    with pytest.raises(ValueError):
        receipt_ocr_service.select_receipt_ocr_provider(
            driver="unsupported-driver",
        )


# Verifies that an image at or below the configured pixel budget is
# still sent to the Tesseract OCR engine.
# This test exists to confirm that the decompression-bomb pixel check
# does not reject normal, appropriately sized receipt photos.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary
#   and the configured pixel budget.
# Returns:
# - None.
def test_tesseract_provider_allows_image_within_pixel_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (100, 100), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.settings,
        "receipt_ocr_max_image_pixels",
        100 * 100,
    )

    image_to_string_mock = MagicMock(
        return_value="LIDL\nSUMME 24.99 EUR",
    )

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        image_to_string_mock,
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    result = provider.extract_text(
        file_path=receipt_image_path,
    )

    assert result == "LIDL\nSUMME 24.99 EUR"
    image_to_string_mock.assert_called_once()


# Verifies that an image whose declared dimensions exceed the configured
# pixel budget is rejected before Tesseract is invoked.
# This test exists to confirm that decompression-bomb-style images
# (small on disk, large when decoded) are rejected using only the cheap
# header-level dimension check, without paying for full decode or OCR.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary
#   and the configured pixel budget.
# Returns:
# - None.
def test_tesseract_provider_rejects_image_over_pixel_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (100, 100), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.settings,
        "receipt_ocr_max_image_pixels",
        (100 * 100) - 1,
    )

    image_to_string_mock = MagicMock()

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        image_to_string_mock,
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with pytest.raises(ReceiptOcrProcessingError):
        provider.extract_text(
            file_path=receipt_image_path,
        )

    image_to_string_mock.assert_not_called()


# Verifies that a Tesseract execution timeout is converted into the
# domain-specific OCR processing error.
# This test exists to confirm that pytesseract's bare RuntimeError
# ("Tesseract process timeout"), raised when the OCR subprocess exceeds
# the configured timeout, does not escape as an unhandled exception.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary.
# Returns:
# - None.
def test_tesseract_provider_wraps_timeout_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (20, 20), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        MagicMock(
            side_effect=RuntimeError("Tesseract process timeout"),
        ),
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with pytest.raises(ReceiptOcrProcessingError) as error_info:
        provider.extract_text(
            file_path=receipt_image_path,
        )

    assert isinstance(
        error_info.value.__cause__,
        RuntimeError,
    )


# Verifies that the configured timeout is passed through to pytesseract
# on every call.
# This test exists to confirm the Tesseract execution timeout is
# actually enforced by the underlying OCR call, not merely configured.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary
#   and the configured timeout.
# Returns:
# - None.
def test_tesseract_provider_passes_configured_timeout_to_pytesseract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (20, 20), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.settings,
        "receipt_ocr_timeout_seconds",
        7,
    )

    image_to_string_mock = MagicMock(
        return_value="LIDL",
    )

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        image_to_string_mock,
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    provider.extract_text(
        file_path=receipt_image_path,
    )

    assert (
        image_to_string_mock.call_args.kwargs["timeout"] == 7
    )