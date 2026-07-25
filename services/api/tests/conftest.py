from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.db.database_session import SessionLocal
from app.main import app
from app.modules.budgets.budgets_models import BudgetModel
from app.modules.categories.category_models import CategoryModel
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.goals.goal_models import GoalModel
from app.modules.receipts.receipt_models import ReceiptModel

# Creates a reusable FastAPI test client.
# This fixture exists to avoid creating TestClient separately in every integration test file.
# Parameters:
# - None.
# Returns:
# - TestClient instance connected to the FastAPI app.
@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# Cleans database tables before and after each test that uses this fixture.
# This fixture exists to keep database-backed tests independent from each other.
# Parameters:
# - None.
# Yields:
# - None. Test runs between database cleanup steps.
@pytest.fixture()
def clean_database() -> Generator[None, None, None]:
    db_session = SessionLocal()

    try:
        db_session.query(ReceiptModel).delete()
        db_session.query(ExpenseModel).delete()
        db_session.query(BudgetModel).delete()
        db_session.query(GoalModel).delete()
        db_session.query(CategoryModel).delete()
        db_session.commit()

        yield

        db_session.query(ReceiptModel).delete()
        db_session.query(ExpenseModel).delete()
        db_session.query(BudgetModel).delete()
        db_session.query(GoalModel).delete()
        db_session.query(CategoryModel).delete()
        db_session.commit()
    finally:
        db_session.close()