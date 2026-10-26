from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.app_config import settings
from app.db.database_session import SessionLocal, engine
from app.main import app
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_transaction_models import AccountTransactionModel
from app.modules.accounts.account_transfer_models import AccountTransferModel
from app.modules.budgets.budgets_models import BudgetModel
from app.modules.categories.category_models import CategoryModel
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.financial_events.financial_event_models import FinancialEventModel
from app.modules.financial_rules.financial_rule_models import (
    FinancialRuleGoalTargetModel,
    FinancialRuleModel,
)
from app.modules.financial_rules.alert_dispatch_progress_models import AlertDispatchProgressModel
from app.modules.financial_rules.rule_alert_models import RuleAlertModel
from app.modules.financial_rules.rule_execution_models import (
    RuleExecutionAuditModel,
    RuleExecutionItemModel,
    RuleExecutionModel,
)
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


# Lets a test create non-archived Goals with a NULL priority_rank, the state
# the pre-D5 runtime could leave behind. It is OPT-IN (never autouse) and only
# relaxes the D5 lifecycle CHECK; nothing in it ranks Goals on anyone's behalf. It drops the D5 lifecycle CHECK for
# the test and, on teardown, deletes every Goal and Goal transaction and
# re-adds the CHECK, so the shared test database is left exactly at the
# current head schema.
@pytest.fixture
def pre_d5_goals_schema(clean_database: None) -> Generator[None, None, None]:
    validate_test_database_url(engine.url)

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE goals DROP CONSTRAINT IF EXISTS ck_goals_priority_rank_lifecycle"
        )

    try:
        yield
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM goal_transactions")
            connection.exec_driver_sql("DELETE FROM goals")
            connection.exec_driver_sql(
                "ALTER TABLE goals ADD CONSTRAINT ck_goals_priority_rank_lifecycle "
                "CHECK ((status = 'archived') = (priority_rank IS NULL))"
            )


# Creates a reusable FastAPI test client.
# This fixture exists to avoid creating TestClient separately in every integration test file.
# Parameters:
# - None.
# Returns:
# - TestClient instance connected to the FastAPI app.
@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# Rule-execution tables created by migration e0503e9ca9d3 (VF-020E6). They are
# OPTIONAL for the cleanup so the same fixture runs against both the E4 and the
# E6 schema (the previous runtime must keep working while the production
# migration is pending). Only these explicitly named tables may be absent; a
# missing core table, or any other SQL error, still fails the test.
# rule_alerts (VF-020E9A, migration a7c3e91d5b24) is optional for the same reason.
# alert_dispatch_progress (VF-020E10, migration c4d8a2f6e193) likewise.
OPTIONAL_E6_TABLES = frozenset({
    "rule_execution_audit", "rule_execution_items", "rule_executions", "rule_alerts",
    "alert_dispatch_progress",
})

# Deletion order that satisfies every foreign key (children first).
_CLEANUP_MODELS = (
    ReceiptModel,
    ExpenseModel,
    FinancialEventModel,
    RuleAlertModel,
    AlertDispatchProgressModel,
    RuleExecutionAuditModel,
    RuleExecutionItemModel,
    GoalTransactionModel,
    RuleExecutionModel,
    FinancialRuleGoalTargetModel,
    FinancialRuleModel,
    IncomeModel,
    BudgetModel,
    GoalModel,
    AccountTransactionModel,
    AccountTransferModel,
    AccountModel,
    CategoryModel,
    UserFinancialSettingsModel,
)


# Deletes every application row, child tables first. The set of tables that
# exist is read from the (already safety-validated) database once per call; only
# the explicitly optional E6 tables are skipped when absent.
def _delete_application_rows(db_session: Session) -> None:
    existing_tables = set(inspect(engine).get_table_names())

    for model in _CLEANUP_MODELS:
        table_name = model.__tablename__

        if table_name in OPTIONAL_E6_TABLES and table_name not in existing_tables:
            continue

        db_session.query(model).delete()


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
        _delete_application_rows(db_session)
        db_session.commit()

        yield

        _delete_application_rows(db_session)
        db_session.commit()
    finally:
        db_session.close()

# The best-effort post-response event drain is off for the whole suite so that
# tests observe the durable outbox states deterministically; the tests of the
# trigger itself switch it on explicitly.
@pytest.fixture(autouse=True)
def disable_background_event_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rule_event_background_dispatch", False)
