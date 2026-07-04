class CategoryAlreadyExistsError(Exception):
    """
    Raised when a category with the same name already exists for the same user.

    What:
        Represents a duplicate category creation attempt.

    Why:
        Keeps database-specific errors separated from HTTP response handling.
    """

    pass