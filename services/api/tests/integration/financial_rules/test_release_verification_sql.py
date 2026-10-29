import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Generator, List, Optional, Tuple
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from alembic.config import Config
from alembic.script import ScriptDirectory
from tests.integration.financial_rules.test_financial_rules_schema_migration import (
    _admin_engine,
    _alembic,
    _create_database,
    _drop_database,
    _revision,
    _url_of,
)

# VF-020E10 OPS-02: the repository-tracked, read-only release verification package
# (docs/operations/sql/*.sql and run_readonly_check.sh). Everything here runs on
# throwaway *_test databases created from the real Alembic chain: no production
# database, credential or backup is involved.

API_DIR = Path(__file__).resolve().parents[3]
SQL_DIR = API_DIR.parents[1] / "docs" / "operations" / "sql"
WRAPPER = SQL_DIR / "run_readonly_check.sh"
sys.path.insert(0, str(SQL_DIR))
import backup_evidence  # noqa: E402  (the production module: the tests exercise the real seal and parsers)
E6_REVISION = "e0503e9ca9d3"
E9A_REVISION = "a7c3e91d5b24"
E10_REVISION = "c4d8a2f6e193"

pytestmark = pytest.mark.skipif(
    subprocess.run(["which", "psql"], capture_output=True).returncode != 0, reason="psql is not installed",
)


# ------------------------------------------------------------------
# Infrastructure
# ------------------------------------------------------------------


def _template(revision: str) -> Generator[str, None, None]:
    name = f"vfops_tpl_{uuid4().hex[:10]}_test"
    url = _create_database(name)
    try:
        result = _alembic(url, "upgrade", revision)
        assert result.returncode == 0, result.stderr
        yield name
    finally:
        _drop_database(name)


@pytest.fixture(scope="module")
def e6_template() -> Generator[str, None, None]:
    yield from _template(E6_REVISION)


@pytest.fixture(scope="module")
def e9a_template() -> Generator[str, None, None]:
    yield from _template(E9A_REVISION)


@pytest.fixture(scope="module")
def e10_template() -> Generator[str, None, None]:
    yield from _template(E10_REVISION)


def _clone(template: str) -> Generator[Tuple[str, Engine], None, None]:
    name = f"vfops_{uuid4().hex[:10]}_test"
    url = _create_database(name, template=template)
    database_engine = create_engine(url)
    try:
        yield name, database_engine
    finally:
        database_engine.dispose()
        _drop_database(name)


@pytest.fixture
def e6_db(e6_template: str) -> Generator[Tuple[str, Engine], None, None]:
    yield from _clone(e6_template)


@pytest.fixture
def e6_db_other(e6_template: str) -> Generator[Tuple[str, Engine], None, None]:
    """A second database with the identical schema and revision as e6_db (used to prove dumps are database-bound)."""
    yield from _clone(e6_template)


@pytest.fixture
def e9a_db(e9a_template: str) -> Generator[Tuple[str, Engine], None, None]:
    yield from _clone(e9a_template)


@pytest.fixture
def e10_db(e10_template: str) -> Generator[Tuple[str, Engine], None, None]:
    yield from _clone(e10_template)


@pytest.fixture
def roles() -> Generator[Dict[str, str], None, None]:
    """Request this fixture BEFORE the database fixture: roles must outlive the databases that reference them.

    Three disposable roles standing in for anon / authenticated / service_role, plus an application role."""
    suffix = uuid4().hex[:8]
    names = {
        "anon": f"vfops_anon_{suffix}", "authenticated": f"vfops_auth_{suffix}",
        "service": f"vfops_svc_{suffix}", "app": f"vfops_app_{suffix}", "parent": f"vfops_parent_{suffix}",
        "viewer": f"vfops_viewer_{suffix}",
    }
    admin = _admin_engine()
    try:
        with admin.connect() as connection:
            for name in names.values():
                connection.execute(text(f'CREATE ROLE "{name}" NOLOGIN'))
        yield names
    finally:
        with admin.connect() as connection:
            for name in names.values():
                connection.execute(text(f'DROP ROLE IF EXISTS "{name}"'))
        admin.dispose()


def _libpq_env(database: str, user: Optional[str] = None, password: Optional[str] = None) -> Dict[str, str]:
    url = _admin_engine().url
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG") and key != "DATABASE_URL"}
    environment.update({
        "PGHOST": str(url.host), "PGPORT": str(url.port or 5432), "PGUSER": user or str(url.username),
        "PGPASSWORD": password or str(url.password), "PGDATABASE": database, "PGSSLMODE": "disable",
        "ALLOW_INSECURE_LOCAL_TEST": "1",
    })
    return environment


