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


class BudgetImmutableFieldError(Exception):
    """
    Raised when a client attempts to change a field that cannot be changed.

    What:
        Represents an attempt to change a budget's currency at any time, or
        its period/start_date after the budget's first period has completed.

    Why:
        These fields define how historical periods are resolved. Changing
        them after periods have already occurred would make past periods
        non-reconstructible.
    """

    pass


class BudgetRetroactiveDeactivationError(Exception):
    """
    Raised when a client attempts to set end_date to a date before today.

    What:
        Represents an attempt to retroactively deactivate a budget.

    Why:
        Setting end_date in the past would erase already-completed periods
        that were previously counted against this budget.
    """

    pass