import threading
from pathlib import Path
from typing import Any, Generator, List
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
from tests.schema_drift import exclude_stages_after

# VF-020E10 schema stage (revision c4d8a2f6e193): alert_dispatch_progress and the
# alert_dispatch_service_seq sequence. Schema only: these tests run the REAL
# Alembic CLI on throwaway *_test databases cloned from a template at the E9A
# revision; no production database or credential is involved.

API_DIR = Path(__file__).resolve().parents[3]
E9A_REVISION = "a7c3e91d5b24"
PROGRESS_REVISION = "c4d8a2f6e193"
MIGRATION_PATH = API_DIR / "alembic" / "versions" / f"{PROGRESS_REVISION}_add_alert_dispatch_progress.py"
TABLE = "alert_dispatch_progress"
SEQUENCE = "alert_dispatch_service_seq"


@pytest.fixture(scope="module")
def e9a_template() -> Generator[str, None, None]:
    name = f"vf020e10_tpl_{uuid4().hex[:10]}_test"
    url = _create_database(name)
    try:
        result = _alembic(url, "upgrade", E9A_REVISION)
        assert result.returncode == 0, result.stderr
        yield name
    finally:
        _drop_database(name)


@pytest.fixture
def e9a_database(e9a_template: str) -> Generator[Engine, None, None]:
    name = f"vf020e10_{uuid4().hex[:10]}_test"
    url = _create_database(name, template=e9a_template)
    database_engine = create_engine(url)
    try:
        yield database_engine
    finally:
        database_engine.dispose()
        _drop_database(name)


@pytest.fixture
def progress_database(e9a_database: Engine) -> Engine:
    result = _alembic(_url_of(e9a_database), "upgrade", PROGRESS_REVISION)
    assert result.returncode == 0, result.stderr
    return e9a_database


def _next_seq(database_engine: Engine) -> int:
    with database_engine.begin() as connection:
        return int(connection.execute(text(f"SELECT nextval('{SEQUENCE}')")).scalar_one())


def _insert(database_engine: Engine, user_id: UUID, **overrides: Any) -> None:
    values = {"user_id": user_id, "service_seq": _next_seq(database_engine)}
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join(f":{name}" for name in values)
    with database_engine.begin() as connection:
        connection.execute(text(f"INSERT INTO {TABLE} ({columns}) VALUES ({placeholders})"), values)


def _rejected(database_engine: Engine, user_id: UUID, **overrides: Any) -> str:
    with pytest.raises(IntegrityError) as caught:
        _insert(database_engine, user_id, **overrides)
    return _constraint(caught.value) or ""


def test_revision_chain_has_one_head_on_top_of_e9a() -> None:
    script = ScriptDirectory.from_config(Config(str(API_DIR / "alembic.ini")))

    assert script.get_heads() == [PROGRESS_REVISION]
    assert script.get_revision(PROGRESS_REVISION).down_revision == E9A_REVISION


def test_upgrade_downgrade_and_upgrade_again_touch_only_the_new_objects(e9a_database: Engine) -> None:
    url = _url_of(e9a_database)
    before = {t: _digest(e9a_database, t) for t in ("accounts", "financial_rules", "rule_alerts", "goal_transactions")}
    assert not _table_exists(e9a_database, TABLE)

    assert _alembic(url, "upgrade", PROGRESS_REVISION).returncode == 0
    assert _revision(e9a_database) == PROGRESS_REVISION and _table_exists(e9a_database, TABLE)
    assert {t: _digest(e9a_database, t) for t in before} == before

    _insert(e9a_database, uuid4())  # operational rows may exist: the downgrade needs no history guard
    down = _alembic(url, "downgrade", E9A_REVISION)
    assert down.returncode == 0, down.stderr
    assert _revision(e9a_database) == E9A_REVISION and not _table_exists(e9a_database, TABLE)
    assert _count(e9a_database, "SELECT count(*) FROM pg_class WHERE relname = :n", n=SEQUENCE) == 0
    assert {t: _digest(e9a_database, t) for t in before} == before

    assert _alembic(url, "upgrade", PROGRESS_REVISION).returncode == 0
    assert _table_exists(e9a_database, TABLE)


def test_migration_has_no_data_statements_and_no_foreign_keys() -> None:
    source = MIGRATION_PATH.read_text()
    upgrade_body = source.split("def upgrade")[1].split("def downgrade")[0]

    assert "SET LOCAL" not in source and "LOCK TABLE" not in source  # it locks no existing table
    for forbidden in ("INSERT INTO", "UPDATE ", "DELETE FROM", "ForeignKey", "REFERENCES"):
        assert forbidden not in upgrade_body


def test_columns_types_nullability_and_defaults(progress_database: Engine) -> None:
    with progress_database.connect() as connection:
        rows = connection.execute(text(
            "SELECT column_name, data_type, character_maximum_length, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = :t ORDER BY ordinal_position"), {"t": TABLE}).all()

    assert [tuple(row) for row in rows] == [
        ("user_id", "uuid", None, "NO", None),
        ("service_seq", "bigint", None, "NO", None),
        ("last_attempted_at", "timestamp with time zone", None, "NO", "now()"),
        ("last_success_at", "timestamp with time zone", None, "YES", None),
        ("consecutive_failures", "integer", None, "NO", "0"),
        ("last_error_code", "character varying", 64, "YES", None),
    ]


