from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.expenses.expenses_errors import ExpenseNotFoundError
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.expenses.expenses_schemas import ExpenseCreate, ExpenseUpdate


# Creates a new expense database record, together with its FX snapshot.
# This function exists to isolate PostgreSQL write logic
# and support service-controlled transactions. The FX snapshot fields are
# separate parameters (not part of expense_data) because they are always
# backend-resolved - expenses_service.create_expense resolves them via
# app.modules.fx before this function is ever called, so the original and
# base-currency truth are persisted together in one INSERT.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_data: validated expense input data from the service layer.
# - user_id: authenticated user identifier that owns the expense.
# - base_amount/base_currency/fx_rate/fx_rate_date/fx_source: the resolved
#   FX snapshot for this expense (VF-014B5C).
# - commit: whether the repository should commit the transaction immediately.
# Returns:
# - ExpenseModel instance saved or flushed in the current transaction.
def create_expense(
    db_session: Session,
    expense_data: ExpenseCreate,
    user_id: UUID,
    base_amount: Decimal,
    base_currency: str,
    fx_rate: Decimal,
    fx_rate_date: date,
    fx_source: str,
    commit: bool = True,
) -> ExpenseModel:
    expense_model = ExpenseModel(
        user_id=user_id,
        category_id=expense_data.category_id,
        title=expense_data.title,
        amount=expense_data.amount,
        currency=expense_data.currency,
        expense_date=expense_data.expense_date,
        description=expense_data.description,
        source=expense_data.source,
        base_amount=base_amount,
        base_currency=base_currency,
        fx_rate=fx_rate,
        fx_rate_date=fx_rate_date,
        fx_source=fx_source,
    )

    db_session.add(expense_model)

    if commit:
        db_session.commit()
    else:
        db_session.flush()

    db_session.refresh(expense_model)

    return expense_model


# Returns expense database records.
# This function exists to isolate PostgreSQL read logic from business logic.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: optional user identifier used to filter expenses.
# Returns:
# - List of ExpenseModel instances from the database.
def get_expenses(
    db_session: Session,
    user_id: Optional[UUID] = None,
) -> list[ExpenseModel]:
    query = db_session.query(ExpenseModel)

    if user_id is not None:
        query = query.filter(ExpenseModel.user_id == user_id)

    return query.order_by(ExpenseModel.expense_date.desc()).all()


# Returns expense database records for one user within an inclusive date
# range, filtered at the database level.
# This function exists for analytics reads that only need a bounded window
# of history (e.g. VF-015B spending trend) - unlike get_expenses above, it
# never loads a user's entire lifetime of expenses just to filter most of
# them back out in Python.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter expenses.
# - start_date: inclusive lower bound on expense_date.
# - end_date: inclusive upper bound on expense_date.
# Returns:
# - List of ExpenseModel instances within the range, scoped to the user.
def get_expenses_in_date_range(
    db_session: Session,
    user_id: UUID,
    start_date: date,
    end_date: date,
) -> list[ExpenseModel]:
    return (
        db_session.query(ExpenseModel)
        .filter(
            ExpenseModel.user_id == user_id,
            ExpenseModel.expense_date >= start_date,
            ExpenseModel.expense_date <= end_date,
        )
        .all()
    )


# Returns one expense by expense id and authenticated user id.
# This function exists to enforce ownership at the database query level.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_id: expense identifier.
# - user_id: authenticated user identifier that owns the expense.
# Returns:
# - ExpenseModel instance from the database.
# Raises:
# - ExpenseNotFoundError: when expense does not exist or does not belong to the user.
def get_expense_by_id(
    db_session: Session,
    expense_id: UUID,
    user_id: UUID,
) -> ExpenseModel:
    expense_model = (
        db_session.query(ExpenseModel)
        .filter(
            ExpenseModel.id == expense_id,
            ExpenseModel.user_id == user_id,
        )
        .first()
    )

    if expense_model is None:
        raise ExpenseNotFoundError()

    return expense_model


