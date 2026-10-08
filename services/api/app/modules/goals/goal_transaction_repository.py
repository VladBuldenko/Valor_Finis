from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.goals.goal_errors import (
    GoalAccountLinkInvalidError,
    GoalTransactionClientRequestIdTakenError,
)
from app.modules.goals.goal_transaction_models import GoalTransactionModel

# The create-idempotency unique constraint (VF-020B2, used since VF-020B3).
# Only a violation of exactly this constraint is translated into
# GoalTransactionClientRequestIdTakenError; every other IntegrityError
# propagates unchanged.
CLIENT_REQUEST_ID_UNIQUE_CONSTRAINT = "uq_goal_transactions_user_id_client_request_id"

# The Account link foreign key (VF-020C1). A violation on insert means the
# named Account vanished or changed currency after the service validated it;
# the service layer locks the Account first, so this is a backstop only.
ACCOUNT_LINK_FK_CONSTRAINT = "fk_goal_transactions_account_id_user_id_currency"


# Calculates a goal's ledger balance from its transaction history.
# This function exists as the single source of truth for "what does the
# ledger say this Goal is worth right now" - opening_balance and
# contribution rows add to the balance, withdrawal rows subtract from it.
# A goal with no transactions has a balance of exactly Decimal("0.00").
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier to sum transactions for.
# - user_id: authenticated user identifier that owns the goal, used as a
#   defense-in-depth filter alongside goal_id.
# Returns:
# - Decimal ledger balance for the goal.
def calculate_ledger_balance(
    db_session: Session,
    goal_id: UUID,
    user_id: UUID,
) -> Decimal:
    transactions = (
        db_session.query(GoalTransactionModel)
        .filter(
            GoalTransactionModel.goal_id == goal_id,
            GoalTransactionModel.user_id == user_id,
        )
        .all()
    )

    balance = Decimal("0.00")

    for transaction in transactions:
        if transaction.type == "withdrawal":
            balance -= transaction.amount
        else:
            balance += transaction.amount

    return balance


# Creates and saves a new append-only goal transaction record.
# This function exists to isolate PostgreSQL write operations for the
# ledger from business logic and HTTP handling. It never commits by
# default so the caller (goal_service) can keep this insert inside the
# same service-controlled database transaction as the owned Goal row lock
# it acquired first (SELECT ... FOR UPDATE) - the lock must stay held until
# the insert itself commits. It persists exactly the values it is given:
# the caller decides currency (always the owning goal's) and effective_date.
# A duplicate (user_id, client_request_id) fails the flush on
# uq_goal_transactions_user_id_client_request_id; that one constraint is
# re-raised as GoalTransactionClientRequestIdTakenError (identified by
# PostgreSQL constraint metadata, never by message text - the same pattern
# account_transfer_repository uses) so the service can resolve the race as
# a replay or a conflict. Every other IntegrityError propagates unchanged.
# The session is left in its failed state: rolling back belongs to the
# caller, which owns the transaction.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal this transaction belongs to.
# - user_id: authenticated user identifier that owns the goal.
# - type: one of "opening_balance", "contribution", "withdrawal".
# - amount: always positive; direction is carried by type.
# - description: optional free-text note.
# - currency: the owning goal's currency.
# - effective_date: business date of the transaction (None only for
#   rows that represent history without a known date).
# - client_request_id: optional client-generated idempotency key.
# - account_id: Account the row is reserved against (linked partition), or
#   None for the tracked partition.
# - commit: whether the repository should commit the transaction
#   immediately. Pass False when composing this write with other changes
#   the caller will commit together.
# Returns:
# - GoalTransactionModel instance saved/flushed in the current transaction.
# Raises:
# - GoalTransactionClientRequestIdTakenError: the user already has a goal
#   transaction with this client_request_id (original IntegrityError
#   chained).
# - GoalAccountLinkInvalidError: the account link foreign key rejected the
#   row (original IntegrityError chained).
def create_transaction(
    db_session: Session,
    goal_id: UUID,
    user_id: UUID,
    type: str,
    amount: Decimal,
    description: Optional[str],
    currency: str,
    effective_date: Optional[date],
    client_request_id: Optional[UUID] = None,
    account_id: Optional[UUID] = None,
    commit: bool = True,
) -> GoalTransactionModel:
    transaction_model = GoalTransactionModel(
        goal_id=goal_id,
        user_id=user_id,
        type=type,
        amount=amount,
        description=description,
        currency=currency,
        effective_date=effective_date,
        client_request_id=client_request_id,
        account_id=account_id,
    )

    db_session.add(transaction_model)

    try:
        db_session.flush()
    except IntegrityError as error:
        constraint_name = getattr(
            getattr(error.orig, "diag", None),
            "constraint_name",
            None,
        )

        if constraint_name == CLIENT_REQUEST_ID_UNIQUE_CONSTRAINT:
            raise GoalTransactionClientRequestIdTakenError() from error

        if constraint_name == ACCOUNT_LINK_FK_CONSTRAINT:
            raise GoalAccountLinkInvalidError() from error

        raise

    if commit:
        db_session.commit()
        db_session.refresh(transaction_model)

    return transaction_model


