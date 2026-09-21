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


class GoalCurrencyImmutableError(Exception):
    """
    Raised when an actual currency change is attempted on a goal that
    already has transaction history.

    What:
        Represents an invalid Goal currency change in the goals module.

    Why:
        GoalTransaction rows do not store their own currency. Changing a
        Goal's currency after history exists would silently reinterpret
        every historical ledger amount in a different currency, which is
        invalid. A PATCH that resends the same normalized currency is not
        an actual change and does not raise this error.
    """

    pass


class GoalDeletionNotAllowedError(Exception):
    """
    Raised when deletion is attempted on a goal that has transaction
    history.

    What:
        Represents a forbidden Goal deletion in the goals module.

    Why:
        A Goal with any transaction history (including a withdrawal that
        brought the balance back to 0) must not be hard-deleted, since that
        would silently destroy real financial history. The user can archive
        the goal instead via PATCH status="archived".
    """

    pass