from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.goals import goal_repository, goal_transaction_repository
from app.modules.goals.goal_errors import (
    GoalArchivedError,
    GoalCurrencyImmutableError,
    GoalDeletionNotAllowedError,
    GoalInsufficientFundsError,
    GoalTransactionClientRequestIdTakenError,
    GoalTransactionEffectiveDateInFutureError,
    GoalTransactionIdempotencyConflictError,
)
from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_schemas import (
    GoalCreate,
    GoalResponse,
    GoalUpdate,
)
from app.modules.goals.goal_transaction_models import GoalTransactionModel
from app.modules.goals.goal_transaction_schemas import (
    GoalTransactionCreate,
    GoalTransactionResponse,
)


@dataclass(frozen=True)
class GoalTransactionCreateResult:
    """
    Outcome of create_or_replay_goal_transaction.

    What:
        The transaction's public representation plus whether this call
        created it.

    Why:
        POST /api/v1/goals/{goal_id}/transactions has two successful
        outcomes (VF-020B3) - 201 for a newly created transaction and 200
        for an idempotent replay of an already-created one - and the router
        needs to know which occurred without re-deriving it.

    Fields:
        transaction: the transaction's public representation.
        created: True if this call created the transaction, False for a
            replay.
    """

    transaction: GoalTransactionResponse
    created: bool


# Builds a GoalResponse from a Goal model and an already-computed
# ledger-derived balance.
# This function exists to make the source of current_amount explicit and
# auditable (VF-016D): every public read path must pass in a balance it
# calculated from goal_transactions, never GoalResponse.model_validate(
# goal_model) - the Goal row has no balance column to read in the first
# place (VF-016G), so this is the only way to populate current_amount.
# Parameters:
# - goal_model: the Goal database record (name/target_amount/etc.).
# - current_amount: ledger-derived balance to report for this goal.
# Returns:
# - GoalResponse with current_amount set to the given ledger balance.
def _build_goal_response(
    goal_model: GoalModel,
    current_amount: Decimal,
) -> GoalResponse:
    return GoalResponse(
        id=goal_model.id,
        user_id=goal_model.user_id,
        name=goal_model.name,
        target_amount=goal_model.target_amount,
        current_amount=current_amount,
        currency=goal_model.currency,
        target_date=goal_model.target_date,
        status=goal_model.status,
        created_at=goal_model.created_at,
        updated_at=goal_model.updated_at,
    )


# Creates a new financial goal using validated input data and authenticated user id.
# This function exists to keep application and business logic
# separate from database and HTTP layers.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_data: validated goal creation data.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - GoalResponse created from the saved database model, with a
#   ledger-derived current_amount (always 0.00 for a brand new goal, since
#   it cannot have any transactions yet - but this still goes through the
#   same authoritative-read calculation as every other Goal response).
def create_goal(
    db_session: Session,
    goal_data: GoalCreate,
    user_id: UUID,
) -> GoalResponse:
    goal_model = goal_repository.create_goal(
        db_session=db_session,
        goal_data=goal_data,
        user_id=user_id,
    )

    current_amount = goal_transaction_repository.calculate_ledger_balance(
        db_session=db_session,
        goal_id=goal_model.id,
        user_id=user_id,
    )

    return _build_goal_response(goal_model, current_amount)


# Returns financial goals for the authenticated user.
# This function exists to map database models to public API responses
# and to ensure service-level reads are always scoped to a user.
# current_amount is ledger-derived (VF-016D): one bulk grouped query
# fetches every one of the user's goal balances up front, so this never
# issues one balance query per Goal no matter how many goals are returned.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter goals.
# Returns:
# - List of GoalResponse objects, ordered exactly as
#   goal_repository.get_goals returns them (created_at DESC).
def get_goals(
    db_session: Session,
    user_id: UUID,
) -> list[GoalResponse]:
    goal_models = goal_repository.get_goals(
        db_session=db_session,
        user_id=user_id,
    )

    balances = goal_transaction_repository.get_ledger_balances_for_user(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        _build_goal_response(
            goal_model,
            balances.get(goal_model.id, Decimal("0.00")),
        )
        for goal_model in goal_models
    ]


