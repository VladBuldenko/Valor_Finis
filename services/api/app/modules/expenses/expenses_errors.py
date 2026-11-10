class ExpenseNotFoundError(Exception):
    """
    Raised when an expense does not exist or does not belong to the user.

    What:
        Represents a missing expense error in the expenses module.

    Why:
        Allows the repository and service layers to signal that the requested
        expense cannot be found for the authenticated user.
    """

    pass


class ExpenseAccountCurrencyMismatchError(Exception):
    """
    Raised when linking (creating, attaching, or moving) an Expense to an
    Account whose currency does not match the Expense's own currency.

    What:
        Represents a rejected Expense<->Account link in the expenses
        module.

    Why:
        VF-017E allows linking only on an exact currency match, after
        normalization - no FX conversion happens between Expense and
        Account (that is a separate, unrelated concern from Expense's own
        base-currency FX snapshot, which is untouched by linking; the
        ledger always uses Expense.amount/currency, never base_amount).
        Never raised for an Expense that stays unlinked, and never
        triggers a silent auto-detach when it fires on an update - the
        client must explicitly choose to detach first if they want to
        change currency away from the linked Account's own currency.
        Mirrors IncomeAccountCurrencyMismatchError one-for-one.
    """

    pass

class ExpenseIdempotencyConflictError(Exception):
    """
    Raised when a create request reuses a client_request_id that already
    identifies a expense created from a different request.

    What:
        Represents a create-idempotency conflict (VF-MVP-CORE-002).

    Why:
        The same key with the same original request is an idempotent replay
        (200); the same key with any materially different request is
        ambiguous and must never silently create, or return, a different
        expense. The message never echoes either request.
    """

    pass


class ExpenseClientRequestIdTakenError(Exception):
    """
    Raised by the repository when the insert violates the per-user
    client_request_id unique constraint.

    What:
        Internal signal (never mapped to HTTP): a concurrent create with the
        same key committed first.

    Why:
        The service reacts by reloading the winner and resolving it as a
        replay or a conflict, so a unique violation never surfaces as a 500.
    """

    pass
