import importlib.util
import inspect
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_API_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI_PATH = _API_ROOT / "alembic.ini"
_MIGRATION_PATH = (
    _API_ROOT / "alembic" / "versions"
    / "edcfdf3f7114_harden_supabase_data_api_privileges.py"
)


def _load_migration_module():
    # The local alembic/versions/ directory has no __init__.py, and
    # "alembic" itself is a real installed third-party package (the
    # migration tool) - a normal "from alembic.versions import ..."
    # import would resolve against that installed package instead of
    # this project's own versions/ directory (which isn't a subpackage
    # of it at all) and fail. Loading the file directly by path sidesteps
    # that name collision entirely.
    spec = importlib.util.spec_from_file_location(
        "vf_sec_01_migration_edcfdf3f7114", _MIGRATION_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration_module()

_DATA_API_ROLES = ("anon", "authenticated", "service_role")

_APPLICATION_TABLES = (
    "public.categories", "public.expenses", "public.budgets",
    "public.budget_versions", "public.goals", "public.goal_transactions",
    "public.accounts", "public.account_transactions", "public.income",
    "public.receipts", "public.user_financial_settings",
    "public.alembic_version",
)


def _script_directory() -> ScriptDirectory:
    config = Config(str(_ALEMBIC_INI_PATH))
    return ScriptDirectory.from_config(config)


# Tests that exactly one Alembic head exists after the VF-SEC-01
# migration, and that it is this migration's own revision.
# This exists as a lightweight, non-DB-mutating structural check - it
# reads the versions/ directory's revision graph, not the live database
# - unlike A/B/C below (upgrade/downgrade/re-upgrade against a real
# database), which this codebase's own convention (see
# test_goal_current_amount_migration.py's module docstring) verifies via
# the Alembic CLI against a disposable database rather than by flipping
# the shared pytest database's live schema mid-suite, since a failure
# partway through a live upgrade/downgrade call inside the test run
# would corrupt the schema for every other test that runs afterward.
# Parameters:
# - None.
# Returns:
# - None. The test passes if there is exactly one head and it matches
#   this migration's revision id.
def test_exactly_one_alembic_head_after_vf_sec_01_migration() -> None:
    script = _script_directory()
    heads = script.get_heads()

    assert len(heads) == 1
    assert heads[0] == "edcfdf3f7114"


# Tests that the migration's down_revision correctly chains onto
# 811506d8afd2 (VF-017D's head at the time this migration was written),
# so this migration is the sole, unambiguous next step in the chain.
# Parameters:
# - None.
# Returns:
# - None. The test passes if down_revision matches exactly.
def test_migration_chains_onto_811506d8afd2() -> None:
    assert migration.down_revision == "811506d8afd2"
    assert migration.revision == "edcfdf3f7114"


# Tests that neither upgrade() nor downgrade() ever uses the blanket
# "ALL TABLES IN SCHEMA public" form.
# This is the single most important structural safety property this
# migration must have: it must only ever name the 12 explicit
# application-owned tables, never every table in the public schema,
# so a future, unrelated object added to public by something other than
# this Alembic chain is never accidentally touched by this migration.
# Parameters:
# - None.
# Returns:
# - None. The test passes if neither function's source contains the
#   blanket schema-wide form.
def test_migration_never_uses_blanket_schema_wide_privilege_statement() -> None:
    upgrade_source = inspect.getsource(migration.upgrade)
    downgrade_source = inspect.getsource(migration.downgrade)

    assert "ALL TABLES IN SCHEMA public" not in upgrade_source
    assert "ALL TABLES IN SCHEMA public" not in downgrade_source


# Tests that upgrade()'s table-privilege REVOKE and downgrade()'s
# table-privilege GRANT both name every one of the 12 explicit
# application tables, including alembic_version.
# Parameters:
# - None.
# Returns:
# - None. The test passes if every table name appears in both
#   functions' source (via the shared APPLICATION_TABLES_SQL constant).
def test_migration_names_every_application_table_explicitly() -> None:
    for table in _APPLICATION_TABLES:
        assert table in migration.APPLICATION_TABLES_SQL

    assert "public.alembic_version" in migration.APPLICATION_TABLES_SQL


# Tests that every statement in upgrade()/downgrade() naming a Supabase
# Data API role (anon/authenticated/service_role) is guarded by a
# pg_roles existence check, so the migration safely no-ops on local/CI
# PostgreSQL, which defines none of these roles (confirmed empirically
# against valor_test - see VF-SEC-01's discovery report).
# Parameters:
# - None.
# Returns:
# - None. The test passes if both functions' source contains the guard
#   construct and the full three-role array.
def test_migration_guards_every_data_api_role_statement() -> None:
    upgrade_source = inspect.getsource(migration.upgrade)
    downgrade_source = inspect.getsource(migration.downgrade)

    for source in (upgrade_source, downgrade_source):
        assert "pg_roles" in source
        assert "SELECT 1 FROM pg_roles WHERE rolname = target_role" in source
        for role in _DATA_API_ROLES:
            assert role in source


# Tests that downgrade() restores only SELECT/INSERT/UPDATE/DELETE on
# the application tables, never TRUNCATE/REFERENCES/TRIGGER - the
# intentional asymmetry documented in downgrade()'s own docstring: this
# is an operational rollback to a working Data API state, not a
# byte-for-byte restoration of the original overly-broad production
# ACLs.
# Parameters:
# - None.
# Returns:
# - None. The test passes if downgrade()'s table-privilege GRANT
#   statement contains none of the three excluded privilege types.
def test_migration_downgrade_does_not_restore_excess_table_privileges() -> None:
    downgrade_source = inspect.getsource(migration.downgrade)
    downgrade_body_only = downgrade_source.split('"""', 2)[-1]

    assert (
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
        "{APPLICATION_TABLES_SQL} TO %I" in downgrade_source
    )

    # Checked against the executable body only (docstring text above
    # legitimately explains, in prose, that these privileges are
    # deliberately excluded - that prose would otherwise trip a naive
    # whole-source substring check).
    assert "TRUNCATE" not in downgrade_body_only
    assert "REFERENCES" not in downgrade_body_only
    assert "TRIGGER" not in downgrade_body_only


# Tests that upgrade() revokes the default EXECUTE-on-functions grant
# from PUBLIC (the plain PostgreSQL default that would otherwise let any
# role execute a future application function), and that downgrade()
# restores it - both as unconditional statements with no pg_roles guard,
# since PUBLIC is a pseudo-role that always exists.
# Parameters:
# - None.
# Returns:
# - None. The test passes if both statements are present and neither is
#   wrapped in a pg_roles guard.
def test_migration_handles_public_function_execute_default_unconditionally() -> None:
    upgrade_source = inspect.getsource(migration.upgrade)
    downgrade_source = inspect.getsource(migration.downgrade)

    assert (
        "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC" in upgrade_source
    )
    assert (
        "GRANT EXECUTE ON FUNCTIONS TO PUBLIC" in downgrade_source
    )


# Tests that upgrade() revokes default privileges for role postgres on
# all three future-object kinds VF-SEC-01 must cover (tables, sequences,
# functions), and that downgrade() restores exactly the same three -
# closing the "October 30 / future table" gap identified during
# discovery, where a new Alembic-created table would otherwise silently
# inherit the same broad Data API access being revoked from existing
# tables here.
# Parameters:
# - None.
# Returns:
# - None. The test passes if every default-privilege object kind and
#   privilege list appears in both functions' source.
def test_migration_covers_default_privileges_for_tables_sequences_and_functions() -> None:
    upgrade_source = inspect.getsource(migration.upgrade)
    downgrade_source = inspect.getsource(migration.downgrade)

    for source in (upgrade_source, downgrade_source):
        assert "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public" in source
        assert "ON TABLES" in source
        assert "ON SEQUENCES" in source
        assert "ON FUNCTIONS" in source

    assert "SELECT, INSERT, UPDATE, DELETE ON TABLES" in upgrade_source
    assert "USAGE, SELECT, UPDATE ON SEQUENCES" in upgrade_source
    assert "EXECUTE ON FUNCTIONS" in upgrade_source
