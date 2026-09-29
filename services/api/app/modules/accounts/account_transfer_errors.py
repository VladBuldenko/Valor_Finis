class AccountTransferNotFoundError(Exception):
    """
    Raised when an account transfer does not exist or does not belong to
    the user.

    What:
        Represents a missing account transfer in the accounts module.

    Why:
        Allows repository and service layers to signal that the requested
        transfer cannot be found for the authenticated user. Another user's
        transfer behaves exactly like a missing one, never leaking whether
        it exists.
    """

    pass