# Returns the user's goal transaction created with a given client request
# id, if any.
# This function exists as the single lookup the create-idempotency
# algorithm uses (its fast lookup, its second lookup under the goal row
# lock, and its unique-violation recovery). It never locks: an idempotent
# replay must not take row locks. The key is unique per user across all of
# the user's goals, so the lookup is scoped by user only - never by goal -
# and can never return another user's transaction.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier.
# - client_request_id: client-generated create idempotency key.
# Returns:
# - GoalTransactionModel if one exists for this user and key, None
#   otherwise.
def get_transaction_by_client_request_id(
    db_session: Session,
    user_id: UUID,
    client_request_id: UUID,
) -> Optional[GoalTransactionModel]:
    return (
        db_session.query(GoalTransactionModel)
        .filter(
            GoalTransactionModel.user_id == user_id,
            GoalTransactionModel.client_request_id == client_request_id,
        )
        .first()
    )


# Returns a goal's full transaction history, newest first.
# This function exists to isolate PostgreSQL read operations for the ledger
# from business logic and HTTP handling. Ordering is deterministic
# (created_at DESC, id DESC) so two transactions written in the same
# instant never come back in an arbitrary order between requests.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier to list transactions for.
# - user_id: authenticated user identifier that owns the goal, used as a
#   defense-in-depth filter alongside goal_id.
# Returns:
# - List of GoalTransactionModel instances, newest first.
def get_transactions_for_goal(
    db_session: Session,
    goal_id: UUID,
    user_id: UUID,
) -> list[GoalTransactionModel]:
    return (
        db_session.query(GoalTransactionModel)
        .filter(
            GoalTransactionModel.goal_id == goal_id,
            GoalTransactionModel.user_id == user_id,
        )
        .order_by(
            GoalTransactionModel.created_at.desc(),
            GoalTransactionModel.id.desc(),
        )
        .all()
    )


# Returns every one of a user's goals' ledger balances in a single grouped
# query.
# This function exists so a read path that lists multiple Goals at once
# (GET /goals, Goal Progress analytics) never issues one balance query per
# Goal (VF-016D). A Goal with no transactions simply has no entry in the
# returned mapping - callers must default a missing goal_id to
# Decimal("0.00") themselves, since a goal that was never funded has
# nothing to aggregate.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier to scope the aggregation to.
#   Ownership-safe by construction: another user's transactions can never
#   appear in the result, even for a goal_id that happens to collide only
#   in theory (goal_id is already unique, but filtering by user_id here
#   too matches the ownership-defense-in-depth convention used everywhere
#   else in this module).
# Returns:
# - Dict mapping goal_id to its Decimal ledger balance, for goals that
#   have at least one transaction.
def get_ledger_balances_for_user(
    db_session: Session,
    user_id: UUID,
) -> dict[UUID, Decimal]:
    signed_amount = case(
        (GoalTransactionModel.type == "withdrawal", -GoalTransactionModel.amount),
        else_=GoalTransactionModel.amount,
    )

    rows = (
        db_session.query(
            GoalTransactionModel.goal_id,
            func.sum(signed_amount).label("balance"),
        )
        .filter(GoalTransactionModel.user_id == user_id)
        .group_by(GoalTransactionModel.goal_id)
        .all()
    )

    return {goal_id: balance for goal_id, balance in rows}


# Returns whether a goal has any transaction history at all.
# This function exists as the single source of truth for "is this Goal
# funded/history-bearing" (VF-016E), used to decide whether currency may
# still change and whether the Goal may still be hard-deleted. Any
# transaction type counts - opening_balance, contribution, and withdrawal
# all establish history, including a withdrawal that brings the ledger
# balance back to exactly 0. This deliberately never uses a ledger balance
# calculation as a proxy for history: a Goal can have real history and a
# 0.00 balance at the same time.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: financial goal identifier to check.
# - user_id: authenticated user identifier that owns the goal, used as a
#   defense-in-depth filter alongside goal_id.
# Returns:
# - True if at least one GoalTransaction row exists for this goal, False
#   otherwise. Uses an existence check (first matching id only) rather
#   than loading full history or aggregating a balance.
def has_transactions_for_goal(
    db_session: Session,
    goal_id: UUID,
    user_id: UUID,
) -> bool:
    first_transaction_id = (
        db_session.query(GoalTransactionModel.id)
        .filter(
            GoalTransactionModel.goal_id == goal_id,
            GoalTransactionModel.user_id == user_id,
        )
        .first()
    )

    return first_transaction_id is not None


