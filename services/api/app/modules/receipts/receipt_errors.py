class ReceiptNotFoundError(Exception):
    """
    Raised when a receipt does not exist or does not belong to the user.

    What:
        Represents a missing receipt error in the receipts module.

    Why:
        Allows repository and service layers to signal that the requested
        receipt cannot be found for the authenticated user.
    """

    pass


class ReceiptExpenseNotFoundError(Exception):
    """
    Raised when a receipt is linked to an expense that does not belong to the user.

    What:
        Represents an invalid receipt-to-expense link.

    Why:
        Prevents users from linking their receipts to expenses owned by another user.
    """

    pass

class ReceiptFileEmptyError(Exception):
    """
    Raised when an uploaded receipt file contains no data.

    What:
        Represents an empty receipt upload.

    Why:
        Prevents the application from storing invalid zero-byte receipt files.
    """

    pass


class ReceiptFileTypeNotAllowedError(Exception):
    """
    Raised when an uploaded receipt file type is not supported.

    What:
        Represents an unsupported receipt MIME type or file extension.

    Why:
        Prevents unsupported or potentially unsafe files from being stored.
    """

    pass


class ReceiptFileTooLargeError(Exception):
    """
    Raised when an uploaded receipt file exceeds the configured size limit.

    What:
        Represents a receipt upload that is larger than the allowed maximum.

    Why:
        Protects the application from excessive storage and memory usage.
    """

    pass


class ReceiptFileStorageError(Exception):
    """
    Raised when a receipt file storage operation fails.

    What:
        Represents an unexpected filesystem operation failure.

    Why:
        Allows storage failures to be handled without exposing
        filesystem implementation details to the API layer.
    """

    pass

class ReceiptProcessingNotAllowedError(Exception):
    """
    Raised when a receipt cannot be processed in its current state.

    What:
        Represents an invalid receipt status transition.

    Why:
        Prevents already processed, confirmed, or currently processing
        receipts from starting OCR processing again.
    """

    pass


class ReceiptOcrFileNotFoundError(Exception):
    """
    Raised when the stored receipt file cannot be found.

    What:
        Represents a missing receipt file required for OCR processing.

    Why:
        Prevents OCR processing from starting without an available source file.
    """

    pass


class ReceiptOcrProcessingError(Exception):
    """
    Raised when OCR processing cannot extract usable text.

    What:
        Represents an OCR provider failure or an empty OCR result.

    Why:
        Allows the service and router layers to handle OCR failures
        without exposing provider implementation details.
    """

    pass