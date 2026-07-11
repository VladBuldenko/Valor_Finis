from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.budgets import budget_repository
from app.modules.budgets.budget_schemas import BudgetCreate, BudgetResponse


# Creates a new budget using validated input data and authenticated user id.
# This function exists to keep application and business logic
# separate from database and HTTP layers.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_data: validated budget creation data.
# - user_id: authenticated user identifier that owns the budget.
# Returns:
# - BudgetResponse created from the saved database model.
def create_budget(
    db_session: Session,
    budget_data: BudgetCreate,
    user_id: UUID,
) -> BudgetResponse:
    budget_model = budget_repository.create_budget(
        db_session=db_session,
        budget_data=budget_data,
        user_id=user_id,
    )

    return BudgetResponse.model_validate(budget_model)


# Returns budgets for a user or all budgets when user_id is not provided.
# This function exists to map database models to public API responses
# and provide a place for future business rules.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: optional user identifier used to filter budgets.
# Returns:
# - List of BudgetResponse objects.
def get_budgets(
    db_session: Session,
    user_id: Optional[UUID] = None,
) -> list[BudgetResponse]:
    budget_models = budget_repository.get_budgets(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        BudgetResponse.model_validate(budget_model)
        for budget_model in budget_models
    ]