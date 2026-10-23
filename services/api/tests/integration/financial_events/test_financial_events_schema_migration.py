import hashlib
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.exc import IntegrityError, ProgrammingError

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.db.database_base import Base
from app.db.database_models import import_database_models
from app.db.database_session import engine as application_engine
from tests.database_safety import validate_test_database_url
from tests.schema_drift import exclude_stages_after

# VF-020E2 schema-expand tests (revision 115998e2e795): the financial_events
# outbox table, its approved CHECKs, the partial created-event UNIQUE index,
# the P52 FIFO partial index, the due index and the Data API REVOKE.
#
# They run the REAL Alembic CLI against throwaway *_test databases cloned from
# a template migrated to the D5 revision (the C1/D2/D5 pattern); every
# database name ends in "_test", passes the project's safety guard and is
# dropped afterwards. The shared valor_test database is not migrated by these
# tests, and no production database or credential is ever involved.

API_DIR = Path(__file__).resolve().parents[3]
APP_DIR = API_DIR / "app"
D5_REVISION = "7c1e5a9b3d28"
E2_REVISION = "115998e2e795"

TABLE = "financial_events"
UNIQUE_CREATED_INDEX = "uq_financial_events_income_created_aggregate_id"
FIFO_INDEX = "ix_financial_events_user_id_occurred_at_id_unfinished"
DUE_INDEX = "ix_financial_events_status_not_before_next_attempt_at"

DATA_API_ROLES = ("anon", "authenticated", "service_role")

EXPECTED_COLUMNS = {
    # name: (data_type, is_nullable, max_length, precision, scale)
    "id": ("uuid", "NO", None, None, None),
    "user_id": ("uuid", "NO", None, None, None),
    "event_type": ("character varying", "NO", 32, None, None),
    "aggregate_type": ("character varying", "NO", 32, None, None),
    "aggregate_id": ("uuid", "NO", None, None, None),
    "origin": ("character varying", "NO", 16, None, None),
    "ingestion_mode": ("character varying", "NO", 16, None, None),
    "snap_amount": ("numeric", "NO", None, 12, 2),
    "snap_currency": ("character varying", "NO", 3, None, None),
    "snap_received_at": ("date", "NO", None, None, None),
    "snap_account_id": ("uuid", "YES", None, None, None),
    "snap_income_source": ("character varying", "NO", 20, None, None),
    "snap_aggregate_updated_at": ("timestamp with time zone", "NO", None, None, None),
    "occurred_at": ("timestamp with time zone", "NO", None, None, None),
    "status": ("character varying", "NO", 20, None, None),
    "not_before": ("timestamp with time zone", "YES", None, None, None),
    "attempts": ("integer", "NO", None, 32, 0),
    "next_attempt_at": ("timestamp with time zone", "YES", None, None, None),
    "lease_expires_at": ("timestamp with time zone", "YES", None, None, None),
    "claim_token": ("uuid", "YES", None, None, None),
    "last_error_code": ("character varying", "YES", 64, None, None),
    "processed_at": ("timestamp with time zone", "YES", None, None, None),
    "outcome_summary": ("jsonb", "YES", None, None, None),
}

EXPECTED_DEFAULTS = {
    "occurred_at": "now()",
    "status": "'pending'::character varying",
    "attempts": "0",
}

EVENT_TYPES = ("income.created", "income.updated", "income.deleted")
ORIGINS = ("manual", "receipt", "import", "system")
INGESTION_MODES = ("live", "historical", "correction")
STATUSES = ("pending", "processing", "processed", "failed_retryable", "dead")


def _admin_engine() -> Engine:
    return create_engine(application_engine.url.set(database="postgres"), isolation_level="AUTOCOMMIT")


def _database_url(name: str) -> URL:
    url = application_engine.url.set(database=name)
    validate_test_database_url(url)
    return url


def _create_database(name: str, template: Optional[str] = None) -> URL:
    url = _database_url(name)
    admin = _admin_engine()
    try:
        with admin.connect() as connection:
            suffix = f' TEMPLATE "{template}"' if template else ""
            connection.execute(text(f'CREATE DATABASE "{name}"{suffix}'))
    finally:
        admin.dispose()
    return url


def _drop_database(name: str) -> None:
    admin = _admin_engine()
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


