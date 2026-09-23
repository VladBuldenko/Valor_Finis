class IncomeNotFoundError(Exception):
    """
    Raised when an income record does not exist or does not belong to the
    user.

    What:
        Represents a missing income error in the income module.

    Why:
        Allows the repository and service layers to signal that the
        requested income record cannot be found for the authenticated
        user.
    """

    pass


class IncomeFutureDatedNotSupportedError(Exception):
    """
    Raised when a foreign-currency income is dated in the future.

    What:
        Represents an attempt to resolve a historical FX snapshot for an
        income received_at date that has not happened yet.

    Why:
        Mirrors expenses' FxFutureDatedNotSupportedError one-for-one: a
        future rate does not exist, and using today's rate as an estimate
        would create a fake, immutable "historical" snapshot
        indistinguishable later from a real one. This is a distinct
        error class (not a reuse of FxFutureDatedNotSupportedError)
        purely so the two domains can carry their own public error
        message ("income" vs "expense") - the underlying FX resolution
        that raises the shared fx_service.FxFutureDatedNotSupportedError
        is identical, unmodified FX architecture; income_service simply
        translates it to this domain-specific error before it reaches the
        client. Base-currency income is unaffected (identity conversion
        needs no rate).
    """

    pass
