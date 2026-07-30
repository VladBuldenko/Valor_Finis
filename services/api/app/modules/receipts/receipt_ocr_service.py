from pathlib import Path
from typing import Protocol

from app.modules.receipts.receipt_errors import (
    ReceiptOcrFileNotFoundError,
    ReceiptOcrProcessingError,
)


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


receipt_ocr_provider: ReceiptOcrProvider = UnconfiguredReceiptOcrProvider()


# Extracts normalized text from a stored receipt file.
# This function exists to isolate receipt business logic
# from the selected OCR provider implementation.
# Parameters:
# - storage_path: internal path of the stored receipt file.
# Returns:
# - Non-empty normalized OCR text.
# Raises:
# - ReceiptOcrFileNotFoundError when the stored file does not exist.
# - ReceiptOcrProcessingError when the provider fails or returns empty text.
def extract_receipt_text(storage_path: str) -> str:
    file_path = Path(storage_path)

    if not file_path.is_file():
        raise ReceiptOcrFileNotFoundError()

    try:
        extracted_text = receipt_ocr_provider.extract_text(
            file_path=file_path,
        )
    except ReceiptOcrProcessingError:
        raise
    except Exception as error:
        raise ReceiptOcrProcessingError() from error

    normalized_text = extracted_text.strip()

    if not normalized_text:
        raise ReceiptOcrProcessingError()

    return normalized_text