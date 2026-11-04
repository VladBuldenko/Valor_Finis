"""
Operator checks for staging (docs/operations/staging/sql) against a REAL disposable PostgreSQL.

Proves the distinction the runbook depends on:
  A. application database security checks run and gate on a database without Supabase roles;
  B. a PASS never claims Supabase Data API parity, and the unchanged production runner still
     refuses or stops where it must (absent roles are never converted into a PASS).
These run the real shell scripts and the real psql binary; nothing is mocked.
"""

import os
import subprocess
from pathlib import Path

import pytest

from staging_ops.bootstrap import bootstrap
from staging_ops.operations import real_operations

from .helpers import SpyOperations, approved_for, environ_for, execute

REPO = Path(__file__).resolve().parents[5]
STAGING_RUNNER = REPO / "docs" / "operations" / "staging" / "sql" / "run_staging_check.sh"
PRODUCTION_RUNNER = REPO / "docs" / "operations" / "sql" / "run_readonly_check.sh"
PARITY_LINE = "DATA_API_PARITY: NOT VERIFIED"


def head():
    return real_operations().repository_heads()[0]


def run(runner, pg_bin, cluster, check, database, user="vf_app", **overrides):
    env = {
        "PATH": f"{pg_bin}:/usr/bin:/bin",
        "HOME": os.environ.get("HOME", "/tmp"),
        "PGHOST": cluster.host,
        "PGPORT": str(cluster.port),
        "PGUSER": user,
        "PGDATABASE": database,
        "PGSSLMODE": "disable",
        "ALLOW_INSECURE_LOCAL_TEST": "1",
        "EXPECTED_ALEMBIC_REVISION": head(),
    }

    for name, value in overrides.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value

    completed = subprocess.run(["bash", str(runner), check, database], env=env, capture_output=True, text=True, timeout=120)

    return completed.returncode, completed.stdout + completed.stderr


STAND_IN_ROLES = "DROP ROLE IF EXISTS anon, authenticated, service_role"


@pytest.fixture
def staging_db(local_cluster, pg_bin):
    # Roles are cluster-global: a stand-in role created by one test must never leak into another.
    execute(local_cluster, "postgres", STAND_IN_ROLES)
    name, oid = local_cluster.create_database()
    bootstrap("staging", "STG-1", environ_for(local_cluster, name), approved_for(local_cluster, name, oid), SpyOperations().operations(), None, lambda _t: None)
    execute(local_cluster, "postgres", "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vf_app') THEN CREATE ROLE vf_app LOGIN; END IF; END $$")
    execute(
        local_cluster, name,
        "GRANT USAGE ON SCHEMA public TO vf_app",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO vf_app",
        "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO vf_app",
        "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
    )

    yield name

    execute(local_cluster, "postgres", STAND_IN_ROLES)


