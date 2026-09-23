from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.modules.accounts.account_transaction_models import AccountTransactionModel

# VF-017D: Income <-> Account ledger projection primitives.
#
# These four functions are the ONLY way an "income"-kind AccountTransaction
# row may ever be created, read, updated, or deleted. They exist as
# narrowly-scoped primitives - not a generic "update any AccountTransaction"
# function - specifically so no future code path can accidentally make a
# direct opening_balance/adjustment row mutable by reusing something meant
# only for source-backed projections. create_income_projection hardcodes
# kind="income", direction="credit", description=None; update_income_
# projection may only ever change account_id/amount/transaction_date (the
# three fields Income synchronization can legitimately need to change) -
# there is deliberately no way to change kind, direction, or description
# through it.


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


# Returns an Income's current AccountTransaction projection, if any.
# This function exists as the single way income_service resolves "is this
# Income currently linked, and to which Account" - callers that need to
# serialize against concurrent changes must have already locked the
# Income row (via income_repository.get_income_by_id_for_update) before
# calling this, so the projection observed here cannot be concurrently
# moved/detached out from under the caller.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - income_id: income identifier to look up the projection for.
# - user_id: authenticated user identifier that owns the income record,
#   used as a defense-in-depth filter alongside income_id.
# Returns:
# - AccountTransactionModel if a projection exists, None otherwise (an
#   unlinked Income has none).
def get_income_projection(
    db_session: Session,
    income_id: UUID,
    user_id: UUID,
) -> Optional[AccountTransactionModel]:
    return (
        db_session.query(AccountTransactionModel)
        .filter(
            AccountTransactionModel.income_id == income_id,
            AccountTransactionModel.user_id == user_id,
        )
        .first()
    )


# Validates that a projection given to update_income_projection or
# delete_income_projection is actually an Income projection, before any
# mutation or delete is issued.
# This function exists so those two functions guard against programmer
# misuse structurally, not merely by convention: without this check, a
# future internal caller could accidentally pass a direct opening_balance
# or adjustment row (e.g. from a mis-scoped query) and this repository
# would silently mutate/delete a row that is supposed to be immutable.
# This is an internal invariant violation, not a user-facing business
# error - it can only happen from a programming mistake inside this
# codebase, never from any client request, so it deliberately raises a
# plain ValueError rather than a new domain/HTTP error class.
# Parameters:
# - projection: the AccountTransactionModel a caller is about to mutate
#   or delete.
# Returns:
# - None.
# Raises:
# - ValueError: projection is not an Income projection (kind != "income"
#   or income_id is None).
def _validate_income_projection_for_mutation(
    projection: AccountTransactionModel,
) -> None:
    if projection.kind != "income" or projection.income_id is None:
        raise ValueError(
            "update_income_projection/delete_income_projection may only be "
            "called with an Income projection (kind='income', income_id "
            "set) - refusing to mutate/delete a direct "
            "opening_balance/adjustment row."
        )


# Creates the one AccountTransaction projection row for a newly-linked
# Income.
# This function exists as the only way a kind="income" row may be
# created - it hardcodes kind="income", direction="credit", and
# description=None (Income's own description/source stay the single
# canonical copy of that text; see account_transaction_models.py). Never
# commits by default so the caller (income_service) can keep this insert
# inside the same service-controlled transaction as the Income row write
# and the owned Account row lock it acquired first.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_id: the Account this Income is being linked to.
# - income_id: the Income this projection represents.
# - user_id: authenticated user identifier that owns both resources.
# - amount: the Income's own amount at the moment of linking.
# - transaction_date: the Income's own received_at at the moment of linking.
# - commit: whether the repository should commit the transaction
#   immediately.
# Returns:
# - AccountTransactionModel instance saved/flushed in the current
#   transaction.
def create_income_projection(
    db_session: Session,
    account_id: UUID,
    income_id: UUID,
    user_id: UUID,
    amount: Decimal,
    transaction_date: date,
    commit: bool = True,
) -> AccountTransactionModel:
    projection = AccountTransactionModel(
        account_id=account_id,
        user_id=user_id,
        kind="income",
        direction="credit",
        amount=amount,
        transaction_date=transaction_date,
        description=None,
        income_id=income_id,
    )

    db_session.add(projection)

    if commit:
        db_session.commit()
        db_session.refresh(projection)
    else:
        db_session.flush()

    return projection


