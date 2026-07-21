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


class GoalInvalidAmountError(Exception):
    """
    Raised when current_amount is greater than target_amount.

    What:
        Represents an invalid financial goal amount state.

    Why:
        Prevents saving a goal where the already saved amount is greater
        than the target amount.
    """

    pass