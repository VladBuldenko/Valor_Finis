class BudgetAlreadyExistsError(Exception):
    """
    Raised when a user tries to create a duplicate budget.

    What:
        Represents a duplicate budget error in the budgets module.

    Why:
        Allows repository and service layers to signal that the user already
        has a budget with the same name, period, and start date.
    """

    pass


class BudgetNotFoundError(Exception):
    """
    Raised when a budget does not exist or does not belong to the user.

    What:
        Represents a missing budget error in the budgets module.

    Why:
        Allows repository and service layers to signal that the requested
        budget cannot be found for the authenticated user.
    """

    pass