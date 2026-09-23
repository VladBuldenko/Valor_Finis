from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.accounts.account_errors import AccountNotFoundError
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_schemas import AccountCreate, AccountUpdate


# Creates and saves a new account database record.
# This function exists to isolate PostgreSQL write operations from
# business logic and HTTP handling. It never commits by default so the
# caller (account_service.create_account) can keep this insert inside the
# same service-controlled database transaction as the optional
# opening_balance AccountTransaction insert - both rows must be created
# atomically or not at all.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_data: validated account creation data.
# - user_id: authenticated user identifier that owns the account.
# - commit: whether the repository should commit the transaction
#   immediately. Pass False when composing this write with the opening
#   balance transaction the caller will commit together.
# Returns:
# - AccountModel instance saved/flushed in the current transaction.
def create_account(
    db_session: Session,
    account_data: AccountCreate,
    user_id: UUID,
    commit: bool = True,
) -> AccountModel:
    # A new Account has no account_transactions rows yet unless the
    # service inserts an opening_balance one right after this call, so its
    # ledger-derived balance is Decimal("0.00") by construction until then
    # - there is no balance field to set here at all.
    account_model = AccountModel(
        user_id=user_id,
        name=account_data.name,
        type=account_data.type,
        currency=account_data.currency,
        status=account_data.status,
    )

    db_session.add(account_model)

    if commit:
        db_session.commit()
    else:
        db_session.flush()

    db_session.refresh(account_model)

    return account_model


# Returns account database records.
# This function exists to isolate PostgreSQL read operations from
# business logic and HTTP handling.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: optional user identifier used to filter accounts.
# Returns:
# - List of AccountModel instances from the database.
def get_accounts(
    db_session: Session,
    user_id: Optional[UUID] = None,
) -> list[AccountModel]:
    query = db_session.query(AccountModel)

    if user_id is not None:
        query = query.filter(AccountModel.user_id == user_id)

    return query.order_by(AccountModel.created_at.desc()).all()


# Returns one account by account id and authenticated user id.
# This function exists to enforce ownership at the database query level.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_id: account identifier.
# - user_id: authenticated user identifier that owns the account.
# Returns:
# - AccountModel instance from the database.
# Raises:
# - AccountNotFoundError: when the account does not exist or does not
#   belong to the user.
def get_account_by_id(
    db_session: Session,
    account_id: UUID,
    user_id: UUID,
) -> AccountModel:
    account_model = (
        db_session.query(AccountModel)
        .filter(
            AccountModel.id == account_id,
            AccountModel.user_id == user_id,
        )
        .first()
    )

    if account_model is None:
        raise AccountNotFoundError()

    return account_model


# Returns one account by account id and authenticated user id, locking the
# row with SELECT ... FOR UPDATE for the duration of the caller's
# transaction.
# This function exists so every lifecycle operation that can race against
# a concurrent write on the same Account - a new transaction, a currency
# change, a delete, an archive - reads the Account under a row lock first.
# Callers must not commit or release the session between this call and the
# write it guards. Note that unlike Goal, this lock is never used to
# validate a balance (Account balances may go negative) - it exists purely
# to serialize lifecycle-state races.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_id: account identifier.
# - user_id: authenticated user identifier that owns the account.
# Returns:
# - AccountModel instance from the database, locked for update.
# Raises:
# - AccountNotFoundError: when the account does not exist or does not
#   belong to the user.
def get_account_by_id_for_update(
    db_session: Session,
    account_id: UUID,
    user_id: UUID,
) -> AccountModel:
    account_model = (
        db_session.query(AccountModel)
        .filter(
            AccountModel.id == account_id,
            AccountModel.user_id == user_id,
        )
        .with_for_update()
        .first()
    )

    if account_model is None:
        raise AccountNotFoundError()

    return account_model


# Applies validated partial update data to an already-locked Account model
# and commits.
# This function exists to isolate PostgreSQL update operations from
# business logic and HTTP handling. Callers (account_service.update_account)
# must have already obtained the row lock via get_account_by_id_for_update
# and performed any business-rule checks (e.g. currency immutability)
# before calling this - it applies changes unconditionally and never
# re-checks ownership or business rules itself.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_model: the already-locked AccountModel instance to update.
# - account_data: validated partial account update data.
# Returns:
# - Updated AccountModel instance.
def apply_account_update(
    db_session: Session,
    account_model: AccountModel,
    account_data: AccountUpdate,
) -> AccountModel:
    update_data = account_data.model_dump(exclude_unset=True)

    for field_name, field_value in update_data.items():
        setattr(account_model, field_name, field_value)

    db_session.commit()
    db_session.refresh(account_model)

    return account_model


# Deletes an already-locked Account model and commits.
# This function exists to isolate PostgreSQL delete operations from
# business logic and HTTP handling. Callers (account_service.delete_account)
# must have already obtained the row lock via get_account_by_id_for_update
# and confirmed no transaction history exists before calling this - it
# deletes unconditionally and never re-checks ownership or transaction
# history itself. The FK RESTRICT on account_transactions.account_id
# remains as defense-in-depth if that check is ever bypassed.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - account_model: the already-locked AccountModel instance to delete.
# Returns:
# - None.
def delete_locked_account(
    db_session: Session,
    account_model: AccountModel,
) -> None:
    db_session.delete(account_model)
    db_session.commit()