class TestApplicationDatabaseSecurity:
    def test_a_correct_database_passes_and_never_claims_data_api_parity(self, local_cluster, pg_bin, staging_db):
        code, output = run(STAGING_RUNNER, pg_bin, local_cluster, "app_database_security", staging_db)

        assert code == 0, output
        assert "RESULT: PASS (app_database_security)" in output
        assert PARITY_LINE in output
        assert "alembic_revision_equals_expected" in output

    def test_empty_stand_in_data_api_roles_do_not_turn_into_parity(self, local_cluster, pg_bin, staging_db):
        execute(local_cluster, "postgres", "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF; IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF; IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN CREATE ROLE service_role NOLOGIN; END IF; END $$")
        code, output = run(STAGING_RUNNER, pg_bin, local_cluster, "app_database_security", staging_db)

        assert code == 0, output
        assert "3 of 3 (this check does not establish Data API parity)" in output and PARITY_LINE in output

    @pytest.mark.parametrize(
        "damage, failing",
        [
            ("GRANT SELECT ON accounts TO PUBLIC", "no_public_privileges_on_application_tables_or_sequences"),
            ("GRANT CREATE ON SCHEMA public TO PUBLIC", "public_cannot_create_in_schema_public"),
            ("REVOKE DELETE ON goals FROM vf_app", "application_role_can_use_every_application_table"),
            ("UPDATE alembic_version SET version_num = 'ffffffffffff'", "alembic_revision_equals_expected"),
        ],
    )
    def test_each_gating_check_can_fail(self, local_cluster, pg_bin, staging_db, damage, failing):
        execute(local_cluster, staging_db, damage)
        code, output = run(STAGING_RUNNER, pg_bin, local_cluster, "app_database_security", staging_db)

        assert code == 10 and "RESULT: STOP" in output, output
        assert any(line.startswith(f" {failing}") and "| FAIL" in line for line in output.splitlines()), output
        assert PARITY_LINE in output

    def test_a_superuser_application_role_stops(self, local_cluster, pg_bin, staging_db):
        code, output = run(STAGING_RUNNER, pg_bin, local_cluster, "app_database_security", staging_db, user="postgres")

        assert code == 10 and "application_role_is_not_superuser" in output

    def test_a_wrong_revision_expectation_stops(self, local_cluster, pg_bin, staging_db):
        code, output = run(STAGING_RUNNER, pg_bin, local_cluster, "app_database_security", staging_db, EXPECTED_ALEMBIC_REVISION="000000000000")

        assert code == 10 and "alembic_revision_equals_expected" in output

    def test_the_session_is_read_only(self, local_cluster, pg_bin, staging_db):
        before = (Path(STAGING_RUNNER).read_text(), STAGING_RUNNER.with_name("app_database_security.sql").read_text())

        assert "BEGIN READ ONLY;" in before[1] and before[1].rstrip().endswith("ROLLBACK;")
        assert "default_transaction_read_only=on" in before[0]


class TestRunnerRefusals:
    @pytest.mark.parametrize(
        "overrides, fragment",
        [
            ({"PGHOST": "db.example.test", "PGSSLMODE": "require"}, "verify-full"),
            ({"PGHOST": "db.example.test", "PGSSLMODE": None}, "verify-full"),
            ({"DATABASE_URL": "postgresql://x@y/z"}, "DATABASE_URL"),
            ({"PGSERVICE": "svc"}, "PGSERVICE"),
            ({"PGHOSTADDR": "192.0.2.1"}, "PGHOSTADDR"),
            ({"EXPECTED_ALEMBIC_REVISION": None}, "EXPECTED_ALEMBIC_REVISION"),
            ({"EXPECTED_ALEMBIC_REVISION": "not-a-revision"}, "EXPECTED_ALEMBIC_REVISION"),
            ({"PGSSLMODE": "disable", "ALLOW_INSECURE_LOCAL_TEST": None}, "PGSSLMODE"),
        ],
    )
    def test_unsafe_environments_are_refused_before_any_connection(self, local_cluster, pg_bin, staging_db, overrides, fragment):
        code, output = run(STAGING_RUNNER, pg_bin, local_cluster, "app_database_security", staging_db, **overrides)

        assert code == 64 and "REFUSED" in output and fragment in output, output

    def test_a_non_staging_database_name_is_refused(self, local_cluster, pg_bin):
        code, output = run(STAGING_RUNNER, pg_bin, local_cluster, "app_database_security", "postgres")

        assert code == 64 and "_staging" in output

    def test_unknown_checks_and_mismatched_database_are_refused(self, local_cluster, pg_bin, staging_db):
        assert run(STAGING_RUNNER, pg_bin, local_cluster, "e10_postcheck", staging_db)[0] == 64
        assert run(STAGING_RUNNER, pg_bin, local_cluster, "app_database_security", staging_db, PGDATABASE="other_staging")[0] == 64


