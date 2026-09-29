from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.accounts import (
    account_repository,
    account_transaction_repository,
    account_transfer_repository,
)
from app.modules.accounts.account_errors import AccountArchivedError, AccountNotFoundError
from app.modules.accounts.account_transfer_errors import (
    AccountTransferAlreadyPostedError,
    AccountTransferClientRequestIdTakenError,
    AccountTransferCurrencyMismatchError,
    AccountTransferEffectiveDateInFutureError,
    AccountTransferIdempotencyConflictError,
)
from app.modules.accounts.account_transfer_models import AccountTransferModel
from app.modules.accounts.account_transfer_schemas import (
    AccountTransferCreate,
    AccountTransferPost,
    AccountTransferResponse,
)

# VF-018C: AccountTransfer create/list/delete orchestration.
# VF-018D: manual posting of a planned transfer (post_account_transfer).
# Contract: docs/modules/account-transfers.md (D1-D19). Ledger projections
# are created only by an immediately posted create or by manual posting;
# there is no automatic posting of planned transfers.


@dataclass(frozen=True)
class AccountTransferCreateResult:
    """
    Outcome of create_account_transfer.

    What:
        The current state of the transfer plus whether this call created it.

    Why:
        POST /api/v1/account-transfers has two successful outcomes - 201 for
        a newly created transfer and 200 for an idempotent replay of an
        already-created one - and the router needs to know which occurred
        without re-deriving it.

    Fields:
        transfer: the transfer's current public representation.
        created: True if this call created the transfer, False for a replay.
    """

    transfer: AccountTransferResponse
    created: bool


# Reconstructs the transfer_date of the create request that produced a
# stored transfer.
# This function exists because transfer_date is not persisted: the create
# path stores it either as planned_date (a future date) or as
# effective_date (today or earlier). planned_date is never changed after
# creation - including when a planned transfer is later posted (VF-018D) -
# and an immediately posted transfer's effective_date is never changed
# either (there is no PATCH), so this always yields the original value.
# Parameters:
# - transfer_model: the stored transfer.
# Returns:
# - The original request's transfer_date.
def _original_transfer_date(transfer_model: AccountTransferModel) -> Optional[date]:
    if transfer_model.planned_date is not None:
        return transfer_model.planned_date

    return transfer_model.effective_date


# Returns whether a stored transfer was created from exactly this create
# request's payload.
# This function exists as the single definition of "same payload" for
# create idempotency: source, destination, amount (Decimal equality, so
# "300" equals "300.00"), original transfer_date, and description compared
# as-is - no description normalization was approved, so None and "" are
# different payloads. client_request_id and user_id already matched through
# the lookup that found the transfer.
# Parameters:
# - transfer_model: the stored transfer found by (user_id, client_request_id).
# - transfer_data: the validated create request.
# Returns:
# - True if every compared field matches.
def _matches_original_create_request(
    transfer_model: AccountTransferModel,
    transfer_data: AccountTransferCreate,
) -> bool:
    return (
        transfer_model.source_account_id == transfer_data.source_account_id
        and transfer_model.destination_account_id == transfer_data.destination_account_id
        and transfer_model.amount == transfer_data.amount
        and _original_transfer_date(transfer_model) == transfer_data.transfer_date
        and transfer_model.description == transfer_data.description
    )


# Resolves a create request whose client_request_id already identifies a
# stored transfer.
# This function exists so every idempotency path (fast lookup, second
# lookup under Account locks, unique-violation recovery) resolves an
# existing transfer identically. It never looks at current Account state:
# once the logical transfer exists, an exact replay returns it even if an
# Account was archived since - replay semantics take precedence over
# Account lifecycle state. The response reflects the transfer's CURRENT
# state (e.g. posted, if a planned transfer was posted since).
# Parameters:
# - transfer_model: the stored transfer found by (user_id, client_request_id).
# - transfer_data: the validated create request.
# Returns:
# - AccountTransferCreateResult with created=False.
# Raises:
# - AccountTransferIdempotencyConflictError: the stored transfer came from a
#   different payload.
def _resolve_existing_transfer(
    transfer_model: AccountTransferModel,
    transfer_data: AccountTransferCreate,
) -> AccountTransferCreateResult:
    if not _matches_original_create_request(transfer_model, transfer_data):
        raise AccountTransferIdempotencyConflictError()

    return AccountTransferCreateResult(
        transfer=AccountTransferResponse.model_validate(transfer_model),
        created=False,
    )


