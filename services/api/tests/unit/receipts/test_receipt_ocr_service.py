import logging
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


# Verifies that a missing Tesseract binary is logged under its own safe
# diagnostic category, distinguishable from a generic engine failure.
# This test exists to satisfy the requirement that Render logs can tell
# apart "Tesseract binary unavailable" from other OCR failure modes,
# without asserting the full formatted log message.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_tesseract_provider_logs_tesseract_not_found_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
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

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ReceiptOcrProcessingError):
            provider.extract_text(
                file_path=receipt_image_path,
            )

    assert "receipt_ocr_tesseract_not_found" in caplog.text


# Verifies that a generic Tesseract engine failure is logged under the
# engine-failure category rather than the missing-language-data category.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_tesseract_provider_logs_engine_failed_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (20, 20), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        MagicMock(
            side_effect=receipt_ocr_service.pytesseract.TesseractError(
                1,
                "Segmentation fault (core dumped)",
            ),
        ),
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ReceiptOcrProcessingError):
            provider.extract_text(
                file_path=receipt_image_path,
            )

    assert "receipt_ocr_engine_failed" in caplog.text
    assert "receipt_ocr_tesseract_language_data_missing" not in caplog.text


# Verifies that a Tesseract failure caused by missing language trained
# data is logged under its own distinguishable category.
# This test exists to satisfy the requirement that Render logs can tell
# apart "required language data unavailable" from a generic engine
# failure, using only a safe keyword match (never the raw engine
# message, which is not logged).
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_tesseract_provider_logs_language_data_missing_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (20, 20), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        MagicMock(
            side_effect=receipt_ocr_service.pytesseract.TesseractError(
                1,
                "Failed loading language 'deu' Tessdata directory is not"
                " writable",
            ),
        ),
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ReceiptOcrProcessingError):
            provider.extract_text(
                file_path=receipt_image_path,
            )

    assert "receipt_ocr_tesseract_language_data_missing" in caplog.text


# Verifies that a Tesseract subprocess timeout is logged under its own
# timeout category, distinguishable from a generic engine failure.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_tesseract_provider_logs_timeout_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
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

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ReceiptOcrProcessingError):
            provider.extract_text(
                file_path=receipt_image_path,
            )

    assert "receipt_ocr_timeout" in caplog.text


# Verifies that an unreadable/corrupt image is logged under the
# invalid-image category.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_tesseract_provider_logs_invalid_image_category(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    invalid_image_path = tmp_path / "receipt.png"
    invalid_image_path.write_bytes(b"not-a-real-image")

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ReceiptOcrProcessingError):
            provider.extract_text(
                file_path=invalid_image_path,
            )

    assert "receipt_ocr_invalid_image" in caplog.text


# Verifies that an oversized image is logged under the
# image-too-large category before Tesseract would have been invoked.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the configured pixel
#   budget.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_tesseract_provider_logs_image_too_large_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (100, 100), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.settings,
        "receipt_ocr_max_image_pixels",
        (100 * 100) - 1,
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ReceiptOcrProcessingError):
            provider.extract_text(
                file_path=receipt_image_path,
            )

    assert "receipt_ocr_image_too_large" in caplog.text


# Verifies that an empty OCR result is logged under its own category.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the OCR provider.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_extract_receipt_text_logs_empty_result_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    receipt_file_path = tmp_path / "receipt.jpg"
    receipt_file_path.write_bytes(b"receipt-image-content")

    ocr_provider_mock = MagicMock()
    ocr_provider_mock.extract_text.return_value = "   "

    monkeypatch.setattr(
        receipt_ocr_service,
        "receipt_ocr_provider",
        ocr_provider_mock,
    )

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ReceiptOcrProcessingError):
            receipt_ocr_service.extract_receipt_text(
                storage_path=receipt_file_path.as_posix(),
            )

    assert "receipt_ocr_empty_result" in caplog.text


# Verifies that a missing stored receipt file is logged under its own
# category.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the OCR provider.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_extract_receipt_text_logs_file_not_found_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    missing_file_path = tmp_path / "missing-receipt.jpg"

    ocr_provider_mock = MagicMock()

    monkeypatch.setattr(
        receipt_ocr_service,
        "receipt_ocr_provider",
        ocr_provider_mock,
    )

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ReceiptOcrFileNotFoundError):
            receipt_ocr_service.extract_receipt_text(
                storage_path=missing_file_path.as_posix(),
            )

    assert "receipt_ocr_file_not_found" in caplog.text