class TestSupabaseProjectExposure:
    @pytest.fixture
    def project_db(self, local_cluster):
        name = f"vfqa1_supabase_like_{os.getpid()}"
        execute(local_cluster, "postgres", f'DROP DATABASE IF EXISTS "{name}"', f'CREATE DATABASE "{name}"')

        return name

    def test_a_project_database_without_application_relations_passes_but_is_not_parity(self, local_cluster, pg_bin, project_db):
        code, output = run(STAGING_RUNNER, pg_bin, local_cluster, "supabase_project_exposure", project_db, user="postgres")

        assert code == 0, output
        assert "no_application_relations_in_public" in output and PARITY_LINE in output

    @pytest.mark.parametrize("statement, failing", [
        ("CREATE TABLE public.accounts (id int)", "no_application_relations_in_public"),
        ("CREATE VIEW public.v AS SELECT 1 AS x", "no_application_relations_in_public"),
        ("CREATE FUNCTION public.f() RETURNS int LANGUAGE sql AS 'select 1'", "no_application_functions_in_public"),
        ("CREATE TABLE public.alembic_version (version_num text)", "no_alembic_version_table"),
    ])
    def test_application_objects_in_the_project_database_stop(self, local_cluster, pg_bin, project_db, statement, failing):
        execute(local_cluster, project_db, statement)
        code, output = run(STAGING_RUNNER, pg_bin, local_cluster, "supabase_project_exposure", project_db, user="postgres")

        assert code == 10 and any(line.startswith(f" {failing}") and "| FAIL" in line for line in output.splitlines()), output

    def test_it_refuses_an_application_database(self, local_cluster, pg_bin, staging_db):
        assert run(STAGING_RUNNER, pg_bin, local_cluster, "supabase_project_exposure", staging_db)[0] == 64


class TestTheProductionRunnerStaysStrictAndIsNotUsableOnAnApplicationOnlyDatabase:
    """Why runbook step R6 was wrong: the unchanged production runner cannot yield a PASS here."""

    def test_without_the_supabase_roles_it_stops_instead_of_passing(self, local_cluster, pg_bin, staging_db):
        code, output = run(PRODUCTION_RUNNER, pg_bin, local_cluster, "e10_postcheck", staging_db, EXPECTED_ALEMBIC_REVISION=None, APP_ROLE="vf_app")

        assert code == 10 and "RESULT: STOP" in output
        assert any(line.startswith(" data_api_roles_resolved") and "| FAIL" in line for line in output.splitlines()), output

    def test_weakening_it_is_refused_for_a_staging_named_database(self, local_cluster, pg_bin, staging_db):
        code, output = run(PRODUCTION_RUNNER, pg_bin, local_cluster, "e10_postcheck", staging_db, REQUIRE_DATA_API_ROLES="no", EXPECTED_ALEMBIC_REVISION=None)

        assert code == 64 and "_test" in output

    def test_weakening_it_is_refused_for_a_remote_host(self, local_cluster, pg_bin, staging_db):
        code, output = run(PRODUCTION_RUNNER, pg_bin, local_cluster, "e10_postcheck", staging_db, PGHOST="db.example.test", PGSSLMODE="require", REQUIRE_DATA_API_ROLES="no", EXPECTED_ALEMBIC_REVISION=None)

        assert code == 64 and "only for a local database" in output

    def test_stand_in_roles_would_make_it_pass_vacuously_which_is_why_they_are_forbidden(self, local_cluster, pg_bin, staging_db):
        """Negative control documenting the hazard: with empty stand-in roles the roles check goes green."""

        execute(local_cluster, "postgres", "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF; IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF; IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN CREATE ROLE service_role NOLOGIN; END IF; END $$")
        code, output = run(PRODUCTION_RUNNER, pg_bin, local_cluster, "e10_postcheck", staging_db, EXPECTED_ALEMBIC_REVISION=None, APP_ROLE="vf_app")
        roles_line = [line for line in output.splitlines() if line.startswith(" data_api_roles_resolved")]

        assert roles_line and "| OK" in roles_line[0], "the hazard this test documents: stand-in roles turn the roles check green"
        assert "no_effective_data_api_access" in output  # vacuous: the stand-in roles hold nothing
