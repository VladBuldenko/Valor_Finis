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


# Updates an existing expense owned by the authenticated user, together
# with its resolved FX snapshot.
# This function exists to isolate PostgreSQL update logic from business
# logic. The FX snapshot fields are separate, always-required parameters
# (not part of expense_data) because expenses_service.update_expense has
# already decided their final values before calling this function -
# whether that means reusing the existing snapshot unchanged (a metadata-
# only or amount-only update) or a freshly resolved one (currency/date
# changed) - so this function never itself decides whether to call the
# FX resolver.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_id: expense identifier.
# - expense_data: validated partial expense update data.
# - user_id: authenticated user identifier that owns the expense.
# - base_amount/base_currency/fx_rate/fx_rate_date/fx_source: the final
#   FX snapshot values to persist (VF-014B5C) - may be None/unchanged
#   copies of the existing values when no monetary field changed.
# - commit: whether the repository should commit the transaction immediately.
# Returns:
# - Updated ExpenseModel instance, flushed or committed in the current
#   transaction.
# Raises:
# - ExpenseNotFoundError: when expense does not exist or does not belong to the user.
def update_expense(
    db_session: Session,
    expense_id: UUID,
    expense_data: ExpenseUpdate,
    user_id: UUID,
    base_amount: Optional[Decimal],
    base_currency: Optional[str],
    fx_rate: Optional[Decimal],
    fx_rate_date: Optional[date],
    fx_source: Optional[str],
    commit: bool = True,
) -> ExpenseModel:
    expense_model = get_expense_by_id(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )

    update_data = expense_data.model_dump(exclude_unset=True)

    for field_name, field_value in update_data.items():
        setattr(expense_model, field_name, field_value)

    expense_model.base_amount = base_amount
    expense_model.base_currency = base_currency
    expense_model.fx_rate = fx_rate
    expense_model.fx_rate_date = fx_rate_date
    expense_model.fx_source = fx_source

    if commit:
        db_session.commit()
    else:
        db_session.flush()

    db_session.refresh(expense_model)

    return expense_model


# Deletes an existing expense owned by the authenticated user.
# This function exists to isolate PostgreSQL delete logic from business logic.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - expense_id: expense identifier.
# - user_id: authenticated user identifier that owns the expense.
# Returns:
# - None.
# Raises:
# - ExpenseNotFoundError: when expense does not exist or does not belong to the user.
def delete_expense(
    db_session: Session,
    expense_id: UUID,
    user_id: UUID,
) -> None:
    expense_model = get_expense_by_id(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )

    db_session.delete(expense_model)
    db_session.commit()