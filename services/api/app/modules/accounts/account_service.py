from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.accounts import (
    account_repository,
    account_transaction_repository,
    account_transfer_repository,
)
from app.modules.accounts.account_errors import (
    AccountArchivedError,
    AccountCurrencyImmutableError,
    AccountDeletionNotAllowedError,
    AccountReferencedByGoalAllocationError,
    AccountReferencedByPlannedTransferError,
)
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_transaction_models import AccountTransactionModel
from app.modules.accounts.account_schemas import (
    AccountCreate,
    AccountResponse,
    AccountUpdate,
)
from app.modules.accounts.account_transaction_schemas import (
    AccountTransactionCreate,
    AccountTransactionResponse,
)
from app.modules.goals import goal_transaction_repository


# Builds AccountResponses (ledger balance + Goal reservation read model) for
# the given Account models of one user.
# This function exists to make the source of every money field explicit and
# auditable: current_balance and the VF-020C2 capacity fields are all
# derived from the ledger, planned transfers and linked Goal transactions -
# the Account row has no balance column to read, so never use
# AccountResponse.model_validate(account_model).
#
# Formulas (all signed Decimal, D = the single server date for the request):
# - balance_as_of_today = signed ledger sum with transaction_date <= D;
# - scheduled_outflows = positive sum of debits with transaction_date > D;
# - planned_transfer_outflows = amount of planned transfers leaving the
#   Account, whatever their planned_date;
# - reserved_amount = linked Goal contributions - linked withdrawals over
#   ALL Goals, archived included;
# - unallocated_amount = balance_as_of_today - reserved_amount;
# - reservable_amount = unallocated_amount - scheduled_outflows
#   - planned_transfer_outflows (signed; may be negative);
# - allocation_status = "overcommitted" iff reserved_amount > 0 and
#   unallocated_amount < 0, else "normal";
# - negative_balance = balance_as_of_today < 0.
# current_balance is unchanged: the full ledger sum, future rows included.
# Query count is constant in the number of Accounts: one grouped query each
# for the full balance, the dated aggregates, planned transfers and
# reservations.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier that owns the Accounts.
# - account_models: Account database records to serialize.
# - as_of: server "today" used for the whole request.
# Returns:
# - AccountResponse list in the same order as account_models.
def _build_account_responses(
    db_session: Session,
    user_id: UUID,
    account_models: list[AccountModel],
    as_of: date,
) -> list[AccountResponse]:
    if not account_models:
        return []

    zero = Decimal("0.00")
    account_ids = [account_model.id for account_model in account_models]

    balances = account_transaction_repository.get_ledger_balances_for_user(
        db_session=db_session,
        user_id=user_id,
        account_ids=account_ids,
    )
    dated = account_transaction_repository.get_ledger_aggregates_as_of_for_user(
        db_session=db_session,
        user_id=user_id,
        as_of=as_of,
        account_ids=account_ids,
    )
    planned_outflows = account_transfer_repository.get_planned_transfer_outflows_for_user(
        db_session=db_session,
        user_id=user_id,
        account_ids=account_ids,
    )
    reserved = goal_transaction_repository.get_reserved_amounts_for_user(
        db_session=db_session,
        user_id=user_id,
        account_ids=account_ids,
    )

    responses = []

    for account_model in account_models:
        balance_as_of_today, scheduled_outflows = dated.get(
            account_model.id,
            (zero, zero),
        )
        planned_transfer_outflows = planned_outflows.get(account_model.id, zero)
        reserved_amount = reserved.get(account_model.id, zero)
        unallocated_amount = balance_as_of_today - reserved_amount
        reservable_amount = (
            unallocated_amount - scheduled_outflows - planned_transfer_outflows
        )

        responses.append(
            AccountResponse(
                id=account_model.id,
                user_id=account_model.user_id,
                name=account_model.name,
                type=account_model.type,
                currency=account_model.currency,
                status=account_model.status,
                current_balance=balances.get(account_model.id, zero),
                balance_as_of_today=balance_as_of_today,
                scheduled_outflows=scheduled_outflows,
                planned_transfer_outflows=planned_transfer_outflows,
                reserved_amount=reserved_amount,
                unallocated_amount=unallocated_amount,
                reservable_amount=reservable_amount,
                allocation_status=(
                    "overcommitted"
                    if reserved_amount > 0 and unallocated_amount < 0
                    else "normal"
                ),
                negative_balance=balance_as_of_today < 0,
                created_at=account_model.created_at,
                updated_at=account_model.updated_at,
            )
        )

    return responses


