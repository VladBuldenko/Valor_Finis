"""VF-MVP-CORE-002 schema stage (revision b8e2c5d1f739): the create-idempotency columns of
income and expenses.

These tests run the REAL Alembic CLI on throwaway *_test databases cloned from a template at the
previous revision (c4d8a2f6e193), populated with HISTORICAL rows before the upgrade. No hosted
database, production database or credential is involved.
"""
import hashlib
from pathlib import Path
from typing import Any, Generator
from uuid import uuid4

import pytest
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.db.database_base import Base
from app.db.database_models import import_database_models
from tests.integration.financial_rules.test_financial_rules_schema_migration import (
    _alembic,
    _constraint,
    _count,
    _create_database,
    _drop_database,
    _revision,
    _url_of,
)
from tests.schema_drift import exclude_stages_after

API_DIR = Path(__file__).resolve().parents[3]
PREVIOUS_REVISION = "c4d8a2f6e193"
REVISION = "b8e2c5d1f739"
MIGRATION_PATH = API_DIR / "alembic" / "versions" / f"{REVISION}_add_income_expense_create_idempotency.py"
NEW_COLUMNS = ("client_request_id", "client_request_fingerprint")
TABLES = {
    "income": ("uq_income_user_id_client_request_id", "ck_income_client_request_all_or_none"),
    "expenses": ("uq_expenses_user_id_client_request_id", "ck_expenses_client_request_all_or_none"),
}
FINGERPRINT = "a" * 64


@pytest.fixture(scope="module")
def previous_template() -> Generator[str, None, None]:
    name = f"core002_tpl_{uuid4().hex[:10]}_test"
    url = _create_database(name)
    try:
        result = _alembic(url, "upgrade", PREVIOUS_REVISION)
        assert result.returncode == 0, result.stderr
        yield name
    finally:
        _drop_database(name)


@pytest.fixture
def previous_database(previous_template: str) -> Generator[Engine, None, None]:
    name = f"core002_{uuid4().hex[:10]}_test"
    url = _create_database(name, template=previous_template)
    database_engine = create_engine(url)
    try:
        yield database_engine
    finally:
        database_engine.dispose()
        _drop_database(name)


@pytest.fixture
def migrated_database(previous_database: Engine) -> Engine:
    result = _alembic(_url_of(previous_database), "upgrade", REVISION)
    assert result.returncode == 0, result.stderr
    return previous_database


def _digest_columns(database_engine: Engine, table: str, columns: str) -> str:
    with database_engine.connect() as connection:
        rows = connection.execute(text(f"SELECT concat_ws('|', {columns}) FROM {table} ORDER BY id")).all()
    return hashlib.sha256("\n".join(row[0] for row in rows).encode()).hexdigest()


# Columns that exist BEFORE the stage: the digest of exactly these must survive the migration.
INCOME_OLD = "id, user_id, amount, currency, received_at, source, description, base_amount, base_currency, fx_rate, fx_rate_date, fx_source, created_at, updated_at"
EXPENSES_OLD = "id, user_id, category_id, title, amount, currency, expense_date, description, source, base_amount, base_currency, fx_rate, fx_rate_date, fx_source, created_at, updated_at"