# Creates an AccountTransfer for the authenticated user, idempotently, as a
# planned or an immediately posted transfer.
# This function exists as the single create path for transfers. The whole
# write is one service-owned database transaction; the algorithm is the
# approved VF-018A contract (section 7 / D18):
#   1. (schema validation happened in AccountTransferCreate)
#   2. fast lookup by (user_id, client_request_id), no locks - an existing
#      transfer is resolved as replay (200) or conflict (409) with NO
#      current Account validation;
#   3. lock both Accounts FOR UPDATE, user-scoped, in ascending UUID order
#      - for planned creates too, so a plan cannot race an Account delete or
#      currency change into an IntegrityError. The lock helper does not
#      raise for a missing Account;
#   4. second lookup by the same key, now under the Account locks: another
#      request may have committed the same logical transfer while this one
#      waited - resolved exactly like step 2, again with no Account
#      validation;
#   5. only if both lookups found nothing: both Accounts exist and belong to
#      the user (else 404), both are active (else 409), same currency (else
#      422);
#   6. insert the transfer with the server-derived currency and, when
#      transfer_date <= today, status posted plus both ledger projections;
#      otherwise status planned with no ledger rows;
#   7. commit once;
#   8. if the insert hits uq_account_transfers_user_id_client_request_id (a
#      concurrent same-key request, e.g. for different Accounts and so not
#      serialized by these locks, reached INSERT first), roll back, reload
#      the winner, and resolve it like step 2.
# Any other failure rolls everything back - a half-written transfer or a
# single projection can never persist. No balance check exists: a posted
# transfer may make the source balance negative.
#
# "today" is the server date (the same notion the FX future-date rule uses),
# resolved once per call; as_of exists so tests can pin the boundary. It is
# not a user-timezone decision (D13 - known planner follow-up).
# Parameters:
# - db_session: active SQLAlchemy database session.
# - transfer_data: validated create request.
# - user_id: authenticated user identifier that owns the transfer.
# - as_of: optional reference "today"; defaults to date.today().
# Returns:
# - AccountTransferCreateResult - created=True for a new transfer,
#   created=False for an idempotent replay.
# Raises:
# - AccountTransferIdempotencyConflictError: the key was used for a
#   different payload.
# - AccountNotFoundError: an Account is missing or not owned by the user.
# - AccountArchivedError: an Account is archived (new create only).
# - AccountTransferCurrencyMismatchError: the Accounts' currencies differ.
def create_account_transfer(
    db_session: Session,
    transfer_data: AccountTransferCreate,
    user_id: UUID,
    as_of: Optional[date] = None,
) -> AccountTransferCreateResult:
    existing_transfer = account_transfer_repository.get_account_transfer_by_client_request_id(
        db_session=db_session,
        user_id=user_id,
        client_request_id=transfer_data.client_request_id,
    )

    if existing_transfer is not None:
        return _resolve_existing_transfer(existing_transfer, transfer_data)

    locked_accounts = account_repository.get_accounts_by_ids_for_update(
        db_session=db_session,
        account_ids=[transfer_data.source_account_id, transfer_data.destination_account_id],
        user_id=user_id,
    )

    existing_transfer = account_transfer_repository.get_account_transfer_by_client_request_id(
        db_session=db_session,
        user_id=user_id,
        client_request_id=transfer_data.client_request_id,
    )

    if existing_transfer is not None:
        try:
            return _resolve_existing_transfer(existing_transfer, transfer_data)
        finally:
            # Nothing was written; release the Account locks taken above.
            db_session.rollback()

    source_account = locked_accounts.get(transfer_data.source_account_id)
    destination_account = locked_accounts.get(transfer_data.destination_account_id)

    if source_account is None or destination_account is None:
        db_session.rollback()
        raise AccountNotFoundError()

    if source_account.status == "archived" or destination_account.status == "archived":
        db_session.rollback()
        raise AccountArchivedError()

    if source_account.currency != destination_account.currency:
        db_session.rollback()
        raise AccountTransferCurrencyMismatchError()

    today = as_of if as_of is not None else date.today()
    is_posted = transfer_data.transfer_date <= today

    try:
        transfer_model = account_transfer_repository.create_account_transfer(
            db_session=db_session,
            user_id=user_id,
            client_request_id=transfer_data.client_request_id,
            source_account_id=transfer_data.source_account_id,
            destination_account_id=transfer_data.destination_account_id,
            amount=transfer_data.amount,
            currency=source_account.currency,
            status="posted" if is_posted else "planned",
            planned_date=None if is_posted else transfer_data.transfer_date,
            effective_date=transfer_data.transfer_date if is_posted else None,
            description=transfer_data.description,
            posted_at=datetime.now(timezone.utc) if is_posted else None,
        )

        if is_posted:
            account_transaction_repository.create_transfer_projections(
                db_session=db_session,
                transfer=transfer_model,
            )

        db_session.commit()
    except AccountTransferClientRequestIdTakenError:
        db_session.rollback()

        winning_transfer = account_transfer_repository.get_account_transfer_by_client_request_id(
            db_session=db_session,
            user_id=user_id,
            client_request_id=transfer_data.client_request_id,
        )

        if winning_transfer is None:
            # The unique violation proves a same-key transfer committed, so
            # failing to reload it is an unexpected state - never fabricate
            # a result; surface the original error.
            raise

        return _resolve_existing_transfer(winning_transfer, transfer_data)
    except Exception:
        db_session.rollback()
        raise

    db_session.refresh(transfer_model)

    return AccountTransferCreateResult(
        transfer=AccountTransferResponse.model_validate(transfer_model),
        created=True,
    )