# Returns the Account's current signed reservable_amount for a new Goal
# reservation (VF-020C2). Callers must hold the Account row lock: every
# writer of the Account's ledger or planned transfers locks the Account, so
# the aggregates read here are consistent until the caller commits.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_model: the locked Account.
# - as_of: server "today" for the request.
# Returns:
# - Decimal reservable_amount (signed).
def get_reservable_amount(
    db_session: Session,
    account_model: AccountModel,
    as_of: date,
) -> Decimal:
    return _build_account_responses(
        db_session, account_model.user_id, [account_model], as_of
    )[0].reservable_amount


# Creates a new account using validated input data and authenticated user
# id, optionally recording a real pre-existing balance as one immutable
# opening_balance transaction.
# This function exists to keep application and business logic separate
# from database and HTTP layers. The whole operation is one database
# transaction: the Account row and its optional opening_balance
# transaction are created together, committed once - a real-world account
# that already holds money must never end up persisted with the wrong
# starting balance because of a partial failure between the two inserts.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_data: validated account creation data, including an optional
#   signed opening_balance.
# - user_id: authenticated user identifier that owns the account.
# Returns:
# - AccountResponse created from the saved database model, with a
#   ledger-derived current_balance (0.00 unless an opening_balance was
#   given).
def create_account(
    db_session: Session,
    account_data: AccountCreate,
    user_id: UUID,
) -> AccountResponse:
    account_model = account_repository.create_account(
        db_session=db_session,
        account_data=account_data,
        user_id=user_id,
        commit=False,
    )

    if account_data.opening_balance is not None and account_data.opening_balance != 0:
        if account_data.opening_balance > 0:
            direction = "credit"
            amount = account_data.opening_balance
        else:
            direction = "debit"
            amount = -account_data.opening_balance

        account_transaction_repository.create_transaction(
            db_session=db_session,
            account_id=account_model.id,
            user_id=user_id,
            kind="opening_balance",
            direction=direction,
            amount=amount,
            transaction_date=account_data.opening_balance_date or date.today(),
            description=None,
            commit=False,
        )

    db_session.commit()
    db_session.refresh(account_model)

    return _build_account_responses(
        db_session, user_id, [account_model], date.today()
    )[0]


# Returns accounts for the authenticated user.
# This function exists to map database models to public API responses and
# to ensure service-level reads are always scoped to a user.
# current_balance is ledger-derived: one bulk grouped query fetches every
# one of the user's account balances up front, so this never issues one
# balance query per Account no matter how many accounts are returned.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter accounts.
# Returns:
# - List of AccountResponse objects, ordered exactly as
#   account_repository.get_accounts returns them (created_at DESC).
def get_accounts(
    db_session: Session,
    user_id: UUID,
) -> list[AccountResponse]:
    account_models = account_repository.get_accounts(
        db_session=db_session,
        user_id=user_id,
    )

    return _build_account_responses(
        db_session, user_id, account_models, date.today()
    )


# Updates an existing account owned by the authenticated user, enforcing
# currency immutability once transaction history exists.
# This function exists to keep update business flow in the service layer
# and response mapping outside the repository layer. current_balance in
# the returned response is ledger-derived: the Account row itself has no
# balance column to update, so the response is always computed fresh from
# account_transactions after applying the metadata change.
#
# Concurrency/TOCTOU safety: the Account row is locked with
# SELECT ... FOR UPDATE *before* the history check, in the same database
# transaction as the check and the update. This serializes against
# create_account_transaction's own row lock, so a currency change and the
# Account's first transaction can never both "see" a history-free Account
# and both succeed - whichever acquires the lock first determines the
# outcome for the other.
#
# Currency immutability rule: only an *actual* change is checked against
# history. account_data.currency is already normalized by AccountUpdate's
# own validator (e.g. "eur" -> "EUR") by the time it reaches this
# function, so resending the Account's current currency (in any casing)
# after history exists is a no-op and is allowed, not rejected.
#
# Planned-transfer rule (VF-018C): an actual currency change is also
# rejected while any planned AccountTransfer references the Account - a
# planned transfer has no ledger rows, so the history check above cannot
# see it, and its amount is expressed in this currency. The check is a
# plain read made under the Account lock and BEFORE the UPDATE is issued,
# so the composite (account_id, user_id, currency) foreign key on
# account_transfers never has to reject the write (it stays the last line
# of defense) and this path never takes transfer row locks. A same-value
# currency resend and every other field change (including archiving) do
# not run this check at all.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_id: account identifier.
# - account_data: validated partial account update data.
# - user_id: authenticated user identifier that owns the account.
# Returns:
# - AccountResponse created from the updated database model, with a
#   ledger-derived current_balance.
# Raises:
# - AccountNotFoundError: when account does not exist or does not belong
#   to the user.
# - AccountCurrencyImmutableError: when currency is actually changing and
#   the account already has transaction history.
# - AccountReferencedByGoalAllocationError: when currency is actually
#   changing and linked Goal transactions reference the account (checked
#   after ledger history, before planned transfers).
# - AccountReferencedByPlannedTransferError: when currency is actually
#   changing and a planned transfer references the account.
def update_account(
    db_session: Session,
    account_id: UUID,
    account_data: AccountUpdate,
    user_id: UUID,
) -> AccountResponse:
    account_model = account_repository.get_account_by_id_for_update(
        db_session=db_session,
        account_id=account_id,
        user_id=user_id,
    )

    if "currency" in account_data.model_fields_set:
        is_actual_currency_change = account_data.currency != account_model.currency

        if is_actual_currency_change:
            has_history = account_transaction_repository.has_transactions_for_account(
                db_session=db_session,
                account_id=account_id,
                user_id=user_id,
            )

            if has_history:
                db_session.rollback()
                raise AccountCurrencyImmutableError()

            if goal_transaction_repository.has_linked_transactions_for_account(
                db_session=db_session,
                account_id=account_id,
                user_id=user_id,
            ):
                db_session.rollback()
                raise AccountReferencedByGoalAllocationError()

            has_planned_transfers = account_transfer_repository.has_planned_transfers_for_account(
                db_session=db_session,
                account_id=account_id,
                user_id=user_id,
            )

            if has_planned_transfers:
                db_session.rollback()
                raise AccountReferencedByPlannedTransferError()

    account_model = account_repository.apply_account_update(
        db_session=db_session,
        account_model=account_model,
        account_data=account_data,
    )

    return _build_account_responses(
        db_session, user_id, [account_model], date.today()
    )[0]


