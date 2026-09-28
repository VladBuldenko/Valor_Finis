from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.db.database_session import SessionLocal, engine
from app.main import app
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_transaction_models import AccountTransactionModel
from app.modules.accounts.account_transfer_models import AccountTransferModel
from app.modules.budgets.budgets_models import BudgetModel
from app.modules.categories.category_models import CategoryModel
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.financial_settings.financial_settings_models import (
    UserFinancialSettingsModel,
)
from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_transaction_models import GoalTransactionModel
from app.modules.income.income_models import IncomeModel
from app.modules.receipts.receipt_models import ReceiptModel
from tests.database_safety import UnsafeTestDatabaseError, validate_test_database_url


# Aborts the whole pytest run unless the effective test database is a
# dedicated PostgreSQL *_test database (VF-TEST-01).
# This hook exists so an accidental run against the development or a
# production database fails before any test or fixture can write to it.
# It validates engine.url - the already-resolved URL that SessionLocal and
# the TestClient app actually use - and runs during pytest configuration,
# before collection and test execution. Importing the app above creates
# the engine lazily and opens no connection, so nothing touches the
# database before this check.
# Parameters:
# - config: pytest configuration object (unused).
# Returns:
# - None.
# Raises:
# - pytest.UsageError: when the database is not a dedicated test database.
def pytest_configure(config: pytest.Config) -> None:
    del config

    try:
        validate_test_database_url(engine.url)
    except UnsafeTestDatabaseError as error:
        raise pytest.UsageError(str(error)) from None


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
    # Defense in depth (VF-TEST-01): pytest_configure normally rejects an
    # unsafe database first, but this fixture is the destructive path, so
    # it re-checks the same engine URL before its first DELETE.
    validate_test_database_url(engine.url)

    db_session = SessionLocal()

    try:
        db_session.query(ReceiptModel).delete()
        db_session.query(ExpenseModel).delete()
        db_session.query(IncomeModel).delete()
        db_session.query(BudgetModel).delete()
        db_session.query(GoalTransactionModel).delete()
        db_session.query(GoalModel).delete()
        db_session.query(AccountTransactionModel).delete()
        db_session.query(AccountTransferModel).delete()
        db_session.query(AccountModel).delete()
        db_session.query(CategoryModel).delete()
        db_session.query(UserFinancialSettingsModel).delete()
        db_session.commit()

        yield

        db_session.query(ReceiptModel).delete()
        db_session.query(ExpenseModel).delete()
        db_session.query(IncomeModel).delete()
        db_session.query(BudgetModel).delete()
        db_session.query(GoalTransactionModel).delete()
        db_session.query(GoalModel).delete()
        db_session.query(AccountTransactionModel).delete()
        db_session.query(AccountTransferModel).delete()
        db_session.query(AccountModel).delete()
        db_session.query(CategoryModel).delete()
        db_session.query(UserFinancialSettingsModel).delete()
        db_session.commit()
    finally:
        db_session.close()