def _run_sql(
    database: str, script: str, app_role: str = "postgres", data_api_roles: str = "anon,authenticated,service_role",
    require_roles: str = "no", user: Optional[str] = None, password: Optional[str] = None,
) -> Dict[str, Tuple[str, str]]:
    """Runs one script exactly like the wrapper does (read-only session options) and returns check -> (status, actual)."""
    environment = _libpq_env(database, user, password)
    environment["PGOPTIONS"] = (
        "-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=2000"
    )
    result = subprocess.run(
        ["psql", "-X", "-q", "-A", "-t", "-F", "|", "-v", "ON_ERROR_STOP=1",
         "-v", f"expected_db={database}", "-v", f"app_role={app_role}",
         "-v", f"data_api_roles={data_api_roles}", "-v", f"require_roles={require_roles}",
         "-f", str(SQL_DIR / f"{script}.sql")],
        env=environment, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stderr
    report: Dict[str, Tuple[str, str]] = {}
    for line in result.stdout.splitlines():
        parts = line.split("|")
        if len(parts) >= 4:
            report[parts[0]] = (parts[1], parts[3])
    assert "CLASSIFICATION" in report, result.stdout
    return report


def _verdict(report: Dict[str, Tuple[str, str]]) -> str:
    return report["CLASSIFICATION"][0]


def _failing(report: Dict[str, Tuple[str, str]]) -> List[str]:
    return sorted(name for name, (status, _actual) in report.items() if status == "FAIL")


def _execute(database_engine: Engine, *statements: str) -> None:
    with database_engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _roles_arg(roles: Dict[str, str]) -> str:
    return ",".join((roles["anon"], roles["authenticated"], roles["service"]))


# ------------------------------------------------------------------
# E9A preflight
# ------------------------------------------------------------------


def test_e9a_preflight_passes_on_the_expected_preceding_schema(e6_db: Tuple[str, Engine]) -> None:
    report = _run_sql(e6_db[0], "e9a_preflight")

    assert _verdict(report) == "PASS", _failing(report)
    assert report["alembic_revision_is_e6_parent"][1] == E6_REVISION
    assert report["row_count:financial_rules"][1] == "0"


def test_e9a_preflight_stops_when_e9a_is_already_applied(e9a_db: Tuple[str, Engine]) -> None:
    report = _run_sql(e9a_db[0], "e9a_preflight")

    assert _verdict(report) == "STOP"
    assert {"alembic_revision_is_e6_parent", "rule_alerts_absent"} <= set(_failing(report))


def test_e9a_preflight_stops_on_a_partially_existing_object(e6_db: Tuple[str, Engine]) -> None:
    _execute(e6_db[1], "CREATE SEQUENCE public.rule_alerts_orphan_seq")

    report = _run_sql(e6_db[0], "e9a_preflight")

    assert _verdict(report) == "STOP" and "no_partial_relations_any_schema" in _failing(report)


def test_e9a_preflight_stops_on_a_partial_object_in_another_schema(e6_db: Tuple[str, Engine]) -> None:
    _execute(e6_db[1], "CREATE SCHEMA stray", "CREATE TABLE stray.rule_alerts (id integer)")

    report = _run_sql(e6_db[0], "e9a_preflight")

    assert _verdict(report) == "STOP" and "no_partial_relations_any_schema" in _failing(report)


def test_e9a_preflight_stops_when_a_prerequisite_table_is_missing(e6_db: Tuple[str, Engine]) -> None:
    _execute(e6_db[1], "ALTER TABLE goal_transactions RENAME TO goal_transactions_moved")

    report = _run_sql(e6_db[0], "e9a_preflight")

    assert _verdict(report) == "STOP" and "prerequisite_tables_exist" in _failing(report)


def test_e9a_preflight_stops_on_an_unexpected_or_duplicated_revision(e6_db: Tuple[str, Engine]) -> None:
    _execute(e6_db[1], "INSERT INTO alembic_version (version_num) VALUES ('deadbeef0000')")

    report = _run_sql(e6_db[0], "e9a_preflight")

    assert _verdict(report) == "STOP" and "alembic_version_rows" in _failing(report)


def test_e9a_preflight_stops_when_the_wrong_database_is_connected(e6_db: Tuple[str, Engine]) -> None:
    environment = _libpq_env(e6_db[0])
    result = subprocess.run(
        ["psql", "-X", "-q", "-A", "-t", "-F", "|", "-v", "ON_ERROR_STOP=1", "-v", "expected_db=some_other_db",
         "-v", "app_role=postgres", "-v", "data_api_roles=a,b", "-v", "require_roles=no",
         "-f", str(SQL_DIR / "e9a_preflight.sql")],
        env=environment, capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )

    assert "CLASSIFICATION|STOP" in result.stdout and "database_name|FAIL" in result.stdout


def test_e9a_preflight_stops_while_a_conflicting_lock_is_held_on_financial_rules(e6_db: Tuple[str, Engine]) -> None:
    holder = e6_db[1].connect()
    try:
        holder.execute(text("BEGIN"))
        holder.execute(text("LOCK TABLE financial_rules IN ROW EXCLUSIVE MODE"))

        report = _run_sql(e6_db[0], "e9a_preflight")
    finally:
        holder.rollback()
        holder.close()

    assert _verdict(report) == "STOP"
    assert "locks_on_financial_rules_that_conflict_with_the_migration" in _failing(report)


# ------------------------------------------------------------------
# E9A post-check
# ------------------------------------------------------------------


def test_e9a_postcheck_passes_on_a_correctly_migrated_database(e9a_db: Tuple[str, Engine]) -> None:
    report = _run_sql(e9a_db[0], "e9a_postcheck")

    assert _verdict(report) == "PASS", _failing(report)


def test_e9a_postcheck_stops_at_a_revision_before_e9a(e6_db: Tuple[str, Engine]) -> None:
    report = _run_sql(e6_db[0], "e9a_postcheck")

    assert _verdict(report) == "STOP" and "alembic_revision_is_e9a_or_e10" in _failing(report)


def test_e9a_postcheck_stays_valid_after_e10_so_rule_alerts_is_still_verified(e10_db: Tuple[str, Engine]) -> None:
    report = _run_sql(e10_db[0], "e9a_postcheck")

    assert _verdict(report) == "PASS", _failing(report)
    assert report["alembic_revision_is_e9a_or_e10"][1] == E10_REVISION


def test_the_rule_alerts_privileges_are_verified_at_the_e10_revision_too(
    roles: Dict[str, str], e10_db: Tuple[str, Engine],
) -> None:
    _execute(e10_db[1], f'GRANT SELECT, INSERT, UPDATE, DELETE ON rule_alerts TO "{roles["app"]}"',
             f'GRANT SELECT ON rule_alerts TO "{roles["authenticated"]}"')

    report = _run_sql(e10_db[0], "e9a_postcheck", app_role=roles["app"], data_api_roles=_roles_arg(roles),
                      require_roles="yes")

    assert _verdict(report) == "STOP" and "no_effective_data_api_access" in _failing(report)


def test_e9a_postcheck_detects_a_missing_check_constraint(e9a_db: Tuple[str, Engine]) -> None:
    _execute(e9a_db[1], "ALTER TABLE rule_alerts DROP CONSTRAINT ck_rule_alerts_type_shape")

    report = _run_sql(e9a_db[0], "e9a_postcheck")

    assert _verdict(report) == "STOP" and "constraints_pk_fk_unique_and_six_checks_all_validated" in _failing(report)


def test_e9a_postcheck_detects_a_wrong_foreign_key_action(e9a_db: Tuple[str, Engine]) -> None:
    _execute(
        e9a_db[1],
        "ALTER TABLE rule_alerts DROP CONSTRAINT fk_rule_alerts_rule_id_user_id",
        "ALTER TABLE rule_alerts ADD CONSTRAINT fk_rule_alerts_rule_id_user_id "
        "FOREIGN KEY (rule_id, user_id) REFERENCES financial_rules (id, user_id) ON DELETE CASCADE",
    )

    assert "foreign_key_nulls_only_rule_id_on_rule_delete" in _failing(_run_sql(e9a_db[0], "e9a_postcheck"))


def test_e9a_postcheck_detects_a_missing_index(e9a_db: Tuple[str, Engine]) -> None:
    _execute(e9a_db[1], "DROP INDEX uq_rule_alerts_open_account_episode")

    assert "five_valid_indexes_with_partial_predicates" in _failing(_run_sql(e9a_db[0], "e9a_postcheck"))


@pytest.mark.parametrize("exposure", ["direct", "inherited", "public", "column"])
def test_e9a_postcheck_detects_every_kind_of_effective_data_api_access(
    roles: Dict[str, str], e9a_db: Tuple[str, Engine], exposure: str,
) -> None:
    name, database_engine = e9a_db
    if exposure == "direct":
        _execute(database_engine, f'GRANT SELECT ON rule_alerts TO "{roles["anon"]}"')
    elif exposure == "inherited":  # no GRANT to the Data API role itself: access comes through a parent role
        _execute(database_engine, f'GRANT SELECT ON rule_alerts TO "{roles["parent"]}"',
                 f'GRANT "{roles["parent"]}" TO "{roles["authenticated"]}"')
    elif exposure == "public":
        _execute(database_engine, "GRANT SELECT ON rule_alerts TO PUBLIC")
    else:
        _execute(database_engine, f'GRANT SELECT (id) ON rule_alerts TO "{roles["service"]}"')

    report = _run_sql(name, "e9a_postcheck", app_role=roles["app"], data_api_roles=_roles_arg(roles), require_roles="yes")

    assert _verdict(report) == "STOP"
    assert {"no_effective_data_api_access", "no_public_access_on_table"} & set(_failing(report))


def test_e9a_postcheck_passes_with_data_api_roles_present_and_no_access(
    roles: Dict[str, str], e9a_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e9a_db
    _execute(database_engine, f'GRANT SELECT, INSERT, UPDATE, DELETE ON rule_alerts TO "{roles["app"]}"')

    report = _run_sql(name, "e9a_postcheck", app_role=roles["app"], data_api_roles=_roles_arg(roles), require_roles="yes")

    assert _verdict(report) == "PASS", _failing(report)


def test_e9a_postcheck_requires_the_application_role_to_have_access(
    roles: Dict[str, str], e9a_db: Tuple[str, Engine],
) -> None:
    report = _run_sql(e9a_db[0], "e9a_postcheck", app_role=roles["app"], data_api_roles=_roles_arg(roles), require_roles="yes")

    assert "application_role_can_read_write_table" in _failing(report)


# ------------------------------------------------------------------
# E10 preflight
# ------------------------------------------------------------------


def test_e10_preflight_passes_at_e9a(e9a_db: Tuple[str, Engine]) -> None:
    report = _run_sql(e9a_db[0], "e10_preflight")

    assert _verdict(report) == "PASS", _failing(report)
    assert report["alembic_revision_is_e9a"][1] == E9A_REVISION


def test_e10_preflight_refuses_missing_prerequisites(e6_db: Tuple[str, Engine]) -> None:
    report = _run_sql(e6_db[0], "e10_preflight")

    assert _verdict(report) == "STOP"
    assert {"alembic_revision_is_e9a", "rule_alerts_exists"} <= set(_failing(report))


def test_e10_preflight_refuses_a_database_that_already_has_e10(e10_db: Tuple[str, Engine]) -> None:
    report = _run_sql(e10_db[0], "e10_preflight")

    assert _verdict(report) == "STOP"
    assert {"progress_table_absent", "progress_sequence_absent", "no_partial_relations_any_schema"} <= set(_failing(report))


@pytest.mark.parametrize("statement", [
    "CREATE SEQUENCE public.alert_dispatch_service_seq",
    "CREATE TABLE public.alert_dispatch_progress (user_id uuid)",
    "CREATE INDEX ix_alert_dispatch_progress_last_success_at ON rule_alerts (created_at)",
    "CREATE SCHEMA stray; CREATE SEQUENCE stray.alert_dispatch_service_seq",
    "CREATE TYPE public.alert_dispatch_progress_kind AS ENUM ('a')",
])
def test_e10_preflight_refuses_partially_existing_objects(e9a_db: Tuple[str, Engine], statement: str) -> None:
    for part in statement.split("; "):
        _execute(e9a_db[1], part)

    report = _run_sql(e9a_db[0], "e10_preflight")

    assert _verdict(report) == "STOP" and _failing(report)


def test_e10_preflight_stops_on_a_long_running_transaction(e9a_db: Tuple[str, Engine]) -> None:
    holder = e9a_db[1].connect()
    try:
        holder.execute(text("BEGIN"))
        holder.execute(text("SELECT 1"))

        report = _run_sql(e9a_db[0], "e10_preflight")
    finally:
        holder.rollback()
        holder.close()

    # A freshly opened idle-in-transaction session is exactly what the preflight must not accept.
    assert _verdict(report) == "STOP" and "sessions_idle_in_transaction" in _failing(report)


def test_e10_preflight_fails_closed_when_other_sessions_are_hidden_from_the_runner_role(
    roles: Dict[str, str], e9a_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e9a_db
    _execute(database_engine, f"ALTER ROLE \"{roles['viewer']}\" LOGIN PASSWORD 'viewer-pw'",
             f'GRANT SELECT ON alembic_version TO "{roles["viewer"]}"')
    holder = database_engine.connect()  # a session of ANOTHER user that the viewer cannot inspect
    try:
        holder.execute(text("BEGIN"))
        holder.execute(text("SELECT 1"))

        report = _run_sql(name, "e10_preflight", user=roles["viewer"], password="viewer-pw")
    finally:
        holder.rollback()
        holder.close()

    assert _verdict(report) == "STOP" and "runner_can_see_all_sessions" in _failing(report)


def test_e10_preflight_requires_the_data_api_roles_on_supabase(e9a_db: Tuple[str, Engine]) -> None:
    report = _run_sql(e9a_db[0], "e10_preflight", data_api_roles="no_such_role_a,no_such_role_b", require_roles="yes")

    assert _verdict(report) == "STOP" and "data_api_roles_present" in _failing(report)


# ------------------------------------------------------------------
# E10 post-check
# ------------------------------------------------------------------


def test_e10_postcheck_passes_on_a_correctly_migrated_database(e10_db: Tuple[str, Engine]) -> None:
    report = _run_sql(e10_db[0], "e10_postcheck")

    assert _verdict(report) == "PASS", _failing(report)
    assert report["progress_row_count_and_sequence_last_value"][1] == "0 / unused"


def test_e10_postcheck_stops_at_e9a(e9a_db: Tuple[str, Engine]) -> None:
    report = _run_sql(e9a_db[0], "e10_postcheck")

    assert _verdict(report) == "STOP"
    assert {"alembic_revision_is_e10", "progress_table_exists_regular_permanent", "service_sequence_exists"} <= set(_failing(report))


@pytest.mark.parametrize("statement,expected_failure", [
    ("ALTER TABLE alert_dispatch_progress DROP CONSTRAINT ck_alert_dispatch_progress_last_success_at_valid",
     "constraints_pk_unique_two_checks_no_foreign_keys"),
    ("ALTER TABLE alert_dispatch_progress DROP CONSTRAINT ck_alert_dispatch_progress_consecutive_failures_valid",
     "constraints_pk_unique_two_checks_no_foreign_keys"),
    ("ALTER TABLE alert_dispatch_progress DROP CONSTRAINT uq_alert_dispatch_progress_service_seq",
     "constraints_pk_unique_two_checks_no_foreign_keys"),
    ("ALTER TABLE alert_dispatch_progress DROP CONSTRAINT ck_alert_dispatch_progress_consecutive_failures_valid; "
     "ALTER TABLE alert_dispatch_progress ADD CONSTRAINT ck_alert_dispatch_progress_consecutive_failures_valid "
     "CHECK (consecutive_failures >= -5)", "constraints_pk_unique_two_checks_no_foreign_keys"),
    ("ALTER TABLE alert_dispatch_progress ADD CONSTRAINT ck_extra CHECK (service_seq > 0) NOT VALID",
     "constraints_pk_unique_two_checks_no_foreign_keys"),
    ("DROP INDEX ix_alert_dispatch_progress_last_success_at", "indexes_pk_unique_and_monitoring_all_valid"),
    ("ALTER TABLE alert_dispatch_progress ADD COLUMN extra integer",
     "exactly_six_columns_with_types_nullability_defaults"),
    ("ALTER TABLE alert_dispatch_progress ALTER COLUMN last_error_code TYPE varchar(200)",
     "exactly_six_columns_with_types_nullability_defaults"),
    ("ALTER TABLE alert_dispatch_progress ALTER COLUMN consecutive_failures DROP DEFAULT",
     "exactly_six_columns_with_types_nullability_defaults"),
    ("ALTER TABLE alert_dispatch_progress ALTER COLUMN last_success_at SET NOT NULL",
     "exactly_six_columns_with_types_nullability_defaults"),
    ("ALTER SEQUENCE alert_dispatch_service_seq CYCLE", "sequence_properties"),
    ("ALTER SEQUENCE alert_dispatch_service_seq INCREMENT BY 2", "sequence_properties"),
    ("ALTER SEQUENCE alert_dispatch_service_seq CACHE 20", "sequence_properties"),
])
def test_e10_postcheck_detects_schema_drift(e10_db: Tuple[str, Engine], statement: str, expected_failure: str) -> None:
    for part in statement.split("; "):
        _execute(e10_db[1], part)

    report = _run_sql(e10_db[0], "e10_postcheck")

    assert _verdict(report) == "STOP" and expected_failure in _failing(report)


def test_e10_postcheck_detects_a_foreign_key_that_should_not_exist(e10_db: Tuple[str, Engine]) -> None:
    _execute(
        e10_db[1],
        "ALTER TABLE alert_dispatch_progress ADD CONSTRAINT fk_extra "
        "FOREIGN KEY (user_id) REFERENCES goals (id) NOT VALID",
    )

    assert "constraints_pk_unique_two_checks_no_foreign_keys" in _failing(_run_sql(e10_db[0], "e10_postcheck"))


def _e10_with_roles(e10_db: Tuple[str, Engine], roles: Dict[str, str]) -> Tuple[str, Engine]:
    _execute(
        e10_db[1],
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON alert_dispatch_progress TO "{roles["app"]}"',
        f'GRANT USAGE ON SEQUENCE alert_dispatch_service_seq TO "{roles["app"]}"',
    )
    return e10_db


def _postcheck_with_roles(db: Tuple[str, Engine], roles: Dict[str, str]) -> Dict[str, Tuple[str, str]]:
    return _run_sql(db[0], "e10_postcheck", app_role=roles["app"], data_api_roles=_roles_arg(roles), require_roles="yes")


def test_e10_postcheck_passes_with_a_dedicated_application_role_and_private_data_api_roles(
    roles: Dict[str, str], e10_db: Tuple[str, Engine],
) -> None:
    report = _postcheck_with_roles(_e10_with_roles(e10_db, roles), roles)

    assert _verdict(report) == "PASS", _failing(report)
    assert report["no_effective_data_api_access"][1] == "0"


@pytest.mark.parametrize("exposure", [
    "table_direct", "table_inherited", "table_public", "table_column", "sequence_direct", "sequence_inherited",
    "sequence_public", "superuser", "table_maintain", "membership_noinherit",
])
def test_e10_postcheck_detects_every_kind_of_effective_data_api_access(
    roles: Dict[str, str], e10_db: Tuple[str, Engine], exposure: str,
) -> None:
    db = _e10_with_roles(e10_db, roles)
    with db[1].connect() as connection:
        server_version = int(connection.execute(text("SHOW server_version_num")).scalar_one())
    if exposure == "table_maintain" and server_version < 170000:
        pytest.skip("the MAINTAIN privilege exists only on PostgreSQL 17+")
    if exposure == "membership_noinherit" and server_version < 160000:
        pytest.skip("WITH INHERIT FALSE exists only on PostgreSQL 16+")
    statements = {
        "table_direct": [f'GRANT SELECT ON alert_dispatch_progress TO "{roles["anon"]}"'],
        # No GRANT names the Data API role: access exists only through role membership.
        "table_inherited": [f'GRANT INSERT ON alert_dispatch_progress TO "{roles["parent"]}"',
                            f'GRANT "{roles["parent"]}" TO "{roles["authenticated"]}"'],
        "table_public": ["GRANT SELECT ON alert_dispatch_progress TO PUBLIC"],
        "table_column": [f'GRANT UPDATE (last_error_code) ON alert_dispatch_progress TO "{roles["service"]}"'],
        "sequence_direct": [f'GRANT USAGE ON SEQUENCE alert_dispatch_service_seq TO "{roles["anon"]}"'],
        "sequence_inherited": [f'GRANT UPDATE ON SEQUENCE alert_dispatch_service_seq TO "{roles["parent"]}"',
                               f'GRANT "{roles["parent"]}" TO "{roles["service"]}"'],
        "sequence_public": ["GRANT USAGE ON SEQUENCE alert_dispatch_service_seq TO PUBLIC"],
        "superuser": [f'ALTER ROLE "{roles["authenticated"]}" SUPERUSER'],
        # Privilege types are not enumerated by the check: a newer type (MAINTAIN, PG17+) and a membership
        # without INHERIT (access via SET ROLE) are both caught through the ACL entries.
        "table_maintain": [f'GRANT MAINTAIN ON alert_dispatch_progress TO "{roles["anon"]}"'],
        "membership_noinherit": [f'GRANT INSERT ON alert_dispatch_progress TO "{roles["parent"]}"',
                                 f'GRANT "{roles["parent"]}" TO "{roles["service"]}" WITH INHERIT FALSE, SET TRUE'],
    }[exposure]
    _execute(db[1], *statements)

    report = _postcheck_with_roles(db, roles)

    assert _verdict(report) == "STOP"
    assert {"no_effective_data_api_access", "no_public_access_on_table_or_sequence"} & set(_failing(report)), exposure


def test_e10_postcheck_detects_a_data_api_role_that_owns_the_objects(
    roles: Dict[str, str], e10_db: Tuple[str, Engine],
) -> None:
    db = _e10_with_roles(e10_db, roles)
    _execute(db[1], f'ALTER TABLE alert_dispatch_progress OWNER TO "{roles["anon"]}"',
             f'ALTER SEQUENCE alert_dispatch_service_seq OWNER TO "{roles["anon"]}"')

    report = _postcheck_with_roles(db, roles)

    assert _verdict(report) == "STOP" and "owner_is_not_a_data_api_role" in _failing(report)


def test_e10_postcheck_detects_split_ownership(roles: Dict[str, str], e10_db: Tuple[str, Engine]) -> None:
    db = _e10_with_roles(e10_db, roles)
    _execute(db[1], f'ALTER SEQUENCE alert_dispatch_service_seq OWNER TO "{roles["parent"]}"')

    assert "table_and_sequence_have_the_same_owner" in _failing(_postcheck_with_roles(db, roles))


def test_e10_postcheck_requires_the_application_role_to_use_table_and_sequence(
    roles: Dict[str, str], e10_db: Tuple[str, Engine],
) -> None:
    report = _postcheck_with_roles(e10_db, roles)  # the application role was granted nothing

    assert {"application_role_can_read_write_table", "application_role_can_call_nextval"} <= set(_failing(report))


def test_e10_postcheck_is_never_vacuous_when_the_data_api_roles_are_missing(e10_db: Tuple[str, Engine]) -> None:
    report = _run_sql(e10_db[0], "e10_postcheck", data_api_roles="no_such_a,no_such_b,no_such_c", require_roles="yes")

    assert _verdict(report) == "STOP" and "data_api_roles_resolved" in _failing(report)


# ------------------------------------------------------------------
# Read-only guarantees
# ------------------------------------------------------------------

CHECKS = ("e9a_preflight", "e9a_postcheck", "e10_preflight", "e10_postcheck")
WRITE_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COMMIT|VACUUM|COPY|LOCK|DO|CALL|REINDEX|CLUSTER)\b",
    re.IGNORECASE,
)


def _executable_sql(script: str) -> str:
    source = (SQL_DIR / f"{script}.sql").read_text()
    source = re.sub(r"--[^\n]*", "", source)  # comments
    source = re.sub(r"\$q\$.*?\$q\$", "''", source, flags=re.DOTALL)
    return re.sub(r"'(?:[^']|'')*'", "''", source)  # string literals (privilege names, expectations)


@pytest.mark.parametrize("script", CHECKS)
def test_the_scripts_contain_no_write_statement_and_are_a_single_rolled_back_read_only_transaction(script: str) -> None:
    executable = _executable_sql(script)

    assert not WRITE_KEYWORDS.findall(executable), WRITE_KEYWORDS.findall(executable)
    statements = [s.strip() for s in executable.split(";") if s.strip()]
    assert statements[0] == "BEGIN READ ONLY" and statements[-1] == "ROLLBACK"
    assert "COMMIT" not in executable.upper() and "\\" not in executable  # no psql meta-commands


@pytest.mark.parametrize("script", CHECKS)
def test_the_scripts_set_bounded_timeouts(script: str) -> None:
    source = (SQL_DIR / f"{script}.sql").read_text()

    for setting in ("statement_timeout", "lock_timeout", "idle_in_transaction_session_timeout"):
        assert f"SET LOCAL {setting}" in source


def _database_fingerprint(name: str, database_engine: Engine) -> str:
    environment = _libpq_env(name)
    schema = subprocess.run(["pg_dump", "--schema-only", "--no-owner", "--no-privileges"], env=environment,
                            capture_output=True, text=True, timeout=120)
    if schema.returncode != 0 and "version mismatch" in schema.stderr:
        pytest.skip("pg_dump is older than the test server")
    assert schema.returncode == 0, schema.stderr
    with database_engine.connect() as connection:
        tables = connection.execute(text(
            "SELECT string_agg(c.relname || ':' || (xpath('/row/c/text()', query_to_xml("
            "format('SELECT count(*) AS c FROM public.%I', c.relname), false, true, '')))[1]::text, ',' ORDER BY c.relname) "
            "FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'")).scalar_one()
        acl = connection.execute(text(
            "SELECT string_agg(relname || coalesce(relacl::text, ''), ',' ORDER BY relname) FROM pg_class "
            "WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'S')")).scalar_one()
        sequences = connection.execute(text(
            "SELECT string_agg(sequencename || ':' || coalesce(last_value::text, 'null'), ',' ORDER BY sequencename) "
            "FROM pg_sequences WHERE schemaname = 'public'")).scalar_one()
    # pg_dump emits a random \restrict token on every run; it is not part of the schema.
    dump = "\n".join(line for line in schema.stdout.splitlines() if not line.startswith(("\\restrict", "\\unrestrict")))
    return "\n".join((dump, str(tables), str(acl), str(sequences)))


@pytest.mark.parametrize("script,fixture_name", [
    ("e9a_preflight", "e6_db"), ("e9a_postcheck", "e9a_db"), ("e10_preflight", "e9a_db"), ("e10_postcheck", "e10_db"),
])
def test_running_a_script_changes_neither_schema_nor_rows_nor_sequences(
    request: pytest.FixtureRequest, script: str, fixture_name: str,
) -> None:
    name, database_engine = request.getfixturevalue(fixture_name)
    before = _database_fingerprint(name, database_engine)

    _run_sql(name, script)
    _run_sql(name, script)

    assert _database_fingerprint(name, database_engine) == before


def test_the_read_only_session_options_reject_any_write_even_outside_the_scripts(e10_db: Tuple[str, Engine]) -> None:
    environment = _libpq_env(e10_db[0])
    environment["PGOPTIONS"] = "-c default_transaction_read_only=on"

    result = subprocess.run(
        ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", "CREATE TABLE should_not_exist (id integer)"],
        env=environment, capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )

    assert result.returncode != 0 and "read-only" in result.stderr


# ------------------------------------------------------------------
# The wrapper
# ------------------------------------------------------------------


def _wrapper(check: str, expected_db: str, **overrides: Optional[str]) -> subprocess.CompletedProcess:
    environment = _libpq_env(expected_db)
    environment["REQUIRE_DATA_API_ROLES"] = "no"
    for key, value in overrides.items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    return subprocess.run([str(WRAPPER), check, expected_db], env=environment, capture_output=True, text=True,
                          timeout=120, stdin=subprocess.DEVNULL)


def test_the_wrapper_reports_pass_with_exit_zero(e9a_db: Tuple[str, Engine]) -> None:
    result = _wrapper("e10_preflight", e9a_db[0])

    assert result.returncode == 0 and "RESULT: PASS (e10_preflight)" in result.stdout


def test_the_wrapper_reports_stop_with_exit_ten(e10_db: Tuple[str, Engine]) -> None:
    result = _wrapper("e10_preflight", e10_db[0])

    assert result.returncode == 10 and "RESULT: STOP (e10_preflight)" in result.stdout


def test_the_wrapper_defaults_demand_the_supabase_data_api_roles(e10_db: Tuple[str, Engine]) -> None:
    result = _wrapper("e10_postcheck", e10_db[0], REQUIRE_DATA_API_ROLES=None)

    assert result.returncode == 10 and "data_api_roles_resolved" in result.stdout and "FAIL" in result.stdout


@pytest.mark.parametrize("arguments,overrides", [
    (("not_a_check", "x"), {}),
    (("e10_preflight",), {}),
    (("e10_preflight", "bad name;drop"), {}),
    (("e10_preflight", "other_db"), {}),
    (("e10_preflight", "KEEP"), {"DATABASE_URL": "postgresql://u:p@h/db"}),
    (("e10_preflight", "KEEP"), {"PGSSLMODE": "disable", "ALLOW_INSECURE_LOCAL_TEST": None}),
    (("e10_preflight", "KEEP"), {"PGSSLMODE": "prefer", "ALLOW_INSECURE_LOCAL_TEST": None}),
    (("e10_preflight", "KEEP"), {"DATA_API_ROLES": "anon;drop table x"}),
    (("e10_preflight", "KEEP"), {"REQUIRE_DATA_API_ROLES": "maybe"}),
    (("e10_preflight", "KEEP"), {"PGHOST": None}),
    (("e10_preflight", "KEEP"), {"PGSERVICE": "staging"}),
    (("e10_preflight", "KEEP"), {"PGSERVICEFILE": "/tmp/pg_service.conf"}),
    (("e10_preflight", "KEEP"), {"PGHOSTADDR": "203.0.113.7"}),
])
def test_the_wrapper_refuses_unsafe_invocations_before_connecting(
    e9a_db: Tuple[str, Engine], arguments: Tuple[str, ...], overrides: Dict[str, Optional[str]],
) -> None:
    database = e9a_db[0]
    environment = _libpq_env(database)
    for key, value in overrides.items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    resolved = tuple(database if argument == "KEEP" else argument for argument in arguments)

    result = subprocess.run([str(WRAPPER), *resolved], env=environment, capture_output=True, text=True,
                            timeout=60, stdin=subprocess.DEVNULL)

    assert result.returncode == 64 and "REFUSED" in result.stderr and "RESULT" not in result.stdout


@pytest.mark.parametrize("overrides", [
    {"REQUIRE_DATA_API_ROLES": "no"},
    {"DATA_API_ROLES": "anon"},
])
def test_the_wrapper_refuses_to_weaken_the_privilege_checks_for_a_remote_host(
    e9a_db: Tuple[str, Engine], overrides: Dict[str, str],
) -> None:
    environment = _libpq_env(e9a_db[0])
    environment.update({"PGHOST": "db.example.invalid", "PGSSLMODE": "require"})
    environment.pop("ALLOW_INSECURE_LOCAL_TEST", None)
    environment.update(overrides)

    result = subprocess.run([str(WRAPPER), "e10_postcheck", e9a_db[0]], env=environment, capture_output=True,
                            text=True, timeout=60, stdin=subprocess.DEVNULL)

    assert result.returncode == 64 and "local database" in result.stderr


def test_the_wrapper_allows_weakened_checks_only_for_databases_named_like_test_databases(
    e9a_db: Tuple[str, Engine],
) -> None:
    environment = _libpq_env("production_like_name")  # looks local (a tunnel), but is not a *_test database
    environment["REQUIRE_DATA_API_ROLES"] = "no"

    result = subprocess.run([str(WRAPPER), "e10_postcheck", "production_like_name"], env=environment,
                            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)

    assert result.returncode == 64 and "_test" in result.stderr


def test_the_wrapper_redacts_a_host_name_from_a_dns_failure() -> None:
    environment = _libpq_env("some_db")
    environment.update({"PGHOST": "secret-db-host.example.invalid", "PGSSLMODE": "require"})
    environment.pop("ALLOW_INSECURE_LOCAL_TEST", None)
    environment.pop("REQUIRE_DATA_API_ROLES", None)

    result = subprocess.run([str(WRAPPER), "e10_preflight", "some_db"], env=environment, capture_output=True,
                            text=True, timeout=60, stdin=subprocess.DEVNULL)
    combined = result.stdout + result.stderr

    assert result.returncode == 10 and "RESULT: STOP" in combined
    assert "secret-db-host" not in combined and "example.invalid" not in combined


def test_the_wrapper_never_prints_connection_details_or_secrets_when_the_connection_fails(
    e9a_db: Tuple[str, Engine],
) -> None:
    secret = "S3NTINEL-do-not-print-7781"
    result = _wrapper("e10_preflight", e9a_db[0], PGPORT="1", PGPASSWORD=secret)
    combined = result.stdout + result.stderr

    assert result.returncode == 10 and "RESULT: STOP" in combined
    assert secret not in combined and "localhost" not in combined and "127.0.0.1" not in combined


def test_the_wrapper_has_no_secret_in_its_arguments_and_no_trace_output() -> None:
    source = WRAPPER.read_text()

    assert "set -x" not in source and "PGPASSWORD=" not in source and "--password" not in source
    assert "password" not in " ".join(re.findall(r'psql[^\n]*', source)).lower().replace("password[^", "")
    assert source.startswith("#!/usr/bin/env bash") and os.access(WRAPPER, os.X_OK)


# ------------------------------------------------------------------
# The fail-closed migration runner (docs/operations/sql/run_guarded_migration.sh)
# ------------------------------------------------------------------

GUARDED = SQL_DIR / "run_guarded_migration.sh"


_PARENT_OF = {E9A_REVISION: E6_REVISION, E10_REVISION: E9A_REVISION}
_TABLES = {E9A_REVISION: "alembic_version,financial_rules,rule_executions",
           E10_REVISION: "alembic_version,financial_rules,rule_executions,rule_alerts"}
_evidence_counter = [0]


def _utc(seconds_ago: float) -> str:
    return datetime.fromtimestamp(time.time() - seconds_ago, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _dump_of(directory: Path, database: str) -> Path:
    _evidence_counter[0] += 1
    dump = directory / f"dump-{_evidence_counter[0]}.dump"
    subprocess.run(["pg_dump", "--format=custom", "--schema=public", f"--file={dump}"],
                   env=_libpq_env(database), check=True, capture_output=True, timeout=120)
    dump.chmod(0o600)
    return dump


def _revision_of_database(database: str) -> str:
    result = subprocess.run(["psql", "-X", "-q", "-At", "-c", "SELECT version_num FROM alembic_version"],
                            env=_libpq_env(database), capture_output=True, text=True, timeout=60)
    return result.stdout.strip()


def _make_evidence(directory: Path, dump_database: str, target: str, expected_db: str, reseal: bool = True,
                   **overrides: Optional[str]) -> Path:
    """A real logical dump plus a receipt in the verifier's format, sealed with the production seal function.

    This is the FAST path used by the many runner tests; the real verifier script (restore + preflight) has its own
    dedicated tests. Facts about the dump come from the production inspector; overrides then craft invalid receipts.
    """
    dump = _dump_of(directory, dump_database)
    facts = backup_evidence.inspect_dump(str(dump), dump_database, _revision_of_database(dump_database), "alembic_version")
    fields: Dict[str, Optional[str]] = {
        "RECEIPT_VERSION": "2", "GATE_TARGET": target, "DATABASE": expected_db, "SOURCE_REVISION": _PARENT_OF[target],
        "DUMP_FILE": str(dump), "DUMP_SHA256": facts["DUMP_SHA256"], "DUMP_DBNAME": facts["DUMP_DBNAME"],
        "DUMP_SERVER_MAJOR": facts["DUMP_SERVER_MAJOR"], "DUMP_CREATED_AT_UTC": facts["DUMP_CREATED_AT_UTC"],
        "RESTORE_DATABASE": "vf_restore_verify_test", "RESTORE_REVISION": _PARENT_OF[target],
        "RESTORE_PREFLIGHT": "PASS", "RESTORE_SERVER_MAJOR": facts["DUMP_SERVER_MAJOR"],
        "RESTORE_VERIFIED_AT_UTC": _utc(0), "RECEIPT_SEAL": "x",
    }
    fields.update(overrides)
    if reseal:
        sealable = {key: value for key, value in fields.items() if value is not None}
        sealable["RECEIPT_SEAL"] = ""
        fields["RECEIPT_SEAL"] = backup_evidence.seal_of(sealable)
    receipt = directory / f"receipt-{_evidence_counter[0]}.env"
    receipt.write_text("".join(f"{key}={value}\n" for key, value in fields.items() if value is not None))
    receipt.chmod(0o600)
    return receipt


def _receipt_fields(receipt: Path) -> Dict[str, str]:
    return dict(line.split("=", 1) for line in receipt.read_text().splitlines() if line)


def _advisory_lock_objects(database_engine: Engine) -> List[int]:
    """objid of every advisory lock (class 7165) held in this database: 1 = runner session lock, 2 = migration transaction."""
    with database_engine.connect() as connection:
        return sorted(row[0] for row in connection.execute(text(
            "SELECT objid FROM pg_locks WHERE locktype = 'advisory' AND classid = 7165 AND granted "
            "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())")))


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _direct_guarded_alembic(url, source: str, *args: str) -> subprocess.CompletedProcess:
    """What the runner executes for the upgrade (same environment variable), without the runner's own guards."""
    environment = dict(os.environ)
    environment.update({"DATABASE_URL": url.render_as_string(hide_password=False), "VF_GUARDED_MIGRATION_FROM": source})
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=str(API_DIR), env=environment,
                          capture_output=True, text=True, timeout=180)


def _locks_released(database_engine: Engine, seconds: float = 5.0) -> bool:
    """PostgreSQL drops a session's advisory lock when its backend notices the closed connection (a moment later)."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _advisory_locks(database_engine) == 0:
            return True
        time.sleep(0.1)
    return _advisory_locks(database_engine) == 0


def _advisory_locks(database_engine: Engine) -> int:
    with database_engine.connect() as connection:
        return connection.execute(text(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
            "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())")).scalar_one()


class _Guarded:
    def __init__(self, tmp_path: Path) -> None:
        self.dir = tmp_path
        self.log = tmp_path / "python-calls.log"
        self.stub = tmp_path / "stub-python.sh"
        self.stub.write_text(
            "#!/bin/sh\n"
            'echo "$@" >> "$STUB_LOG"\n'
            'if [ -n "$STUB_FAIL_UPGRADE" ]; then case "$*" in *"alembic upgrade"*)\n'
            '  if [ "$STUB_FAIL_UPGRADE" = leak ]; then echo "OperationalError: could not translate host name leakhost.example for postgresql://leakuser:leakpw@leakhost.example/leakdb" >&2; fi\n'
            "  exit 1;; esac; fi\n"
            # Hold an in-flight upgrade open until the test releases it (concurrency tests).
            'case "$*" in *"alembic upgrade"*) if [ -n "$STUB_PAUSE_DIR" ]; then touch "$STUB_PAUSE_DIR/started.$$";'
            ' n=0; while [ ! -e "$STUB_PAUSE_DIR/release" ] && [ "$n" -lt 300 ]; do sleep 0.2; n=$((n+1)); done; fi;; esac\n'
            # Real Alembic, paused INSIDE its migration transaction (after env.py took the database-level lock).
            'case "$*" in *"alembic upgrade"*) if [ -n "$STUB_PAUSE_IN_TXN_DIR" ]; then for last; do :; done;'
            f' exec "{os.sys.executable}" "$STUB_PATCH_SCRIPT" "$last"; fi;; esac\n'
            # Simulated drift between the first checks and the pre-upgrade re-check (counts per kind of call).
            'case "$*" in\n'
            '  *pg_postmaster_start_time*) k=proof;;\n'
            '  *"alembic current"*) k=current;;\n'
            '  *) k=;;\n'
            'esac\n'
            'if [ -n "$k" ]; then\n'
            '  n=$(cat "$STUB_COUNTS.$k" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$STUB_COUNTS.$k"\n'
            '  if [ "$n" -ge 2 ] && [ "$STUB_DRIFT" = "$k" ]; then\n'
            '    if [ "$k" = proof ]; then echo "1|1|x|x|5s|1min"; else echo "ffffffffffff (head)"; fi\n'
            '    exit 0\n'
            '  fi\n'
            'fi\n'
            f'exec "{os.sys.executable}" "$@"\n'
        )
        self.stub.chmod(0o755)
        self.patch_script = tmp_path / "alembic-paused-in-transaction.py"
        self.patch_script.write_text(
            "import os, sys, time\n"
            "from alembic.runtime import migration\n"
            "original = migration.MigrationContext.run_migrations\n"
            "def paused(self, **kw):\n"
            "    directory = os.environ['STUB_PAUSE_IN_TXN_DIR']\n"
            "    open(os.path.join(directory, 'in-txn.%d' % os.getpid()), 'w').close()\n"
            "    waited = 0\n"
            "    while not os.path.exists(os.path.join(directory, 'release')) and waited < 600:\n"
            "        time.sleep(0.1); waited += 1\n"
            "    return original(self, **kw)\n"
            "migration.MigrationContext.run_migrations = paused\n"
            "from alembic.config import main\n"
            "main(argv=['upgrade', sys.argv[1]])\n"
        )

    def environment(self, args: Tuple[str, ...], pg_database: str, url_engine: Optional[Engine],
                    env: Optional[Dict[str, Optional[str]]] = None, evidence: Optional[Dict[str, Optional[str]]] = None,
                    evidence_dump_from: Optional[str] = None) -> Dict[str, str]:
        environment = _libpq_env(pg_database)
        environment.update({"MIGRATION_PYTHON": str(self.stub), "STUB_LOG": str(self.log),
                            "STUB_COUNTS": str(self.dir / "stub-count"), "REQUIRE_DATA_API_ROLES": "no",
                            "STUB_PATCH_SCRIPT": str(self.patch_script)})
        if len(args) == 2 and args[0] in (E9A_REVISION, E10_REVISION):
            environment["BACKUP_EVIDENCE_FILE"] = str(
                _make_evidence(self.dir, evidence_dump_from or pg_database, args[0], args[1], **(evidence or {})))
        if url_engine is not None:
            environment["DATABASE_URL"] = _url_of(url_engine).render_as_string(hide_password=False)
        for key, value in (env or {}).items():
            if value is None:
                environment.pop(key, None)
            else:
                environment[key] = value
        return environment

    def run(self, args: Tuple[str, ...], pg_database: str, url_engine: Optional[Engine],
            env: Optional[Dict[str, Optional[str]]] = None, evidence: Optional[Dict[str, Optional[str]]] = None,
            evidence_dump_from: Optional[str] = None) -> subprocess.CompletedProcess:
        environment = self.environment(args, pg_database, url_engine, env, evidence, evidence_dump_from)
        return subprocess.run([str(GUARDED), *args], env=environment, capture_output=True, text=True,
                              timeout=240, stdin=subprocess.DEVNULL)

    def start(self, args: Tuple[str, ...], pg_database: str, url_engine: Optional[Engine],
              env: Optional[Dict[str, Optional[str]]] = None) -> "subprocess.Popen[str]":
        return subprocess.Popen([str(GUARDED), *args], env=self.environment(args, pg_database, url_engine, env),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL,
                                start_new_session=True)

    def upgrade_calls(self) -> List[str]:
        if not self.log.exists():
            return []
        return [line for line in self.log.read_text().splitlines() if "alembic upgrade" in line]


@pytest.fixture
def guarded(tmp_path: Path) -> _Guarded:
    return _Guarded(tmp_path)


def _assert_stopped_before_any_migration(
    result: subprocess.CompletedProcess, guarded: _Guarded, databases: List[Tuple[str, Engine]],
    before: List[str], revisions: List[str],
) -> None:
    assert result.returncode == 11, (result.returncode, result.stdout, result.stderr)
    assert guarded.upgrade_calls() == []  # `alembic upgrade` was never invoked
    assert [_revision(engine) for _name, engine in databases] == revisions
    assert [_database_fingerprint(name, engine) for name, engine in databases] == before
    assert "postgresql://" not in result.stdout + result.stderr


def _snapshot(databases: List[Tuple[str, Engine]]) -> Tuple[List[str], List[str]]:
    return ([_database_fingerprint(name, engine) for name, engine in databases],
            [_revision(engine) for _name, engine in databases])


def test_the_guarded_runner_applies_exactly_the_named_revisions_in_order_and_verifies_each(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e6_db

    first = guarded.run((E9A_REVISION, name), name, database_engine)
    assert first.returncode == 0, (first.stdout, first.stderr)
    assert _revision(database_engine) == E9A_REVISION and "MIGRATED AND VERIFIED" in first.stdout

    second = guarded.run((E10_REVISION, name), name, database_engine)
    assert second.returncode == 0, (second.stdout, second.stderr)
    assert _revision(database_engine) == E10_REVISION

    calls = guarded.upgrade_calls()
    assert len(calls) == 2 and calls[0].endswith(f"upgrade {E9A_REVISION}") and calls[1].endswith(f"upgrade {E10_REVISION}")
    assert not any("head" in call for call in calls)


def test_a_mismatch_between_pg_variables_and_database_url_stops_before_any_migration(
    guarded: _Guarded, e6_db: Tuple[str, Engine], e9a_db: Tuple[str, Engine],
) -> None:
    databases = [e6_db, e9a_db]
    before, revisions = _snapshot(databases)

    # The preflight would PASS for the PG* database (at the parent revision); DATABASE_URL names another database.
    result = guarded.run((E9A_REVISION, e6_db[0]), e6_db[0], e9a_db[1])

    _assert_stopped_before_any_migration(result, guarded, databases, before, revisions)
    assert "same server" in result.stderr


def test_a_database_url_that_drops_the_lock_timeout_stops_before_any_migration(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e6_db
    before, revisions = _snapshot([e6_db])
    url = _url_of(database_engine).render_as_string(hide_password=False) + "?options=-c%20lock_timeout%3D0"

    result = guarded.run((E9A_REVISION, name), name, None, env={"DATABASE_URL": url})

    _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)


@pytest.mark.parametrize("target,template,live", [
    (E9A_REVISION, "e6_template", E9A_REVISION),    # the target is already applied
    (E9A_REVISION, "e6_template", E10_REVISION),    # the database is ahead of the target
    (E10_REVISION, "e9a_template", E6_REVISION),    # the parent of the target is missing (database moved back)
])
def test_an_unexpected_current_revision_stops_before_any_migration(
    request: pytest.FixtureRequest, guarded: _Guarded, target: str, template: str, live: str,
) -> None:
    # A VALID backup of this very database was taken at the gate's source revision; the database has since moved to a
    # different revision. Only the `alembic current` guard can (and must) stop this run.
    name = f"vfops_{uuid4().hex[:10]}_test"
    url = _create_database(name, template=request.getfixturevalue(template))
    database_engine = create_engine(url)
    try:
        receipt = _make_evidence(guarded.dir, name, target, name)
        moved = _alembic(url, "upgrade" if live != E6_REVISION else "downgrade", live)
        assert moved.returncode == 0, moved.stderr
        before, revisions = _snapshot([(name, database_engine)])
        assert revisions == [live]

        result = guarded.run((target, name), name, database_engine, env={"BACKUP_EVIDENCE_FILE": str(receipt)})

        _assert_stopped_before_any_migration(result, guarded, [(name, database_engine)], before, revisions)
        assert "alembic current" in result.stderr
    finally:
        database_engine.dispose()
        _drop_database(name)


def test_a_failed_preflight_prerequisite_stops_before_any_migration(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    _execute(e6_db[1], "CREATE SEQUENCE public.rule_alerts_orphan_seq")  # partial target object
    before, revisions = _snapshot([e6_db])

    result = guarded.run((E9A_REVISION, e6_db[0]), e6_db[0], e6_db[1])

    _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)
    assert "e9a_preflight did not PASS" in result.stderr


def test_a_conflicting_lock_stops_before_any_migration(guarded: _Guarded, e6_db: Tuple[str, Engine]) -> None:
    holder = e6_db[1].connect()
    try:
        holder.execute(text("BEGIN"))
        holder.execute(text("LOCK TABLE financial_rules IN ROW EXCLUSIVE MODE"))
        before, revisions = _snapshot([e6_db])

        result = guarded.run((E9A_REVISION, e6_db[0]), e6_db[0], e6_db[1])
    finally:
        holder.rollback()
        holder.close()

    _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)


def test_an_unreachable_server_stops_before_any_migration(guarded: _Guarded, e6_db: Tuple[str, Engine]) -> None:
    result = guarded.run((E9A_REVISION, e6_db[0]), e6_db[0], e6_db[1], env={"PGPORT": "1"})

    assert result.returncode == 11 and guarded.upgrade_calls() == []
    assert _revision(e6_db[1]) == E6_REVISION


@pytest.mark.parametrize("args,env", [
    (("head", "KEEP"), {}),
    ((E9A_REVISION,), {}),
    ((E9A_REVISION, "bad;name"), {}),
    ((E9A_REVISION, "other_db"), {}),
    ((E9A_REVISION, "KEEP"), {"DATABASE_URL": None}),
    ((E9A_REVISION, "KEEP"), {"PGSERVICE": "staging"}),
    ((E9A_REVISION, "KEEP"), {"PGHOSTADDR": "203.0.113.7"}),
    ((E9A_REVISION, "KEEP"), {"PGHOST": None}),
    ((E9A_REVISION, "KEEP"), {"PGUSER": None}),
    ((E9A_REVISION, "KEEP"), {"PGDATABASE": None}),
    ((E9A_REVISION, "KEEP"), {"BACKUP_EVIDENCE_FILE": None}),
    ((E9A_REVISION, "KEEP"), {"MIGRATION_PYTHON": "/nonexistent/python"}),
    ((E9A_REVISION, "KEEP"), {"ALLOW_INSECURE_LOCAL_TEST": None}),                  # the stub interpreter is test-only
    ((E9A_REVISION, "KEEP"), {"PGHOST": "db.example.invalid"}),                      # ... and local-only
    ((E9A_REVISION, "KEEP"), {"DATABASE_URL": "postgresql://u:p@localhost/x?sslmode=disable",
                              "ALLOW_INSECURE_LOCAL_TEST": None, "MIGRATION_PYTHON": None, "PGSSLMODE": "require"}),
    ((E9A_REVISION, "KEEP"), {"PGSSLMODE": "prefer", "ALLOW_INSECURE_LOCAL_TEST": None}),
    (("d4a1b2c3e5f6", "KEEP"), {}),
])
def test_the_guarded_runner_refuses_unsafe_invocations_without_running_anything(
    guarded: _Guarded, e6_db: Tuple[str, Engine], args: Tuple[str, ...], env: Dict[str, Optional[str]],
) -> None:
    resolved = tuple(e6_db[0] if value == "KEEP" else value for value in args)

    result = guarded.run(resolved, e6_db[0], e6_db[1], env=env)

    assert result.returncode == 64 and "REFUSED" in result.stderr
    assert guarded.upgrade_calls() == [] and not guarded.log.exists()
    assert _revision(e6_db[1]) == E6_REVISION


def test_a_failing_alembic_upgrade_exits_nonzero_and_leaves_the_database_unchanged(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    before, revisions = _snapshot([e6_db])

    result = guarded.run((E9A_REVISION, e6_db[0]), e6_db[0], e6_db[1], env={"STUB_FAIL_UPGRADE": "1"})

    assert result.returncode == 12 and len(guarded.upgrade_calls()) == 1
    assert _snapshot([e6_db]) == (before, revisions)


def test_a_failing_post_check_exits_nonzero_after_the_upgrade(guarded: _Guarded, e6_db: Tuple[str, Engine]) -> None:
    # The application role does not exist: the post-check fails although the migration itself succeeded.
    result = guarded.run((E9A_REVISION, e6_db[0]), e6_db[0], e6_db[1], env={"APP_ROLE": "no_such_app_role"})

    assert result.returncode == 13 and "did not PASS" in result.stderr
    assert _revision(e6_db[1]) == E9A_REVISION  # reported as migrated-but-unverified, never silently OK


def test_a_missing_receipt_file_stops_before_any_migration(guarded: _Guarded, e6_db: Tuple[str, Engine]) -> None:
    before, revisions = _snapshot([e6_db])

    result = guarded.run((E9A_REVISION, e6_db[0]), e6_db[0], e6_db[1],
                         env={"BACKUP_EVIDENCE_FILE": str(guarded.dir / "no-such-receipt.env")})

    _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)
    assert "backup evidence rejected" in result.stderr


@pytest.mark.parametrize("overrides,expected", [
    ({"GATE_TARGET": E10_REVISION}, "not bound"),
    ({"DATABASE": "some_other_db"}, "not bound"),
    ({"SOURCE_REVISION": E9A_REVISION}, "not bound"),                          # e.g. the wrong gate's receipt
    ({"RESTORE_PREFLIGHT": "FAIL"}, "PASSed restore"),
    ({"RESTORE_REVISION": E9A_REVISION}, "expected database and revision"),
    ({"RESTORE_REVISION": None}, "exactly the required fields"),
    ({"RESTORE_DATABASE": "production_db"}, "*_test"),                          # restore not on a throwaway database
    ({"DUMP_SHA256": "0" * 64}, "SHA-256"),
    ({"DUMP_FILE": "relative.dump"}, "absolute"),
    ({"DUMP_FILE": "/nonexistent/missing.dump"}, "missing or unreadable"),
    ({"DUMP_CREATED_AT_UTC": "not-a-time"}, "UTC timestamp"),
    ({"DUMP_CREATED_AT_UTC": "STALE", "RESTORE_VERIFIED_AT_UTC": "STALE"}, "older than 24 hours"),
    ({"DUMP_CREATED_AT_UTC": "FUTURE", "RESTORE_VERIFIED_AT_UTC": "FUTURE"}, "inconsistent"),
    ({"RESTORE_VERIFIED_AT_UTC": "BEFORE_DUMP"}, "inconsistent"),
    ({"DUMP_SERVER_MAJOR": "9"}, "DUMP_SERVER_MAJOR"),                         # claims another server version than the dump
    ({"UNKNOWN_FIELD": "x"}, "unknown, duplicate or malformed"),
])
def test_invalid_backup_or_restore_evidence_stops_before_any_migration(
    guarded: _Guarded, e6_db: Tuple[str, Engine], overrides: Dict[str, Optional[str]], expected: str,
) -> None:
    name, database_engine = e6_db
    before, revisions = _snapshot([e6_db])
    resolved: Dict[str, Optional[str]] = {}
    for key, value in overrides.items():
        resolved[key] = {"STALE": _utc(3 * 24 * 3600), "FUTURE": _utc(-2 * 3600), "BEFORE_DUMP": _utc(2 * 3600)}.get(
            value or "", value)
    receipt = _make_evidence(guarded.dir, name, E9A_REVISION, name, **resolved)

    result = guarded.run((E9A_REVISION, name), name, database_engine, env={"BACKUP_EVIDENCE_FILE": str(receipt)})

    _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)
    assert expected in result.stderr, result.stderr


def test_a_hand_edited_or_hand_written_receipt_fails_the_seal(guarded: _Guarded, e6_db: Tuple[str, Engine]) -> None:
    name, database_engine = e6_db
    before, revisions = _snapshot([e6_db])
    edited = _make_evidence(guarded.dir, name, E9A_REVISION, name, reseal=False, RESTORE_SERVER_MAJOR="99")
    legacy = guarded.dir / "legacy-receipt.env"       # the former hand-typed format (operator-asserted PASS)
    legacy.write_text(f"GATE_TARGET={E9A_REVISION}\nDATABASE={name}\nSOURCE_REVISION={E6_REVISION}\nRESTORE_VERIFIED=PASS\n")
    legacy.chmod(0o600)

    results = [guarded.run((E9A_REVISION, name), name, database_engine, env={"BACKUP_EVIDENCE_FILE": str(candidate)})
               for candidate in (edited, legacy)]

    for result in results:
        _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)
    assert "seal mismatch" in results[0].stderr and "unknown, duplicate or malformed" in results[1].stderr


def test_a_duplicated_receipt_field_stops_before_any_migration(guarded: _Guarded, e6_db: Tuple[str, Engine]) -> None:
    name, database_engine = e6_db
    before, revisions = _snapshot([e6_db])
    receipt = _make_evidence(guarded.dir, name, E9A_REVISION, name)
    receipt.write_text(receipt.read_text() + "RESTORE_PREFLIGHT=PASS\n")

    result = guarded.run((E9A_REVISION, name), name, database_engine, env={"BACKUP_EVIDENCE_FILE": str(receipt)})

    _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)


def test_a_dump_changed_after_its_checksum_was_recorded_stops_before_any_migration(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e6_db
    before, revisions = _snapshot([e6_db])
    receipt = _make_evidence(guarded.dir, name, E9A_REVISION, name)
    with open(_receipt_fields(receipt)["DUMP_FILE"], "ab") as handle:
        handle.write(b"tampered")

    result = guarded.run((E9A_REVISION, name), name, database_engine, env={"BACKUP_EVIDENCE_FILE": str(receipt)})

    _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)
    assert "SHA-256" in result.stderr


def test_a_dump_that_lacks_a_required_table_stops_before_any_migration(
    guarded: _Guarded, e6_db: Tuple[str, Engine], e9a_db: Tuple[str, Engine],
) -> None:
    # Gate F on the E9A database, but the "backup" was taken from an E6 database: it has no rule_alerts (and holds
    # the E6 revision). The production inspector refuses it.
    before, revisions = _snapshot([e9a_db])
    dump = _dump_of(guarded.dir, e6_db[0])
    with pytest.raises(SystemExit):
        backup_evidence.inspect_dump(str(dump), e6_db[0], E9A_REVISION, _TABLES[E10_REVISION])
    receipt = _make_evidence(guarded.dir, e9a_db[0], E10_REVISION, e9a_db[0], DUMP_FILE=str(dump))

    result = guarded.run((E10_REVISION, e9a_db[0]), e9a_db[0], e9a_db[1], env={"BACKUP_EVIDENCE_FILE": str(receipt)})

    _assert_stopped_before_any_migration(result, guarded, [e9a_db], before, revisions)
    assert "backup evidence rejected" in result.stderr


def test_sr01_a_dump_of_another_database_with_identical_schema_and_revision_is_rejected(
    guarded: _Guarded, e6_db: Tuple[str, Engine], e6_db_other: Tuple[str, Engine],
) -> None:
    name, database_engine = e6_db
    other_name = e6_db_other[0]
    assert _revision(e6_db[1]) == _revision(e6_db_other[1]) == E6_REVISION  # same schema and revision
    before, revisions = _snapshot([e6_db])

    # (a) an honest receipt for the OTHER database presented for this one, and (b) a receipt that LIES about the origin
    honest = _make_evidence(guarded.dir, other_name, E9A_REVISION, name)
    lying = _make_evidence(guarded.dir, other_name, E9A_REVISION, name, DUMP_DBNAME=name)

    for candidate, message in ((honest, "does not record the expected database"), (lying, "not taken from the expected database")):
        result = guarded.run((E9A_REVISION, name), name, database_engine, env={"BACKUP_EVIDENCE_FILE": str(candidate)})
        _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)
        assert message in result.stderr, result.stderr


def test_sr01_a_dump_holding_another_alembic_revision_than_the_source_is_rejected(
    guarded: _Guarded, e6_db: Tuple[str, Engine], e9a_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e6_db
    before, revisions = _snapshot([e6_db])
    # The receipt claims source e0503e9ca9d3, the archive DATA holds a7c3e91d5b24 (a dump of a later database).
    dump = _dump_of(guarded.dir, e9a_db[0])
    facts = {"DUMP_FILE": str(dump), "DUMP_SHA256": hashlib.sha256(dump.read_bytes()).hexdigest(),
             "DUMP_DBNAME": e9a_db[0]}
    receipt = _make_evidence(guarded.dir, name, E9A_REVISION, e9a_db[0], **facts)
    result = guarded.run((E9A_REVISION, e9a_db[0]), e9a_db[0], e9a_db[1], env={"BACKUP_EVIDENCE_FILE": str(receipt)})

    assert result.returncode == 11 and guarded.upgrade_calls() == []
    assert "different alembic revision" in result.stderr or "not at the" in result.stderr or "expected database and revision" in result.stderr


@pytest.mark.parametrize("unsafe", ["group_writable", "symlink", "dump_world_readable"])
def test_unsafe_evidence_files_stop_before_any_migration(
    guarded: _Guarded, e6_db: Tuple[str, Engine], unsafe: str,
) -> None:
    name, database_engine = e6_db
    before, revisions = _snapshot([e6_db])
    receipt = _make_evidence(guarded.dir, name, E9A_REVISION, name)
    if unsafe == "group_writable":
        receipt.chmod(0o666)
    elif unsafe == "symlink":
        link = guarded.dir / "receipt-link.env"
        link.symlink_to(receipt)
        receipt = link
    else:
        Path(_receipt_fields(receipt)["DUMP_FILE"]).chmod(0o644)

    result = guarded.run((E9A_REVISION, name), name, database_engine, env={"BACKUP_EVIDENCE_FILE": str(receipt)})

    _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)


def test_a_dump_from_another_server_major_version_stops_before_any_migration(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e6_db
    before, revisions = _snapshot([e6_db])
    # A receipt whose recorded server major differs from the live server: the seal is valid, the dump is genuine,
    # but the inspector re-derives the major from the archive, so the lie is caught as a changed fact.
    receipt = _make_evidence(guarded.dir, name, E9A_REVISION, name, DUMP_SERVER_MAJOR="1")

    result = guarded.run((E9A_REVISION, name), name, database_engine, env={"BACKUP_EVIDENCE_FILE": str(receipt)})

    _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)


def test_a_database_url_that_drops_the_statement_timeout_stops_before_any_migration(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e6_db
    before, revisions = _snapshot([e6_db])
    url = _url_of(database_engine).render_as_string(hide_password=False) + "?options=-c%20statement_timeout%3D0"

    result = guarded.run((E9A_REVISION, name), name, None, env={"DATABASE_URL": url})

    _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)


@pytest.mark.parametrize("drift", ["proof", "current"])
def test_a_change_between_the_first_checks_and_the_upgrade_stops_before_any_migration(
    guarded: _Guarded, e6_db: Tuple[str, Engine], drift: str,
) -> None:
    before, revisions = _snapshot([e6_db])

    result = guarded.run((E9A_REVISION, e6_db[0]), e6_db[0], e6_db[1], env={"STUB_DRIFT": drift})

    _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)
    counts = guarded.log.parent / f"stub-count.{drift}"
    assert counts.read_text().strip() == "2"  # the proof really was repeated right before the upgrade


def test_the_runner_refuses_an_empty_database_it_is_not_a_bootstrap(guarded: _Guarded, e6_db: Tuple[str, Engine]) -> None:
    empty = f"vfops_{uuid4().hex[:10]}_test"
    url = _create_database(empty)
    empty_engine = create_engine(url)
    try:
        result = guarded.run((E9A_REVISION, empty), empty, empty_engine, evidence_dump_from=e6_db[0])

        # No valid backup evidence can exist for an unmigrated database (no revision to dump or restore), and the
        # `alembic current` guard would stop it next: either way the runner is not a bootstrap.
        assert result.returncode == 11 and guarded.upgrade_calls() == []
        assert "backup evidence rejected" in result.stderr or "alembic current" in result.stderr
        with empty_engine.connect() as connection:
            assert connection.execute(text("SELECT to_regclass('public.alembic_version')")).scalar() is None
    finally:
        empty_engine.dispose()
        _drop_database(empty)


def test_the_release_documents_contain_no_unguarded_migration_command() -> None:
    root = API_DIR.parents[1] / "docs"
    fenced = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
    for document in sorted((root / "operations").glob("*.md")):
        for block in fenced.findall(document.read_text()):
            assert "alembic upgrade" not in block, f"{document.name} contains a hand-typed alembic upgrade"
    development = (root / "development.md").read_text()
    for revision in (E9A_REVISION, E10_REVISION):
        assert f"alembic upgrade {revision}" not in development, "development.md still shows a hand-typed release upgrade"


# ---- SR-02: the verifier performs the restore and the preflight and produces the receipt ----------------------------

VERIFIER = SQL_DIR / "verify_backup_restore.sh"


def _local_server() -> Tuple[Path, Optional[str]]:
    """Data directory (and socket directory) of the local PostgreSQL the tests use; skip when it is not on this machine."""
    admin = _admin_engine()
    try:
        with admin.connect() as connection:
            data_dir = Path(connection.execute(text("SHOW data_directory")).scalar_one())
            sockets = connection.execute(text("SHOW unix_socket_directories")).scalar_one().split(",")[0].strip()
    except Exception:
        pytest.skip("cannot read data_directory (the verifier tests need a local server and a superuser test role)")
    finally:
        admin.dispose()
    if not (data_dir / "postmaster.pid").is_file():
        pytest.skip("the test database server is not running on this machine (no local postmaster.pid)")
    return data_dir, (sockets if sockets.startswith("/") else None)


def _shims(directory: Path, **scripts: str) -> Path:
    """PATH shims for createdb/dropdb/pg_restore that log every call (SHIM_LOG) and then run `body`."""
    shim_dir = directory / "shims"
    shim_dir.mkdir(exist_ok=True)
    for name in ("createdb", "dropdb", "pg_restore"):
        real = shutil.which(name)
        assert real, name
        body = scripts.get(name, f'exec "{real}" "$@"')
        # The log lives next to the shim: the verifier runs its tools under `env -i`, so no test variable reaches them.
        (shim_dir / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "$(dirname "$0")/calls.log"\nREAL="{real}"\n{body}\n')
        (shim_dir / name).chmod(0o755)
    return shim_dir


def _verify(directory: Path, dump: Path, gate: str, expected_db: str, receipt: Path,
            env: Optional[Dict[str, Optional[str]]] = None, shims: Optional[Path] = None,
            socket_mode: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run([str(VERIFIER), gate, expected_db, str(dump), str(receipt)],
                          env=_verifier_environment(directory, env, shims, socket_mode), capture_output=True, text=True,
                          timeout=240, stdin=subprocess.DEVNULL)


def _verifier_environment(directory: Path, env: Optional[Dict[str, Optional[str]]] = None, shims: Optional[Path] = None,
                          socket_mode: bool = False) -> Dict[str, str]:
    data_dir, sockets = _local_server()
    base = _libpq_env("postgres")
    environment = {key: value for key, value in base.items() if not key.startswith("PG")}
    environment.update({"RESTORE_PGHOST": base["PGHOST"], "RESTORE_PGPORT": base["PGPORT"],
                        "RESTORE_PGUSER": base["PGUSER"], "RESTORE_PGPASSWORD": base["PGPASSWORD"],
                        "RESTORE_PGSSLMODE": "disable", "RESTORE_PGDATA": str(data_dir),
                        "RESTORE_ALLOW_LOOPBACK_TCP": "1", "SHIM_LOG": str(directory / "shim.log"),
                        # What an operator's shell holds while verifying: production variables that must be ignored.
                        "PGHOST": "db.production.invalid", "DATABASE_URL": "postgresql://u:p@db.production.invalid/x"})
    if socket_mode:
        if not sockets or not os.path.exists(os.path.join(sockets, f".s.PGSQL.{base['PGPORT']}")):
            pytest.skip("no Unix socket for the test server")
        environment.update({"RESTORE_PGHOST": sockets, "RESTORE_ALLOW_LOOPBACK_TCP": ""})
    if shims is not None:
        environment["PATH"] = f"{shims}:{environment.get('PATH', os.environ['PATH'])}"
    for key, value in (env or {}).items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    return environment


def _throwaway_databases() -> int:
    admin = _admin_engine()
    try:
        with admin.connect() as connection:
            return connection.execute(text("SELECT count(*) FROM pg_database WHERE datname LIKE 'vf_restore_%'")).scalar_one()
    finally:
        admin.dispose()


def test_sr02_the_verifier_restores_runs_the_preflight_and_its_receipt_is_accepted_by_the_runner(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e6_db
    dump = _dump_of(guarded.dir, name)
    receipt = guarded.dir / "verifier-receipt.env"
    leftovers = _throwaway_databases()

    verified = _verify(guarded.dir, dump, E9A_REVISION, name, receipt)

    assert verified.returncode == 0, (verified.stdout, verified.stderr)
    assert "RECEIPT WRITTEN" in verified.stdout and (receipt.stat().st_mode & 0o777) == 0o600
    fields = _receipt_fields(receipt)
    assert fields["RESTORE_PREFLIGHT"] == "PASS" and fields["RESTORE_REVISION"] == E6_REVISION
    assert fields["DUMP_DBNAME"] == name and re.fullmatch(r"vf_restore_\d+_\d+_test", fields["RESTORE_DATABASE"])
    assert _throwaway_databases() == leftovers  # the throwaway restore database was dropped
    assert "db.production.invalid" not in verified.stdout + verified.stderr

    result = guarded.run((E9A_REVISION, name), name, database_engine, env={"BACKUP_EVIDENCE_FILE": str(receipt)})

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert _revision(database_engine) == E9A_REVISION and len(guarded.upgrade_calls()) == 1


def test_sr02_the_verifier_rejects_a_dump_of_another_database_and_writes_no_receipt(
    guarded: _Guarded, e6_db: Tuple[str, Engine], e6_db_other: Tuple[str, Engine],
) -> None:
    dump = _dump_of(guarded.dir, e6_db_other[0])
    receipt = guarded.dir / "no-receipt.env"
    leftovers = _throwaway_databases()

    result = _verify(guarded.dir, dump, E9A_REVISION, e6_db[0], receipt)

    assert result.returncode == 1 and "not taken from the expected database" in result.stderr
    assert not receipt.exists() and _throwaway_databases() == leftovers


def test_sr02_the_verifier_rejects_the_wrong_source_revision_and_writes_no_receipt(
    guarded: _Guarded, e9a_db: Tuple[str, Engine],
) -> None:
    dump = _dump_of(guarded.dir, e9a_db[0])   # holds a7c3e91d5b24, not the e0503e9ca9d3 that gate C requires
    receipt = guarded.dir / "no-receipt.env"

    result = _verify(guarded.dir, dump, E9A_REVISION, e9a_db[0], receipt)

    assert result.returncode == 1 and "different alembic revision" in result.stderr and not receipt.exists()


def test_sr02_a_failing_preflight_on_the_restored_copy_writes_no_receipt_and_drops_the_throwaway(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    _execute(e6_db[1], "CREATE SEQUENCE public.rule_alerts_orphan_seq")  # a partial E9A object: the preflight must fail
    dump = _dump_of(guarded.dir, e6_db[0])
    receipt = guarded.dir / "no-receipt.env"
    leftovers = _throwaway_databases()

    result = _verify(guarded.dir, dump, E9A_REVISION, e6_db[0], receipt)

    assert result.returncode == 1 and "did not PASS" in result.stderr
    assert not receipt.exists() and _throwaway_databases() == leftovers


@pytest.mark.parametrize("env", [{"RESTORE_PGHOST": "db.example.invalid"}, {"RESTORE_PGUSER": None}, {"RESTORE_PGHOST": None}])
def test_sr02_the_verifier_refuses_a_non_local_restore_server(
    guarded: _Guarded, e6_db: Tuple[str, Engine], env: Dict[str, Optional[str]],
) -> None:
    receipt = guarded.dir / "no-receipt.env"

    result = _verify(guarded.dir, _dump_of(guarded.dir, e6_db[0]), E9A_REVISION, e6_db[0], receipt, env=env)

    assert result.returncode == 64 and "REFUSED" in result.stderr and not receipt.exists()


# ---- SR-05 / SR-06: cleanup of the throwaway database ----------------------------------------------------------

def _shim_calls(directory: Path, tool: str) -> List[str]:
    log = directory / "shims" / "calls.log"
    return [line for line in log.read_text().splitlines() if line.startswith(tool + " ")] if log.exists() else []


def test_sr05_a_failed_createdb_never_leads_to_a_dropdb_and_spares_an_existing_database(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    # createdb "fails because the name already exists": the shim creates the database first (another process's database),
    # then runs the real createdb, which fails with `database ... already exists`.
    real = shutil.which("createdb")
    shims = _shims(guarded.dir, createdb=f'"$REAL" "$@" || exit 1; exec "$REAL" "$@"')
    receipt = guarded.dir / "no-receipt.env"

    result = _verify(guarded.dir, _dump_of(guarded.dir, e6_db[0]), E9A_REVISION, e6_db[0], receipt, shims=shims)

    assert real and result.returncode == 1 and "cannot create the throwaway database" in result.stderr
    assert len(_shim_calls(guarded.dir, "createdb")) == 1
    assert _shim_calls(guarded.dir, "dropdb") == []                # no dropdb invocation at all
    assert not receipt.exists() and not list(guarded.dir.glob("*.pending.*"))
    admin = _admin_engine()
    try:
        with admin.connect() as connection:
            survivors = [row[0] for row in connection.execute(text("SELECT datname FROM pg_database WHERE datname LIKE 'vf_restore_%'"))]
    finally:
        admin.dispose()
    assert len(survivors) == 1                                       # the pre-existing database was not deleted
    _drop_database(survivors[0])


def test_sr06_a_failing_dropdb_prevents_success_and_invalidates_the_receipt(guarded: _Guarded, e6_db: Tuple[str, Engine]) -> None:
    shims = _shims(guarded.dir, dropdb="exit 1")
    receipt = guarded.dir / "receipt.env"

    result = _verify(guarded.dir, _dump_of(guarded.dir, e6_db[0]), E9A_REVISION, e6_db[0], receipt, shims=shims)

    combined = result.stdout + result.stderr
    assert result.returncode == 1 and "CLEANUP FAILED" in result.stderr and "manual investigation" in result.stderr
    assert "RECEIPT WRITTEN" not in combined
    assert not receipt.exists() and not list(guarded.dir.glob("*.pending.*"))   # nothing usable is left behind
    assert "postgres" not in combined.replace("PostgreSQL", "") or "password" not in combined.lower()
    leftover = re.search(r"vf_restore_\d+_\d+_test", result.stderr)
    assert leftover                                                  # the operator is told which database to inspect
    _drop_database(leftover.group(0))                                # the test cleans up what the shim refused to drop


def test_sr06_normal_cleanup_drops_exactly_once_and_then_writes_the_receipt(guarded: _Guarded, e6_db: Tuple[str, Engine]) -> None:
    shims = _shims(guarded.dir)
    receipt = guarded.dir / "receipt.env"
    leftovers = _throwaway_databases()

    result = _verify(guarded.dir, _dump_of(guarded.dir, e6_db[0]), E9A_REVISION, e6_db[0], receipt, shims=shims)

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert len(_shim_calls(guarded.dir, "createdb")) == 1 and len(_shim_calls(guarded.dir, "dropdb")) == 1
    assert receipt.exists() and _throwaway_databases() == leftovers


def test_sr05_an_interrupted_verifier_still_drops_the_database_it_created(guarded: _Guarded, e6_db: Tuple[str, Engine]) -> None:
    shims = _shims(guarded.dir, pg_restore='case "$*" in *--dbname*) touch "$(dirname "$0")/restoring"; sleep 60;; *) exec "$REAL" "$@";; esac')
    receipt = guarded.dir / "receipt.env"
    leftovers = _throwaway_databases()
    process = subprocess.Popen(
        [str(VERIFIER), E9A_REVISION, e6_db[0], str(_dump_of(guarded.dir, e6_db[0])), str(receipt)],
        env=_verifier_environment(guarded.dir, shims=shims), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        for _ in range(150):
            if (guarded.dir / "shims" / "restoring").exists():
                break
            time.sleep(0.2)
        assert (guarded.dir / "shims" / "restoring").exists()
        os.killpg(process.pid, signal.SIGTERM)                       # what Ctrl-C / a terminal hangup does
        process.communicate(timeout=60)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
    assert process.returncode in (143, -signal.SIGTERM) and not receipt.exists()
    assert len(_shim_calls(guarded.dir, "dropdb")) == 1 and _throwaway_databases() == leftovers


# ---- SR-08: the restore server must be provably local ------------------------------------------------------------

def _pid_file_copy(directory: Path, **changes: str) -> Path:
    """A copy of the local postmaster.pid (with the directory line pointing at the copy) and some lines changed."""
    data_dir, _sockets = _local_server()
    lines = (data_dir / "postmaster.pid").read_text().splitlines()
    fake = directory / "fake-pgdata"
    fake.mkdir(exist_ok=True)
    lines[1] = str(fake)
    for index, key in ((0, "pid"), (2, "start"), (3, "port")):
        if key in changes:
            lines[index] = changes[key]
    (fake / "postmaster.pid").write_text("\n".join(lines) + "\n")
    return fake


@pytest.mark.parametrize("env", [
    {"RESTORE_ALLOW_LOOPBACK_TCP": ""},                 # loopback TCP can be a tunnel: needs the explicit flag
    {"RESTORE_PGDATA": None},                           # no data directory to prove the server against
    {"RESTORE_PGDATA": "relative/path"},
    {"RESTORE_PGDATA": "/nonexistent/pgdata"},
    {"RESTORE_PGHOST": "/nonexistent/socket-dir", "RESTORE_ALLOW_LOOPBACK_TCP": ""},
    {"RESTORE_PGPORT": "54x2"},
])
def test_sr08_unverified_or_unsafe_connection_configurations_are_refused_before_anything_is_created(
    guarded: _Guarded, e6_db: Tuple[str, Engine], env: Dict[str, Optional[str]],
) -> None:
    receipt = guarded.dir / "no-receipt.env"
    shims = _shims(guarded.dir)

    result = _verify(guarded.dir, _dump_of(guarded.dir, e6_db[0]), E9A_REVISION, e6_db[0], receipt, env=env, shims=shims)

    assert result.returncode == 64 and "REFUSED" in result.stderr and not receipt.exists()
    assert _shim_calls(guarded.dir, "createdb") == []


@pytest.mark.parametrize("change,message", [
    ({"start": "1000000000"}, "start times differ"),                 # a server with another start time: a tunnel to elsewhere
    ({"pid": "999999"}, "not a running local process"),
    ({"port": "1"}, "different port"),
])
def test_sr08_a_server_that_is_not_the_local_postmaster_is_rejected_before_createdb(
    guarded: _Guarded, e6_db: Tuple[str, Engine], change: Dict[str, str], message: str,
) -> None:
    fake = _pid_file_copy(guarded.dir, **change)
    receipt = guarded.dir / "no-receipt.env"
    shims = _shims(guarded.dir)

    result = _verify(guarded.dir, _dump_of(guarded.dir, e6_db[0]), E9A_REVISION, e6_db[0], receipt,
                     env={"RESTORE_PGDATA": str(fake)}, shims=shims)

    assert result.returncode == 1 and message in result.stderr and not receipt.exists()
    assert _shim_calls(guarded.dir, "createdb") == [] and _shim_calls(guarded.dir, "dropdb") == []


def test_sr08_a_unix_socket_connection_to_the_local_server_is_accepted(guarded: _Guarded, e6_db: Tuple[str, Engine]) -> None:
    receipt = guarded.dir / "receipt.env"

    result = _verify(guarded.dir, _dump_of(guarded.dir, e6_db[0]), E9A_REVISION, e6_db[0], receipt, socket_mode=True)

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert receipt.exists()


# ---- SR-07: lock lifetime, loss of the holder, poolers ------------------------------------------------------------------

def _wait_for(path_glob: Path, pattern: str, seconds: float = 30.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if list(path_glob.glob(pattern)):
            return True
        time.sleep(0.2)
    return False


def _holder_pids() -> List[int]:
    output = subprocess.run(["pgrep", "-f", "hold_migration_lock.py"], capture_output=True, text=True).stdout
    return [int(value) for value in output.split()]


def test_sr07_the_holder_has_no_time_cap_and_a_long_migration_keeps_the_lock_throughout(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    assert "MAX_SECONDS" not in (SQL_DIR / "hold_migration_lock.py").read_text()
    name, database_engine = e6_db
    pause = guarded.dir / "pause"
    pause.mkdir()
    runner = guarded.start((E9A_REVISION, name), name, database_engine, env={"STUB_PAUSE_DIR": str(pause)})
    try:
        assert _wait_for(pause, "started.*")
        for _ in range(8):                                        # a "long" upgrade: the lock is re-verified every second
            assert _advisory_locks(database_engine) == 1 and runner.poll() is None
            time.sleep(1.0)
        (pause / "release").write_text("go")
        out, err = runner.communicate(timeout=120)
        assert runner.returncode == 0, (out, err)
    finally:
        if runner.poll() is None:
            os.killpg(runner.pid, signal.SIGKILL)
    assert _revision(database_engine) == E9A_REVISION


@pytest.mark.parametrize("how", ["process_killed", "backend_terminated"])
def test_sr07_losing_the_lock_holder_terminates_the_upgrade_instead_of_continuing(
    guarded: _Guarded, e6_db: Tuple[str, Engine], how: str,
) -> None:
    name, database_engine = e6_db
    before, revisions = _snapshot([e6_db])
    pause = guarded.dir / "pause"
    pause.mkdir()
    runner = guarded.start((E9A_REVISION, name), name, database_engine, env={"STUB_PAUSE_DIR": str(pause)})
    try:
        assert _wait_for(pause, "started.*")
        if how == "process_killed":
            for pid in _holder_pids():
                os.kill(pid, signal.SIGKILL)
        else:                                                       # the server (or a pooler) drops the holder's connection
            with database_engine.connect() as connection:
                connection.execute(text(
                    "SELECT pg_terminate_backend(pid) FROM pg_locks WHERE locktype = 'advisory' AND classid = 7165 "
                    "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"))
        out, err = runner.communicate(timeout=60)
    finally:
        if runner.poll() is None:
            os.killpg(runner.pid, signal.SIGKILL)
    assert runner.returncode == 14 and "migration lock was lost" in err, (runner.returncode, err)
    assert _snapshot([e6_db]) == (before, revisions)                # the upgrade never completed
    assert _locks_released(database_engine)


@pytest.mark.parametrize("env", [
    {"PGPORT": "6543"},                                             # Supabase transaction-mode pooler port, PG* path
    {"DATABASE_URL": "postgresql://u:p@localhost:6543/x"},          # ... DATABASE_URL path
    {"DATABASE_URL": "postgresql://u:p@pgbouncer.internal:5432/x"},
])
def test_sr07_transaction_poolers_are_refused_for_the_migration(
    guarded: _Guarded, e6_db: Tuple[str, Engine], env: Dict[str, Optional[str]],
) -> None:
    result = guarded.run((E9A_REVISION, e6_db[0]), e6_db[0], e6_db[1], env=env)

    assert result.returncode == 64 and "transaction-mode pooler" in result.stderr
    assert guarded.upgrade_calls() == [] and not guarded.log.exists()


# ---- SR-03: the test mode needs every condition, localhost alone is never enough ----------------------------------

@pytest.mark.parametrize("env", [
    {"PGHOST": "db.example.invalid"},                                                   # remote PG* host
    {"DATABASE_URL": "postgresql://u:p@db.example.invalid/x"},                          # remote DATABASE_URL host
    {"ALLOW_INSECURE_LOCAL_TEST": None},                                                # no explicit flag
    {"ALLOW_INSECURE_LOCAL_TEST": "yes"},                                               # flag must be exactly 1
])
def test_sr03_the_interpreter_override_is_refused_unless_every_test_mode_condition_holds(
    guarded: _Guarded, e6_db: Tuple[str, Engine], env: Dict[str, Optional[str]],
) -> None:
    result = guarded.run((E9A_REVISION, e6_db[0]), e6_db[0], e6_db[1], env=env)

    assert result.returncode == 64 and "REFUSED" in result.stderr
    assert guarded.upgrade_calls() == [] and not guarded.log.exists()


def test_sr03_a_localhost_database_whose_name_is_not_a_test_database_is_refused_the_override(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    # localhost, flag set, interpreter override set, but the expected database does not end in _test. (The suite's own
    # safety guard forbids creating such a database, and the refusal happens before any connection, so none is needed.)
    name = f"vfops_{uuid4().hex[:10]}_prod"

    result = guarded.run((E9A_REVISION, name), name, e6_db[1], evidence_dump_from=e6_db[0])

    assert result.returncode == 64 and "REFUSED" in result.stderr
    assert guarded.upgrade_calls() == [] and not guarded.log.exists()


def test_sr03_the_test_mode_announces_itself_and_a_local_test_database_still_works(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    result = guarded.run((E9A_REVISION, e6_db[0]), e6_db[0], e6_db[1])

    assert result.returncode == 0 and "disposable local TEST MODE" in result.stderr


# ---- SR-04: concurrent runs are serialized by a session-level advisory lock -----------------------------------------

def test_sr04_a_second_run_cannot_reach_the_upgrade_while_the_first_holds_the_lock(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e6_db
    pause = guarded.dir / "pause"
    pause.mkdir()
    first = guarded.start((E9A_REVISION, name), name, database_engine, env={"STUB_PAUSE_DIR": str(pause)})
    try:
        for _ in range(150):
            if list(pause.glob("started.*")):
                break
            time.sleep(0.2)
        assert list(pause.glob("started.*")), "the first run never reached the upgrade"
        assert _advisory_locks(database_engine) == 1                      # held by the first run

        second = guarded.run((E9A_REVISION, name), name, database_engine)

        assert second.returncode == 11 and "another guarded migration run holds the lock" in second.stderr
        assert len(guarded.upgrade_calls()) == 1                          # only the first run reached the upgrade
        (pause / "release").write_text("go")
        out, err = first.communicate(timeout=120)
        assert first.returncode == 0, (out, err)
    finally:
        if first.poll() is None:
            os.killpg(first.pid, signal.SIGKILL)
    assert _revision(database_engine) == E9A_REVISION and len(guarded.upgrade_calls()) == 1
    assert _locks_released(database_engine)                               # nothing stays held after success


@pytest.mark.parametrize("fixture_name,target", [("e9a_db", E9A_REVISION), ("e6_db", E9A_REVISION)])
def test_sr04_no_advisory_lock_stays_held_after_a_stop_or_a_failed_upgrade(
    request: pytest.FixtureRequest, guarded: _Guarded, fixture_name: str, target: str,
) -> None:
    db = request.getfixturevalue(fixture_name)
    env = {"STUB_FAIL_UPGRADE": "1"} if fixture_name == "e6_db" else {}

    result = guarded.run((target, db[0]), db[0], db[1], env=env)

    assert result.returncode in (11, 12)
    assert _locks_released(db[1])


def test_sr04_the_lock_is_released_even_when_the_runner_is_killed(guarded: _Guarded, e6_db: Tuple[str, Engine]) -> None:
    name, database_engine = e6_db
    pause = guarded.dir / "pause"
    pause.mkdir()
    runner = guarded.start((E9A_REVISION, name), name, database_engine, env={"STUB_PAUSE_DIR": str(pause)})
    try:
        for _ in range(150):
            if list(pause.glob("started.*")):
                break
            time.sleep(0.2)
        assert _advisory_locks(database_engine) == 1
        os.kill(runner.pid, signal.SIGKILL)                               # only the runner: its cleanup trap cannot run
        for _ in range(50):
            if _advisory_locks(database_engine) == 0:
                break
            time.sleep(0.2)
        assert _advisory_locks(database_engine) == 0                      # the holder noticed the dead parent
    finally:
        os.killpg(runner.pid, signal.SIGKILL)


# ---- SR-09: the migration's own connection holds the database-level lock, so killing the runner cannot unprotect it ----

def test_sr09_after_sigkill_of_the_runner_the_orphaned_migration_is_still_serialized_by_the_database(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e6_db
    before, revisions = _snapshot([e6_db])
    pause = guarded.dir / "txn-pause"
    pause.mkdir()
    runner_a = guarded.start((E9A_REVISION, name), name, database_engine, env={"STUB_PAUSE_IN_TXN_DIR": str(pause)})
    try:
        assert _wait_for(pause, "in-txn.*"), "runner A never reached the inside of the migration transaction"
        migration_pid = int(next(pause.glob("in-txn.*")).name.split(".")[1])
        # Both locks exist: the runner's session lock (1) and the migration transaction's own lock (2).
        assert _advisory_lock_objects(database_engine) == [1, 2]

        os.kill(runner_a.pid, signal.SIGKILL)                        # ONLY the supervising shell: no trap, no cleanup
        runner_a.wait(timeout=30)
        for _ in range(100):                                         # the holder notices the dead parent and exits
            if _advisory_lock_objects(database_engine) == [2]:
                break
            time.sleep(0.1)
        assert _advisory_lock_objects(database_engine) == [2]        # the session lock is gone, the migration's lock is NOT
        assert _process_alive(migration_pid)                         # the orphaned Alembic is still running ...
        assert _revision(database_engine) == E6_REVISION             # ... and has not committed anything yet

        # (a) a complete second runner cannot perform an overlapping upgrade
        second = guarded.run((E9A_REVISION, name), name, database_engine)
        assert second.returncode in (11, 12), (second.returncode, second.stderr)
        assert _revision(database_engine) == E6_REVISION
        # (b) the database-level invariant itself, with every runner guard out of the way: a second Alembic is refused
        overlapping = _direct_guarded_alembic(_url_of(database_engine), E6_REVISION, "upgrade", E9A_REVISION)
        assert overlapping.returncode != 0 and "VF_MIGRATION_LOCK_BUSY" in overlapping.stderr
        assert _revision(database_engine) == E6_REVISION

        (pause / "release").write_text("go")                         # let the orphan finish on its own
        for _ in range(300):
            if not _process_alive(migration_pid):
                break
            time.sleep(0.1)
        assert not _process_alive(migration_pid)
    finally:
        try:
            os.killpg(runner_a.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    assert _revision(database_engine) == E9A_REVISION                # exactly one upgrade happened
    assert _wrapper("e9a_postcheck", name).returncode == 0           # schema consistent (post-check PASS)
    assert _locks_released(database_engine) and _advisory_lock_objects(database_engine) == []


def test_sr09_sigterm_of_the_runner_stops_the_running_migration_and_releases_everything(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e6_db
    before, revisions = _snapshot([e6_db])
    pause = guarded.dir / "txn-pause"
    pause.mkdir()
    runner = guarded.start((E9A_REVISION, name), name, database_engine, env={"STUB_PAUSE_IN_TXN_DIR": str(pause)})
    try:
        assert _wait_for(pause, "in-txn.*")
        migration_pid = int(next(pause.glob("in-txn.*")).name.split(".")[1])
        os.kill(runner.pid, signal.SIGTERM)                          # only the runner: its trap must stop the child
        runner.communicate(timeout=60)
        for _ in range(100):
            if not _process_alive(migration_pid):
                break
            time.sleep(0.1)
        assert not _process_alive(migration_pid)
    finally:
        try:
            os.killpg(runner.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    assert runner.returncode in (143, -signal.SIGTERM)
    assert _snapshot([e6_db]) == (before, revisions)                 # rolled back: nothing changed
    assert _locks_released(database_engine) and _advisory_lock_objects(database_engine) == []


def test_sr09_a_failing_migration_rolls_back_and_releases_the_database_lock(e6_db: Tuple[str, Engine]) -> None:
    name, database_engine = e6_db
    _execute(database_engine, "CREATE TABLE public.rule_alerts (id integer)")   # makes the E9A DDL fail inside the transaction
    before, revisions = _snapshot([e6_db])

    result = _direct_guarded_alembic(_url_of(database_engine), E6_REVISION, "upgrade", E9A_REVISION)

    assert result.returncode != 0 and _snapshot([e6_db]) == (before, revisions)
    assert _locks_released(database_engine) and _advisory_lock_objects(database_engine) == []


def test_sr09_the_lock_holder_loss_still_stops_a_running_migration_and_leaves_no_lock(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e6_db
    pause = guarded.dir / "txn-pause"
    pause.mkdir()
    runner = guarded.start((E9A_REVISION, name), name, database_engine, env={"STUB_PAUSE_IN_TXN_DIR": str(pause)})
    try:
        assert _wait_for(pause, "in-txn.*")
        migration_pid = int(next(pause.glob("in-txn.*")).name.split(".")[1])
        for pid in _holder_pids():
            os.kill(pid, signal.SIGKILL)
        out, err = runner.communicate(timeout=60)
        for _ in range(100):
            if not _process_alive(migration_pid):
                break
            time.sleep(0.1)
        assert runner.returncode == 14 and not _process_alive(migration_pid)
    finally:
        try:
            os.killpg(runner.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    assert _revision(database_engine) == E6_REVISION
    assert _locks_released(database_engine) and _advisory_lock_objects(database_engine) == []


def test_sr09_ordinary_alembic_commands_are_unchanged_and_the_guard_checks_the_revision_under_the_lock(
    e6_db: Tuple[str, Engine],
) -> None:
    url = _url_of(e6_db[1])
    ordinary = _alembic(url, "current")                              # no environment variable: no lock, no new behavior
    assert ordinary.returncode == 0 and E6_REVISION in ordinary.stdout

    wrong_source = _direct_guarded_alembic(url, E9A_REVISION, "upgrade", E9A_REVISION)   # the database is NOT at that source
    assert wrong_source.returncode != 0 and "VF_MIGRATION_REVISION_CHANGED" in wrong_source.stderr
    assert _revision(e6_db[1]) == E6_REVISION

    correct = _direct_guarded_alembic(url, E6_REVISION, "upgrade", E9A_REVISION)
    assert correct.returncode == 0 and _revision(e6_db[1]) == E9A_REVISION
    assert _locks_released(e6_db[1]) and _advisory_lock_objects(e6_db[1]) == []

    again = _alembic(url, "upgrade", E10_REVISION)                   # an ordinary command still works afterwards
    assert again.returncode == 0 and _revision(e6_db[1]) == E10_REVISION


# ---- Alembic error redaction ----------------------------------------------------------------------------------------

def test_a_failing_alembic_upgrade_never_echoes_connection_details(guarded: _Guarded, e6_db: Tuple[str, Engine]) -> None:
    result = guarded.run((E9A_REVISION, e6_db[0]), e6_db[0], e6_db[1], env={"STUB_FAIL_UPGRADE": "leak"})

    combined = result.stdout + result.stderr
    assert result.returncode == 12 and "alembic upgrade failed (exit 1): a connection failure" in result.stderr
    for secret in ("leakhost", "leakuser", "leakpw", "leakdb", "postgresql://"):
        assert secret not in combined


def test_the_runbooks_reference_only_existing_executable_tools_and_no_hand_typed_receipt() -> None:
    operations = API_DIR.parents[1] / "docs" / "operations"
    for script in ("run_guarded_migration.sh", "verify_backup_restore.sh", "run_readonly_check.sh"):
        assert os.access(SQL_DIR / script, os.X_OK), script
    for module in ("backup_evidence.py", "hold_migration_lock.py"):
        assert (SQL_DIR / module).is_file(), module
    for script in ("run_guarded_migration.sh", "verify_backup_restore.sh"):
        assert subprocess.run(["bash", "-n", str(SQL_DIR / script)]).returncode == 0
    text = "".join(path.read_text() for path in (operations / "e9a-production-migration.md", operations / "e10-production-migration.md"))
    assert "verify_backup_restore.sh" in text and "RESTORE_VERIFIED=PASS" not in text and "cat > \"$RECEIPT\"" not in text


def test_the_guarded_runner_source_orders_every_guard_before_the_upgrade() -> None:
    source = GUARDED.read_text()
    upgrade = source.index('alembic upgrade "$TARGET"')

    for marker in ("1b. backup evidence", "endpoint proof", "alembic current", "run_readonly_check.sh\" \"$PREFLIGHT\"",
                   "2b. serialize concurrent runs", "4b. repeat the identity"):
        assert source.index(marker) < upgrade, marker
    assert "set -x" not in source and "upgrade head" not in source and "--force" not in source
    assert source.count('"$PY" -m alembic upgrade') == 1  # the single invocation
    assert os.access(GUARDED, os.X_OK) and source.startswith("#!/usr/bin/env bash")


# ------------------------------------------------------------------
# Gate H stage 1b: the read-only Cron runtime connection and schema check
# ------------------------------------------------------------------


def _cron_runtime_check_command() -> str:
    document = (SQL_DIR.parent / "financial-rules-production-release.md").read_text()
    start = document.index("python -c 'import sys; from sqlalchemy")
    end = document.index("\n", start)
    return document[start:end].replace("python -c", f'"{os.sys.executable}" -c', 1)


def _run_cron_runtime_check(database_url: str) -> subprocess.CompletedProcess:
    environment = {key: value for key, value in os.environ.items() if key != "DATABASE_URL"}
    environment["DATABASE_URL"] = database_url
    return subprocess.run(["sh", "-c", _cron_runtime_check_command()], cwd=str(API_DIR), env=environment,
                          capture_output=True, text=True, timeout=90)


def test_the_cron_runtime_check_passes_on_a_fully_migrated_database_and_writes_nothing(
    e10_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e10_db
    before = _database_fingerprint(name, database_engine)

    result = _run_cron_runtime_check(_url_of(database_engine).render_as_string(hide_password=False))

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "('c4d8a2f6e193', 1, True, True, 'on', True, True)" in result.stdout
    assert "postgresql://" not in result.stdout + result.stderr
    assert _database_fingerprint(name, database_engine) == before


@pytest.mark.parametrize("fixture_name", ["e9a_db", "e6_db"])
def test_the_cron_runtime_check_fails_when_the_schema_is_not_fully_migrated(
    request: pytest.FixtureRequest, fixture_name: str,
) -> None:
    name, database_engine = request.getfixturevalue(fixture_name)

    result = _run_cron_runtime_check(_url_of(database_engine).render_as_string(hide_password=False))

    assert result.returncode != 0 and "('c4d8a2f6e193', 1, True, True, 'on', True, True)" not in result.stdout


def test_the_cron_runtime_check_fails_without_a_reachable_database(e10_db: Tuple[str, Engine]) -> None:
    url = _url_of(e10_db[1]).set(port=1).render_as_string(hide_password=False)

    result = _run_cron_runtime_check(url)

    assert result.returncode != 0 and "c4d8a2f6e193" not in result.stdout


def test_the_cron_runtime_check_fails_when_the_connecting_role_lacks_access(
    roles: Dict[str, str], e10_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e10_db
    _execute(database_engine, f"ALTER ROLE \"{roles['viewer']}\" LOGIN PASSWORD 'viewer-pw'",
             f'GRANT SELECT ON alembic_version TO "{roles["viewer"]}"')
    url = _url_of(database_engine).set(username=roles["viewer"], password="viewer-pw")

    result = _run_cron_runtime_check(url.render_as_string(hide_password=False))

    assert result.returncode != 0 and "c4d8a2f6e193', 1, True, True, 'on', True, True" not in result.stdout


@pytest.mark.parametrize("granted", ["SELECT", "SELECT, INSERT", "SELECT, INSERT, UPDATE"])
def test_the_cron_runtime_check_needs_every_table_privilege_not_just_any_of_them(
    roles: Dict[str, str], e10_db: Tuple[str, Engine], granted: str,
) -> None:
    name, database_engine = e10_db
    _execute(database_engine, f"ALTER ROLE \"{roles['viewer']}\" LOGIN PASSWORD 'viewer-pw'",
             f'GRANT SELECT ON alembic_version TO "{roles["viewer"]}"',
             f'GRANT {granted} ON alert_dispatch_progress TO "{roles["viewer"]}"',
             f'GRANT USAGE ON SEQUENCE alert_dispatch_service_seq TO "{roles["viewer"]}"')
    url = _url_of(database_engine).set(username=roles["viewer"], password="viewer-pw")

    result = _run_cron_runtime_check(url.render_as_string(hide_password=False))

    assert result.returncode != 0 and "'on', True, True)" not in result.stdout


def test_the_cron_runtime_check_passes_for_a_role_with_all_four_privileges_and_sequence_usage(
    roles: Dict[str, str], e10_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e10_db
    _execute(database_engine, f"ALTER ROLE \"{roles['viewer']}\" LOGIN PASSWORD 'viewer-pw'",
             f'GRANT SELECT ON alembic_version TO "{roles["viewer"]}"',
             f'GRANT SELECT, INSERT, UPDATE, DELETE ON alert_dispatch_progress TO "{roles["viewer"]}"',
             f'GRANT USAGE ON SEQUENCE alert_dispatch_service_seq TO "{roles["viewer"]}"')
    url = _url_of(database_engine).set(username=roles["viewer"], password="viewer-pw")

    result = _run_cron_runtime_check(url.render_as_string(hide_password=False))

    assert result.returncode == 0, (result.stdout, result.stderr)


def test_a_disabled_dispatcher_run_never_opens_a_database_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Why Gate H stage 1 cannot prove connectivity: the disabled path returns before any session factory call."""
    from app.modules.financial_rules import dispatcher

    def must_not_be_called():
        raise AssertionError("a database session was opened")

    summary = dispatcher.run_once(dispatcher.DispatcherConfig(enabled=False), session_factory=must_not_be_called)

    assert summary.outcome == "disabled"


# ------------------------------------------------------------------
# The documented migration command (exact revision, bounded lock wait)
# ------------------------------------------------------------------


def _alembic_with_lock_timeout(url, *args: str) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    environment["DATABASE_URL"] = url.render_as_string(hide_password=False)
    environment["PGOPTIONS"] = "-c lock_timeout=500"
    return subprocess.run([os.sys.executable, "-m", "alembic", *args], cwd=str(API_DIR), env=environment,
                          capture_output=True, text=True, timeout=120)


def test_the_e9a_upgrade_fails_fast_and_cleanly_when_financial_rules_is_busy(e6_db: Tuple[str, Engine]) -> None:
    name, database_engine = e6_db
    holder = database_engine.connect()
    try:
        holder.execute(text("BEGIN"))
        holder.execute(text("LOCK TABLE financial_rules IN ROW EXCLUSIVE MODE"))

        result = _alembic_with_lock_timeout(_url_of(database_engine), "upgrade", E9A_REVISION)
    finally:
        holder.rollback()
        holder.close()

    assert result.returncode != 0 and "lock timeout" in (result.stderr + result.stdout).lower()
    assert _revision(database_engine) == E6_REVISION  # nothing committed
    assert _run_sql(name, "e9a_preflight")["rule_alerts_absent"][0] == "OK"  # and the preflight still passes


def test_the_exact_revision_upgrade_with_the_documented_lock_timeout_succeeds_when_idle(
    e6_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e6_db

    first = _alembic_with_lock_timeout(_url_of(database_engine), "upgrade", E9A_REVISION)
    assert first.returncode == 0, first.stderr
    assert _revision(database_engine) == E9A_REVISION  # exact revision, not head
    assert _verdict(_run_sql(name, "e9a_postcheck")) == "PASS"

    second = _alembic_with_lock_timeout(_url_of(database_engine), "upgrade", E10_REVISION)
    assert second.returncode == 0, second.stderr
    assert _verdict(_run_sql(name, "e10_postcheck")) == "PASS"


# ------------------------------------------------------------------
# Repository invariants
# ------------------------------------------------------------------


def test_alembic_stays_single_headed_with_the_expected_chain() -> None:
    script = ScriptDirectory.from_config(Config(str(API_DIR / "alembic.ini")))

    assert script.get_heads() == [E10_REVISION]
    assert script.get_revision(E10_REVISION).down_revision == E9A_REVISION
    assert script.get_revision(E9A_REVISION).down_revision == E6_REVISION
