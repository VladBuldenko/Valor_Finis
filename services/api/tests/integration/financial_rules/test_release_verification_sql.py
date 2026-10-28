import hashlib
import os
import re
import subprocess
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
_evidence_counter = [0]


def _utc(seconds_ago: float) -> str:
    return datetime.fromtimestamp(time.time() - seconds_ago, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _make_evidence(directory: Path, dump_database: str, target: str, expected_db: str,
                   taken_ago: float = 600, verified_ago: float = 300, **overrides: Optional[str]) -> Path:
    """A real logical dump of a disposable test database plus a receipt in the documented format."""
    _evidence_counter[0] += 1
    dump = directory / f"dump-{_evidence_counter[0]}.dump"
    subprocess.run(["pg_dump", "--format=custom", "--schema=public", f"--file={dump}"],
                   env=_libpq_env(dump_database), check=True, capture_output=True, timeout=120)
    dump.chmod(0o600)
    fields: Dict[str, Optional[str]] = {
        "GATE_TARGET": target, "DATABASE": expected_db, "SOURCE_REVISION": _PARENT_OF[target],
        "DUMP_FILE": str(dump), "DUMP_SHA256": hashlib.sha256(dump.read_bytes()).hexdigest(),
        "DUMP_TAKEN_AT_UTC": _utc(taken_ago), "RESTORE_VERIFIED": "PASS",
        "RESTORE_DATABASE": "vf_restore_verify_test", "RESTORE_PREFLIGHT": "PASS",
        "RESTORE_VERIFIED_AT_UTC": _utc(verified_ago),
    }
    fields.update(overrides)
    receipt = directory / f"receipt-{_evidence_counter[0]}.env"
    receipt.write_text("".join(f"{key}={value}\n" for key, value in fields.items() if value is not None))
    receipt.chmod(0o600)
    return receipt


class _Guarded:
    def __init__(self, tmp_path: Path) -> None:
        self.log = tmp_path / "python-calls.log"
        self.stub = tmp_path / "stub-python.sh"
        self.stub.write_text(
            "#!/bin/sh\n"
            'echo "$@" >> "$STUB_LOG"\n'
            'if [ -n "$STUB_FAIL_UPGRADE" ]; then case "$*" in *"alembic upgrade"*) exit 1;; esac; fi\n'
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

    def run(self, args: Tuple[str, ...], pg_database: str, url_engine: Optional[Engine],
            env: Optional[Dict[str, Optional[str]]] = None, evidence: Optional[Dict[str, Optional[str]]] = None,
            evidence_dump_from: Optional[str] = None) -> subprocess.CompletedProcess:
        environment = _libpq_env(pg_database)
        environment.update({"MIGRATION_PYTHON": str(self.stub), "STUB_LOG": str(self.log),
                            "STUB_COUNTS": str(self.log.parent / "stub-count"), "REQUIRE_DATA_API_ROLES": "no"})
        if len(args) == 2 and args[0] in (E9A_REVISION, E10_REVISION):
            environment["BACKUP_EVIDENCE_FILE"] = str(
                _make_evidence(self.log.parent, evidence_dump_from or pg_database, args[0], args[1],
                               **(evidence or {})))
        if url_engine is not None:
            environment["DATABASE_URL"] = _url_of(url_engine).render_as_string(hide_password=False)
        for key, value in (env or {}).items():
            if value is None:
                environment.pop(key, None)
            else:
                environment[key] = value
        return subprocess.run([str(GUARDED), *args], env=environment, capture_output=True, text=True,
                              timeout=240, stdin=subprocess.DEVNULL)

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


@pytest.mark.parametrize("fixture_name,target", [
    ("e9a_db", E9A_REVISION),   # the target is already applied
    ("e10_db", E9A_REVISION),   # the database is ahead of the target
    ("e6_db", E10_REVISION),    # the parent of the target is missing
])
def test_an_unexpected_current_revision_stops_before_any_migration(
    request: pytest.FixtureRequest, guarded: _Guarded, fixture_name: str, target: str,
) -> None:
    db = request.getfixturevalue(fixture_name)
    before, revisions = _snapshot([db])
    # Give the receipt a valid dump (one that lists rule_alerts for gate F) so that the revision guard is what stops the run.
    dump_from = request.getfixturevalue("e9a_db")[0] if target == E10_REVISION else db[0]

    result = guarded.run((target, db[0]), db[0], db[1], evidence_dump_from=dump_from)

    _assert_stopped_before_any_migration(result, guarded, [db], before, revisions)
    assert "alembic current" in result.stderr


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
                         env={"BACKUP_EVIDENCE_FILE": str(guarded.log.parent / "no-such-receipt.env")})

    _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)
    assert "backup evidence rejected" in result.stderr