def _alembic(url: URL, *args: str) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    environment["DATABASE_URL"] = url.render_as_string(hide_password=False)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(API_DIR), env=environment, capture_output=True, text=True, timeout=180,
    )


def _url_of(database_engine: Engine) -> URL:
    return make_url(database_engine.url.render_as_string(hide_password=False))


def _revision(database_engine: Engine) -> str:
    with database_engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _table_exists(database_engine: Engine, table: str = TABLE) -> bool:
    with database_engine.connect() as connection:
        return connection.execute(
            text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"public.{table}"},
        ).scalar_one()


@pytest.fixture(scope="module")
def d5_template() -> Generator[str, None, None]:
    name = f"vf020e2_tpl_{uuid4().hex[:10]}_test"
    url = _create_database(name)
    try:
        result = _alembic(url, "upgrade", D5_REVISION)
        assert result.returncode == 0, result.stderr
        yield name
    finally:
        _drop_database(name)


@pytest.fixture
def d5_database(d5_template: str) -> Generator[Engine, None, None]:
    name = f"vf020e2_{uuid4().hex[:10]}_test"
    url = _create_database(name, template=d5_template)
    database_engine = create_engine(url)
    try:
        yield database_engine
    finally:
        database_engine.dispose()
        _drop_database(name)


@pytest.fixture
def e2_database(d5_database: Engine) -> Engine:
    result = _alembic(_url_of(d5_database), "upgrade", E2_REVISION)
    assert result.returncode == 0, result.stderr
    return d5_database


def _event(**overrides: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "id": uuid4(),
        "user_id": uuid4(),
        "event_type": "income.created",
        "aggregate_type": "income",
        "aggregate_id": uuid4(),
        "origin": "manual",
        "ingestion_mode": "live",
        "snap_amount": Decimal("100.00"),
        "snap_currency": "EUR",
        "snap_received_at": date(2026, 10, 1),
        "snap_income_source": "salary",
        "snap_aggregate_updated_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return values


def _insert_event(database_engine: Engine, **overrides: Any) -> Dict[str, Any]:
    values = _event(**overrides)
    columns = ", ".join(values)
    placeholders = ", ".join(f":{name}" for name in values)
    with database_engine.begin() as connection:
        connection.execute(
            text(f"INSERT INTO financial_events ({columns}) VALUES ({placeholders})"),
            values,
        )
    return values


def _violated_constraint(error: IntegrityError) -> Optional[str]:
    return error.orig.diag.constraint_name


# ------------------------------------------------------------------
# A. chain
# ------------------------------------------------------------------


def test_revision_chain_and_single_head() -> None:
    script = ScriptDirectory.from_config(Config(str(API_DIR / "alembic.ini")))

    heads = script.get_heads()
    assert len(heads) == 1
    revision = script.get_revision(E2_REVISION)
    assert revision.down_revision == D5_REVISION
    # E2 stays in the ancestry of the single head (later stages build on it).
    assert E2_REVISION in {r.revision for r in script.walk_revisions(base="base", head=heads[0])}

    migration_source = (API_DIR / "alembic" / "versions" / f"{E2_REVISION}_add_financial_events.py").read_text()
    assert "lock_timeout" not in migration_source.lower().replace("no lock_timeout", "")


def test_upgrade_from_d5_reaches_e2_and_creates_table(d5_database: Engine) -> None:
    assert _revision(d5_database) == D5_REVISION
    assert not _table_exists(d5_database)

    result = _alembic(_url_of(d5_database), "upgrade", E2_REVISION)

    assert result.returncode == 0, result.stderr
    assert _revision(d5_database) == E2_REVISION
    assert _table_exists(d5_database)


# ------------------------------------------------------------------
# B. table shape
# ------------------------------------------------------------------


def test_table_shape_types_nullability_and_defaults(e2_database: Engine) -> None:
    with e2_database.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT column_name, data_type, is_nullable, character_maximum_length, "
                "numeric_precision, numeric_scale, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t"
            ),
            {"t": TABLE},
        ).all()
        primary_key = connection.execute(
            text(
                "SELECT a.attname FROM pg_index i "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid = CAST(:t AS regclass) AND i.indisprimary"
            ),
            {"t": f"public.{TABLE}"},
        ).all()

    actual = {row[0]: (row[1], row[2], row[3], row[4], row[5]) for row in rows}
    defaults = {row[0]: row[6] for row in rows if row[6] is not None}

    assert set(actual) == set(EXPECTED_COLUMNS)
    for name, expected in EXPECTED_COLUMNS.items():
        assert actual[name] == expected, name
    assert defaults == EXPECTED_DEFAULTS
    assert [row[0] for row in primary_key] == ["id"]