# Deletes an existing account owned by the authenticated user, refusing to
# delete an account that has any transaction history.
# This function exists to keep delete business flow in the service layer
# and to avoid exposing repository calls directly to the router. Any
# transaction (opening_balance or adjustment) counts as history, even a
# debit adjustment that brought the ledger balance to exactly 0 or
# negative - balance is never used as a proxy for "no history". A user who
# wants to stop using a history-bearing Account must archive it via PATCH
# status="archived" instead.
#
# Concurrency/TOCTOU safety: the Account row is locked with
# SELECT ... FOR UPDATE *before* the history check, in the same database
# transaction as the check and the delete. This serializes against
# create_account_transaction's own row lock: whichever of "delete this
# Account" or "create its first transaction" acquires the lock first
# determines the outcome the other one observes.
#
# Planned-transfer rule (VF-018C): an Account referenced by any planned
# AccountTransfer cannot be deleted either - a planned transfer has no
# ledger rows, so the history check cannot see it, and deleting the
# Account would silently destroy the plan. The check is a plain read made
# under the Account lock and BEFORE the DELETE is issued: relying on the
# account_transfers ON DELETE RESTRICT foreign key instead would surface an
# IntegrityError (500), and PostgreSQL's FK enforcement would row-lock the
# referencing transfer rows while this Account lock is held - the reverse
# of the Transfer -> Account order transfer deletion uses. Any concurrent
# transfer create/delete touching this Account must hold its lock too, so
# the read is consistent. The FK remains the last line of defense.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_id: account identifier.
# - user_id: authenticated user identifier that owns the account.
# Returns:
# - None.
# Raises:
# - AccountNotFoundError: when account does not exist or does not belong
#   to the user.
# - AccountDeletionNotAllowedError: when the account has any transaction
#   history.
# - AccountReferencedByGoalAllocationError: when any linked Goal
#   transaction references the account (checked after ledger history,
#   before planned transfers).
# - AccountReferencedByPlannedTransferError: when a planned transfer
#   references the account.
def delete_account(
    db_session: Session,
    account_id: UUID,
    user_id: UUID,
) -> None:
    account_model = account_repository.get_account_by_id_for_update(
        db_session=db_session,
        account_id=account_id,
        user_id=user_id,
    )

    has_history = account_transaction_repository.has_transactions_for_account(
        db_session=db_session,
        account_id=account_id,
        user_id=user_id,
    )

    if has_history:
        db_session.rollback()
        raise AccountDeletionNotAllowedError()

    # Linked Goal history (VF-020C2) blocks deletion even at a zero net
    # reservation and whether or not the Goal is archived.
    if goal_transaction_repository.has_linked_transactions_for_account(
        db_session=db_session,
        account_id=account_id,
        user_id=user_id,
    ):
        db_session.rollback()
        raise AccountReferencedByGoalAllocationError()

    has_planned_transfers = account_transfer_repository.has_planned_transfers_for_account(
        db_session=db_session,
        account_id=account_id,
        user_id=user_id,
    )

    if has_planned_transfers:
        db_session.rollback()
        raise AccountReferencedByPlannedTransferError()

    account_repository.delete_locked_account(
        db_session=db_session,
        account_model=account_model,
    )


