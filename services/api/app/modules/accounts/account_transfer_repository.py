from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.accounts.account_transfer_errors import AccountTransferNotFoundError
from app.modules.accounts.account_transfer_models import AccountTransferModel

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
# A duplicate (user_id, client_request_id) raises IntegrityError on flush
# (uq_account_transfers_user_id_client_request_id); translating that into
# an idempotent replay or conflict is the service's job.
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
    db_session.flush()

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
