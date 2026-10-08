from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.accounts.account_transfer_errors import (
    AccountTransferClientRequestIdTakenError,
    AccountTransferNotFoundError,
)
from app.modules.accounts.account_transfer_models import AccountTransferModel

# The create-idempotency unique constraint (VF-018B). Only a violation of
# exactly this constraint is translated into
# AccountTransferClientRequestIdTakenError; every other IntegrityError
# propagates unchanged.
CLIENT_REQUEST_ID_UNIQUE_CONSTRAINT = "uq_account_transfers_user_id_client_request_id"

# VF-018B: AccountTransfer persistence primitives.
#
# Unlike the older account/income/expense repository functions, the write
# primitives here deliberately have no commit parameter at all: every
# AccountTransfer write belongs to a service-owned database transaction
# (docs/modules/account-transfers.md, section 18) - a posted create must
# commit the canonical row and both ledger projections together, and a
# planned create must commit only after the service's Account locks and
# idempotency lookups. They only ever flush. No business rule (status
# classification, archived Accounts, currency match, idempotency replay)
# lives here - those belong to the service layer.


# Creates and flushes a new AccountTransfer row.
# This function exists to isolate the canonical transfer INSERT from
# business logic and HTTP handling. It persists exactly the values it is
# given: the caller (the future transfer service) decides status and the
# matching planned_date/effective_date/posted_at combination, which the
# database then validates via ck_account_transfers_lifecycle_consistent.
# A duplicate (user_id, client_request_id) fails the flush on
# uq_account_transfers_user_id_client_request_id; that one constraint is
# re-raised as AccountTransferClientRequestIdTakenError (identified by
# PostgreSQL constraint metadata, never by message text - the same pattern
# budget_repository uses) so the service can resolve the race as a replay
# or a conflict. Every other IntegrityError propagates unchanged. The
# session is left in its failed state: rolling back belongs to the caller,
# which owns the transaction.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier that owns the transfer and both
#   Accounts.
# - client_request_id: client-generated create idempotency key.
# - source_account_id: Account the money leaves.
# - destination_account_id: Account the money enters.
# - amount: positive transfer amount.
# - currency: the shared currency of both Accounts.
# - status: "planned" or "posted".
# - planned_date: expected date for a planned transfer, else None.
# - effective_date: accounting date for a posted transfer, else None.
# - description: optional free-text note.
# - posted_at: technical posting timestamp for a posted transfer, else None.
# Returns:
# - AccountTransferModel instance flushed in the current transaction.
# Raises:
# - AccountTransferClientRequestIdTakenError: the user already has a
#   transfer with this client_request_id (original IntegrityError chained).
def create_account_transfer(
    db_session: Session,
    user_id: UUID,
    client_request_id: UUID,
    source_account_id: UUID,
    destination_account_id: UUID,
    amount: Decimal,
    currency: str,
    status: str,
    planned_date: Optional[date],
    effective_date: Optional[date],
    description: Optional[str],
    posted_at: Optional[datetime],
) -> AccountTransferModel:
    transfer_model = AccountTransferModel(
        user_id=user_id,
        client_request_id=client_request_id,
        source_account_id=source_account_id,
        destination_account_id=destination_account_id,
        amount=amount,
        currency=currency,
        status=status,
        planned_date=planned_date,
        effective_date=effective_date,
        description=description,
        posted_at=posted_at,
    )

    db_session.add(transfer_model)

    try:
        db_session.flush()
    except IntegrityError as error:
        constraint_name = getattr(
            getattr(error.orig, "diag", None),
            "constraint_name",
            None,
        )

        if constraint_name == CLIENT_REQUEST_ID_UNIQUE_CONSTRAINT:
            raise AccountTransferClientRequestIdTakenError() from error

        raise

    return transfer_model