def _seed_history(database_engine: Engine, user_id: Any) -> None:
    """Historical rows exactly as the previous runtime wrote them: no idempotency columns exist."""
    account_id, income_id, expense_id, legacy_expense_id = uuid4(), uuid4(), uuid4(), uuid4()
    with database_engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO accounts (id, user_id, name, type, currency, status) VALUES (:a, :u, 'Main', 'checking', 'EUR', 'active')"),
            {"a": account_id, "u": user_id})
        connection.execute(text(
            "INSERT INTO income (id, user_id, amount, currency, received_at, source, base_amount, base_currency, fx_rate, fx_rate_date, fx_source) "
            "VALUES (:i, :u, 2500.00, 'EUR', '2025-01-15', 'salary', 2500.00, 'EUR', 1, '2025-01-15', 'identity')"),
            {"i": income_id, "u": user_id})
        connection.execute(text(
            "INSERT INTO expenses (id, user_id, title, amount, currency, expense_date, source, base_amount, base_currency, fx_rate, fx_rate_date, fx_source) "
            "VALUES (:e, :u, 'Rent', 800.00, 'EUR', '2025-01-16', 'manual', 800.00, 'EUR', 1, '2025-01-16', 'identity')"),
            {"e": expense_id, "u": user_id})
        # A legacy foreign-currency expense whose FX snapshot was never resolved (all five NULL).
        connection.execute(text(
            "INSERT INTO expenses (id, user_id, title, amount, currency, expense_date, source) "
            "VALUES (:e, :u, 'Old USD', 12.34, 'USD', '2024-06-01', 'manual')"),
            {"e": legacy_expense_id, "u": user_id})
        connection.execute(text(
            "INSERT INTO account_transactions (id, account_id, user_id, kind, direction, amount, transaction_date, income_id) "
            "VALUES (:t, :a, :u, 'income', 'credit', 2500.00, '2025-01-15', :i)"),
            {"t": uuid4(), "a": account_id, "u": user_id, "i": income_id})
        connection.execute(text(
            "INSERT INTO account_transactions (id, account_id, user_id, kind, direction, amount, transaction_date, expense_id) "
            "VALUES (:t, :a, :u, 'expense', 'debit', 800.00, '2025-01-16', :e)"),
            {"t": uuid4(), "a": account_id, "u": user_id, "e": expense_id})


def _insert(database_engine: Engine, table: str, user_id: Any, **keys: Any) -> None:
    values = {"id": uuid4(), "user_id": user_id, **keys}
    if table == "income":
        values.update(amount=1, currency="EUR", received_at="2026-01-01", source="gift")
    else:
        values.update(title="t", amount=1, currency="EUR", expense_date="2026-01-01")
    columns = ", ".join(values)
    placeholders = ", ".join(f":{name}" for name in values)
    with database_engine.begin() as connection:
        connection.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"), values)


def _rejected(database_engine: Engine, table: str, user_id: Any, **keys: Any) -> str:
    with pytest.raises(IntegrityError) as caught:
        _insert(database_engine, table, user_id, **keys)
    return _constraint(caught.value) or ""


def test_revision_chain_has_one_head_on_top_of_the_previous_revision() -> None:
    script = ScriptDirectory.from_config(Config(str(API_DIR / "alembic.ini")))

    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS_REVISION


def test_migration_is_additive_and_contains_no_data_statement() -> None:
    source = MIGRATION_PATH.read_text()
    upgrade_body = source.split("def upgrade")[1].split("def downgrade")[0]

    for forbidden in ("INSERT INTO", "UPDATE ", "DELETE FROM", "DROP ", "TRUNCATE", "ALTER COLUMN", "server_default", "ForeignKey"):
        assert forbidden not in upgrade_body, forbidden
    assert "nullable=False" not in upgrade_body


def test_historical_rows_survive_the_upgrade_unchanged_and_get_null_keys(previous_database: Engine) -> None:
    user_id = uuid4()
    _seed_history(previous_database, user_id)
    before = {
        "income": _digest_columns(previous_database, "income", INCOME_OLD),
        "expenses": _digest_columns(previous_database, "expenses", EXPENSES_OLD),
    }
    counts = {t: _count(previous_database, f"SELECT count(*) FROM {t}") for t in ("income", "expenses", "accounts", "account_transactions")}
    ledger_sum = _count(previous_database, "SELECT sum(CASE direction WHEN 'credit' THEN amount ELSE -amount END)::int FROM account_transactions")

    result = _alembic(_url_of(previous_database), "upgrade", REVISION)
    assert result.returncode == 0, result.stderr

    assert _revision(previous_database) == REVISION
    assert before == {
        "income": _digest_columns(previous_database, "income", INCOME_OLD),
        "expenses": _digest_columns(previous_database, "expenses", EXPENSES_OLD),
    }
    assert counts == {t: _count(previous_database, f"SELECT count(*) FROM {t}") for t in counts}
    assert ledger_sum == _count(previous_database, "SELECT sum(CASE direction WHEN 'credit' THEN amount ELSE -amount END)::int FROM account_transactions")
    for table in TABLES:
        assert _count(previous_database, f"SELECT count(*) FROM {table} WHERE client_request_id IS NOT NULL OR client_request_fingerprint IS NOT NULL") == 0
    # The legacy unresolved-FX expense is untouched (not interpreted, not backfilled).
    assert _count(previous_database, "SELECT count(*) FROM expenses WHERE title = 'Old USD' AND base_amount IS NULL AND fx_source IS NULL") == 1


