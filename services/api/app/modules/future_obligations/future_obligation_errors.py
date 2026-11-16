class FutureObligationNotFoundError(Exception):
    """
    Raised when a future obligation does not exist or does not belong to the user.

    What:
        Represents a missing future obligation. Another user's obligation is
        reported exactly like a missing one, so existence is never revealed.
    """

    pass


class FutureObligationScheduleInvalidError(Exception):
    """
    Raised when the schedule fields of an updated obligation, taken together,
    are invalid.

    What:
        Represents a rejected update (VF-GOALS-PLANNING-002C1): a one-time
        obligation with a final due date, or a final due date before the first
        due date.

    Why:
        An update is validated as the RESULTING state, not field by field, so a
        request that is fine on its own can still be refused because of the
        stored values it is combined with. The message says which rule failed.
    """

    pass


class FutureObligationLimitReachedError(Exception):
    """
    Raised when the user already has the maximum number of active obligations.

    What:
        Represents a refused create or restore (VF-GOALS-PLANNING-002C1).

    Why:
        The upcoming projection reads and calculates every active obligation on
        each request, so the number of active ones is bounded. Archived
        obligations do not count; archive one to make room.
    """

    pass


class FutureObligationIdempotencyConflictError(Exception):
    """
    Raised when a create request reuses a client_request_id that already
    identifies an obligation created from a different request.

    What:
        Represents a create-idempotency conflict. The same key with the same
        original request is an idempotent replay (200); the same key with any
        materially different request is ambiguous and must never silently
        create, or return, a different obligation.
    """

    pass


class FutureObligationClientRequestIdTakenError(Exception):
    """
    Raised by the repository when the insert violates the per-user
    client_request_id unique constraint.

    What:
        Internal signal (never mapped to HTTP): a concurrent create with the
        same key committed first. The service reloads the winner and resolves it
        as a replay or a conflict, so a unique violation never becomes a 500.
    """

    pass
