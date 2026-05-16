from sqlalchemy.orm import Session

from app.modules.budgets.budgets_models import BudgetModel
from app.modules.budgets.budget_schemas import BudgetCreate, BudgetResponse


# Creates a new budget limit record in PostgreSQL.
# This function exists to isolate database write logic from business logic.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - budget_data: validated budget input data from the service layer.
# Returns:
# - BudgetResponse object created from the saved database model.
def create_budget(
    db_session: Session,
    budget_data: BudgetCreate,
) -> BudgetResponse:
    budget_model = BudgetModel(
        category=budget_data.category,
        monthly_limit=budget_data.monthly_limit,
        month=budget_data.month,
    )

    db_session.add(budget_model)
    db_session.commit()
    db_session.refresh(budget_model)

    return BudgetResponse.model_validate(budget_model)


# Returns all budget limit records from PostgreSQL.
# This function exists to isolate database read logic from business logic.
# Parameters:
# - db_session: active SQLAlchemy database session.
# Returns:
# - List of BudgetResponse objects created from database models.
def get_budgets(db_session: Session) -> list[BudgetResponse]:
    budget_models = db_session.query(BudgetModel).all()

    return [
        BudgetResponse.model_validate(budget_model)
        for budget_model in budget_models
    ]