def test_minimal_event_gets_defaults_and_supports_pre_processing_state(e2_database: Engine) -> None:
    values = _insert_event(e2_database)

    with e2_database.connect() as connection:
        row = connection.execute(
            text(
                "SELECT status, attempts, occurred_at IS NOT NULL, not_before, next_attempt_at, "
                "lease_expires_at, claim_token, last_error_code, processed_at, outcome_summary, "
                "snap_account_id FROM financial_events WHERE id = :id"
            ),
            {"id": values["id"]},
        ).one()

    assert tuple(row) == ("pending", 0, True, None, None, None, None, None, None, None, None)


def test_event_snapshot_supports_account_and_outcome_summary_storage(e2_database: Engine) -> None:
    values = _insert_event(
        e2_database,
        snap_account_id=uuid4(),
        status="processed",
        attempts=1,
        processed_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
        outcome_summary='{"codes": ["not_eligible"]}',
    )

    with e2_database.connect() as connection:
        row = connection.execute(
            text("SELECT snap_account_id, outcome_summary FROM financial_events WHERE id = :id"),
            {"id": values["id"]},
        ).one()

    assert row[0] == values["snap_account_id"]
    assert row[1] == {"codes": ["not_eligible"]}


# ------------------------------------------------------------------
# C. CHECK constraints
# ------------------------------------------------------------------


def test_check_constraint_names_exist(e2_database: Engine) -> None:
    with e2_database.connect() as connection:
        names = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = CAST(:t AS regclass) AND contype = 'c'"
                ),
                {"t": f"public.{TABLE}"},
            )
        }

    assert names == {
        "ck_financial_events_event_type_valid",
        "ck_financial_events_origin_valid",
        "ck_financial_events_ingestion_mode_valid",
        "ck_financial_events_status_valid",
        "ck_financial_events_attempts_valid",
    }


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_every_approved_event_type_is_accepted(e2_database: Engine, event_type: str) -> None:
    _insert_event(e2_database, event_type=event_type)


@pytest.mark.parametrize("origin", ORIGINS)
def test_every_approved_origin_is_accepted(e2_database: Engine, origin: str) -> None:
    _insert_event(e2_database, origin=origin)


@pytest.mark.parametrize("mode", INGESTION_MODES)
def test_every_approved_ingestion_mode_is_accepted(e2_database: Engine, mode: str) -> None:
    _insert_event(e2_database, ingestion_mode=mode)


@pytest.mark.parametrize("status", STATUSES)
def test_every_approved_status_is_accepted(e2_database: Engine, status: str) -> None:
    _insert_event(e2_database, status=status)


@pytest.mark.parametrize(
    "overrides, constraint",
    [
        ({"event_type": "income.cancelled"}, "ck_financial_events_event_type_valid"),
        ({"event_type": "expense.created"}, "ck_financial_events_event_type_valid"),
        ({"event_type": ""}, "ck_financial_events_event_type_valid"),
        ({"origin": "bank"}, "ck_financial_events_origin_valid"),
        ({"origin": "Manual"}, "ck_financial_events_origin_valid"),
        ({"ingestion_mode": "backfill"}, "ck_financial_events_ingestion_mode_valid"),
        ({"ingestion_mode": "LIVE"}, "ck_financial_events_ingestion_mode_valid"),
        ({"status": "claimed"}, "ck_financial_events_status_valid"),
        ({"status": "failed"}, "ck_financial_events_status_valid"),
        ({"status": "applied"}, "ck_financial_events_status_valid"),
        ({"status": "cancelled"}, "ck_financial_events_status_valid"),
        ({"attempts": -1}, "ck_financial_events_attempts_valid"),
        ({"attempts": 7}, "ck_financial_events_attempts_valid"),
    ],
)
def test_invalid_values_are_rejected_by_the_named_check(
    e2_database: Engine, overrides: Dict[str, Any], constraint: str,
) -> None:
    with pytest.raises(IntegrityError) as error:
        _insert_event(e2_database, **overrides)

    assert _violated_constraint(error.value) == constraint
    with e2_database.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM financial_events")).scalar_one() == 0