# Updates an existing financial goal owned by the authenticated user,
# enforcing currency immutability once transaction history exists.
# This function exists to keep update business flow in the service layer
# and response mapping outside the repository layer. current_amount in the
# returned response is ledger-derived (VF-016D): the Goal row itself has no
# balance column to update, so the response is always computed fresh from
# goal_transactions after applying the metadata change.
#
# Concurrency/TOCTOU safety (VF-016E): the Goal row is locked with
# SELECT ... FOR UPDATE *before* the history check, in the same database
# transaction as the check and the update. This serializes against
# create_goal_transaction's own row lock, so a currency change and the
# Goal's first transaction can never both "see" a history-free Goal and
# both succeed - whichever acquires the lock first determines the outcome
# for the other.
#
# Currency immutability rule: only an *actual* change is checked against
# history. goal_data.currency is already normalized by GoalUpdate's own
# validator (e.g. "eur" -> "EUR") by the time it reaches this function, so
# resending the Goal's current currency (in any casing) after history
# exists is a no-op and is allowed, not rejected.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier.
# - goal_data: validated partial goal update data.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - GoalResponse created from the updated database model, with a
#   ledger-derived current_amount.
# Raises:
# - GoalNotFoundError: when goal does not exist or does not belong to the user.
# - GoalCurrencyImmutableError: when currency is actually changing and the
#   goal already has transaction history.
def update_goal(
    db_session: Session,
    goal_id: UUID,
    goal_data: GoalUpdate,
    user_id: UUID,
) -> GoalResponse:
    goal_model = goal_repository.get_goal_by_id_for_update(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )

    if "currency" in goal_data.model_fields_set:
        is_actual_currency_change = goal_data.currency != goal_model.currency

        if is_actual_currency_change:
            has_history = goal_transaction_repository.has_transactions_for_goal(
                db_session=db_session,
                goal_id=goal_id,
                user_id=user_id,
            )

            if has_history:
                db_session.rollback()
                raise GoalCurrencyImmutableError()

    goal_model = goal_repository.apply_goal_update(
        db_session=db_session,
        goal_model=goal_model,
        goal_data=goal_data,
    )

    current_amount = goal_transaction_repository.calculate_ledger_balance(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )

    return _build_goal_response(goal_model, current_amount)


# Deletes an existing financial goal owned by the authenticated user,
# refusing to delete a goal that has any transaction history.
# This function exists to keep delete business flow in the service layer
# and to avoid exposing repository calls directly to the router. Any
# transaction (opening_balance, contribution, or withdrawal) counts as
# history, even a withdrawal that brought the ledger balance back to
# exactly 0 - balance is never used as a proxy for "no history" (VF-016E).
# A user who wants to stop using a history-bearing Goal must archive it
# via PATCH status="archived" instead.
#
# Concurrency/TOCTOU safety: the Goal row is locked with
# SELECT ... FOR UPDATE *before* the history check, in the same database
# transaction as the check and the delete. This serializes against
# create_goal_transaction's own row lock: whichever of "delete this Goal"
# or "create its first transaction" acquires the lock first determines the
# outcome - either the Goal is deleted and the later transaction attempt
# gets GoalNotFoundError, or the transaction is created first and the
# later delete attempt sees history and gets GoalDeletionNotAllowedError.
# The existing FK RESTRICT on goal_transactions.goal_id remains as
# defense-in-depth and must never surface as a raw IntegrityError/500.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - None.
# Raises:
# - GoalNotFoundError: when goal does not exist or does not belong to the user.
# - GoalDeletionNotAllowedError: when the goal has any transaction history.
def delete_goal(
    db_session: Session,
    goal_id: UUID,
    user_id: UUID,
) -> None:
    goal_model = goal_repository.get_goal_by_id_for_update(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )

    has_history = goal_transaction_repository.has_transactions_for_goal(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )

    if has_history:
        db_session.rollback()
        raise GoalDeletionNotAllowedError()

    goal_repository.delete_locked_goal(
        db_session=db_session,
        goal_model=goal_model,
    )


# Returns whether a stored goal transaction was created from exactly this
# create request's payload.
# This function exists as the single definition of "same payload" for goal
# transaction create idempotency (VF-020B3):
# - goal_id, type and description must be equal. description is compared
#   as-is because the create path never normalizes it - it is stored
#   exactly as sent - so None and "" are different payloads, the same rule
#   AccountTransfer idempotency uses.
# - amount is compared as Decimal, so "10" equals the stored "10.00".
# - effective_date is compared only when this request states one. An
#   omitted (or null) effective_date means "the server date at creation";
#   recomputing today and comparing it would turn a retry after midnight
#   into a false conflict, so it is ignored and the original date stands.
# client_request_id and user_id already matched through the lookup that
# found the transaction.
# Parameters:
# - transaction_model: the stored transaction found by (user_id,
#   client_request_id).
# - goal_id: goal identifier from the current request path.
# - transaction_data: the validated create request.
# Returns:
# - True if every compared field matches.
def _matches_original_transaction_request(
    transaction_model: GoalTransactionModel,
    goal_id: UUID,
    transaction_data: GoalTransactionCreate,
) -> bool:
    if (
        transaction_data.effective_date is not None
        and transaction_model.effective_date != transaction_data.effective_date
    ):
        return False

    return (
        transaction_model.goal_id == goal_id
        and transaction_model.type == transaction_data.type
        and transaction_model.amount == transaction_data.amount
        and transaction_model.description == transaction_data.description
    )