# Signed ledger amount of a goal transaction: withdrawals subtract.
_SIGNED_AMOUNT = case(
    (GoalTransactionModel.type == "withdrawal", -GoalTransactionModel.amount),
    else_=GoalTransactionModel.amount,
)


# Returns a goal's net amount in one partition.
# account_id None = the tracked partition (rows with no Account link);
# otherwise the partition linked to that Account. One SQL aggregate; a
# partition with no rows is exactly Decimal("0.00"). The caller holds the
# Goal row lock, which serializes every writer of this Goal's rows, so the
# value cannot change before the dependent insert commits.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - goal_id: goal identifier.
# - user_id: authenticated owner (defense-in-depth filter).
# - account_id: linked Account, or None for the tracked partition.
# Returns:
# - Decimal net amount of the partition.
def calculate_partition_balance(
    db_session: Session,
    goal_id: UUID,
    user_id: UUID,
    account_id: Optional[UUID],
) -> Decimal:
    if account_id is None:
        partition_filter = GoalTransactionModel.account_id.is_(None)
    else:
        partition_filter = GoalTransactionModel.account_id == account_id

    total = (
        db_session.query(func.coalesce(func.sum(_SIGNED_AMOUNT), 0))
        .filter(
            GoalTransactionModel.goal_id == goal_id,
            GoalTransactionModel.user_id == user_id,
            partition_filter,
        )
        .scalar()
    )

    return Decimal(total).quantize(Decimal("0.01"))


# Returns every one of a user's goals' partition amounts in one grouped
# query: {goal_id: {account_id or None: net amount}}.
# Used by the Goal read model (tracked_amount, linked_amount, allocations)
# so listing Goals never issues a query per Goal. Groups with no rows are
# absent; callers default to Decimal("0.00").
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier to scope the aggregation to.
# - goal_ids: optional restriction to these Goals.
# Returns:
# - Nested dict of Decimal net amounts per goal and partition.
def get_partition_balances_for_user(
    db_session: Session,
    user_id: UUID,
    goal_ids: Optional[list[UUID]] = None,
) -> dict[UUID, dict[Optional[UUID], Decimal]]:
    query = db_session.query(
        GoalTransactionModel.goal_id,
        GoalTransactionModel.account_id,
        func.sum(_SIGNED_AMOUNT).label("balance"),
    ).filter(GoalTransactionModel.user_id == user_id)

    if goal_ids is not None:
        query = query.filter(GoalTransactionModel.goal_id.in_(goal_ids))

    rows = query.group_by(
        GoalTransactionModel.goal_id, GoalTransactionModel.account_id
    ).all()

    balances: dict[UUID, dict[Optional[UUID], Decimal]] = {}

    for goal_id, account_id, balance in rows:
        balances.setdefault(goal_id, {})[account_id] = balance

    return balances


# Returns the user's net reserved amount per Account in one grouped query.
# reserved_amount = linked contributions - linked withdrawals across ALL of
# the user's Goals, archived included. Accounts with no linked rows are
# absent; callers default to Decimal("0.00").
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier.
# - account_ids: optional restriction to these Accounts.
# Returns:
# - Dict mapping account_id to its Decimal reserved amount.
def get_reserved_amounts_for_user(
    db_session: Session,
    user_id: UUID,
    account_ids: Optional[list[UUID]] = None,
) -> dict[UUID, Decimal]:
    query = db_session.query(
        GoalTransactionModel.account_id,
        func.sum(_SIGNED_AMOUNT).label("reserved"),
    ).filter(
        GoalTransactionModel.user_id == user_id,
        GoalTransactionModel.account_id.isnot(None),
    )

    if account_ids is not None:
        query = query.filter(GoalTransactionModel.account_id.in_(account_ids))

    rows = query.group_by(GoalTransactionModel.account_id).all()

    return {account_id: reserved for account_id, reserved in rows}


# Returns whether ANY Goal transaction (contribution or withdrawal, any
# Goal, archived or not, any net amount) was ever linked to the Account.
# Used by Account delete / currency-change protection: linked history is
# financial history even when the net reservation is zero.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_id: account identifier.
# - user_id: authenticated owner (defense-in-depth filter).
# Returns:
# - True if at least one linked row exists.
def has_linked_transactions_for_account(
    db_session: Session,
    account_id: UUID,
    user_id: UUID,
) -> bool:
    first_id = (
        db_session.query(GoalTransactionModel.id)
        .filter(
            GoalTransactionModel.account_id == account_id,
            GoalTransactionModel.user_id == user_id,
        )
        .first()
    )

    return first_id is not None
