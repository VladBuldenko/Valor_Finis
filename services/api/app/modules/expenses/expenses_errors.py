class ExpenseNotFoundError(Exception):
    """
    Raised when an expense does not exist or does not belong to the user.

    What:
        Represents a missing expense error in the expenses module.

    Why:
        Allows the repository and service layers to signal that the requested
        expense cannot be found for the authenticated user.
    """

    pass