# Resolves a create request whose client_request_id already identifies a
# stored goal transaction.
# This function exists so every idempotency path (fast lookup, second
# lookup under the goal lock, unique-violation recovery) resolves an
# existing transaction identically. It never looks at the goal's current
# state: once the transaction exists, an exact replay returns it even if
# the goal was archived or its balance dropped since - a replay is not a
# new contribution or withdrawal.
# Parameters:
# - transaction_model: the stored transaction found by (user_id,
#   client_request_id).
# - goal_id: goal identifier from the current request path.
# - transaction_data: the validated create request.
# Returns:
# - GoalTransactionCreateResult with created=False.
# Raises:
# - GoalTransactionIdempotencyConflictError: the stored transaction came
#   from a different payload.
def _resolve_existing_transaction(
    transaction_model: GoalTransactionModel,
    goal_id: UUID,
    transaction_data: GoalTransactionCreate,
) -> GoalTransactionCreateResult:
    if not _matches_original_transaction_request(transaction_model, goal_id, transaction_data):
        raise GoalTransactionIdempotencyConflictError()

    return GoalTransactionCreateResult(
        transaction=GoalTransactionResponse.model_validate(transaction_model),
        created=False,
    )


# Creates a contribution or withdrawal transaction for a goal owned by the
# authenticated user, idempotently when the request carries a
# client_request_id.
# This function exists as the single write path for balance-changing goal
# transactions (VF-016C). The whole write is one service-owned database
# transaction:
#   1. with a key: fast lookup by (user_id, client_request_id), no row
#      locks - an existing transaction is resolved as replay (200) or
#      conflict (409) FIRST, before any other validation: a key that is
#      already bound always answers for its original payload, so a replay
#      stating a different (even future) effective_date is a 409, and goal
#      lifecycle and balance are never re-checked (VF-020B3). When nothing
#      is found, the lookup's transaction is ended so the goal is always
#      locked before goal_transactions is touched;
#   2. only for a new request (no key, or a key not yet used): reject a
#      future effective_date (422) - before the goal lookup, so an invalid
#      date is 422 rather than 404;
#   3. lock the owned Goal row (SELECT ... FOR UPDATE; missing or foreign
#      goal -> 404) so two concurrent writes never validate against the
#      same stale balance;
#   4. with a key: second lookup under the goal lock - a same-key request
#      for this goal may have committed while this one waited - resolved
#      exactly like step 1;
#   5. reject a contribution to an archived goal (VF-020A P10);
#   6. calculate the current ledger balance; reject a withdrawal that would
#      take it negative;
#   7. insert the append-only transaction with currency copied from the
#      locked goal (never from the client), the resolved effective_date
#      (omitted -> server date) and the key;
#   8. commit once;
#   9. if the insert hits uq_goal_transactions_user_id_client_request_id (a
#      concurrent same-key request for ANOTHER goal, not serialized by this
#      goal's lock, inserted first), roll back, reload the winner and
#      resolve it like step 1.
# Without a key, steps 1, 4 and 9 do not apply: every request creates a new
# transaction (legacy clients; the key stays NULL - none is synthesized).
# The Goal row itself is never written here (VF-016G); the row lock still
# serializes this write against concurrent writes, archive and delete on
# the same goal. Archived-goal rule (VF-020B1): an archived goal accepts
# withdrawals but no new contributions; active and completed goals accept
# both.
#
# "today" is the server date, resolved once per call (the same notion
# AccountTransfer uses); as_of exists so tests can pin it.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier.
# - transaction_data: validated contribution/withdrawal request data.
# - user_id: authenticated user identifier that owns the goal.
# - as_of: optional reference "today"; defaults to date.today().
# Returns:
# - GoalTransactionCreateResult - created=True for a new transaction,
#   created=False for an idempotent replay.
# Raises:
# - GoalTransactionEffectiveDateInFutureError: effective_date > today on a
#   new request (a bound key resolves as replay or conflict instead).
# - GoalTransactionIdempotencyConflictError: the key was used for a
#   different payload.
# - GoalNotFoundError: when goal does not exist or does not belong to the user.
# - GoalArchivedError: when a new contribution targets an archived goal.
# - GoalInsufficientFundsError: when a new withdrawal exceeds the balance.
def create_or_replay_goal_transaction(
    db_session: Session,
    goal_id: UUID,
    transaction_data: GoalTransactionCreate,
    user_id: UUID,
    as_of: Optional[date] = None,
) -> GoalTransactionCreateResult:
    today = as_of if as_of is not None else date.today()
    requested_date = transaction_data.effective_date
    client_request_id = transaction_data.client_request_id

    if client_request_id is not None:
        existing_transaction = goal_transaction_repository.get_transaction_by_client_request_id(
            db_session=db_session,
            user_id=user_id,
            client_request_id=client_request_id,
        )

        if existing_transaction is not None:
            return _resolve_existing_transaction(existing_transaction, goal_id, transaction_data)

        # End the read-only lookup transaction before locking the goal: the
        # lookup holds a table lock on goal_transactions until the
        # transaction ends, and every write path (and the VF-020B2 migration
        # order) takes goals first, then goal_transactions. Keeping it would
        # invert that order and could deadlock with a migration that locks
        # both tables.
        db_session.rollback()

    if requested_date is not None and requested_date > today:
        raise GoalTransactionEffectiveDateInFutureError()

    goal_model = goal_repository.get_goal_by_id_for_update(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )

    if client_request_id is not None:
        existing_transaction = goal_transaction_repository.get_transaction_by_client_request_id(
            db_session=db_session,
            user_id=user_id,
            client_request_id=client_request_id,
        )

        if existing_transaction is not None:
            try:
                return _resolve_existing_transaction(
                    existing_transaction, goal_id, transaction_data,
                )
            finally:
                # Nothing was written; release the goal lock taken above.
                db_session.rollback()

    if goal_model.status == "archived" and transaction_data.type == "contribution":
        db_session.rollback()
        raise GoalArchivedError()

    current_balance = goal_transaction_repository.calculate_ledger_balance(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )

    if (
        transaction_data.type == "withdrawal"
        and transaction_data.amount > current_balance
    ):
        db_session.rollback()
        raise GoalInsufficientFundsError()

    try:
        transaction_model = goal_transaction_repository.create_transaction(
            db_session=db_session,
            goal_id=goal_id,
            user_id=user_id,
            type=transaction_data.type,
            amount=transaction_data.amount,
            description=transaction_data.description,
            currency=goal_model.currency,
            effective_date=requested_date if requested_date is not None else today,
            client_request_id=client_request_id,
            commit=False,
        )

        db_session.commit()
    except GoalTransactionClientRequestIdTakenError:
        db_session.rollback()

        winning_transaction = goal_transaction_repository.get_transaction_by_client_request_id(
            db_session=db_session,
            user_id=user_id,
            client_request_id=client_request_id,
        )

        if winning_transaction is None:
            # The unique violation proves a same-key transaction committed,
            # so failing to reload it is an unexpected state - never
            # fabricate a result; surface the original error.
            raise

        return _resolve_existing_transaction(winning_transaction, goal_id, transaction_data)
    except Exception:
        db_session.rollback()
        raise

    db_session.refresh(transaction_model)

    return GoalTransactionCreateResult(
        transaction=GoalTransactionResponse.model_validate(transaction_model),
        created=True,
    )


