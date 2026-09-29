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


class AccountTransferIdempotencyConflictError(Exception):
    """
    Raised when a create request reuses a client_request_id that already
    identifies a transfer created from a different payload.

    What:
        Represents a create-idempotency conflict in the accounts module
        (VF-018C).

    Why:
        The same key with the same original payload is an idempotent
        replay (200); the same key with any different payload is ambiguous
        and must never silently create or return a different transfer. The
        existing transfer is not revealed.
    """

    pass


class AccountTransferCurrencyMismatchError(Exception):
    """
    Raised when a new transfer's source and destination Accounts use
    different currencies.

    What:
        Represents a rejected cross-currency transfer in the accounts
        module (VF-018C).

    Why:
        Transfers are same-currency only (no FX conversion). The transfer
        currency is derived from the Accounts, so a mismatch cannot be
        resolved by the client choosing a currency.
    """

    pass


class AccountTransferClientRequestIdTakenError(Exception):
    """
    Internal signal: inserting a transfer violated
    uq_account_transfers_user_id_client_request_id.

    What:
        Raised by account_transfer_repository.create_account_transfer when
        the flush fails on the create-idempotency unique constraint, and
        only that constraint. The original IntegrityError is chained as
        __cause__.

    Why:
        Two concurrent creates with the same key (possibly for completely
        different Accounts, so not serialized by any Account lock) can both
        miss the idempotency lookups; the database unique constraint is the
        final race defense. The service catches this signal, rolls back,
        reloads the winning transfer, and resolves it as a replay or a
        conflict. It is never mapped to an HTTP response.
    """

    pass


class AccountTransferAlreadyPostedError(Exception):
    """
    Raised when manual posting is requested for a transfer that is not
    planned (VF-018D).

    What:
        Represents a rejected planned -> posted transition in the accounts
        module.

    Why:
        planned -> posted is the only transition and it happens at most
        once. Posting is deliberately not idempotent (it has no request
        key): a repeated post - e.g. a retry after a lost response - gets a
        409 and the client refetches the transfer, which already shows
        posted. It never creates a second pair of ledger projections.
    """

    pass


class AccountTransferEffectiveDateInFutureError(Exception):
    """
    Raised when manual posting names an effective_date after the server
    date (VF-018D).

    What:
        Represents an invalid posting date in the accounts module.

    Why:
        effective_date becomes the transaction_date of both ledger
        projections, and the posted ledger must never contain a
        future-dated transfer row. This single rule replaces any "not yet
        due" restriction: posting before or after planned_date is allowed.
        It is checked before the transfer is looked up, so it takes
        precedence over 404/409.
    """

    pass
