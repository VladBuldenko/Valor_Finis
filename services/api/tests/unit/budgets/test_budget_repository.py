from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.db.database_session import SessionLocal
from app.modules.budgets import budget_repository
from app.modules.budgets.budget_schemas import BudgetCreate
from app.modules.budgets.budgets_models import BudgetModel


# Tests that the repository creates a new budget in the database.
# This test exists to verify that budget data is converted into BudgetModel and persisted through SQLAlchemy.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the created database model contains the expected values.
def test_create_budget_creates_new_budget(clean_database: None) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    budget_data = BudgetCreate(
        user_id=user_id,
        category_id=None,
        name="Food budget",
        limit_amount=Decimal("400"),
        currency="EUR",
        period="monthly",
        start_date=date(2026, 5, 1),
        end_date=None,
    )

    try:
        # Act
        created_budget = budget_repository.create_budget(
            db_session=db_session,
            budget_data=budget_data,
        )

        # Assert
        assert isinstance(created_budget, BudgetModel)
        assert created_budget.user_id == user_id
        assert created_budget.category_id is None
        assert created_budget.name == budget_data.name
        assert created_budget.limit_amount == Decimal("400")
        assert created_budget.currency == budget_data.currency
        assert created_budget.period == budget_data.period
        assert created_budget.start_date == budget_data.start_date
        assert created_budget.end_date is None
        assert created_budget.id is not None
        assert created_budget.created_at is not None
        assert created_budget.updated_at is not None
    finally:
        db_session.close()


# Tests that the repository returns budget records for a specific user.
# This test exists to verify that users only receive their own budgets from the repository layer.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the requested user's budget is returned.
def test_get_budgets_returns_budgets_for_user(clean_database: None) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    user_budget_data = BudgetCreate(
        user_id=user_id,
        category_id=None,
        name="Food budget",
        limit_amount=Decimal("400"),
        currency="EUR",
        period="monthly",
        start_date=date(2026, 5, 1),
        end_date=None,
    )

    other_user_budget_data = BudgetCreate(
        user_id=other_user_id,
        category_id=None,
        name="Transport budget",
        limit_amount=Decimal("150"),
        currency="EUR",
        period="monthly",
        start_date=date(2026, 5, 1),
        end_date=None,
    )

    try:
        budget_repository.create_budget(
            db_session=db_session,
            budget_data=user_budget_data,
        )
        budget_repository.create_budget(
            db_session=db_session,
            budget_data=other_user_budget_data,
        )

        # Act
        budgets = budget_repository.get_budgets(
            db_session=db_session,
            user_id=user_id,
        )
        # Assert
        assert len(budgets) == 1
        assert isinstance(budgets[0], BudgetModel)
        assert budgets[0].user_id == user_id
        assert budgets[0].category_id is None
        assert budgets[0].name == user_budget_data.name
        assert budgets[0].limit_amount == Decimal("400")
        assert budgets[0].currency == user_budget_data.currency
        assert budgets[0].period == user_budget_data.period
        assert budgets[0].start_date == user_budget_data.start_date
        assert budgets[0].end_date is None
    finally:
        db_session.close()