# Returns every one of the authenticated user's transfers, planned and
# posted, newest first.
# This function exists to map stored transfers to public responses and keep
# the read user-scoped. It returns stored state only - a planned transfer
# whose planned_date has passed stays planned (no automatic posting).
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier.
# Returns:
# - List of AccountTransferResponse objects, ordered by
#   COALESCE(effective_date, planned_date) DESC, created_at DESC, id DESC.
def get_account_transfers(
    db_session: Session,
    user_id: UUID,
) -> list[AccountTransferResponse]:
    transfer_models = account_transfer_repository.get_account_transfers(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        AccountTransferResponse.model_validate(transfer_model)
        for transfer_model in transfer_models
    ]


# Hard-deletes one of the authenticated user's transfers, planned or posted.
# This function exists as the single delete path, one service-owned
# transaction, in the approved lock order: the transfer row FOR UPDATE
# first, then both Accounts FOR UPDATE in ascending UUID order, then the
# delete. Deleting a posted transfer removes both ledger projections via
# ON DELETE CASCADE, so its balance effect disappears; a planned transfer
# has none. Archived Accounts never block deletion (removing history is a
# correction, not new activity), so no Account state is validated here.
# Hard delete also frees the transfer's client_request_id - reusing it
# afterwards creates a new transfer (accepted MVP behavior, D18).
# Parameters:
# - db_session: active SQLAlchemy database session.
# - transfer_id: transfer identifier.
# - user_id: authenticated user identifier that owns the transfer.
# Returns:
# - None.
# Raises:
# - AccountTransferNotFoundError: the transfer does not exist or is not
#   owned by the user.
def delete_account_transfer(
    db_session: Session,
    transfer_id: UUID,
    user_id: UUID,
) -> None:
    transfer_model = account_transfer_repository.get_account_transfer_by_id_for_update(
        db_session=db_session,
        transfer_id=transfer_id,
        user_id=user_id,
    )

    try:
        account_repository.get_accounts_by_ids_for_update(
            db_session=db_session,
            account_ids=[
                transfer_model.source_account_id,
                transfer_model.destination_account_id,
            ],
            user_id=user_id,
        )

        account_transfer_repository.delete_locked_account_transfer(
            db_session=db_session,
            transfer_model=transfer_model,
        )

        db_session.commit()
    except Exception:
        db_session.rollback()
        raise


