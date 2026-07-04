from typing import Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.budgets.budgets_models import BudgetModel
from app.modules.budgets.budget_schemas import BudgetCreate
from app.modules.budgets.errors import BudgetAlreadyExistsError


# Creates and saves a new budget database record.
# This function exists to isolate PostgreSQL write operations
# from business logic and HTTP handling.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_data: validated budget creation data.
# Returns:
# - BudgetModel instance saved in PostgreSQL.
# Raises:
# - BudgetAlreadyExistsError: when the same user already has this budget.
def create_budget(
    db_session: Session,
    budget_data: BudgetCreate,
) -> BudgetModel:
    budget_model = BudgetModel(
        user_id=budget_data.user_id,
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
        db_session.commit()
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