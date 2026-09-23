from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.modules.accounts.account_transaction_models import AccountTransactionModel


# Calculates an account's ledger balance from its transaction history.
# This function exists as the single source of truth for "what does the
# ledger say this Account is worth right now" - credit rows add to the
# balance, debit rows subtract from it. An account with no transactions
# has a balance of exactly Decimal("0.00"). Unlike Goal, this balance may
# be negative - there is no floor anywhere in this calculation.
#
# Uses one PostgreSQL SUM aggregate query (the same signed-CASE expression
# get_ledger_balances_for_user uses for its bulk grouped variant) rather
# than loading every row into Python and summing there - an account's
# ledger can grow indefinitely, so this keeps the query O(1) in
# transferred rows and memory regardless of history length. The
# arithmetic itself still happens in PostgreSQL NUMERIC, and the driver
# returns it as a Python Decimal - never float.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_id: account identifier to sum transactions for.
# - user_id: authenticated user identifier that owns the account, used as
#   a defense-in-depth filter alongside account_id.
# Returns:
# - Decimal ledger balance for the account.
def calculate_ledger_balance(
    db_session: Session,
    account_id: UUID,
    user_id: UUID,
) -> Decimal:
    signed_amount = case(
        (AccountTransactionModel.direction == "debit", -AccountTransactionModel.amount),
        else_=AccountTransactionModel.amount,
    )

    balance = (
        db_session.query(func.sum(signed_amount))
        .filter(
            AccountTransactionModel.account_id == account_id,
            AccountTransactionModel.user_id == user_id,
        )
        .scalar()
    )

    return balance if balance is not None else Decimal("0.00")


# Creates and saves a new immutable account transaction record.
# This function exists to isolate PostgreSQL write operations for the
# ledger from business logic and HTTP handling. It never commits by
# default so the caller (account_service) can keep this insert inside the
# same service-controlled database transaction as the owned Account row
# lock it acquired first (SELECT ... FOR UPDATE) - the lock must stay held
# until the insert itself commits.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_id: account this transaction belongs to.
# - user_id: authenticated user identifier that owns the account.
# - kind: one of "opening_balance", "adjustment".
# - direction: one of "credit", "debit".
# - amount: always positive; direction is carried by the direction column.
# - transaction_date: the date this event actually happened.
# - description: optional free-text note.
# - commit: whether the repository should commit the transaction
#   immediately. Pass False when composing this write with other changes
#   the caller will commit together.
# Returns:
# - AccountTransactionModel instance saved/flushed in the current
#   transaction.
def create_transaction(
    db_session: Session,
    account_id: UUID,
    user_id: UUID,
    kind: str,
    direction: str,
    amount: Decimal,
    transaction_date: date,
    description: Optional[str],
    commit: bool = True,
) -> AccountTransactionModel:
    transaction_model = AccountTransactionModel(
        account_id=account_id,
        user_id=user_id,
        kind=kind,
        direction=direction,
        amount=amount,
        transaction_date=transaction_date,
        description=description,
    )

    db_session.add(transaction_model)

    if commit:
        db_session.commit()
        db_session.refresh(transaction_model)
    else:
        db_session.flush()

    return transaction_model


# Returns an account's full transaction history, newest first.
# This function exists to isolate PostgreSQL read operations for the
# ledger from business logic and HTTP handling. Ordering is deterministic
# (transaction_date DESC, created_at DESC, id DESC) so transactions dated
# on the same day, or written in the same instant, never come back in an
# arbitrary order between requests.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_id: account identifier to list transactions for.
# - user_id: authenticated user identifier that owns the account, used as
#   a defense-in-depth filter alongside account_id.
# Returns:
# - List of AccountTransactionModel instances, newest first.
def get_transactions_for_account(
    db_session: Session,
    account_id: UUID,
    user_id: UUID,
) -> list[AccountTransactionModel]:
    return (
        db_session.query(AccountTransactionModel)
        .filter(
            AccountTransactionModel.account_id == account_id,
            AccountTransactionModel.user_id == user_id,
        )
        .order_by(
            AccountTransactionModel.transaction_date.desc(),
            AccountTransactionModel.created_at.desc(),
            AccountTransactionModel.id.desc(),
        )
        .all()
    )


# Returns every one of a user's accounts' ledger balances in a single
# grouped query.
# This function exists so a read path that lists multiple Accounts at once
# (GET /accounts) never issues one balance query per Account. An Account
# with no transactions simply has no entry in the returned mapping -
# callers must default a missing account_id to Decimal("0.00") themselves,
# since an account that was never funded has nothing to aggregate.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier to scope the aggregation to.
#   Ownership-safe by construction: another user's transactions can never
#   appear in the result, even for an account_id that happens to collide
#   only in theory (account_id is already unique, but filtering by
#   user_id here too matches the ownership-defense-in-depth convention
#   used everywhere else in this module).
# Returns:
# - Dict mapping account_id to its Decimal ledger balance, for accounts
#   that have at least one transaction.
def get_ledger_balances_for_user(
    db_session: Session,
    user_id: UUID,
) -> dict[UUID, Decimal]:
    signed_amount = case(
        (AccountTransactionModel.direction == "debit", -AccountTransactionModel.amount),
        else_=AccountTransactionModel.amount,
    )

    rows = (
        db_session.query(
            AccountTransactionModel.account_id,
            func.sum(signed_amount).label("balance"),
        )
        .filter(AccountTransactionModel.user_id == user_id)
        .group_by(AccountTransactionModel.account_id)
        .all()
    )

    return {account_id: balance for account_id, balance in rows}


# Returns whether an account has any transaction history at all.
# This function exists as the single source of truth for "is this Account
# funded/history-bearing", used to decide whether currency may still
# change and whether the Account may still be hard-deleted. Any
# transaction kind counts - opening_balance and adjustment both establish
# history, including a debit adjustment that brings the ledger balance
# back to exactly 0 or negative. This deliberately never uses a ledger
# balance calculation as a proxy for history: an Account can have real
# history and a 0.00 balance at the same time.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_id: account identifier to check.
# - user_id: authenticated user identifier that owns the account, used as
#   a defense-in-depth filter alongside account_id.
# Returns:
# - True if at least one AccountTransaction row exists for this account,
#   False otherwise. Uses an existence check (first matching id only)
#   rather than loading full history or aggregating a balance.
def has_transactions_for_account(
    db_session: Session,
    account_id: UUID,
    user_id: UUID,
) -> bool:
    first_transaction_id = (
        db_session.query(AccountTransactionModel.id)
        .filter(
            AccountTransactionModel.account_id == account_id,
            AccountTransactionModel.user_id == user_id,
        )
        .first()
    )

    return first_transaction_id is not None