# Synchronizes an existing Income projection's account_id/amount/
# transaction_date - the only three fields Income synchronization is ever
# allowed to change.
# This function exists as the only way an existing kind="income" row may
# be mutated - there is deliberately no way to change kind, direction, or
# description through it, keeping every other AccountTransaction row
# (opening_balance, adjustment) genuinely immutable by construction, not
# merely by convention: _validate_income_projection_for_mutation is
# called BEFORE any field is touched, so passing a direct row here raises
# ValueError instead of silently mutating it. Passing None for a
# parameter leaves that field unchanged - e.g. a same-Account amount/date
# sync passes account_id=None, while a move passes the new account_id
# alongside the current amount/transaction_date (harmless no-op writes
# when those did not themselves change). Never commits by default, for
# the same service-controlled-transaction reason as
# create_income_projection.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - projection: the already-resolved AccountTransactionModel to update
#   (from get_income_projection).
# - account_id: new Account to move this projection to, or None to leave
#   it on its current Account.
# - amount: new amount, or None to leave it unchanged.
# - transaction_date: new transaction date, or None to leave it unchanged.
# - commit: whether the repository should commit the transaction
#   immediately.
# Returns:
# - Updated AccountTransactionModel instance.
# Raises:
# - ValueError: projection is not an Income projection - see
#   _validate_income_projection_for_mutation.
def update_income_projection(
    db_session: Session,
    projection: AccountTransactionModel,
    account_id: Optional[UUID] = None,
    amount: Optional[Decimal] = None,
    transaction_date: Optional[date] = None,
    commit: bool = True,
) -> AccountTransactionModel:
    _validate_income_projection_for_mutation(projection)

    if account_id is not None:
        projection.account_id = account_id

    if amount is not None:
        projection.amount = amount

    if transaction_date is not None:
        projection.transaction_date = transaction_date

    if commit:
        db_session.commit()
        db_session.refresh(projection)
    else:
        db_session.flush()

    return projection


# Deletes an Income projection directly.
# This function exists for DETACH only (Income stays, its link to an
# Account is removed) - it must never be used when the Income itself is
# also being deleted. Deleting a linked Income relies on
# ON DELETE CASCADE (income_id -> income.id) to remove the projection
# automatically, once the owning service has already locked the linked
# Account row - see income_service.delete_income. Calling this function
# immediately before deleting the same Income would merely duplicate what
# CASCADE already does, without the lock-ordering guarantee CASCADE alone
# cannot provide. Never commits by default, for the same
# service-controlled-transaction reason as the other projection functions.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - projection: the already-resolved AccountTransactionModel to delete.
# - commit: whether the repository should commit the transaction
#   immediately.
# Returns:
# - None.
# Raises:
# - ValueError: projection is not an Income projection - see
#   _validate_income_projection_for_mutation.
def delete_income_projection(
    db_session: Session,
    projection: AccountTransactionModel,
    commit: bool = True,
) -> None:
    _validate_income_projection_for_mutation(projection)

    db_session.delete(projection)

    if commit:
        db_session.commit()
    else:
        db_session.flush()


# Returns every one of a user's Income-to-Account links in a single
# query.
# This function exists so a read path that lists multiple Income records
# at once (GET /income) never issues one projection lookup per Income -
# it mirrors get_ledger_balances_for_user's exact N+1-avoidance shape,
# applied to relationship-resolution instead of balance-aggregation. An
# Income with no entry in the returned mapping is simply unlinked.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier to scope the lookup to.
# Returns:
# - Dict mapping income_id to the account_id it is currently linked to,
#   for every linked Income the user owns.
def get_income_account_links_for_user(
    db_session: Session,
    user_id: UUID,
) -> dict[UUID, UUID]:
    rows = (
        db_session.query(
            AccountTransactionModel.income_id,
            AccountTransactionModel.account_id,
        )
        .filter(
            AccountTransactionModel.user_id == user_id,
            AccountTransactionModel.income_id.isnot(None),
        )
        .all()
    )

    return {income_id: account_id for income_id, account_id in rows}