# ------------------------------------------------------------------
# H. attempts boundary
# ------------------------------------------------------------------


@pytest.mark.parametrize("attempts, accepted", [(0, True), (1, True), (6, True), (-1, False), (7, False)])
def test_attempts_boundary(e2_database: Engine, attempts: int, accepted: bool) -> None:
    if accepted:
        _insert_event(e2_database, attempts=attempts)
        return

    with pytest.raises(IntegrityError) as error:
        _insert_event(e2_database, attempts=attempts)
    assert _violated_constraint(error.value) == "ck_financial_events_attempts_valid"


def test_update_cannot_push_attempts_past_the_bound(e2_database: Engine) -> None:
    values = _insert_event(e2_database, attempts=6, status="processing")

    with pytest.raises(IntegrityError) as error:
        with e2_database.begin() as connection:
            connection.execute(
                text("UPDATE financial_events SET attempts = attempts + 1 WHERE id = :id"),
                {"id": values["id"]},
            )

    assert _violated_constraint(error.value) == "ck_financial_events_attempts_valid"


def test_every_state_specific_absence_is_storable(e2_database: Engine) -> None:
    now = datetime(2026, 10, 3, tzinfo=timezone.utc)
    _insert_event(e2_database, status="pending", not_before=now)
    _insert_event(e2_database, status="processing", attempts=1, claim_token=uuid4(), lease_expires_at=now)
    _insert_event(e2_database, status="failed_retryable", attempts=2, next_attempt_at=now, last_error_code="x")
    _insert_event(e2_database, status="processed", attempts=1, processed_at=now, outcome_summary="{}")
    _insert_event(
        e2_database, status="dead", attempts=6, last_error_code="lease_expired_max_attempts",
        lease_expires_at=None, next_attempt_at=None,
    )


# ------------------------------------------------------------------
# D. soft aggregate reference
# ------------------------------------------------------------------


def test_there_is_no_foreign_key_on_or_from_financial_events(e2_database: Engine) -> None:
    with e2_database.connect() as connection:
        outgoing = connection.execute(
            text("SELECT conname FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) AND contype = 'f'"),
            {"t": f"public.{TABLE}"},
        ).all()
        incoming = connection.execute(
            text("SELECT conname FROM pg_constraint WHERE confrelid = CAST(:t AS regclass)"),
            {"t": f"public.{TABLE}"},
        ).all()

    assert outgoing == []
    assert incoming == []


def test_event_survives_absence_and_deletion_of_its_income(e2_database: Engine) -> None:
    income_id = uuid4()
    user_id = uuid4()

    # An event for an Income that does not exist at all.
    _insert_event(e2_database, aggregate_id=income_id, user_id=user_id)

    # The same identity later exists, then is deleted: the event must remain.
    with e2_database.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO income (id, user_id, amount, currency, received_at, source) "
                "VALUES (:id, :u, 100.00, 'EUR', '2026-10-01', 'salary')"
            ),
            {"id": income_id, "u": user_id},
        )
    with e2_database.begin() as connection:
        connection.execute(text("DELETE FROM income WHERE id = :id"), {"id": income_id})
        deleted_event = _event(
            event_type="income.deleted", aggregate_id=income_id, user_id=user_id, ingestion_mode="correction",
        )
        columns = ", ".join(deleted_event)
        placeholders = ", ".join(f":{name}" for name in deleted_event)
        connection.execute(text(f"INSERT INTO financial_events ({columns}) VALUES ({placeholders})"), deleted_event)

    with e2_database.connect() as connection:
        remaining = connection.execute(
            text("SELECT event_type FROM financial_events WHERE aggregate_id = :id ORDER BY event_type"),
            {"id": income_id},
        ).all()
    assert [row[0] for row in remaining] == ["income.created", "income.deleted"]


# ------------------------------------------------------------------
# E. created-event uniqueness
# ------------------------------------------------------------------


def test_second_created_event_for_the_same_aggregate_is_rejected(e2_database: Engine) -> None:
    aggregate_id = uuid4()
    _insert_event(e2_database, aggregate_id=aggregate_id, event_type="income.created")

    with pytest.raises(IntegrityError) as error:
        _insert_event(e2_database, aggregate_id=aggregate_id, event_type="income.created")

    assert _violated_constraint(error.value) == UNIQUE_CREATED_INDEX


