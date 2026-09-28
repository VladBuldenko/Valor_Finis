import importlib.util
import inspect
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.db.database_session import engine

_API_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI_PATH = _API_ROOT / "alembic.ini"
_MIGRATION_PATH = (
    _API_ROOT / "alembic" / "versions" / "1edb74dc96d8_add_account_transfers.py"
)

_DATA_API_ROLES = ("anon", "authenticated", "service_role")


def _load_migration_module():
    # Loaded by file path for the same reason as
    # tests/unit/core/test_supabase_data_api_hardening_migration.py: the
    # local alembic/versions/ directory is not an importable subpackage of
    # the installed "alembic" package.
    spec = importlib.util.spec_from_file_location(
        "vf_018b_migration_1edb74dc96d8", _MIGRATION_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration_module()


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(_ALEMBIC_INI_PATH)))


# Returns a function's source without its docstring, so assertions about
# executable statements are never tripped by explanatory prose.
def _body_without_docstring(function) -> str:
    return inspect.getsource(function).split('"""', 2)[-1]


# Tests that the VF-018B migration chains onto 7dd404d0d20e (VF-017E, the
# head when it was written) and stays part of the single head's ancestry.
# Structural only - reads the revision graph, never the live database -
# for the same reason as the VF-SEC-01 migration test: the upgrade/
# downgrade round trip is verified via the Alembic CLI against a
# disposable database, not by flipping the shared pytest schema.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the chain is linear and includes this revision.
def test_migration_chains_onto_7dd404d0d20e_and_stays_in_head_ancestry() -> None:
    assert migration.revision == "1edb74dc96d8"
    assert migration.down_revision == "7dd404d0d20e"

    script = _script_directory()
    heads = script.get_heads()
    assert len(heads) == 1

    ancestor_revisions = {
        revision.revision
        for revision in script.walk_revisions(base="base", head=heads[0])
    }
    assert "1edb74dc96d8" in ancestor_revisions
    assert "edcfdf3f7114" in ancestor_revisions


# Tests that upgrade() explicitly revokes every privilege on the new
# account_transfers table from all three Supabase Data API roles, names the
# table explicitly (never a schema-wide statement), and guards every role
# statement with a pg_roles existence check so it is a no-op on local/CI
# PostgreSQL where those roles do not exist.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the guarded, table-specific REVOKE is present.
def test_migration_revokes_data_api_privileges_on_account_transfers() -> None:
    upgrade_source = inspect.getsource(migration.upgrade)

    assert migration.ACCOUNT_TRANSFERS_TABLE_SQL == "public.account_transfers"
    assert (
        "REVOKE ALL PRIVILEGES ON TABLE {ACCOUNT_TRANSFERS_TABLE_SQL} FROM %I"
        in upgrade_source
    )
    assert "SELECT 1 FROM pg_roles WHERE rolname = target_role" in upgrade_source
    assert "DATA_API_ROLES_ARRAY_SQL" in upgrade_source
    for role in _DATA_API_ROLES:
        assert f"'{role}'" in migration.DATA_API_ROLES_ARRAY_SQL


# Tests that neither upgrade() nor downgrade() ever uses the blanket
# "ALL TABLES IN SCHEMA public" form, and that downgrade() never grants
# anything back - a downgrade must never reopen Data API access.
# Parameters:
# - None.
# Returns:
# - None. The test passes if no schema-wide statement and no GRANT exist.
def test_migration_never_widens_privileges() -> None:
    upgrade_body = _body_without_docstring(migration.upgrade)
    downgrade_body = _body_without_docstring(migration.downgrade)

    assert "ALL TABLES IN SCHEMA" not in upgrade_body
    assert "ALL TABLES IN SCHEMA" not in downgrade_body
    assert "GRANT" not in upgrade_body
    assert "GRANT" not in downgrade_body


# Tests that downgrade() deletes only kind='transfer' ledger rows, and does
# so before narrowing the kind CHECK back - otherwise the downgrade would
# fail on existing transfer rows, and income/expense/direct rows must never
# be touched.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the targeted DELETE precedes the CHECK
#   restoration.
def test_migration_downgrade_deletes_only_transfer_rows_first() -> None:
    downgrade_body = _body_without_docstring(migration.downgrade)

    delete_statement = "DELETE FROM account_transactions WHERE kind = 'transfer'"
    assert delete_statement in downgrade_body
    assert downgrade_body.count("DELETE FROM") == 1
    assert downgrade_body.index(delete_statement) < downgrade_body.index(
        "_KIND_VALID_WITHOUT_TRANSFER_SQL"
    )
    assert "'transfer'" not in migration._KIND_VALID_WITHOUT_TRANSFER_SQL
    assert "transfer_id" not in migration._SOURCE_LINKAGE_WITHOUT_TRANSFER_SQL


# Tests, against the live test database, that none of the Supabase Data
# API roles present on this cluster has any privilege on account_transfers.
# On local/CI PostgreSQL none of these roles exist, so there is nothing to
# check and the test passes trivially - the migration applying cleanly
# there already proves the pg_roles guard works when the roles are absent.
# On a cluster that does define them, this asserts the REVOKE took effect.
# Parameters:
# - None.
# Returns:
# - None. The test passes if no existing Data API role has a privilege.
def test_existing_data_api_roles_have_no_privileges_on_account_transfers() -> None:
    with engine.connect() as connection:
        existing_roles = [
            row[0]
            for row in connection.execute(
                text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles)"),
                {"roles": list(_DATA_API_ROLES)},
            )
        ]

        for role in existing_roles:
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                has_privilege = connection.execute(
                    text(
                        "SELECT has_table_privilege("
                        ":role, 'public.account_transfers', :privilege)"
                    ),
                    {"role": role, "privilege": privilege},
                ).scalar()
                assert has_privilege is False, (role, privilege)
