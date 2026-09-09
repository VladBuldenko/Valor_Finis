from pathlib import Path
from typing import Protocol

import pytesseract
from PIL import Image, UnidentifiedImageError

from app.core.app_config import settings
from app.modules.receipts import receipt_storage_service
from app.modules.receipts.receipt_errors import (
    ReceiptFileStorageError,
    ReceiptOcrFileNotFoundError,
    ReceiptOcrProcessingError,
)


# Languages loaded by the Tesseract OCR engine for receipt text extraction.
# "eng" (English) is bundled with the tesseract-ocr OS package by default.
# "deu" (German) is installed explicitly via tesseract-ocr-deu in the
# Dockerfile to correctly recognize German receipts (umlauts and common
# German retail terms such as "SUMME"/"GESAMT"/"MWST" used by the parser).
TESSERACT_OCR_LANGUAGES = "eng+deu"


class ReceiptOcrProvider(Protocol):
    """
    Interface for receipt OCR providers.

    What:
        Defines the operation required from any OCR provider.

    Why:
        Allows the application to replace the OCR implementation
        without changing receipt business logic.
    """

    def extract_text(self, file_path: Path) -> str:
        """
        Extracts text from a receipt file.

        Parameters:
        - file_path: local path of the receipt image or PDF.

        Returns:
        - Raw text extracted from the receipt.
        """

        ...


class UnconfiguredReceiptOcrProvider:
    """
    Placeholder OCR provider used before a real provider is configured.

    What:
        Represents the temporary OCR implementation.

    Why:
        Keeps the OCR architecture operational while preventing
        fake or incomplete OCR results from being returned.
    """

    def extract_text(self, file_path: Path) -> str:
        """
        Rejects OCR processing because no provider is configured.

        Parameters:
        - file_path: local path of the receipt file.

        Returns:
        - Never returns successfully.

        Raises:
        - ReceiptOcrProcessingError always.
        """

        raise ReceiptOcrProcessingError()


class TesseractReceiptOcrProvider:
    """
    OCR provider backed by the open-source Tesseract OCR engine.

    What:
        Extracts raw text from JPEG/PNG receipt images using the
        tesseract-ocr binary through the pytesseract wrapper.

    Why:
        Provides a production-usable, deterministic, and free OCR
        implementation suitable for an MVP, replacing the temporary
        UnconfiguredReceiptOcrProvider. Running Tesseract locally in the
        application container avoids external paid OCR credentials.
    """

    def extract_text(self, file_path: Path) -> str:
        """
        Extracts raw text from a receipt image using Tesseract OCR.

        Parameters:
        - file_path: local path of the receipt image.

        Returns:
        - Raw text extracted by the Tesseract OCR engine. May be empty
          when no text is detected; emptiness is validated by the caller.

        Raises:
        - ReceiptOcrProcessingError when the file is not a readable image,
          the decoded image exceeds the configured pixel budget, the
          Tesseract OCR engine fails to process it, or processing exceeds
          the configured timeout.
        """

        try:
            with Image.open(file_path) as receipt_image:
                # Image.open() only reads the file header, not the full
                # pixel data. Checking dimensions here (before .load())
                # rejects oversized/decompression-bomb-style images while
                # they are still cheap to inspect, instead of after they
                # have been fully decoded into memory.
                width, height = receipt_image.size
                declared_pixels = width * height

                if declared_pixels > settings.receipt_ocr_max_image_pixels:
                    raise ReceiptOcrProcessingError()

                # Loading the image data here (instead of lazily, on first
                # use by pytesseract) surfaces truncated/corrupt files as
                # UnidentifiedImageError/OSError at this point.
                receipt_image.load()

                return pytesseract.image_to_string(
                    receipt_image,
                    lang=TESSERACT_OCR_LANGUAGES,
                    timeout=settings.receipt_ocr_timeout_seconds,
                )
        except (
            UnidentifiedImageError,
            OSError,
            pytesseract.TesseractError,
            pytesseract.TesseractNotFoundError,
            # pytesseract raises a bare RuntimeError("Tesseract process
            # timeout") when the OCR subprocess exceeds `timeout` (see
            # pytesseract.pytesseract.timeout_manager). TesseractError is
            # itself a RuntimeError subclass, so this also covers it.
            RuntimeError,
        ) as error:
            raise ReceiptOcrProcessingError() from error


# Selects the OCR provider implementation for the configured driver.
# This function exists to keep OCR provider selection isolated from
# application configuration and to fail fast on invalid driver names.
# Parameters:
# - driver: validated receipt OCR driver name.
# Returns:
# - ReceiptOcrProvider implementation matching the requested driver.
# Raises:
# - ValueError when the driver name is not supported.
def select_receipt_ocr_provider(driver: str) -> ReceiptOcrProvider:
    if driver == "tesseract":
        return TesseractReceiptOcrProvider()

    if driver == "unconfigured":
        return UnconfiguredReceiptOcrProvider()

    raise ValueError(
        f"Unsupported RECEIPT_OCR_DRIVER '{driver}'."
    )


receipt_ocr_provider: ReceiptOcrProvider = select_receipt_ocr_provider(
    driver=settings.receipt_ocr_driver,
)


# Extracts normalized text from a stored receipt file.
# This function exists to isolate receipt business logic
# from both the selected OCR provider and storage provider.
# Parameters:
# - storage_path: internal path of the stored receipt file.
# Returns:
# - Non-empty normalized OCR text.
# Raises:
# - ReceiptOcrFileNotFoundError when a local stored file does not exist.
# - ReceiptOcrProcessingError when storage access fails,
#   the OCR provider fails, or the provider returns empty text.
def extract_receipt_text(
    storage_path: str,
) -> str:
    try:
        with receipt_storage_service.materialize_receipt_file(
            storage_path=storage_path,
        ) as file_path:
            if not file_path.is_file():
                raise ReceiptOcrFileNotFoundError()

            try:
                extracted_text = (
                    receipt_ocr_provider.extract_text(
                        file_path=file_path,
                    )
                )
            except ReceiptOcrProcessingError:
                raise
            except Exception as error:
                raise ReceiptOcrProcessingError() from error

    except ReceiptOcrFileNotFoundError:
        raise
    except ReceiptOcrProcessingError:
        raise
    except ReceiptFileStorageError as error:
        raise ReceiptOcrProcessingError() from error

    normalized_text = extracted_text.strip()

    if not normalized_text:
        raise ReceiptOcrProcessingError()

    return normalized_text