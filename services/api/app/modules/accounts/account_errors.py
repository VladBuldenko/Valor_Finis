class AccountNotFoundError(Exception):
    """
    Raised when an account does not exist or does not belong to the user.

    What:
        Represents a missing account error in the accounts module.

    Why:
        Allows repository and service layers to signal that the requested
        account cannot be found for the authenticated user.
    """

    pass


class AccountCurrencyImmutableError(Exception):
    """
    Raised when an actual currency change is attempted on an account that
    already has transaction history.

    What:
        Represents an invalid Account currency change in the accounts
        module.

    Why:
        AccountTransaction rows do not store their own currency. Changing
        an Account's currency after history exists would silently
        reinterpret every historical ledger amount in a different
        currency, which is invalid. A PATCH that resends the same
        normalized currency is not an actual change and does not raise
        this error.
    """

    pass


class AccountDeletionNotAllowedError(Exception):
    """
    Raised when deletion is attempted on an account that has transaction
    history.

    What:
        Represents a forbidden Account deletion in the accounts module.

    Why:
        An Account with any transaction history must not be hard-deleted,
        since that would silently destroy real financial history. The
        user can archive the account instead via PATCH status="archived".
    """

    pass


class AccountArchivedError(Exception):
    """
    Raised when a new direct transaction is attempted on an archived
    account.

    What:
        Represents a rejected write to an archived Account in the accounts
        module.

    Why:
        Archiving is meant to freeze an account's ledger going forward
        while keeping its existing balance and history fully readable.
        Reactivating the account (PATCH status="active") is the only way
        to resume accepting new transactions.
    """

    pass
