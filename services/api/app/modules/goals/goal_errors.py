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


class GoalArchivedError(Exception):
    """
    Raised when a contribution is attempted on an archived goal.

    What:
        Represents a forbidden contribution in the goals module.

    Why:
        An archived goal is retired (VF-020A P10): it keeps its full
        transaction history and still allows withdrawals, but it must not
        receive new money. The check runs in the service while the goal row
        is locked, so it cannot race with a concurrent archive.
    """

    pass


class GoalCurrencyImmutableError(Exception):
    """
    Raised when an actual currency change is attempted on a goal that
    already has transaction history.

    What:
        Represents an invalid Goal currency change in the goals module.

    Why:
        Every GoalTransaction amount is expressed in its Goal's currency
        (since VF-020B3 each new row also stores a copy of it). Changing a
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


class GoalTransactionIdempotencyConflictError(Exception):
    """
    Raised when a create request reuses a client_request_id that already
    identifies a goal transaction created from a different payload.

    What:
        Represents a create-idempotency conflict in the goals module
        (VF-020B3).

    Why:
        The same key with the same original payload is an idempotent
        replay (200); the same key with any different payload is ambiguous
        and must never silently create or return a different transaction.
        The existing transaction is not revealed.
    """

    pass


class GoalTransactionClientRequestIdTakenError(Exception):
    """
    Raised by the repository when inserting a goal transaction violates
    uq_goal_transactions_user_id_client_request_id.

    What:
        Internal signal from the goal transaction repository to the
        service (VF-020B3); never mapped to an HTTP response.

    Why:
        A concurrent request with the same (user_id, client_request_id)
        committed first - possibly for another goal, so the goal row lock
        did not serialize the two. The service rolls back, reloads the
        winning row and resolves the request as a replay or a conflict, so
        a raw IntegrityError never reaches the client.
    """

    pass


class GoalTransactionEffectiveDateInFutureError(Exception):
    """
    Raised when a goal transaction names an effective_date after the
    server date.

    What:
        Represents an invalid business date in the goals module
        (VF-020B3, VF-020A P13).

    Why:
        effective_date records when the money actually moved, so it can be
        today or any past date but never a future one. It applies to new
        requests only: a client_request_id that already identifies a stored
        transaction is resolved first, as a replay or an idempotency
        conflict (409). For a new request it is checked before the goal is
        looked up, so it takes precedence over 404 and lifecycle 409s.
    """

    pass
