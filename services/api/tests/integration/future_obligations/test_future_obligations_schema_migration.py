from pathlib import Path
from typing import Any, Generator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, ProgrammingError

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.db.database_base import Base
from app.db.database_models import import_database_models
from tests.schema_drift import exclude_stages_after
from tests.integration.financial_rules.test_financial_rules_schema_migration import (
    DATA_API_ROLES,
    _admin_engine,
    _alembic,
    _constraint,
    _count,
    _create_database,
    _digest,
    _drop_database,
    _revision,
    _table_exists,
    _url_of,
)

# VF-GOALS-PLANNING-002C1 schema stage (revision e4a8c2d91b36): the future_obligations
# table. These tests run the REAL Alembic CLI on throwaway *_test databases cloned
# from a template at the previous revision; no production database or credential
# is involved, and the shared valor_test database is never migrated by them.

API_DIR = Path(__file__).resolve().parents[3]
PREVIOUS_REVISION = "b8e2c5d1f739"
REVISION = "e4a8c2d91b36"
MIGRATION_PATH = API_DIR / "alembic" / "versions" / f"{REVISION}_add_future_obligations.py"
TABLE = "future_obligations"


@pytest.fixture(scope="module")
def previous_template() -> Generator[str, None, None]:
    name = f"vf002c1_tpl_{uuid4().hex[:10]}_test"
    url = _create_database(name)
    try:
        result = _alembic(url, "upgrade", PREVIOUS_REVISION)
        assert result.returncode == 0, result.stderr
        yield name
    finally:
        _drop_database(name)


@pytest.fixture
def previous_database(previous_template: str) -> Generator[Engine, None, None]:
    name = f"vf002c1_{uuid4().hex[:10]}_test"
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


def _insert(database_engine: Engine, **overrides: Any) -> None:
    values: dict[str, Any] = {
        "id": uuid4(),
        "user_id": uuid4(),
        "name": "Rent",
        "schedule": "monthly",
        "amount": "950.00",
        "currency": "EUR",
        "first_due_date": "2026-12-01",
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join(f":{name}" for name in values)

    with database_engine.begin() as connection:
        connection.execute(text(f"INSERT INTO {TABLE} ({columns}) VALUES ({placeholders})"), values)


def _rejected(database_engine: Engine, **overrides: Any) -> str:
    with pytest.raises(IntegrityError) as caught:
        _insert(database_engine, **overrides)

    return _constraint(caught.value) or ""


def test_revision_chain_has_one_head_directly_on_top_of_the_previous_revision() -> None:
    script = ScriptDirectory.from_config(Config(str(API_DIR / "alembic.ini")))

    assert len(script.get_heads()) == 1
    assert REVISION in {revision.revision for revision in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PREVIOUS_REVISION


def test_upgrade_downgrade_and_upgrade_again_touch_only_the_new_objects(previous_database: Engine) -> None:
    url = _url_of(previous_database)
    watched = ("accounts", "goals", "goal_transactions", "expenses", "income", "budgets", "financial_rules")
    before = {table: _digest(previous_database, table) for table in watched}
    assert not _table_exists(previous_database, TABLE)

    assert _alembic(url, "upgrade", REVISION).returncode == 0
    assert _revision(previous_database) == REVISION and _table_exists(previous_database, TABLE)
    assert {table: _digest(previous_database, table) for table in watched} == before

    down = _alembic(url, "downgrade", PREVIOUS_REVISION)
    assert down.returncode == 0, down.stderr
    assert _revision(previous_database) == PREVIOUS_REVISION and not _table_exists(previous_database, TABLE)
    assert {table: _digest(previous_database, table) for table in watched} == before

    assert _alembic(url, "upgrade", REVISION).returncode == 0
    assert _table_exists(previous_database, TABLE)


def test_the_downgrade_refuses_to_destroy_hand_entered_obligations(migrated_database: Engine) -> None:
    user = uuid4()
    _insert(migrated_database, user_id=user)

    down = _alembic(_url_of(migrated_database), "downgrade", PREVIOUS_REVISION)

    assert down.returncode != 0 and "Refusing to downgrade" in down.stderr
    assert _revision(migrated_database) == REVISION
    assert _count(migrated_database, f"SELECT count(*) FROM {TABLE} WHERE user_id = :u", u=user) == 1


def test_the_migration_has_no_data_statements_and_no_foreign_keys() -> None:
    source = MIGRATION_PATH.read_text()
    upgrade_body = source.split("def upgrade")[1].split("def downgrade")[0]

    for forbidden in ("INSERT INTO", "UPDATE ", "DELETE FROM", "ForeignKey", "REFERENCES"):
        assert forbidden not in upgrade_body


def test_columns_types_nullability_and_defaults(migrated_database: Engine) -> None:
    with migrated_database.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT column_name, data_type, character_maximum_length, numeric_precision, numeric_scale, "
                "is_nullable, column_default FROM information_schema.columns WHERE table_name = :t ORDER BY ordinal_position"
            ),
            {"t": TABLE},
        ).all()

    assert [tuple(row) for row in rows] == [
        ("id", "uuid", None, None, None, "NO", None),
        ("user_id", "uuid", None, None, None, "NO", None),
        ("name", "character varying", 100, None, None, "NO", None),
        ("description", "character varying", 500, None, None, "YES", None),
        ("schedule", "character varying", 10, None, None, "NO", None),
        ("amount", "numeric", None, 12, 2, "NO", None),
        ("currency", "character varying", 3, None, None, "NO", None),
        ("first_due_date", "date", None, None, None, "NO", None),
        ("final_due_date", "date", None, None, None, "YES", None),
        ("status", "character varying", 10, None, None, "NO", "'active'::character varying"),
        ("client_request_id", "uuid", None, None, None, "YES", None),
        ("client_request_fingerprint", "character varying", 64, None, None, "YES", None),
        ("created_at", "timestamp with time zone", None, None, None, "NO", "now()"),
        ("updated_at", "timestamp with time zone", None, None, None, "NO", "now()"),
    ]