# Creates a manual adjustment transaction for an account owned by the
# authenticated user.
# This function exists as the single write path for direct, client-created
# account transactions. The whole operation runs as one database
# transaction:
#   1. lock the owned Account row (SELECT ... FOR UPDATE) so a concurrent
#      lifecycle change (currency change, delete, archive) can never race
#      against this write;
#   2. reject if the account is archived;
#   3. insert the new immutable adjustment transaction;
#   4. commit once.
# The Account row itself is never written here - its balance is never
# stored anywhere, only ever computed from account_transactions, so it
# cannot drift from the ledger. There is deliberately no
# insufficient-funds check anywhere in this function: an Account is a
# descriptive financial record, not a payment-authorization system, so a
# debit larger than the current balance is always allowed and the
# resulting balance may be negative.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_id: account identifier.
# - transaction_data: validated adjustment request data.
# - user_id: authenticated user identifier that owns the account.
# Returns:
# - AccountTransactionResponse for the newly created transaction.
# Raises:
# - AccountNotFoundError: when account does not exist or does not belong
#   to the user.
# - AccountArchivedError: when the account's status is archived.
def create_account_transaction(
    db_session: Session,
    account_id: UUID,
    transaction_data: AccountTransactionCreate,
    user_id: UUID,
) -> AccountTransactionResponse:
    account_model = account_repository.get_account_by_id_for_update(
        db_session=db_session,
        account_id=account_id,
        user_id=user_id,
    )

    if account_model.status == "archived":
        db_session.rollback()
        raise AccountArchivedError()

    transaction_model = account_transaction_repository.create_transaction(
        db_session=db_session,
        account_id=account_id,
        user_id=user_id,
        kind="adjustment",
        direction=transaction_data.direction,
        amount=transaction_data.amount,
        transaction_date=transaction_data.transaction_date,
        description=transaction_data.description,
        commit=False,
    )

    db_session.commit()
    db_session.refresh(transaction_model)

    return AccountTransactionResponse.model_validate(transaction_model)


# Builds an AccountTransactionResponse from a ledger row and its
# already-resolved transfer counterparty.
# This function exists because counterparty_account_id has no database
# column (VF-018C): it is derived from the canonical transfer in the
# history query and must be supplied explicitly, so this is the only place
# a history response is assembled with it.
# Parameters:
# - transaction_model: the AccountTransaction database record.
# - counterparty_account_id: the other Account of the row's transfer, or
#   None for a non-transfer row.
# Returns:
# - AccountTransactionResponse including counterparty_account_id.
def _build_account_transaction_response(
    transaction_model: AccountTransactionModel,
    counterparty_account_id: Optional[UUID],
) -> AccountTransactionResponse:
    return AccountTransactionResponse(
        id=transaction_model.id,
        account_id=transaction_model.account_id,
        user_id=transaction_model.user_id,
        kind=transaction_model.kind,
        direction=transaction_model.direction,
        amount=transaction_model.amount,
        transaction_date=transaction_model.transaction_date,
        description=transaction_model.description,
        income_id=transaction_model.income_id,
        expense_id=transaction_model.expense_id,
        transfer_id=transaction_model.transfer_id,
        counterparty_account_id=counterparty_account_id,
        created_at=transaction_model.created_at,
    )


# Returns the full transaction history for an account owned by the
# authenticated user.
# This function exists to enforce ownership before ever touching the
# ledger: another user's Account must behave as not found, never leaking
# whether it exists. Each transfer row carries counterparty_account_id -
# the other Account of its transfer - resolved in the same single query
# as the history itself (no per-row transfer lookup); every other row
# gets None.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_id: account identifier.
# - user_id: authenticated user identifier that owns the account.
# Returns:
# - List of AccountTransactionResponse objects, newest first.
# Raises:
# - AccountNotFoundError: when account does not exist or does not belong
#   to the user.
def get_account_transactions(
    db_session: Session,
    account_id: UUID,
    user_id: UUID,
) -> list[AccountTransactionResponse]:
    account_repository.get_account_by_id(
        db_session=db_session,
        account_id=account_id,
        user_id=user_id,
    )

    rows = account_transaction_repository.get_transactions_with_transfer_counterparty_for_account(
        db_session=db_session,
        account_id=account_id,
        user_id=user_id,
    )

    return [
        _build_account_transaction_response(transaction_model, counterparty_account_id)
        for transaction_model, counterparty_account_id in rows
    ]