# ---------------------------------------------------------------------------
# Pre-Tesseract image preprocessing (EXIF orientation normalization and
# downscaling of real-resolution camera photos). See
# receipt_ocr_service._prepare_receipt_image_for_ocr().
# ---------------------------------------------------------------------------


# Verifies that an image already at or below the configured maximum long
# edge is passed to Tesseract unchanged, instead of being enlarged.
# This test exists to confirm that small receipt images are never
# upscaled, since upscaling adds interpolation artifacts without adding
# real text detail.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary
#   and the configured maximum long edge.
# Returns:
# - None.
def test_tesseract_provider_does_not_upscale_small_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (40, 30), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.settings,
        "receipt_ocr_max_long_edge",
        2000,
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

    ocr_image = image_to_string_mock.call_args.args[0]
    assert ocr_image.size == (40, 30)


# Verifies that an image larger than the configured maximum long edge is
# downscaled before being passed to Tesseract, preserving its aspect
# ratio.
# This test exists to confirm the actual downscale math (not just that
# resizing happens), since an aspect-ratio bug would distort receipt text.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary
#   and the configured maximum long edge.
# Returns:
# - None.
def test_tesseract_provider_downscales_large_image_preserving_aspect_ratio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    # 2:1 aspect ratio, well above the configured long edge below.
    Image.new("RGB", (400, 200), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.settings,
        "receipt_ocr_max_long_edge",
        100,
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

    ocr_image = image_to_string_mock.call_args.args[0]
    # Aspect ratio (2:1) preserved at the configured 100px long edge.
    assert ocr_image.size == (100, 50)


# Verifies that a receipt image with an EXIF Orientation tag is
# re-oriented before OCR (portrait/landscape swap applied), instead of
# being sent to Tesseract sideways.
# This test exists to confirm that phone photos stored with an EXIF
# orientation tag (instead of physically rotated pixel data) are
# corrected before OCR.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary.
# Returns:
# - None.
def test_tesseract_provider_normalizes_exif_orientation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_image_path = tmp_path / "receipt.jpg"

    # EXIF Orientation tag 6 ("Rotate 90 CW required to display upright")
    # means the physically stored pixel data is 40x20 but must become
    # 20x40 once orientation is applied.
    source_image = Image.new("RGB", (40, 20), color="white")

    exif = Image.Exif()
    exif[0x0112] = 6

    source_image.save(
        receipt_image_path,
        format="JPEG",
        exif=exif,
    )

    monkeypatch.setattr(
        receipt_ocr_service.settings,
        "receipt_ocr_max_long_edge",
        2000,
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

    ocr_image = image_to_string_mock.call_args.args[0]
    assert ocr_image.size == (20, 40)


# Verifies that the pixel-budget rejection still happens before the new
# preprocessing step runs, so an oversized/decompression-bomb-style image
# never reaches the (comparatively expensive) orientation/downscale work.
# This test exists to confirm the preprocessing addition did not weaken
# or reorder the existing security check.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the configured pixel
#   budget and the preprocessing helper.
# Returns:
# - None.
def test_tesseract_provider_rejects_oversized_image_before_preprocessing(
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

    prepare_image_mock = MagicMock()

    monkeypatch.setattr(
        receipt_ocr_service,
        "_prepare_receipt_image_for_ocr",
        prepare_image_mock,
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

    prepare_image_mock.assert_not_called()
    image_to_string_mock.assert_not_called()


# Verifies that a Tesseract timeout is still correctly converted into the
# domain-specific OCR processing error when the image was also
# downscaled by the new preprocessing step.
# This test exists to confirm the preprocessing addition does not
# interfere with existing timeout error mapping.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary
#   and the configured maximum long edge.
# Returns:
# - None.
def test_tesseract_provider_wraps_timeout_error_with_downscaled_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (400, 300), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.settings,
        "receipt_ocr_max_long_edge",
        100,
    )

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


# Verifies that OCR preprocessing never modifies the original stored
# receipt file on disk, even when downscaling occurs.
# This test exists to confirm the preprocessing step only produces an
# in-memory working image for OCR, never overwriting the source file
# that the rest of the application (and the user) still relies on.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary
#   and the configured maximum long edge.
# Returns:
# - None.
def test_tesseract_provider_does_not_modify_original_stored_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (400, 300), color="white").save(receipt_image_path)

    original_bytes = receipt_image_path.read_bytes()

    monkeypatch.setattr(
        receipt_ocr_service.settings,
        "receipt_ocr_max_long_edge",
        100,
    )

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        MagicMock(return_value="LIDL"),
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    provider.extract_text(
        file_path=receipt_image_path,
    )

    assert receipt_image_path.read_bytes() == original_bytes


# Verifies that a resize is logged with only safe, non-sensitive
# dimension information, and never the local file path.
# This test exists to confirm the new resize log line does not introduce
# a path/content leakage regression.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary
#   and the configured maximum long edge.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_tesseract_provider_logs_resize_without_leaking_file_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (400, 200), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.settings,
        "receipt_ocr_max_long_edge",
        100,
    )

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        MagicMock(return_value="LIDL"),
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with caplog.at_level(logging.INFO):
        provider.extract_text(
            file_path=receipt_image_path,
        )

    assert "receipt_ocr_started" in caplog.text
    assert "receipt_ocr_prepared" in caplog.text
    assert "resized=true" in caplog.text
    assert "400x200" in caplog.text
    assert "100x50" in caplog.text
    assert str(tmp_path) not in caplog.text


# Verifies that a successful OCR run emits the full diagnostic telemetry
# sequence (started, prepared, tesseract started, tesseract completed)
# with the expected fields, so production timing bottlenecks can be
# diagnosed from Render logs.
# This test exists to prove the telemetry required to answer "where did
# the 45+ seconds go" is actually present end-to-end for the success
# path, not just reasoned about.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_tesseract_provider_logs_full_telemetry_sequence_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (200, 100), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        MagicMock(return_value="LIDL"),
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with caplog.at_level(logging.INFO):
        provider.extract_text(
            file_path=receipt_image_path,
        )

    assert "receipt_ocr_started original_size=200x100" in caplog.text
    assert "receipt_ocr_prepared" in caplog.text
    assert "ocr_size=200x100" in caplog.text
    assert "resized=false" in caplog.text
    assert "preprocessing_ms=" in caplog.text
    assert f"max_long_edge={receipt_ocr_service.settings.receipt_ocr_max_long_edge}" in caplog.text
    assert "receipt_ocr_tesseract_started" in caplog.text
    assert (
        f"timeout_seconds={receipt_ocr_service.settings.receipt_ocr_timeout_seconds}"
        in caplog.text
    )
    assert "languages=eng+deu" in caplog.text
    assert "receipt_ocr_tesseract_completed" in caplog.text
    assert "elapsed_ms=" in caplog.text


# Verifies that a Tesseract timeout is logged with how long Tesseract
# actually ran before the timeout fired (tesseract_elapsed_ms), not just
# that a timeout occurred.
# This test exists because knowing the elapsed time at failure is the
# specific diagnostic signal needed to distinguish "Tesseract is slow on
# this image" from "Tesseract never started" when reading Render logs.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_tesseract_provider_timeout_log_includes_tesseract_elapsed_ms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (200, 100), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        MagicMock(
            side_effect=RuntimeError("Tesseract process timeout"),
        ),
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with caplog.at_level(logging.INFO):
        with pytest.raises(ReceiptOcrProcessingError):
            provider.extract_text(
                file_path=receipt_image_path,
            )

    assert "receipt_ocr_timeout" in caplog.text
    assert "tesseract_elapsed_ms=" in caplog.text
    # tesseract_elapsed_ms must be a real number, not a missing/None
    # placeholder, since Tesseract did start before timing out here.
    assert "tesseract_elapsed_ms=None" not in caplog.text