def test_created_uniqueness_is_global_per_aggregate_not_per_user(e2_database: Engine) -> None:
    aggregate_id = uuid4()
    _insert_event(e2_database, aggregate_id=aggregate_id, user_id=uuid4())

    with pytest.raises(IntegrityError) as error:
        _insert_event(e2_database, aggregate_id=aggregate_id, user_id=uuid4())

    assert _violated_constraint(error.value) == UNIQUE_CREATED_INDEX


def test_updated_and_deleted_events_do_not_collide_with_the_created_uniqueness(e2_database: Engine) -> None:
    aggregate_id = uuid4()
    _insert_event(e2_database, aggregate_id=aggregate_id, event_type="income.created")

    for _ in range(3):
        _insert_event(e2_database, aggregate_id=aggregate_id, event_type="income.updated", ingestion_mode="correction")
    _insert_event(e2_database, aggregate_id=aggregate_id, event_type="income.deleted", ingestion_mode="correction")
    _insert_event(e2_database, aggregate_id=aggregate_id, event_type="income.deleted", ingestion_mode="correction")

    with e2_database.connect() as connection:
        counts = dict(
            connection.execute(
                text("SELECT event_type, count(*) FROM financial_events WHERE aggregate_id = :id GROUP BY 1"),
                {"id": aggregate_id},
            ).all()
        )
    assert counts == {"income.created": 1, "income.updated": 3, "income.deleted": 2}


def test_created_uniqueness_ignores_status_and_attempts(e2_database: Engine) -> None:
    aggregate_id = uuid4()
    _insert_event(e2_database, aggregate_id=aggregate_id, status="dead", attempts=6)

    with pytest.raises(IntegrityError) as error:
        _insert_event(e2_database, aggregate_id=aggregate_id, status="pending", attempts=0)

    assert _violated_constraint(error.value) == UNIQUE_CREATED_INDEX


# ------------------------------------------------------------------
# F / G. indexes
# ------------------------------------------------------------------


def _index_definition(database_engine: Engine, name: str) -> str:
    with database_engine.connect() as connection:
        return connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND indexname = :n"),
            {"n": name},
        ).scalar_one()


def _quoted_statuses(predicate: str) -> List[str]:
    return sorted(re.findall(r"'([a-z_]+)'", predicate))


def test_unique_created_index_is_a_partial_unique_index_on_aggregate_id(e2_database: Engine) -> None:
    definition = _index_definition(e2_database, UNIQUE_CREATED_INDEX)

    assert "CREATE UNIQUE INDEX" in definition
    assert "(aggregate_id)" in definition
    where = definition.split(" WHERE ", 1)[1]
    assert _quoted_statuses(where) == ["income.created"] or "income.created" in where
    assert "income.updated" not in where and "income.deleted" not in where
    assert "attempts" not in definition and "version" not in definition


def test_fifo_index_is_partial_over_exactly_the_unfinished_statuses(e2_database: Engine) -> None:
    definition = _index_definition(e2_database, FIFO_INDEX)

    assert "CREATE INDEX" in definition and "UNIQUE" not in definition
    assert "(user_id, occurred_at, id)" in definition
    where = definition.split(" WHERE ", 1)[1]
    assert _quoted_statuses(where) == ["failed_retryable", "pending", "processing"]
    assert "processed" not in where and "dead" not in where
    # P52: the predicate lists statuses only; it never narrows to "claimable"
    # rows through due-time columns.
    assert "next_attempt_at" not in where and "lease_expires_at" not in where and "not_before" not in where


def test_due_index_columns_and_order(e2_database: Engine) -> None:
    definition = _index_definition(e2_database, DUE_INDEX)

    assert "(status, not_before, next_attempt_at)" in definition
    assert "UNIQUE" not in definition
    assert " WHERE " not in definition


def test_exactly_the_expected_indexes_exist(e2_database: Engine) -> None:
    with e2_database.connect() as connection:
        names = {
            row[0]
            for row in connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = :t"),
                {"t": TABLE},
            )
        }

    assert names == {"pk_financial_events", UNIQUE_CREATED_INDEX, FIFO_INDEX, DUE_INDEX}


# ------------------------------------------------------------------
# I. Data API security
# ------------------------------------------------------------------


