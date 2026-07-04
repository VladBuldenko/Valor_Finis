class BudgetAlreadyExistsError(Exception):
    """
    Raised when a user tries to create a duplicate budget.

    What:
        Represents an attempt to create a budget with the same
        user, name, period, and start date.

    Why:
        Keeps database-specific duplicate errors separated
        from HTTP response handling.
    """

    pass