# Returns the user's AccountTransfer created with a given client request
# id, if any.
# This function exists as the single lookup the future create-idempotency
# algorithm uses (both its fast lookup and its second lookup under Account
# locks). It never locks: an idempotent replay must not take row locks.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier; the key is only unique per
#   user, so the lookup is always user-scoped.
# - client_request_id: client-generated create idempotency key.
# Returns:
# - AccountTransferModel if one exists for this user and key, None
#   otherwise.
def get_account_transfer_by_client_request_id(
    db_session: Session,
    user_id: UUID,
    client_request_id: UUID,
) -> Optional[AccountTransferModel]:
    return (
        db_session.query(AccountTransferModel)
        .filter(
            AccountTransferModel.user_id == user_id,
            AccountTransferModel.client_request_id == client_request_id,
        )
        .first()
    )


# Returns one AccountTransfer by id and authenticated user id, locking the
# row with SELECT ... FOR UPDATE for the duration of the caller's
# transaction.
# This function exists so post and delete can lock the canonical transfer
# row first, before locking its Accounts in ascending UUID order - the
# approved lock order (canonical row -> Accounts). Callers must not commit
# or release the session between this call and the write it guards.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - transfer_id: transfer identifier.
# - user_id: authenticated user identifier that owns the transfer.
# Returns:
# - AccountTransferModel instance from the database, locked for update.
# Raises:
# - AccountTransferNotFoundError: when the transfer does not exist or does
#   not belong to the user.
def get_account_transfer_by_id_for_update(
    db_session: Session,
    transfer_id: UUID,
    user_id: UUID,
) -> AccountTransferModel:
    transfer_model = (
        db_session.query(AccountTransferModel)
        .filter(
            AccountTransferModel.id == transfer_id,
            AccountTransferModel.user_id == user_id,
        )
        .with_for_update()
        .first()
    )

    if transfer_model is None:
        raise AccountTransferNotFoundError()

    return transfer_model


# Deletes an already-locked AccountTransfer row and flushes.
# This function exists to isolate the canonical transfer DELETE from
# business logic and HTTP handling. For a posted transfer, both ledger
# projections are removed by the database via ON DELETE CASCADE
# (account_transactions.transfer_id) within the same flush/transaction -
# there is intentionally no separate projection delete primitive. Callers
# must have already locked the transfer (get_account_transfer_by_id_for_
# update) and then its Accounts in ascending UUID order before calling
# this.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - transfer_model: the already-locked AccountTransferModel to delete.
# Returns:
# - None.
def delete_locked_account_transfer(
    db_session: Session,
    transfer_model: AccountTransferModel,
) -> None:
    db_session.delete(transfer_model)
    db_session.flush()


# Returns every one of the user's AccountTransfers, planned and posted,
# newest first.
# This function exists to back GET /api/v1/account-transfers. Ordering is
# deterministic: the transfer's own date - effective_date once posted,
# otherwise planned_date - descending, then created_at DESC, then id DESC,
# so transfers on the same date never come back in an arbitrary order. It
# returns stored state only: a planned transfer whose planned_date has
# passed stays planned here (there is no automatic posting).
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier; only this user's transfers are
#   returned.
# Returns:
# - List of AccountTransferModel instances in the order above.
def get_account_transfers(
    db_session: Session,
    user_id: UUID,
) -> list[AccountTransferModel]:
    return (
        db_session.query(AccountTransferModel)
        .filter(AccountTransferModel.user_id == user_id)
        .order_by(
            func.coalesce(
                AccountTransferModel.effective_date,
                AccountTransferModel.planned_date,
            ).desc(),
            AccountTransferModel.created_at.desc(),
            AccountTransferModel.id.desc(),
        )
        .all()
    )