# Verifies that none of the new diagnostic telemetry log lines contain
# the actual OCR-extracted text or receipt content.
# This test exists to guard the safe-logging requirement specifically
# for the new started/prepared/tesseract-started/tesseract-completed
# events, using a distinctive extracted-text value that would be easy
# to spot if it leaked into any log line.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_tesseract_provider_telemetry_logs_do_not_leak_ocr_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (200, 100), color="white").save(receipt_image_path)

    distinctive_ocr_text = "SUPER-SECRET-RECEIPT-CONTENTS-42"

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        MagicMock(return_value=distinctive_ocr_text),
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with caplog.at_level(logging.INFO):
        result = provider.extract_text(
            file_path=receipt_image_path,
        )

    assert result == distinctive_ocr_text
    assert distinctive_ocr_text not in caplog.text


# ---------------------------------------------------------------------------
# CPU/cgroup throttling diagnostics (VF-006 - confirm Render CPU
# throttling). See app/core/cgroup_metrics.py for the underlying reader,
# tested independently in tests/unit/core/test_cgroup_metrics.py. These
# tests confirm the OCR-side wiring: telemetry is logged immediately
# before/after the Tesseract call, deltas are computed correctly, and
# the diagnostic can never break OCR processing itself.
# ---------------------------------------------------------------------------


