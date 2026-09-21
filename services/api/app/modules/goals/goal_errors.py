class GoalNotFoundError(Exception):
    """
    Raised when a goal does not exist or does not belong to the user.

    What:
        Represents a missing goal error in the goals module.

    Why:
        Allows repository and service layers to signal that the requested
        goal cannot be found for the authenticated user.
    """

    pass


class GoalInsufficientFundsError(Exception):
    """
    Raised when a withdrawal amount exceeds the goal's current ledger balance.

    What:
        Represents an invalid withdrawal request in the goals module.

    Why:
        A Goal's balance must never become negative. Overfunding above
        target_amount is allowed, but a withdrawal can never remove more
        than the goal actually holds.
    """

    pass