# Returns whether any planned AccountTransfer references an Account as its
# source or destination.
# This function exists for the Account lifecycle guards (VF-018C): a planned
# transfer has no ledger rows, so has_transactions_for_account cannot see
# it, yet it must block deleting the Account or actually changing its
# currency. It is a plain existence read with no row lock - the Account
# lifecycle path already holds the Account's own FOR UPDATE lock and must
# never take transfer row locks (transfer paths lock Transfer -> Accounts,
# so Account -> Transfer locking would invert that order). Any concurrent
# create/post/delete that could add or remove such a reference must itself
# hold this Account's lock, so the read is consistent for the caller.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_id: account identifier to check.
# - user_id: authenticated user identifier that owns the account, used as a
#   defense-in-depth filter.
# Returns:
# - True if at least one planned transfer references the account.
def has_planned_transfers_for_account(
    db_session: Session,
    account_id: UUID,
    user_id: UUID,
) -> bool:
    first_transfer_id = (
        db_session.query(AccountTransferModel.id)
        .filter(
            AccountTransferModel.user_id == user_id,
            AccountTransferModel.status == "planned",
            or_(
                AccountTransferModel.source_account_id == account_id,
                AccountTransferModel.destination_account_id == account_id,
            ),
        )
        .first()
    )

    return first_transfer_id is not None


# Returns, per Account, the total amount of PLANNED transfers leaving it
# (VF-020C2): SUM(amount) of status='planned' transfers grouped by
# source_account_id, regardless of planned_date - a planned transfer is a
# commitment that will debit the source whenever it is posted. Posted
# transfers are already in the ledger (no double counting) and planned
# INCOMING transfers add nothing (the money has not arrived). Accounts
# without a planned outgoing transfer are absent.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier (ownership filter).
# - account_ids: optional restriction to these source Accounts.
# Returns:
# - Dict mapping source account_id to its Decimal planned outflow total.
def get_planned_transfer_outflows_for_user(
    db_session: Session,
    user_id: UUID,
    account_ids: Optional[list[UUID]] = None,
) -> dict[UUID, Decimal]:
    query = db_session.query(
        AccountTransferModel.source_account_id,
        func.sum(AccountTransferModel.amount),
    ).filter(
        AccountTransferModel.user_id == user_id,
        AccountTransferModel.status == "planned",
    )

    if account_ids is not None:
        query = query.filter(AccountTransferModel.source_account_id.in_(account_ids))

    rows = query.group_by(AccountTransferModel.source_account_id).all()

    return {account_id: Decimal(total) for account_id, total in rows}


# Moves an already-locked planned AccountTransfer to posted and flushes.
# This function exists as the only way a transfer's lifecycle fields
# change after creation (VF-018D manual posting): it sets status, the
# chosen effective_date, and posted_at, and deliberately never touches
# planned_date, which must keep the original expected date forever (it is
# also what create idempotency compares against). There is no generic
# update primitive - no other field of a transfer is ever mutable. The
# caller must have locked the transfer (get_account_transfer_by_id_for_
# update) and its Accounts, and must create the ledger projections in the
# same transaction right after this flush (create_transfer_projections
# requires status="posted"), then commit once; a rollback restores the
# planned state. Refusing a non-planned transfer here is a programming
# invariant (the service checks status first), so it raises ValueError,
# matching the other repository mutation guards.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - transfer_model: the locked planned AccountTransferModel.
# - effective_date: accounting date on which the money moved.
# - posted_at: technical timestamp of the transition.
# Returns:
# - The same AccountTransferModel, flushed with its posted state.
# Raises:
# - ValueError: transfer_model is not planned.
def mark_locked_account_transfer_posted(
    db_session: Session,
    transfer_model: AccountTransferModel,
    effective_date: date,
    posted_at: datetime,
) -> AccountTransferModel:
    if transfer_model.status != "planned":
        raise ValueError(
            "mark_locked_account_transfer_posted may only be called with a "
            "planned AccountTransfer - refusing to re-post a posted transfer."
        )

    transfer_model.status = "posted"
    transfer_model.effective_date = effective_date
    transfer_model.posted_at = posted_at
    db_session.flush()

    return transfer_model
