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


class IncomeAccountCurrencyMismatchError(Exception):
    """
    Raised when linking (creating, attaching, or moving) an Income to an
    Account whose currency does not match the Income's own currency.

    What:
        Represents a rejected Income<->Account link in the income module.

    Why:
        VF-017D allows linking only on an exact currency match, after
        normalization - no FX conversion happens between Income and
        Account (that is a separate, unrelated concern from Income's own
        base-currency FX snapshot, which is untouched by linking). Never
        raised for an Income that stays unlinked, and never triggers a
        silent auto-detach when it fires on an update - the client must
        explicitly choose to detach first if they want to change currency
        away from the linked Account's own currency.
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