# Returns one expense by expense id and authenticated user id, locking
# the row with SELECT ... FOR UPDATE for the duration of the caller's
# transaction. Exact mirror of income_repository.get_income_by_id_for_update.
# This function exists so every Expense PATCH/DELETE reads the Expense
# under a row lock before resolving its current Account projection or
# writing anything (VF-017E). This protects against the same races
# Income row-locking was introduced for: two concurrent updates to the
# SAME Expense, and an update racing a concurrent attach/detach/move of
# the same Expense. Callers must not commit or release the session
# between this call and the write(s) it guards.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_id: expense identifier.
# - user_id: authenticated user identifier that owns the expense.
# Returns:
# - ExpenseModel instance from the database, locked for update.
# Raises:
# - ExpenseNotFoundError: when expense does not exist or does not belong to the user.
def get_expense_by_id_for_update(
    db_session: Session,
    expense_id: UUID,
    user_id: UUID,
) -> ExpenseModel:
    expense_model = (
        db_session.query(ExpenseModel)
        .filter(
            ExpenseModel.id == expense_id,
            ExpenseModel.user_id == user_id,
        )
        .with_for_update()
        .first()
    )

    if expense_model is None:
        raise ExpenseNotFoundError()

    return expense_model


# Applies validated partial update data, plus a resolved FX snapshot, to
# an already-locked Expense model and commits. Exact mirror of
# income_repository.update_income.
# This function exists to isolate PostgreSQL update logic from business
# logic. It takes the already-locked expense_model directly (not an id to
# re-fetch) - VF-017E requires every Expense update to run under
# get_expense_by_id_for_update's row lock first, so re-querying here
# would be redundant and, worse, would not be the locked instance the
# caller already holds. The FX snapshot fields are separate,
# always-required parameters (not part of expense_data) because
# expenses_service.update_expense has already decided their final values
# before calling this function - whether that means reusing the existing
# snapshot unchanged (a metadata-only or amount-only update) or a freshly
# resolved one (currency/date changed) - so this function never itself
# decides whether to call the FX resolver.
#
# account_id is explicitly excluded from the generic update_data loop:
# Expense has no account_id database column at all (VF-017E) - it is a
# derived, read-only response field, never a persisted one. Without this
# exclusion, model_dump(exclude_unset=True) would include a client-
# supplied account_id and the blind setattr(expense_model, "account_id",
# ...) below would silently create a Python-only instance attribute that
# is never persisted and vanishes on the next refresh/reload - exactly
# the kind of "virtual field" bug this exclusion exists to make
# structurally impossible. Linkage itself is applied separately, by
# expenses_service, through the dedicated Expense-projection repository
# functions in account_transaction_repository.py.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_model: the already-locked ExpenseModel instance to update
#   (from get_expense_by_id_for_update).
# - expense_data: validated partial expense update data.
# - base_amount/base_currency/fx_rate/fx_rate_date/fx_source: the final
#   FX snapshot values to persist (VF-014B5C) - may be None/unchanged
#   copies of the existing values when no monetary field changed.
# - commit: whether the repository should commit the transaction immediately.
# Returns:
# - Updated ExpenseModel instance, flushed or committed in the current
#   transaction.
def update_expense(
    db_session: Session,
    expense_model: ExpenseModel,
    expense_data: ExpenseUpdate,
    base_amount: Optional[Decimal],
    base_currency: Optional[str],
    fx_rate: Optional[Decimal],
    fx_rate_date: Optional[date],
    fx_source: Optional[str],
    commit: bool = True,
) -> ExpenseModel:
    update_data = expense_data.model_dump(exclude_unset=True, exclude={"account_id"})

    for field_name, field_value in update_data.items():
        setattr(expense_model, field_name, field_value)

    expense_model.base_amount = base_amount
    expense_model.base_currency = base_currency
    expense_model.fx_rate = fx_rate
    expense_model.fx_rate_date = fx_rate_date
    expense_model.fx_source = fx_source

    if commit:
        db_session.commit()
        db_session.refresh(expense_model)
    else:
        db_session.flush()

    return expense_model


# Deletes an already-locked Expense model. Exact mirror of
# income_repository.delete_income.
# This function exists to isolate PostgreSQL delete logic from business
# logic. Takes the already-locked expense_model directly (from
# get_expense_by_id_for_update) - deleting a linked Expense must run
# under the same row lock expenses_service already acquired before
# resolving/locking its Account projection (VF-017E), not a fresh
# unlocked re-fetch. Any AccountTransaction projection row is removed
# automatically by the database (expense_id -> expenses.id ON DELETE
# CASCADE) as part of this same DELETE - this function never deletes the
# projection itself; see expenses_service.delete_expense for the full
# lock-then-delete sequence.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_model: the already-locked ExpenseModel instance to delete.
# - commit: whether the repository should commit the transaction
#   immediately.
# Returns:
# - None.
def delete_expense(
    db_session: Session,
    expense_model: ExpenseModel,
    commit: bool = True,
) -> None:
    db_session.delete(expense_model)

    if commit:
        db_session.commit()
    else:
        db_session.flush()