# Creates a contribution or withdrawal transaction and returns only the
# transaction.
# This function exists for callers that do not need the 201/200 create
# versus replay distinction; it delegates to
# create_or_replay_goal_transaction, the single write path, unchanged.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier.
# - transaction_data: validated contribution/withdrawal request data.
# - user_id: authenticated user identifier that owns the goal.
# - as_of: optional reference "today"; defaults to date.today().
# Returns:
# - GoalTransactionResponse for the created (or replayed) transaction.
# Raises:
# - The same domain errors as create_or_replay_goal_transaction.
def create_goal_transaction(
    db_session: Session,
    goal_id: UUID,
    transaction_data: GoalTransactionCreate,
    user_id: UUID,
    as_of: Optional[date] = None,
) -> GoalTransactionResponse:
    return create_or_replay_goal_transaction(
        db_session=db_session,
        goal_id=goal_id,
        transaction_data=transaction_data,
        user_id=user_id,
        as_of=as_of,
    ).transaction


# Returns the full transaction history for a goal owned by the
# authenticated user.
# This function exists to enforce ownership before ever touching the
# ledger: another user's Goal must behave as not found, never leaking
# whether it exists.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier.
# - user_id: authenticated user identifier that owns the goal.
# Returns:
# - List of GoalTransactionResponse objects, newest first.
# Raises:
# - GoalNotFoundError: when goal does not exist or does not belong to the user.
def get_goal_transactions(
    db_session: Session,
    goal_id: UUID,
    user_id: UUID,
) -> list[GoalTransactionResponse]:
    goal_repository.get_goal_by_id(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )

    transaction_models = goal_transaction_repository.get_transactions_for_goal(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
    )

    return [
        GoalTransactionResponse.model_validate(transaction_model)
        for transaction_model in transaction_models
    ]