# Manually posts one of the authenticated user's planned transfers.
# This function exists as the single planned -> posted transition (VF-018D).
# The whole transition is one service-owned transaction, in the approved
# order (contract section 8):
#   1. resolve effective_date (default: today) and reject a future date -
#      BEFORE any lookup, so a future date is 422 even for a missing or
#      foreign transfer;
#   2. lock the transfer FOR UPDATE, user-scoped (missing/foreign -> 404);
#   3. only a planned transfer can be posted (else 409) - posting is at most
#      once and not idempotent; there is no "not yet due" rule, so it may be
#      posted before or after planned_date;
#   4. lock both Accounts FOR UPDATE in ascending UUID order - after the
#      transfer, the same Transfer -> Accounts order delete uses;
#   5. both Accounts must be active (else 409; the transfer stays planned
#      with no ledger rows); the currency re-check is defense in depth - the
#      composite (account_id, user_id, currency) foreign keys already make a
#      mismatch impossible;
#   6. mark the transfer posted (effective_date, posted_at; planned_date is
#      kept) and flush, then create both ledger projections dated
#      effective_date - create_transfer_projections requires the transfer to
#      already be posted in this uncommitted transaction;
#   7. commit once.
# Any failure rolls back everything, releasing both locks: the transfer
# stays planned with no effective_date, no posted_at, and no ledger rows.
# There is no balance check - posting may make the source balance negative.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - transfer_id: transfer identifier.
# - user_id: authenticated user identifier that owns the transfer.
# - post_data: optional request body; None or an omitted effective_date
#   means today.
# - as_of: optional reference "today" for tests; defaults to date.today().
# Returns:
# - AccountTransferResponse with the transfer's posted state.
# Raises:
# - AccountTransferEffectiveDateInFutureError: effective_date > today.
# - AccountTransferNotFoundError: missing or foreign transfer.
# - AccountTransferAlreadyPostedError: the transfer is not planned.
# - AccountArchivedError: the source or destination Account is archived.
def post_account_transfer(
    db_session: Session,
    transfer_id: UUID,
    user_id: UUID,
    post_data: Optional[AccountTransferPost] = None,
    as_of: Optional[date] = None,
) -> AccountTransferResponse:
    today = as_of if as_of is not None else date.today()
    requested_date = post_data.effective_date if post_data is not None else None
    effective_date = requested_date if requested_date is not None else today

    if effective_date > today:
        raise AccountTransferEffectiveDateInFutureError()

    transfer_model = account_transfer_repository.get_account_transfer_by_id_for_update(
        db_session=db_session,
        transfer_id=transfer_id,
        user_id=user_id,
    )

    try:
        if transfer_model.status != "planned":
            raise AccountTransferAlreadyPostedError()

        locked_accounts = account_repository.get_accounts_by_ids_for_update(
            db_session=db_session,
            account_ids=[
                transfer_model.source_account_id,
                transfer_model.destination_account_id,
            ],
            user_id=user_id,
        )
        source_account = locked_accounts.get(transfer_model.source_account_id)
        destination_account = locked_accounts.get(transfer_model.destination_account_id)

        if source_account is None or destination_account is None:
            # Unreachable while the ON DELETE RESTRICT foreign keys hold.
            raise AccountNotFoundError()

        if source_account.status == "archived" or destination_account.status == "archived":
            raise AccountArchivedError()

        if (
            source_account.currency != transfer_model.currency
            or destination_account.currency != transfer_model.currency
        ):
            raise AccountTransferCurrencyMismatchError()

        account_transfer_repository.mark_locked_account_transfer_posted(
            db_session=db_session,
            transfer_model=transfer_model,
            effective_date=effective_date,
            posted_at=datetime.now(timezone.utc),
        )

        account_transaction_repository.create_transfer_projections(
            db_session=db_session,
            transfer=transfer_model,
        )

        db_session.commit()
    except Exception:
        db_session.rollback()
        raise

    db_session.refresh(transfer_model)

    return AccountTransferResponse.model_validate(transfer_model)
