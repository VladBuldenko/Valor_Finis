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