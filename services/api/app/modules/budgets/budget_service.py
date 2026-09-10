from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.budgets import budget_repository
from app.modules.budgets.budget_schemas import (
    BudgetCreate,
    BudgetResponse,
    BudgetUpdate,
)
from app.modules.categories import service as categories_service


# Creates a new budget using validated input data and authenticated user id.
# This function exists to keep application and business logic
# separate from database and HTTP layers.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_data: validated budget creation data.
# - user_id: authenticated user identifier that owns the budget.
# Returns:
# - BudgetResponse created from the saved database model.
# Raises:
# - CategoryNotFoundError: when category_id is set and the category does not
#   exist or does not belong to the authenticated user.
def create_budget(
    db_session: Session,
    budget_data: BudgetCreate,
    user_id: UUID,
) -> BudgetResponse:
    if budget_data.category_id is not None:
        # A budget can only reference a category the authenticated user owns.
        # This mirrors the expense category ownership check so cross-user
        # category ids are rejected before persistence.
        categories_service.get_category_by_id(
            db_session=db_session,
            category_id=budget_data.category_id,
            user_id=user_id,
        )

    budget_model = budget_repository.create_budget(
        db_session=db_session,
        budget_data=budget_data,
        user_id=user_id,
    )

    return BudgetResponse.model_validate(budget_model)


# Returns budgets for the authenticated user.
# This function exists to map database models to public API responses
# and to ensure service-level reads are always scoped to a user.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier used to filter budgets.
# Returns:
# - List of BudgetResponse objects.
def get_budgets(
    db_session: Session,
    user_id: UUID,
) -> list[BudgetResponse]:
    budget_models = budget_repository.get_budgets(
        db_session=db_session,
        user_id=user_id,
    )

    return [
        BudgetResponse.model_validate(budget_model)
        for budget_model in budget_models
    ]


# Updates an existing budget owned by the authenticated user.
# This function exists to keep update business flow in the service layer
# and response mapping outside the repository layer.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_id: budget identifier.
# - budget_data: validated partial budget update data.
# - user_id: authenticated user identifier that owns the budget.
# Returns:
# - BudgetResponse created from the updated database model.
# Raises:
# - CategoryNotFoundError: when category_id is being changed to a non-null
#   value and the category does not exist or does not belong to the
#   authenticated user.
def update_budget(
    db_session: Session,
    budget_id: UUID,
    budget_data: BudgetUpdate,
    user_id: UUID,
) -> BudgetResponse:
    if (
        "category_id" in budget_data.model_fields_set
        and budget_data.category_id is not None
    ):
        # Only validate ownership when category_id is explicitly being
        # changed to a non-null value. An omitted category_id must not
        # trigger a lookup, and an explicit null clears the category
        # without needing ownership validation.
        categories_service.get_category_by_id(
            db_session=db_session,
            category_id=budget_data.category_id,
            user_id=user_id,
        )

    budget_model = budget_repository.update_budget(
        db_session=db_session,
        budget_id=budget_id,
        budget_data=budget_data,
        user_id=user_id,
    )

    return BudgetResponse.model_validate(budget_model)


# Deletes an existing budget owned by the authenticated user.
# This function exists to keep delete business flow in the service layer
# and to avoid exposing repository calls directly to the router.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_id: budget identifier.
# - user_id: authenticated user identifier that owns the budget.
# Returns:
# - None.
def delete_budget(
    db_session: Session,
    budget_id: UUID,
    user_id: UUID,
) -> None:
    budget_repository.delete_budget(
        db_session=db_session,
        budget_id=budget_id,
        user_id=user_id,
    )