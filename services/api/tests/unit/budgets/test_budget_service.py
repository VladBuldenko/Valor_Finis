from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.db.database_session import SessionLocal
from app.modules.budgets import budget_service
from app.modules.budgets.budget_schemas import BudgetCreate, BudgetResponse


# Tests that the service creates a budget and returns a response schema.
# This test exists to verify that the service layer maps database models to API responses.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the created budget response contains the expected values.
def test_create_budget_returns_budget_response(clean_database: None) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    budget_data = BudgetCreate(
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
        budget = budget_service.create_budget(
            db_session=db_session,
            budget_data=budget_data,
            user_id=user_id,
        )

        # Assert
        assert isinstance(budget, BudgetResponse)
        assert budget.user_id == user_id
        assert budget.category_id is None
        assert budget.name == budget_data.name
        assert budget.limit_amount == Decimal("400")
        assert budget.currency == budget_data.currency
        assert budget.period == budget_data.period
        assert budget.start_date == budget_data.start_date
        assert budget.end_date is None
        assert budget.id is not None
        assert budget.created_at is not None
        assert budget.updated_at is not None
    finally:
        db_session.close()


# Tests that the service returns budgets for a specific user.
# This test exists to verify that the service layer provides user-scoped budget responses.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the service returns only the requested user's budgets.
def test_get_budgets_returns_user_budget_responses(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    user_budget_data = BudgetCreate(
        category_id=None,
        name="Food budget",
        limit_amount=Decimal("400"),
        currency="EUR",
        period="monthly",
        start_date=date(2026, 5, 1),
        end_date=None,
    )

    other_user_budget_data = BudgetCreate(
        category_id=None,
        name="Transport budget",
        limit_amount=Decimal("150"),
        currency="EUR",
        period="monthly",
        start_date=date(2026, 5, 1),
        end_date=None,
    )

    try:
        budget_service.create_budget(
            db_session=db_session,
            budget_data=user_budget_data,
            user_id=user_id,
        )
        budget_service.create_budget(
            db_session=db_session,
            budget_data=other_user_budget_data,
            user_id=other_user_id,
        )

        # Act
        budgets = budget_service.get_budgets(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert len(budgets) == 1
        assert isinstance(budgets[0], BudgetResponse)
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