def test_constraints_and_indexes_are_exactly_the_documented_set(migrated_database: Engine) -> None:
    with migrated_database.connect() as connection:
        constraints = {
            name: kind
            for name, kind in connection.execute(
                text("SELECT conname, contype FROM pg_constraint WHERE conrelid = 'future_obligations'::regclass AND contype <> 'n'")
            )
        }
        indexes = {name for (name,) in connection.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'future_obligations'"))}

    assert constraints == {
        "future_obligations_pkey": "p",
        "uq_future_obligations_user_id_client_request_id": "u",
        "ck_future_obligations_amount_positive": "c",
        "ck_future_obligations_schedule_valid": "c",
        "ck_future_obligations_status_valid": "c",
        "ck_future_obligations_currency_format": "c",
        "ck_future_obligations_name_not_blank": "c",
        "ck_future_obligations_first_due_date_range": "c",
        "ck_future_obligations_final_due_date_range": "c",
        "ck_future_obligations_final_not_before_first": "c",
        "ck_future_obligations_one_time_has_no_final": "c",
        "ck_future_obligations_client_request_all_or_none": "c",
    }  # no foreign key of any kind: nothing is inferred from or posted to another domain
    assert indexes == {
        "future_obligations_pkey",
        "uq_future_obligations_user_id_client_request_id",
        "ix_future_obligations_user_id_status",
    }


def test_valid_rows_are_accepted(migrated_database: Engine) -> None:
    _insert(migrated_database)
    _insert(migrated_database, schedule="one_time", first_due_date="2100-12-31")
    _insert(migrated_database, first_due_date="2000-01-01", final_due_date="2000-01-01")
    _insert(migrated_database, status="archived", description=None, amount="0.01", currency="USD")
    _insert(migrated_database, amount="9999999999.99")

    assert _count(migrated_database, f"SELECT count(*) FROM {TABLE}") == 5


@pytest.mark.parametrize(
    "overrides, constraint",
    [
        ({"amount": "0"}, "ck_future_obligations_amount_positive"),
        ({"amount": "-1.00"}, "ck_future_obligations_amount_positive"),
        ({"schedule": "weekly"}, "ck_future_obligations_schedule_valid"),
        ({"schedule": ""}, "ck_future_obligations_schedule_valid"),
        ({"status": "paused"}, "ck_future_obligations_status_valid"),
        ({"currency": "eur"}, "ck_future_obligations_currency_format"),
        ({"currency": "EU"}, "ck_future_obligations_currency_format"),
        ({"currency": "E1R"}, "ck_future_obligations_currency_format"),
        ({"name": ""}, "ck_future_obligations_name_not_blank"),
        ({"name": "   "}, "ck_future_obligations_name_not_blank"),
        ({"first_due_date": "1999-12-31"}, "ck_future_obligations_first_due_date_range"),
        ({"first_due_date": "2101-01-01"}, "ck_future_obligations_first_due_date_range"),
        ({"final_due_date": "2101-01-01"}, "ck_future_obligations_final_due_date_range"),
        ({"final_due_date": "2026-11-30"}, "ck_future_obligations_final_not_before_first"),
        ({"schedule": "one_time", "final_due_date": "2027-01-01"}, "ck_future_obligations_one_time_has_no_final"),
        ({"client_request_id": uuid4()}, "ck_future_obligations_client_request_all_or_none"),
        ({"client_request_fingerprint": "a" * 64}, "ck_future_obligations_client_request_all_or_none"),
    ],
)
def test_the_database_rejects_invalid_rows(migrated_database: Engine, overrides: dict[str, Any], constraint: str) -> None:
    assert _rejected(migrated_database, **overrides) == constraint
    assert _count(migrated_database, f"SELECT count(*) FROM {TABLE}") == 0


def test_the_name_description_and_currency_lengths_are_bounded(migrated_database: Engine) -> None:
    with pytest.raises(Exception):
        _insert(migrated_database, name="x" * 101)
    with pytest.raises(Exception):
        _insert(migrated_database, description="x" * 501)
    with pytest.raises(Exception):
        _insert(migrated_database, currency="EURO")  # the column itself is VARCHAR(3)

    _insert(migrated_database, name="x" * 100, description="y" * 500)


def test_a_client_request_id_is_unique_per_user_and_null_keys_never_collide(migrated_database: Engine) -> None:
    user, key = uuid4(), uuid4()
    _insert(migrated_database, user_id=user, client_request_id=key, client_request_fingerprint="a" * 64)

    assert _rejected(
        migrated_database, user_id=user, client_request_id=key, client_request_fingerprint="b" * 64
    ) == "uq_future_obligations_user_id_client_request_id"

    _insert(migrated_database, user_id=uuid4(), client_request_id=key, client_request_fingerprint="a" * 64)  # another user
    _insert(migrated_database, user_id=user)  # NULL keys
    _insert(migrated_database, user_id=user)


def test_the_orm_matches_the_migrated_schema(migrated_database: Engine) -> None:
    import_database_models()

    with migrated_database.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    # Later stages (002C2: the link table and the owner unique key) are in the ORM but
    # not at this revision; they are excluded by name, nothing else is.
    remaining = exclude_stages_after(differences, REVISION)

    assert [difference for difference in remaining if TABLE in repr(difference)] == []


def test_the_data_api_roles_have_no_privilege_on_the_new_table(previous_database: Engine) -> None:
    admin = _admin_engine()
    created_roles: list[str] = []
    database_name = previous_database.url.database

    try:
        try:
            with admin.connect() as connection:
                for role in DATA_API_ROLES:
                    if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first() is None:
                        connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
                        created_roles.append(role)
        except ProgrammingError:
            pytest.skip("test database user cannot create the Data API roles")

        grantees = ", ".join(f'"{role}"' for role in DATA_API_ROLES)
        with previous_database.begin() as connection:
            connection.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {grantees}"))
            connection.execute(text("CREATE TABLE public.control_table (id integer)"))

        assert _alembic(_url_of(previous_database), "upgrade", REVISION).returncode == 0

        with previous_database.connect() as connection:
            for role in DATA_API_ROLES:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    assert connection.execute(
                        text("SELECT has_table_privilege(:r, 'public.control_table', :p)"), {"r": role, "p": privilege}
                    ).scalar_one() is True, ("control", role, privilege)
                    assert connection.execute(
                        text("SELECT has_table_privilege(:r, 'public.future_obligations', :p)"), {"r": role, "p": privilege}
                    ).scalar_one() is False, (role, privilege)
    finally:
        previous_database.dispose()
        try:
            if created_roles:
                _drop_database(database_name)
                with admin.connect() as connection:
                    for role in created_roles:
                        connection.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        finally:
            admin.dispose()