def test_constraints_and_indexes(progress_database: Engine) -> None:
    with progress_database.connect() as connection:
        constraints = {name: kind for name, kind in connection.execute(text(
            "SELECT conname, contype FROM pg_constraint WHERE conrelid = 'alert_dispatch_progress'::regclass "
            "AND contype <> 'n'"))}
        indexes = {name for (name,) in connection.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'alert_dispatch_progress'"))}

    assert constraints == {
        "alert_dispatch_progress_pkey": "p",
        "uq_alert_dispatch_progress_service_seq": "u",
        "ck_alert_dispatch_progress_consecutive_failures_valid": "c",
        "ck_alert_dispatch_progress_last_success_at_valid": "c",
    }  # no foreign key of any kind
    assert indexes == {
        "alert_dispatch_progress_pkey", "uq_alert_dispatch_progress_service_seq",
        "ix_alert_dispatch_progress_last_success_at",
    }


def test_one_row_per_user_and_a_strict_total_service_order(progress_database: Engine) -> None:
    user = uuid4()
    _insert(progress_database, user)

    assert _rejected(progress_database, user) == "alert_dispatch_progress_pkey"
    other = uuid4()
    with pytest.raises(IntegrityError) as caught:  # two users can never share a service position
        _insert(progress_database, other, service_seq=_count(progress_database, "SELECT service_seq FROM alert_dispatch_progress"))
    assert _constraint(caught.value) == "uq_alert_dispatch_progress_service_seq"


def test_check_constraints(progress_database: Engine) -> None:
    assert _rejected(progress_database, uuid4(), consecutive_failures=-1) == (
        "ck_alert_dispatch_progress_consecutive_failures_valid")
    assert _rejected(progress_database, uuid4(), last_success_at="2999-01-01") == (
        "ck_alert_dispatch_progress_last_success_at_valid")
    _insert(progress_database, uuid4(), last_success_at="2000-01-01", consecutive_failures=3, last_error_code="OperationalError")


def test_the_sequence_is_strictly_increasing_across_concurrent_sessions(progress_database: Engine) -> None:
    values: List[int] = []
    lock = threading.Lock()

    def draw() -> None:
        for _ in range(20):
            value = _next_seq(progress_database)
            with lock:
                values.append(value)

    threads = [threading.Thread(target=draw) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert len(values) == 80 and len(set(values)) == 80  # unique: a total order even under concurrency


def test_migration_revokes_with_the_established_guarded_pattern() -> None:
    source = MIGRATION_PATH.read_text()

    assert 'PROGRESS_TABLE_SQL = "public.alert_dispatch_progress"' in source
    assert 'SERVICE_SEQUENCE_SQL = f"public.{SERVICE_SEQUENCE_NAME}"' in source
    assert "REVOKE ALL PRIVILEGES ON TABLE {PROGRESS_TABLE_SQL} FROM %I" in source
    assert "REVOKE ALL PRIVILEGES ON SEQUENCE {SERVICE_SEQUENCE_SQL} FROM %I" in source
    assert "ARRAY['anon', 'authenticated', 'service_role']" in source
    assert "SELECT 1 FROM pg_roles WHERE rolname = target_role" in source


def test_revoke_takes_effect_against_default_privileges_granted_to_data_api_roles(e9a_database: Engine) -> None:
    created_roles: List[str] = []
    admin = _admin_engine()
    database_name = e9a_database.url.database
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
        with e9a_database.begin() as connection:
            connection.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {grantees}"))
            connection.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {grantees}"))
            connection.execute(text("CREATE TABLE public.control_table (id integer)"))
            connection.execute(text("CREATE SEQUENCE public.control_sequence"))

        assert _alembic(_url_of(e9a_database), "upgrade", PROGRESS_REVISION).returncode == 0

        with e9a_database.connect() as connection:
            for role in DATA_API_ROLES:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    assert connection.execute(text("SELECT has_table_privilege(:r, 'public.control_table', :p)"),
                                              {"r": role, "p": privilege}).scalar_one() is True, ("control", role, privilege)
                    assert connection.execute(text("SELECT has_table_privilege(:r, 'public.alert_dispatch_progress', :p)"),
                                              {"r": role, "p": privilege}).scalar_one() is False, (role, privilege)
                for privilege in ("USAGE", "SELECT", "UPDATE"):
                    assert connection.execute(text("SELECT has_sequence_privilege(:r, 'public.control_sequence', :p)"),
                                              {"r": role, "p": privilege}).scalar_one() is True, ("control", role, privilege)
                    assert connection.execute(text("SELECT has_sequence_privilege(:r, :s, :p)"),
                                              {"r": role, "s": f"public.{SEQUENCE}", "p": privilege}).scalar_one() is False, (role, privilege)
    finally:
        e9a_database.dispose()
        try:
            if created_roles:
                _drop_database(database_name)
                with admin.connect() as connection:
                    for role in created_roles:
                        connection.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        finally:
            admin.dispose()


def test_orm_metadata_matches_the_new_schema_exactly(progress_database: Engine) -> None:
    import_database_models()
    assert TABLE in Base.metadata.tables

    with progress_database.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_older_revision_differs_only_by_the_new_table(e9a_database: Engine) -> None:
    import_database_models()
    with e9a_database.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences
    assert exclude_stages_after(differences, E9A_REVISION) == []


def test_the_previous_runtime_cleanup_works_without_the_table(e9a_database: Engine) -> None:
    from tests.conftest import OPTIONAL_E6_TABLES

    assert TABLE in OPTIONAL_E6_TABLES and not _table_exists(e9a_database, TABLE)
