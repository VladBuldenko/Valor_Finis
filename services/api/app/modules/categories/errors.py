class CategoryAlreadyExistsError(Exception):
    """
    Raised when a category with the same name already exists for the same user.

    What:
        Represents a duplicate category creation or update attempt.

    Why:
        Keeps database-specific errors separated from HTTP response handling.
    """

    pass


class CategoryNotFoundError(Exception):
    """
    Raised when a category does not exist or does not belong to the user.

    What:
        Represents a failed category lookup by category id and user id.

    Why:
        Keeps ownership and lookup errors separated from HTTP response handling.
    """

    pass

class CategoryDefaultModificationNotAllowedError(Exception):
    """
    Raised when a default category is modified.

    What:
        Represents an attempt to update a protected default category.

    Why:
        Default categories are managed by the backend
        and must remain stable for the user.
    """

    pass


class CategoryDefaultDeletionNotAllowedError(Exception):
    """
    Raised when a default category is deleted.

    What:
        Represents an attempt to delete a protected default category.

    Why:
        Default categories must remain available
        and cannot be removed by the user.
    """

    pass