# Verifies that a successful OCR run logs cgroup CPU metrics both before
# and after the Tesseract call, with correct before/after values and
# correct deltas between them.
# This test exists to confirm the diagnostic telemetry this task adds is
# actually wired into the success path with the right fields, not just
# that read_cgroup_cpu_metrics() itself works in isolation.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary
#   and the cgroup CPU metrics reader.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_tesseract_provider_logs_cpu_before_and_after_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (200, 100), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        MagicMock(return_value="LIDL"),
    )

    cpu_before_snapshot = receipt_ocr_service.CgroupCpuMetrics(
        cgroup_version="v2",
        quota_us=50000,
        period_us=100000,
        nr_periods=10,
        nr_throttled=2,
        throttled_usec=3000,
        usage_usec=100000,
    )
    cpu_after_snapshot = receipt_ocr_service.CgroupCpuMetrics(
        cgroup_version="v2",
        quota_us=50000,
        period_us=100000,
        nr_periods=15,
        nr_throttled=6,
        throttled_usec=8000,
        usage_usec=140000,
    )

    monkeypatch.setattr(
        receipt_ocr_service,
        "read_cgroup_cpu_metrics",
        MagicMock(side_effect=[cpu_before_snapshot, cpu_after_snapshot]),
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with caplog.at_level(logging.INFO):
        provider.extract_text(
            file_path=receipt_image_path,
        )

    assert (
        "receipt_ocr_cpu_before cgroup_version=v2 quota_us=50000 "
        "period_us=100000 nr_periods=10 nr_throttled=2 "
        "throttled_usec=3000" in caplog.text
    )
    assert (
        "receipt_ocr_cpu_after cgroup_version=v2 nr_periods=15 "
        "nr_throttled=6 throttled_usec=8000 usage_usec=140000 "
        "delta_nr_periods=5 delta_nr_throttled=4 "
        "delta_throttled_usec=5000 delta_usage_usec=40000" in caplog.text
    )


# Verifies that a Tesseract timeout still logs "after" CPU/cgroup
# telemetry with deltas against the "before" snapshot, alongside the
# existing timeout failure category log.
# This test exists because a real timeout under CPU throttling is
# exactly the production scenario this diagnostic was built to observe:
# rising nr_throttled/throttled_usec across a timed-out OCR call is the
# direct confirmation this task set out to obtain.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary
#   and the cgroup CPU metrics reader.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_tesseract_provider_logs_cpu_after_on_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (200, 100), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        MagicMock(side_effect=RuntimeError("Tesseract process timeout")),
    )

    cpu_before_snapshot = receipt_ocr_service.CgroupCpuMetrics(
        cgroup_version="v2",
        quota_us=50000,
        period_us=100000,
        nr_periods=100,
        nr_throttled=40,
        throttled_usec=900000,
        usage_usec=5000000,
    )
    cpu_after_snapshot = receipt_ocr_service.CgroupCpuMetrics(
        cgroup_version="v2",
        quota_us=50000,
        period_us=100000,
        nr_periods=145,
        nr_throttled=88,
        throttled_usec=4400000,
        usage_usec=5600000,
    )

    monkeypatch.setattr(
        receipt_ocr_service,
        "read_cgroup_cpu_metrics",
        MagicMock(side_effect=[cpu_before_snapshot, cpu_after_snapshot]),
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with caplog.at_level(logging.INFO):
        with pytest.raises(ReceiptOcrProcessingError):
            provider.extract_text(
                file_path=receipt_image_path,
            )

    assert "receipt_ocr_cpu_before" in caplog.text
    assert (
        "receipt_ocr_cpu_after cgroup_version=v2 nr_periods=145 "
        "nr_throttled=88 throttled_usec=4400000 usage_usec=5600000 "
        "delta_nr_periods=45 delta_nr_throttled=48 "
        "delta_throttled_usec=3500000 delta_usage_usec=600000"
        in caplog.text
    )
    assert "receipt_ocr_timeout" in caplog.text


# Verifies that no CPU/cgroup telemetry is logged for a failure that
# happens before the Tesseract call is ever reached (an unreadable/
# corrupt image), since there is no "before the Tesseract call"
# snapshot to report or compare against in that case.
# This test exists to confirm the telemetry stays scoped to the
# Tesseract call itself, per the task's diagnostics-only, narrowly
# isolated scope.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the cgroup CPU metrics
#   reader (to prove it is never even called).
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_tesseract_provider_does_not_log_cpu_metrics_for_pre_tesseract_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    invalid_image_path = tmp_path / "receipt.png"
    invalid_image_path.write_bytes(b"not-a-real-image")

    cpu_metrics_mock = MagicMock()

    monkeypatch.setattr(
        receipt_ocr_service,
        "read_cgroup_cpu_metrics",
        cpu_metrics_mock,
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with caplog.at_level(logging.INFO):
        with pytest.raises(ReceiptOcrProcessingError):
            provider.extract_text(
                file_path=invalid_image_path,
            )

    cpu_metrics_mock.assert_not_called()
    assert "receipt_ocr_cpu_before" not in caplog.text
    assert "receipt_ocr_cpu_after" not in caplog.text


# Verifies that OCR still succeeds and returns the correct text when the
# cgroup CPU metrics reader reports every field as "unavailable" (the
# real reader's own degrade-safely behavior when cgroup files are
# missing/unreadable, e.g. on a host with no Linux cgroup filesystem).
# This test exists to prove that an "unavailable" cgroup snapshot never
# breaks OCR processing, per the task's explicit safety requirement.
#
# The cgroup reader is deliberately mocked here rather than left as the
# real implementation: whether the *real* reader actually returns
# "unavailable" depends on the host's own cgroup exposure, which is not
# something a unit test should assume. macOS (no cgroup filesystem)
# reports "unavailable", but a Linux CI runner can genuinely expose a
# real cgroup v2 hierarchy (a correct, different, and equally valid
# outcome for that host) - asserting a specific `cgroup_version` from
# the unmocked reader made this test environment-dependent, which is
# exactly what broke it in CI. Real-reader/real-filesystem behavior
# (including cgroup v2 detection, cgroup v1 fallback, and genuinely
# missing files) is covered independently in test_cgroup_metrics.py.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary
#   and the cgroup metrics reader with a fixed "unavailable" snapshot.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_tesseract_provider_cpu_telemetry_never_breaks_ocr_when_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (200, 100), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        MagicMock(return_value="LIDL"),
    )

    unavailable_snapshot = receipt_ocr_service.CgroupCpuMetrics(
        cgroup_version="unavailable",
        quota_us="unavailable",
        period_us="unavailable",
        nr_periods="unavailable",
        nr_throttled="unavailable",
        throttled_usec="unavailable",
        usage_usec="unavailable",
    )

    monkeypatch.setattr(
        receipt_ocr_service,
        "read_cgroup_cpu_metrics",
        MagicMock(return_value=unavailable_snapshot),
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with caplog.at_level(logging.INFO):
        result = provider.extract_text(
            file_path=receipt_image_path,
        )

    assert result == "LIDL"
    assert "receipt_ocr_cpu_before" in caplog.text
    assert "receipt_ocr_cpu_after" in caplog.text
    assert "cgroup_version=unavailable" in caplog.text


# Verifies that the CPU telemetry log lines never contain the local
# file path, matching the same safe-logging requirement already
# enforced for the other diagnostic log lines in this file.
# Parameters:
# - tmp_path: temporary filesystem directory provided by pytest.
# - monkeypatch: pytest fixture used to replace the pytesseract boundary
#   and the cgroup CPU metrics reader.
# - caplog: pytest fixture used to capture emitted log records.
# Returns:
# - None.
def test_tesseract_provider_cpu_telemetry_does_not_leak_file_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    receipt_image_path = tmp_path / "receipt.png"
    Image.new("RGB", (200, 100), color="white").save(receipt_image_path)

    monkeypatch.setattr(
        receipt_ocr_service.pytesseract,
        "image_to_string",
        MagicMock(return_value="LIDL"),
    )

    provider = receipt_ocr_service.TesseractReceiptOcrProvider()

    with caplog.at_level(logging.INFO):
        provider.extract_text(
            file_path=receipt_image_path,
        )

    assert str(tmp_path) not in caplog.text