from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.accounts import account_repository, account_transaction_repository
from app.modules.accounts.account_errors import (
    AccountArchivedError,
    AccountCurrencyImmutableError,
    AccountDeletionNotAllowedError,
)
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_schemas import (
    AccountCreate,
    AccountResponse,
    AccountUpdate,
)
from app.modules.accounts.account_transaction_schemas import (
    AccountTransactionCreate,
    AccountTransactionResponse,
)


# Builds an AccountResponse from an Account model and an already-computed
# ledger-derived balance.
# This function exists to make the source of current_balance explicit and
# auditable: every public read path must pass in a balance it calculated
# from account_transactions, never AccountResponse.model_validate(
# account_model) - the Account row has no balance column to read in the
# first place, so this is the only way to populate current_balance.
# Parameters:
# - account_model: the Account database record (name/type/etc.).
# - current_balance: ledger-derived balance to report for this account.
# Returns:
# - AccountResponse with current_balance set to the given ledger balance.
def _build_account_response(
    account_model: AccountModel,
    current_balance: Decimal,
) -> AccountResponse:
    return AccountResponse(
        id=account_model.id,
        user_id=account_model.user_id,
        name=account_model.name,
        type=account_model.type,
        currency=account_model.currency,
        status=account_model.status,
        current_balance=current_balance,
        created_at=account_model.created_at,
        updated_at=account_model.updated_at,
    )


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

    current_balance = account_transaction_repository.calculate_ledger_balance(
        db_session=db_session,
        account_id=account_model.id,
        user_id=user_id,
    )

    return _build_account_response(account_model, current_balance)


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

    balances = account_transaction_repository.get_ledger_balances_for_user(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        _build_account_response(
            account_model,
            balances.get(account_model.id, Decimal("0.00")),
        )
        for account_model in account_models
    ]


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

    account_model = account_repository.apply_account_update(
        db_session=db_session,
        account_model=account_model,
        account_data=account_data,
    )

    current_balance = account_transaction_repository.calculate_ledger_balance(
        db_session=db_session,
        account_id=account_id,
        user_id=user_id,
    )

    return _build_account_response(account_model, current_balance)


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


# Returns the full transaction history for an account owned by the
# authenticated user.
# This function exists to enforce ownership before ever touching the
# ledger: another user's Account must behave as not found, never leaking
# whether it exists.
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

    transaction_models = account_transaction_repository.get_transactions_for_account(
        db_session=db_session,
        account_id=account_id,
        user_id=user_id,
    )

    return [
        AccountTransactionResponse.model_validate(transaction_model)
        for transaction_model in transaction_models
    ]