def test_migration_revokes_data_api_privileges_with_the_established_pattern() -> None:
    source = (API_DIR / "alembic" / "versions" / f"{E2_REVISION}_add_financial_events.py").read_text()

    assert 'FINANCIAL_EVENTS_TABLE_SQL = "public.financial_events"' in source
    assert "REVOKE ALL PRIVILEGES ON TABLE {FINANCIAL_EVENTS_TABLE_SQL} FROM %I" in source
    assert "ARRAY['anon', 'authenticated', 'service_role']" in source
    assert "SELECT 1 FROM pg_roles WHERE rolname = target_role" in source
    assert "ALL TABLES IN SCHEMA" not in source
    assert "GRANT" not in source.replace("REVOKE", "")


def test_existing_data_api_roles_have_no_privileges_on_financial_events(e2_database: Engine) -> None:
    with e2_database.connect() as connection:
        roles = [
            row[0]
            for row in connection.execute(
                text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles)"), {"roles": list(DATA_API_ROLES)},
            )
        ]
        for role in roles:
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                assert connection.execute(
                    text("SELECT has_table_privilege(:r, 'public.financial_events', :p)"),
                    {"r": role, "p": privilege},
                ).scalar_one() is False, (role, privilege)


def test_revoke_takes_effect_against_default_privileges_granted_to_data_api_roles(
    d5_database: Engine,
) -> None:
    # Supabase grants new public tables to the Data API roles through default
    # privileges. Reproduce that inside this throwaway database only (default
    # privileges are per database): a control table must be readable by the
    # roles, the migrated financial_events table must not be.
    created_roles: List[str] = []
    admin = _admin_engine()
    try:
        try:
            with admin.connect() as connection:
                for role in DATA_API_ROLES:
                    exists = connection.execute(
                        text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role},
                    ).first()
                    if exists is None:
                        connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
                        created_roles.append(role)
        except ProgrammingError:
            pytest.skip("test database user cannot create the Data API roles")

        grantees = ", ".join(f'"{role}"' for role in DATA_API_ROLES)
        with d5_database.begin() as connection:
            connection.execute(
                text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {grantees}")
            )
            connection.execute(text("CREATE TABLE public.control_table (id integer)"))

        result = _alembic(_url_of(d5_database), "upgrade", E2_REVISION)
        assert result.returncode == 0, result.stderr

        with d5_database.connect() as connection:
            for role in DATA_API_ROLES:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    control = connection.execute(
                        text("SELECT has_table_privilege(:r, 'public.control_table', :p)"),
                        {"r": role, "p": privilege},
                    ).scalar_one()
                    assert control is True, ("control", role, privilege)
                    protected = connection.execute(
                        text("SELECT has_table_privilege(:r, 'public.financial_events', :p)"),
                        {"r": role, "p": privilege},
                    ).scalar_one()
                    assert protected is False, (role, privilege)
    finally:
        d5_database.dispose()
        admin.dispose()
        # The database fixture drops the cloned database afterwards; roles
        # created here are removed by a later cleanup step below.
        _cleanup_roles_after_database(d5_database, created_roles)


def _cleanup_roles_after_database(database_engine: Engine, roles: List[str]) -> None:
    if not roles:
        return
    database_name = database_engine.url.database
    _drop_database(database_name)
    admin = _admin_engine()
    try:
        with admin.connect() as connection:
            for role in roles:
                connection.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
    finally:
        admin.dispose()


# ------------------------------------------------------------------
# J. migration cycle
# ------------------------------------------------------------------


def test_upgrade_downgrade_upgrade_cycle(d5_database: Engine) -> None:
    url = _url_of(d5_database)

    assert _alembic(url, "upgrade", E2_REVISION).returncode == 0
    assert _table_exists(d5_database)

    downgrade = _alembic(url, "downgrade", D5_REVISION)
    assert downgrade.returncode == 0, downgrade.stderr
    assert _revision(d5_database) == D5_REVISION
    assert not _table_exists(d5_database)
    with d5_database.connect() as connection:
        leftovers = connection.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexname LIKE '%financial_events%'")
        ).all()
        sequences = connection.execute(
            text("SELECT relname FROM pg_class WHERE relname LIKE '%financial_events%'")
        ).all()
    assert leftovers == []
    assert sequences == []

    upgrade = _alembic(url, "upgrade", E2_REVISION)
    assert upgrade.returncode == 0, upgrade.stderr
    assert _revision(d5_database) == E2_REVISION
    assert _table_exists(d5_database)
    _insert_event(d5_database)


