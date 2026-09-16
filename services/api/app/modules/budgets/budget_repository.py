from typing import Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.budgets.budget_errors import (
    BudgetAlreadyExistsError,
    BudgetNotFoundError,
)
from app.modules.budgets.budget_schemas import BudgetCreate, BudgetUpdate
from app.modules.budgets.budgets_models import BudgetModel


# Creates and saves a new budget database record.
# This function exists to isolate PostgreSQL write operations
# from business logic and HTTP handling.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_data: validated budget creation data.
# - user_id: authenticated user identifier that owns the budget.
# - commit: whether the repository should commit the transaction immediately.
#   Pass False when the service layer is writing a budget and its initial
#   version as one atomic operation and will commit both together.
# Returns:
# - BudgetModel instance saved or flushed in the current transaction.
# Raises:
# - BudgetAlreadyExistsError: when the same user already has this budget.
def create_budget(
    db_session: Session,
    budget_data: BudgetCreate,
    user_id: UUID,
    commit: bool = True,
) -> BudgetModel:
    budget_model = BudgetModel(
        user_id=user_id,
        category_id=budget_data.category_id,
        name=budget_data.name,
        limit_amount=budget_data.limit_amount,
        currency=budget_data.currency,
        period=budget_data.period,
        start_date=budget_data.start_date,
        end_date=budget_data.end_date,
    )

    db_session.add(budget_model)

    try:
        if commit:
            db_session.commit()
        else:
            db_session.flush()
    except IntegrityError as error:
        db_session.rollback()

        constraint_name = getattr(
            getattr(error.orig, "diag", None),
            "constraint_name",
            None,
        )

        if constraint_name == "uq_budgets_user_id_name_period_start_date":
            raise BudgetAlreadyExistsError from error

        raise

    db_session.refresh(budget_model)

    return budget_model


# Returns budget database records.
# This function exists to isolate PostgreSQL read operations
# from business logic and HTTP handling.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: optional user identifier used to filter budgets.
# Returns:
# - List of BudgetModel instances ordered by start date.
def get_budgets(
    db_session: Session,
    user_id: Optional[UUID] = None,
) -> list[BudgetModel]:
    query = db_session.query(BudgetModel)

    if user_id is not None:
        query = query.filter(BudgetModel.user_id == user_id)

    return query.order_by(BudgetModel.start_date.desc()).all()


# Returns one budget by budget id and authenticated user id.
# This function exists to enforce ownership at the database query level.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_id: budget identifier.
# - user_id: authenticated user identifier that owns the budget.
# Returns:
# - BudgetModel instance from the database.
# Raises:
# - BudgetNotFoundError: when budget does not exist or does not belong to the user.
def get_budget_by_id(
    db_session: Session,
    budget_id: UUID,
    user_id: UUID,
) -> BudgetModel:
    budget_model = (
        db_session.query(BudgetModel)
        .filter(
            BudgetModel.id == budget_id,
            BudgetModel.user_id == user_id,
        )
        .first()
    )

    if budget_model is None:
        raise BudgetNotFoundError()

    return budget_model


# Updates an existing budget owned by the authenticated user.
# This function exists to isolate PostgreSQL update operations
# from business logic and HTTP handling.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_id: budget identifier.
# - budget_data: validated partial budget update data.
# - user_id: authenticated user identifier that owns the budget.
# - commit: whether the repository should commit the transaction immediately.
#   Pass False when the service layer is also writing a version row for
#   this update and will commit both together.
# Returns:
# - Updated BudgetModel instance, flushed or committed in the current
#   transaction.
# Raises:
# - BudgetNotFoundError: when budget does not exist or does not belong to the user.
# - BudgetAlreadyExistsError: when the same user already has this budget.
def update_budget(
    db_session: Session,
    budget_id: UUID,
    budget_data: BudgetUpdate,
    user_id: UUID,
    commit: bool = True,
) -> BudgetModel:
    budget_model = get_budget_by_id(
        db_session=db_session,
        budget_id=budget_id,
        user_id=user_id,
    )

    update_data = budget_data.model_dump(exclude_unset=True)

    for field_name, field_value in update_data.items():
        setattr(budget_model, field_name, field_value)

    try:
        if commit:
            db_session.commit()
        else:
            db_session.flush()
    except IntegrityError as error:
        db_session.rollback()

        constraint_name = getattr(
            getattr(error.orig, "diag", None),
            "constraint_name",
            None,
        )

        if constraint_name == "uq_budgets_user_id_name_period_start_date":
            raise BudgetAlreadyExistsError from error

        raise

    db_session.refresh(budget_model)

    return budget_model


# Deletes an existing budget owned by the authenticated user.
# This function exists to isolate PostgreSQL delete operations
# from business logic and HTTP handling.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_id: budget identifier.
# - user_id: authenticated user identifier that owns the budget.
# Returns:
# - None.
# Raises:
# - BudgetNotFoundError: when budget does not exist or does not belong to the user.
def delete_budget(
    db_session: Session,
    budget_id: UUID,
    user_id: UUID,
) -> None:
    budget_model = get_budget_by_id(
        db_session=db_session,
        budget_id=budget_id,
        user_id=user_id,
    )

    db_session.delete(budget_model)
    db_session.commit()


# Checks whether any budget owned by the user currently references a category.
# This function exists to let the categories module guard deletion without
# querying BudgetModel directly, preserving the repository boundary.
# Includes budgets regardless of end_date - a budget that has ended still
# has history that referenced this category, so it still counts.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - category_id: category identifier being checked.
# - user_id: authenticated user identifier that owns the budgets.
# Returns:
# - True if at least one budget references the category, False otherwise.
def has_budget_referencing_category(
    db_session: Session,
    category_id: UUID,
    user_id: UUID,
) -> bool:
    return (
        db_session.query(BudgetModel)
        .filter(
            BudgetModel.category_id == category_id,
            BudgetModel.user_id == user_id,
        )
        .first()
        is not None
    )