@pytest.mark.parametrize("overrides,expected", [
    ({"GATE_TARGET": E10_REVISION}, "not bound"),
    ({"DATABASE": "some_other_db"}, "not bound"),
    ({"SOURCE_REVISION": E9A_REVISION}, "not bound"),                          # e.g. the wrong gate's receipt
    ({"RESTORE_VERIFIED": "FAIL"}, "PASSed restore"),
    ({"RESTORE_PREFLIGHT": "FAIL"}, "PASSed restore"),
    ({"RESTORE_VERIFIED": None}, "exactly the required fields"),
    ({"RESTORE_DATABASE": "production_db"}, "*_test"),                          # restore not on a throwaway database
    ({"DUMP_SHA256": "0" * 64}, "SHA-256"),
    ({"DUMP_FILE": "relative.dump"}, "absolute"),
    ({"DUMP_FILE": "/nonexistent/missing.dump"}, "missing or unreadable"),
    ({"DUMP_TAKEN_AT_UTC": "not-a-time"}, "UTC timestamp"),
    ({"DUMP_TAKEN_AT_UTC": "STALE", "RESTORE_VERIFIED_AT_UTC": "STALE"}, "older than 24 hours"),
    ({"DUMP_TAKEN_AT_UTC": "FUTURE", "RESTORE_VERIFIED_AT_UTC": "FUTURE"}, "inconsistent"),
    ({"RESTORE_VERIFIED_AT_UTC": "BEFORE_DUMP"}, "inconsistent"),
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
    receipt = _make_evidence(guarded.log.parent, name, E9A_REVISION, name, **resolved)

    result = guarded.run((E9A_REVISION, name), name, database_engine, env={"BACKUP_EVIDENCE_FILE": str(receipt)})

    _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)
    assert expected in result.stderr, result.stderr


def test_a_duplicated_receipt_field_stops_before_any_migration(guarded: _Guarded, e6_db: Tuple[str, Engine]) -> None:
    name, database_engine = e6_db
    before, revisions = _snapshot([e6_db])
    receipt = _make_evidence(guarded.log.parent, name, E9A_REVISION, name)
    receipt.write_text(receipt.read_text() + "RESTORE_VERIFIED=PASS\n")

    result = guarded.run((E9A_REVISION, name), name, database_engine, env={"BACKUP_EVIDENCE_FILE": str(receipt)})

    _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)


def test_a_dump_changed_after_its_checksum_was_recorded_stops_before_any_migration(
    guarded: _Guarded, e6_db: Tuple[str, Engine],
) -> None:
    name, database_engine = e6_db
    before, revisions = _snapshot([e6_db])
    receipt = _make_evidence(guarded.log.parent, name, E9A_REVISION, name)
    dump = Path(dict(line.split("=", 1) for line in receipt.read_text().splitlines())["DUMP_FILE"])
    with open(dump, "ab") as handle:
        handle.write(b"tampered")

    result = guarded.run((E9A_REVISION, name), name, database_engine, env={"BACKUP_EVIDENCE_FILE": str(receipt)})

    _assert_stopped_before_any_migration(result, guarded, [e6_db], before, revisions)
    assert "SHA-256" in result.stderr


def test_a_dump_that_lacks_a_required_table_stops_before_any_migration(
    guarded: _Guarded, e6_db: Tuple[str, Engine], e9a_db: Tuple[str, Engine],
) -> None:
    # Gate F on the E9A database, but the "backup" was taken from an E6 database: it has no rule_alerts.
    before, revisions = _snapshot([e9a_db])

    result = guarded.run((E10_REVISION, e9a_db[0]), e9a_db[0], e9a_db[1], evidence_dump_from=e6_db[0])

    _assert_stopped_before_any_migration(result, guarded, [e9a_db], before, revisions)
    assert "required tables" in result.stderr and "rule_alerts" in result.stderr


@pytest.mark.parametrize("unsafe", ["group_writable", "symlink", "dump_world_readable"])
def test_unsafe_evidence_files_stop_before_any_migration(
    guarded: _Guarded, e6_db: Tuple[str, Engine], unsafe: str,
) -> None:
    name, database_engine = e6_db
    before, revisions = _snapshot([e6_db])
    receipt = _make_evidence(guarded.log.parent, name, E9A_REVISION, name)
    if unsafe == "group_writable":
        receipt.chmod(0o666)
    elif unsafe == "symlink":
        link = guarded.log.parent / "receipt-link.env"
        link.symlink_to(receipt)
        receipt = link
    else:
        Path(dict(line.split("=", 1) for line in receipt.read_text().splitlines())["DUMP_FILE"]).chmod(0o644)

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

        assert result.returncode == 11 and guarded.upgrade_calls() == []
        assert "alembic current" in result.stderr
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


def test_the_guarded_runner_source_orders_every_guard_before_the_upgrade() -> None:
    source = GUARDED.read_text()
    upgrade = source.index('alembic upgrade "$TARGET"')

    for marker in ("1b. backup evidence", "endpoint proof", "alembic current", "run_readonly_check.sh\" \"$PREFLIGHT\"",
                   "4b. repeat the identity"):
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
