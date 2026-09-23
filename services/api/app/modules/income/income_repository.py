from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.income.income_errors import IncomeNotFoundError
from app.modules.income.income_models import IncomeModel
from app.modules.income.income_schemas import IncomeCreate, IncomeUpdate


# Creates a new income database record, together with its FX snapshot.
# This function exists to isolate PostgreSQL write logic and support
# service-controlled transactions. The FX snapshot fields are separate
# parameters (not part of income_data) because they are always
# backend-resolved - income_service.create_income resolves them via
# app.modules.fx before this function is ever called, so the original and
# base-currency truth are persisted together in one INSERT.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - income_data: validated income input data from the service layer.
# - user_id: authenticated user identifier that owns the income record.
# - base_amount/base_currency/fx_rate/fx_rate_date/fx_source: the resolved
#   FX snapshot for this income record.
# - commit: whether the repository should commit the transaction
#   immediately.
# Returns:
# - IncomeModel instance saved or flushed in the current transaction.
def create_income(
    db_session: Session,
    income_data: IncomeCreate,
    user_id: UUID,
    base_amount: Decimal,
    base_currency: str,
    fx_rate: Decimal,
    fx_rate_date: date,
    fx_source: str,
    commit: bool = True,
) -> IncomeModel:
    income_model = IncomeModel(
        user_id=user_id,
        amount=income_data.amount,
        currency=income_data.currency,
        received_at=income_data.received_at,
        source=income_data.source,
        description=income_data.description,
        base_amount=base_amount,
        base_currency=base_currency,
        fx_rate=fx_rate,
        fx_rate_date=fx_rate_date,
        fx_source=fx_source,
    )

    db_session.add(income_model)

    if commit:
        db_session.commit()
    else:
        db_session.flush()

    db_session.refresh(income_model)

    return income_model


# Returns income database records for one user, newest received_at first.
# This function exists to isolate PostgreSQL read logic from business
# logic. Ordering is deterministic (received_at DESC, created_at DESC,
# id DESC) so two income records received on the same day never come back
# in an arbitrary order between requests.
#
# user_id is mandatory, not optional: Income is a strictly user-owned
# financial domain, and this repository must never expose an "all users"
# read path, even one the current service layer happens not to call
# today. Ownership filtering belongs in the repository primitive itself,
# not merely in how callers happen to use it.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter income records.
# Returns:
# - List of IncomeModel instances from the database, scoped to the user.
def get_income(
    db_session: Session,
    user_id: UUID,
) -> list[IncomeModel]:
    return (
        db_session.query(IncomeModel)
        .filter(IncomeModel.user_id == user_id)
        .order_by(
            IncomeModel.received_at.desc(),
            IncomeModel.created_at.desc(),
            IncomeModel.id.desc(),
        )
        .all()
    )


# Returns one income record by id and authenticated user id.
# This function exists to enforce ownership at the database query level.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - income_id: income identifier.
# - user_id: authenticated user identifier that owns the income record.
# Returns:
# - IncomeModel instance from the database.
# Raises:
# - IncomeNotFoundError: when the income record does not exist or does
#   not belong to the user.
def get_income_by_id(
    db_session: Session,
    income_id: UUID,
    user_id: UUID,
) -> IncomeModel:
    income_model = (
        db_session.query(IncomeModel)
        .filter(
            IncomeModel.id == income_id,
            IncomeModel.user_id == user_id,
        )
        .first()
    )

    if income_model is None:
        raise IncomeNotFoundError()

    return income_model


# Updates an existing income record owned by the authenticated user,
# together with its resolved FX snapshot.
# This function exists to isolate PostgreSQL update logic from business
# logic. The FX snapshot fields are separate, always-required parameters
# (not part of income_data) because income_service.update_income has
# already decided their final values before calling this function -
# whether that means reusing the existing snapshot unchanged (a
# metadata-only update) or a freshly resolved one (amount/currency/date
# changed) - so this function never itself decides whether to call the
# FX resolver.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - income_id: income identifier.
# - income_data: validated partial income update data.
# - user_id: authenticated user identifier that owns the income record.
# - base_amount/base_currency/fx_rate/fx_rate_date/fx_source: the final
#   FX snapshot values to persist.
# - commit: whether the repository should commit the transaction
#   immediately.
# Returns:
# - Updated IncomeModel instance, flushed or committed in the current
#   transaction.
# Raises:
# - IncomeNotFoundError: when the income record does not exist or does
#   not belong to the user.
def update_income(
    db_session: Session,
    income_id: UUID,
    income_data: IncomeUpdate,
    user_id: UUID,
    base_amount: Decimal,
    base_currency: str,
    fx_rate: Decimal,
    fx_rate_date: date,
    fx_source: str,
    commit: bool = True,
) -> IncomeModel:
    income_model = get_income_by_id(
        db_session=db_session,
        income_id=income_id,
        user_id=user_id,
    )

    update_data = income_data.model_dump(exclude_unset=True)

    for field_name, field_value in update_data.items():
        setattr(income_model, field_name, field_value)

    income_model.base_amount = base_amount
    income_model.base_currency = base_currency
    income_model.fx_rate = fx_rate
    income_model.fx_rate_date = fx_rate_date
    income_model.fx_source = fx_source

    if commit:
        db_session.commit()
    else:
        db_session.flush()

    db_session.refresh(income_model)

    return income_model


# Deletes an existing income record owned by the authenticated user.
# This function exists to isolate PostgreSQL delete logic from business
# logic.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - income_id: income identifier.
# - user_id: authenticated user identifier that owns the income record.
# Returns:
# - None.
# Raises:
# - IncomeNotFoundError: when the income record does not exist or does
#   not belong to the user.
def delete_income(
    db_session: Session,
    income_id: UUID,
    user_id: UUID,
) -> None:
    income_model = get_income_by_id(
        db_session=db_session,
        income_id=income_id,
        user_id=user_id,
    )

    db_session.delete(income_model)
    db_session.commit()
