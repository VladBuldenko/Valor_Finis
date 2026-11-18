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


# ---------------------------------------------------------------------------
# VF-GOALS-PLANNING-002C2: manual reconciliation of a bill occurrence with an
# existing recorded Expense. A link is relationship metadata: it never creates
# an Expense, posts to an Account, or says a bank payment was verified.
# ---------------------------------------------------------------------------


class FutureObligationOccurrenceInvalidError(Exception):
    """
    Raised when the requested due date is not an occurrence of the obligation.

    What:
        Represents a rejected link request: the date is not on the obligation's
        schedule (including a month-end date that is not the clamped one), or the
        obligation is archived, which contributes no occurrences.
    """

    pass


class FutureObligationLinkCurrencyMismatchError(Exception):
    """
    Raised when the Expense and the obligation are in different currencies.

    What:
        Represents a rejected link: only an exact currency match can be linked.
        Nothing is converted.
    """

    pass


class FutureObligationLinkAmountMismatchError(Exception):
    """
    Raised when the Expense amount is not exactly the occurrence amount.

    What:
        Represents a rejected link: amounts are compared as exact Decimals. A
        matching amount is a precondition, never proof that the records
        correspond; the user makes the choice.
    """

    pass


class FutureObligationLinkExpenseDateError(Exception):
    """
    Raised when the Expense is recorded after the evaluation date.

    What:
        Represents a rejected link: an Expense dated in the future has not
        happened yet, so it cannot correspond to an occurrence.
    """

    pass


class FutureObligationLinkExpenseAlreadyLinkedError(Exception):
    """
    Raised when the Expense is already linked to a different occurrence.

    What:
        One Expense can correspond to only one occurrence. The existing link is
        never silently replaced: it must be removed first.
    """

    pass


class FutureObligationLinkOccurrenceAlreadyLinkedError(Exception):
    """
    Raised when the occurrence is already linked to a different Expense.

    What:
        One occurrence can have only one Expense. The existing link is never
        silently reassigned: it must be removed first.
    """

    pass


class FutureObligationLinkNotFoundError(Exception):
    """
    Raised when a link does not exist or does not belong to the user.

    What:
        Another user's link is reported exactly like a missing one.
    """

    pass


class ExpenseLinkedToFutureObligationError(Exception):
    """
    Raised when a change to an Expense would invalidate its occurrence link.

    What:
        Represents a controlled conflict: deleting a linked Expense, or changing
        its amount or currency, or dating it in the future. Non-financial edits
        are never blocked. The user must remove the link first.
    """

    pass


class FutureObligationHasLinkedOccurrencesError(Exception):
    """
    Raised when an obligation edit would invalidate a linked occurrence.

    What:
        Represents a controlled conflict: changing the amount or currency of an
        obligation that has linked occurrences, or moving its dates so a linked
        due date is no longer on the schedule. Renaming, describing, archiving and
        restoring are never blocked. The user must remove the affected links first.
    """

    pass


class FutureObligationLinkUniqueViolationError(Exception):
    """
    Raised by the repository when an insert violates a link unique constraint.

    What:
        Internal signal (never mapped to HTTP): a concurrent request committed a
        conflicting link first. `constraint_name` says which rule was violated, so
        the service can answer with the matching domain error and never a 500.
    """

    def __init__(self, constraint_name: str) -> None:
        super().__init__(constraint_name)
        self.constraint_name = constraint_name
