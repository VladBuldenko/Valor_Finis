from sqlalchemy.orm import Session

from app.modules.budgets import budget_repository
from app.modules.budgets.budget_schemas import BudgetCreate, BudgetResponse


# Creates a new budget limit using validated budget data.
# This function exists to keep budget business logic separate from API and database layers.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_data: validated budget input data.
# Returns:
# - BudgetResponse object created by the repository.
def create_budget(
    db_session: Session,
    budget_data: BudgetCreate,
) -> BudgetResponse:
    return budget_repository.create_budget(db_session, budget_data)


# Returns all created budget limits.
# This function exists to provide a clean service layer between router and repository.
# Parameters:
# - db_session: active SQLAlchemy database session.
# Returns:
# - List of BudgetResponse objects.
def get_budgets(db_session: Session) -> list[BudgetResponse]:
    return budget_repository.get_budgets(db_session)