def test_columns_are_nullable_without_default_and_typed(migrated_database: Engine) -> None:
    with migrated_database.connect() as connection:
        for table in TABLES:
            rows = connection.execute(text(
                "SELECT column_name, data_type, character_maximum_length, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_name = :t AND column_name IN :c ORDER BY column_name"
            ).bindparams(bindparam("c", expanding=True)), {"t": table, "c": list(NEW_COLUMNS)}).all()
            assert [tuple(r) for r in rows] == [
                ("client_request_fingerprint", "character varying", 64, "YES", None),
                ("client_request_id", "uuid", None, "YES", None),
            ]


@pytest.mark.parametrize("table", sorted(TABLES))
def test_constraints_exist_and_behave(migrated_database: Engine, table: str) -> None:
    unique_name, check_name = TABLES[table]
    user, other_user, key = uuid4(), uuid4(), uuid4()

    # Legacy rows (both NULL) never collide, however many there are.
    _insert(migrated_database, table, user)
    _insert(migrated_database, table, user)
    # One key per user; the same key for another user is independent.
    _insert(migrated_database, table, user, client_request_id=key, client_request_fingerprint=FINGERPRINT)
    _insert(migrated_database, table, other_user, client_request_id=key, client_request_fingerprint=FINGERPRINT)
    assert _rejected(migrated_database, table, user, client_request_id=key, client_request_fingerprint=FINGERPRINT) == unique_name
    # The key and the fingerprint are set together or not at all.
    assert _rejected(migrated_database, table, user, client_request_id=uuid4()) == check_name
    assert _rejected(migrated_database, table, user, client_request_fingerprint=FINGERPRINT) == check_name

    with migrated_database.connect() as connection:
        kinds = dict(connection.execute(text(
            "SELECT conname, contype FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) AND conname IN (:u, :c)"),
            {"t": table, "u": unique_name, "c": check_name}).all())
    assert kinds == {unique_name: "u", check_name: "c"}


def test_orm_metadata_matches_the_migrated_schema_exactly(migrated_database: Engine) -> None:
    import_database_models()

    with migrated_database.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_previous_revision_differs_only_by_the_new_objects(previous_database: Engine) -> None:
    import_database_models()

    with previous_database.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences
    assert exclude_stages_after(differences, PREVIOUS_REVISION) == []


def test_downgrade_removes_only_the_new_objects_and_keeps_every_record_then_upgrades_again(previous_database: Engine) -> None:
    user_id = uuid4()
    _seed_history(previous_database, user_id)
    url = _url_of(previous_database)
    assert _alembic(url, "upgrade", REVISION).returncode == 0
    _insert(previous_database, "income", user_id, client_request_id=uuid4(), client_request_fingerprint=FINGERPRINT)
    income_before = _digest_columns(previous_database, "income", INCOME_OLD)
    expenses_before = _digest_columns(previous_database, "expenses", EXPENSES_OLD)

    down = _alembic(url, "downgrade", PREVIOUS_REVISION)

    assert down.returncode == 0, down.stderr
    assert _revision(previous_database) == PREVIOUS_REVISION
    with previous_database.connect() as connection:
        for table, (unique_name, check_name) in TABLES.items():
            columns = {r[0] for r in connection.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": table})}
            assert not columns & set(NEW_COLUMNS)
            assert connection.execute(text("SELECT count(*) FROM pg_constraint WHERE conname IN (:u, :c)"), {"u": unique_name, "c": check_name}).scalar_one() == 0
    # Every record (including the one that carried a key) is still there, unchanged.
    assert income_before == _digest_columns(previous_database, "income", INCOME_OLD)
    assert expenses_before == _digest_columns(previous_database, "expenses", EXPENSES_OLD)

    assert _alembic(url, "upgrade", REVISION).returncode == 0
    assert _revision(previous_database) == REVISION