# ------------------------------------------------------------------
# K. data safety
# ------------------------------------------------------------------


def _digest(database_engine: Engine, table: str) -> str:
    with database_engine.connect() as connection:
        rows = connection.execute(text(f"SELECT t::text FROM {table} AS t ORDER BY t::text")).all()
    return hashlib.sha256("\n".join(row[0] for row in rows).encode()).hexdigest()


def test_migration_and_downgrade_do_not_mutate_existing_data(d5_database: Engine) -> None:
    user_id = uuid4()
    account_id = uuid4()
    goal_id = uuid4()
    income_id = uuid4()
    with d5_database.begin() as connection:
        connection.execute(
            text("INSERT INTO accounts (id, user_id, name, type, currency, status) VALUES (:i, :u, 'Main', 'checking', 'EUR', 'active')"),
            {"i": account_id, "u": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO goals (id, user_id, name, target_amount, currency, status, priority_rank) "
                "VALUES (:i, :u, 'g', 100, 'EUR', 'active', 1)"
            ),
            {"i": goal_id, "u": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO income (id, user_id, amount, currency, received_at, source) "
                "VALUES (:i, :u, 250.00, 'EUR', '2025-01-01', 'salary')"
            ),
            {"i": income_id, "u": user_id},
        )

    tables = ("accounts", "goals", "income")
    before = {table: _digest(d5_database, table) for table in tables}
    url = _url_of(d5_database)

    assert _alembic(url, "upgrade", E2_REVISION).returncode == 0
    assert {table: _digest(d5_database, table) for table in tables} == before
    with d5_database.connect() as connection:
        # No backfill: the existing Income has no creation event and no event
        # of any kind exists.
        assert connection.execute(text("SELECT count(*) FROM financial_events")).scalar_one() == 0

    assert _alembic(url, "downgrade", D5_REVISION).returncode == 0
    assert {table: _digest(d5_database, table) for table in tables} == before


def test_income_table_is_unchanged_by_the_migration(d5_database: Engine) -> None:
    def income_shape(database_engine: Engine) -> List[Any]:
        with database_engine.connect() as connection:
            columns = connection.execute(
                text(
                    "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'income' ORDER BY column_name"
                )
            ).all()
            constraints = connection.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'public.income'::regclass ORDER BY conname"
                )
            ).all()
            indexes = connection.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'income' ORDER BY indexname")
            ).all()
        return [[tuple(r) for r in columns], [tuple(r) for r in constraints], [tuple(r) for r in indexes]]

    before = income_shape(d5_database)
    assert _alembic(_url_of(d5_database), "upgrade", E2_REVISION).returncode == 0
    assert income_shape(d5_database) == before


# ------------------------------------------------------------------
# Runtime coupling and metadata (E3 maps the E2 table)
# ------------------------------------------------------------------


def test_financial_events_references_are_confined_to_the_event_module_and_income_service() -> None:
    # VF-020E3 maps the table and the Income service writes events; VF-020E7
    # adds the queue repository / processor and the rule execution service.
    # Nothing else in the application may depend on it.
    referencing = sorted(
        str(path.relative_to(API_DIR))
        for path in APP_DIR.rglob("*.py")
        if "financial_events" in path.read_text(encoding="utf-8")
    )

    assert referencing == [
        "app/db/database_models.py",
        "app/modules/financial_events/financial_event_models.py",
        "app/modules/financial_events/financial_event_processor.py",
        "app/modules/financial_events/financial_event_queue_repository.py",
        "app/modules/financial_events/financial_event_repository.py",
        "app/modules/financial_events/financial_event_service.py",
        "app/modules/financial_rules/financial_rule_router.py",
        "app/modules/financial_rules/rule_execution_service.py",
        "app/modules/financial_rules/rule_proposal_service.py",
        "app/modules/income/income_router.py",
        "app/modules/income/income_service.py",
    ]


def test_orm_metadata_matches_the_e2_schema_exactly(e2_database: Engine) -> None:
    import_database_models()
    assert TABLE in Base.metadata.tables

    with e2_database.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    # Objects added by later stages (E4) are not part of the E2 schema.
    assert exclude_stages_after(differences, E2_REVISION) == []
