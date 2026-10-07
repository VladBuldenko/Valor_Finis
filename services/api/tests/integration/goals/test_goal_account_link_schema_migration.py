import importlib.util
import inspect
import os
import subprocess
import sys
from pathlib import Path
from typing import Generator, Optional
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.exc import IntegrityError

from app.db.database_session import engine as application_engine
from app.modules.goals.goal_transaction_models import GoalTransactionModel
from tests.database_safety import validate_test_database_url

# VF-020C1 schema-expand tests (revision 98acdc7016d2): goal_transactions
# gains a nullable account_id with a composite Account foreign key, three
# CHECK constraints and a partial index. There is deliberately NO linked
# runtime in C1, so every test here is a schema/migration/database test.
#
# They run the REAL Alembic CLI (subprocess) against throwaway *_test
# databases (the VF-020B4 pattern): a template database is migrated once to
# the B4 revision, each test clones it, seeds pre-C1 rows with raw SQL, runs
# the migration and inspects the real database afterwards. Every database
# name ends in "_test", is validated by the project's safety guard before
# use and is dropped afterwards. The shared valor_test database is never
# migrated by these tests.

API_DIR = Path(__file__).resolve().parents[3]
B4_REVISION = "8799b7fd923d"
C1_REVISION = "98acdc7016d2"
MIGRATION_PATH = API_DIR / "alembic" / "versions" / "98acdc7016d2_expand_goal_transaction_account_link.py"

ACCOUNT_FK = "fk_goal_transactions_account_id_user_id_currency"
OPENING_CHECK = "ck_goal_transactions_opening_balance_unlinked"
KEY_CHECK = "ck_goal_transactions_linked_requires_client_request_id"
DATE_CHECK = "ck_goal_transactions_linked_requires_effective_date"
LINKED_INDEX = "ix_goal_transactions_linked_account_id"
C1_CONSTRAINTS = {ACCOUNT_FK, OPENING_CHECK, KEY_CHECK, DATE_CHECK}


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


# Runs the real Alembic CLI against one database.
# Parameters:
# - url: database to migrate (already validated as a *_test database).
# - args: Alembic arguments, e.g. ("upgrade", C1_REVISION).
# Returns:
# - The finished process (return code, stdout, stderr).
def _alembic(url: URL, *args: str) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    environment["DATABASE_URL"] = url.render_as_string(hide_password=False)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(API_DIR),
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.fixture(scope="module")
def b4_template() -> Generator[str, None, None]:
    name = f"vf020c1_tpl_{uuid4().hex[:10]}_test"
    url = _create_database(name)
    try:
        result = _alembic(url, "upgrade", B4_REVISION)
        assert result.returncode == 0, result.stderr
        yield name
    finally:
        _drop_database(name)


@pytest.fixture
def b4_database(b4_template: str) -> Generator[Engine, None, None]:
    name = f"vf020c1_{uuid4().hex[:10]}_test"
    url = _create_database(name, template=b4_template)
    database_engine = create_engine(url)
    try:
        yield database_engine
    finally:
        database_engine.dispose()
        _drop_database(name)


@pytest.fixture
def c1_database(b4_database: Engine) -> Engine:
    result = _alembic(_url_of(b4_database), "upgrade", C1_REVISION)
    assert result.returncode == 0, result.stderr
    return b4_database


def _url_of(database_engine: Engine) -> URL:
    return make_url(database_engine.url.render_as_string(hide_password=False))


def _seed_account(database_engine: Engine, user_id: UUID, currency: str = "EUR") -> UUID:
    account_id = uuid4()
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO accounts (id, user_id, name, type, currency, status) "
                "VALUES (:id, :user_id, 'Account', 'checking', :currency, 'active')"
            ),
            {"id": str(account_id), "user_id": str(user_id), "currency": currency},
        )
    return account_id


def _seed_goal(database_engine: Engine, user_id: UUID, currency: str = "EUR") -> UUID:
    goal_id = uuid4()
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO goals (id, user_id, name, target_amount, currency, status) "
                "VALUES (:id, :user_id, 'Goal', 1000, :currency, 'active')"
            ),
            {"id": str(goal_id), "user_id": str(user_id), "currency": currency},
        )
    return goal_id


# Inserts one goal transaction with raw SQL, listing the account_id column
# only when the caller passes one (so the same helper also writes the
# pre-C1 shape, where the column does not exist yet).
def _insert_transaction(
    database_engine: Engine,
    goal_id: UUID,
    user_id: UUID,
    type: str = "contribution",
    currency: str = "EUR",
    amount: str = "10.00",
    effective_date: Optional[str] = "2026-10-08",
    client_request_id: Optional[UUID] = None,
    **link: Optional[UUID],
) -> UUID:
    transaction_id = uuid4()
    columns = "id, goal_id, user_id, type, amount, currency, effective_date, client_request_id"
    values = ":id, :goal_id, :user_id, :type, :amount, :currency, :effective_date, :client_request_id"
    parameters = {
        "id": str(transaction_id),
        "goal_id": str(goal_id),
        "user_id": str(user_id),
        "type": type,
        "amount": amount,
        "currency": currency,
        "effective_date": effective_date,
        "client_request_id": None if client_request_id is None else str(client_request_id),
    }
    if "account_id" in link:
        columns += ", account_id"
        values += ", :account_id"
        parameters["account_id"] = None if link["account_id"] is None else str(link["account_id"])

    with database_engine.begin() as connection:
        connection.execute(
            text(f"INSERT INTO goal_transactions ({columns}) VALUES ({values})"),
            parameters,
        )

    return transaction_id


def _row_count(database_engine: Engine) -> int:
    with database_engine.connect() as connection:
        return connection.execute(text("SELECT count(*) FROM goal_transactions")).scalar_one()


def _revision(database_engine: Engine) -> str:
    with database_engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _definitions(database_engine: Engine, table: str) -> dict:
    with database_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = CAST(:table AS regclass)"
            ),
            {"table": table},
        ).all()
    return {name: definition for name, definition in rows}


def _columns(database_engine: Engine) -> dict:
    with database_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'goal_transactions'"
            )
        ).all()
    return {row[0]: tuple(row[1:]) for row in rows}


def _index_definitions(database_engine: Engine) -> dict:
    with database_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'goal_transactions'")
        ).all()
    return {name: definition for name, definition in rows}


def _expect_rejection(database_engine: Engine, expected_error: str, constraint: str, **arguments) -> None:
    before = _row_count(database_engine)
    with pytest.raises(IntegrityError) as error:
        _insert_transaction(database_engine, **arguments)
    assert type(error.value.orig).__name__ == expected_error
    assert error.value.orig.diag.constraint_name == constraint
    assert _row_count(database_engine) == before


# ------------------------------------------------------------------
# Real Alembic upgrade with pre-C1 (legacy) data
# ------------------------------------------------------------------


# Tests the real `alembic upgrade 98acdc7016d2` over rows written under the
# B4 schema: opening_balance, contribution and withdrawal rows, with and
# without effective_date and client_request_id. Every row is preserved
# unchanged, account_id is NULL for all of them and nothing is inferred.
# Parameters:
# - b4_database: throwaway database at the B4 revision.
# Returns:
# - None. The test passes if the rows are identical and unlinked.
def test_upgrade_preserves_legacy_rows_and_leaves_account_id_null(b4_database: Engine) -> None:
    user_id = uuid4()
    goal_id = _seed_goal(b4_database, user_id)
    _insert_transaction(b4_database, goal_id, user_id, type="opening_balance", amount="200.00", effective_date=None)
    _insert_transaction(b4_database, goal_id, user_id, type="contribution", amount="50.00", effective_date=None)
    _insert_transaction(b4_database, goal_id, user_id, type="contribution", amount="12.34",
                        effective_date="2026-10-01", client_request_id=uuid4())
    _insert_transaction(b4_database, goal_id, user_id, type="withdrawal", amount="30.00",
                        effective_date="2026-10-05", client_request_id=uuid4())
    with b4_database.connect() as connection:
        before = connection.execute(
            text(
                "SELECT id, goal_id, user_id, type, amount, currency, effective_date, "
                "client_request_id, created_at FROM goal_transactions ORDER BY id"
            )
        ).all()
    assert len(before) == 4
    assert "account_id" not in _columns(b4_database)

    result = _alembic(_url_of(b4_database), "upgrade", C1_REVISION)

    assert result.returncode == 0, result.stderr
    assert _revision(b4_database) == C1_REVISION
    with b4_database.connect() as connection:
        after = connection.execute(
            text(
                "SELECT id, goal_id, user_id, type, amount, currency, effective_date, "
                "client_request_id, created_at FROM goal_transactions ORDER BY id"
            )
        ).all()
        linked = connection.execute(
            text("SELECT count(*) FROM goal_transactions WHERE account_id IS NOT NULL")
        ).scalar_one()
    assert after == before
    assert linked == 0


# Tests the real upgrade over an empty ledger.
# Parameters:
# - b4_database: throwaway database at the B4 revision.
# Returns:
# - None. The test passes if the revision advances.
def test_upgrade_on_empty_ledger_succeeds(b4_database: Engine) -> None:
    result = _alembic(_url_of(b4_database), "upgrade", C1_REVISION)

    assert result.returncode == 0, result.stderr
    assert _revision(b4_database) == C1_REVISION


# ------------------------------------------------------------------
# Schema, read from the catalog
# ------------------------------------------------------------------


# Tests the added schema objects by catalog definition and that nothing
# existing was altered: account_id is a nullable uuid without default; the
# Account foreign key, the three CHECKs and the partial index have the exact
# agreed definitions; all B4 goal_transactions constraints and the Account
# uniques are unchanged; currency stays NOT NULL and effective_date and
# client_request_id stay nullable.
# Parameters:
# - b4_database: throwaway database at the B4 revision.
# - c1_database: the same database upgraded to C1.
# Returns:
# - None. The test passes if every definition matches.
def test_c1_schema_is_exactly_as_agreed_and_b4_contract_is_untouched(
    b4_database: Engine,
) -> None:
    b4_constraints = _definitions(b4_database, "goal_transactions")
    b4_columns = _columns(b4_database)
    b4_account_constraints = _definitions(b4_database, "accounts")

    result = _alembic(_url_of(b4_database), "upgrade", C1_REVISION)
    assert result.returncode == 0, result.stderr
    constraints = _definitions(b4_database, "goal_transactions")
    columns = _columns(b4_database)

    assert columns["account_id"] == ("uuid", "YES", None)
    assert {k: v for k, v in columns.items() if k != "account_id"} == b4_columns
    assert columns["currency"][1] == "NO"
    assert columns["effective_date"][1] == "YES" and columns["client_request_id"][1] == "YES"

    assert constraints[ACCOUNT_FK] == (
        "FOREIGN KEY (account_id, user_id, currency) "
        "REFERENCES accounts(id, user_id, currency) ON DELETE RESTRICT"
    )
    assert constraints[OPENING_CHECK] == "CHECK ((((type)::text <> 'opening_balance'::text) OR (account_id IS NULL)))"
    assert constraints[KEY_CHECK] == "CHECK (((account_id IS NULL) OR (client_request_id IS NOT NULL)))"
    assert constraints[DATE_CHECK] == "CHECK (((account_id IS NULL) OR (effective_date IS NOT NULL)))"
    assert {k: v for k, v in constraints.items() if k not in C1_CONSTRAINTS} == b4_constraints
    assert constraints["fk_goal_transactions_goal_id_user_id_currency"].startswith(
        "FOREIGN KEY (goal_id, user_id, currency) REFERENCES goals(id, user_id, currency)"
    )

    index = _index_definitions(b4_database)[LINKED_INDEX]
    assert "(account_id)" in index and "WHERE (account_id IS NOT NULL)" in index
    assert "UNIQUE" not in index

    accounts = _definitions(b4_database, "accounts")
    assert accounts == b4_account_constraints
    assert accounts["uq_accounts_id_user_id_currency"] == "UNIQUE (id, user_id, currency)"
    assert accounts["uq_accounts_id_user_id"] == "UNIQUE (id, user_id)"


# ------------------------------------------------------------------
# Constraint behavior with real writes
# ------------------------------------------------------------------


# Tests that a future-valid linked row can exist: same owner for Goal and
# Account, equal currencies, key and date present - for both a contribution
# and a withdrawal.
# Parameters:
# - c1_database: throwaway database at the C1 revision.
# Returns:
# - None. The test passes if both inserts succeed.
def test_valid_linked_rows_can_be_inserted(c1_database: Engine) -> None:
    user_id = uuid4()
    goal_id = _seed_goal(c1_database, user_id)
    account_id = _seed_account(c1_database, user_id)

    _insert_transaction(c1_database, goal_id, user_id, type="contribution",
                        client_request_id=uuid4(), account_id=account_id)
    _insert_transaction(c1_database, goal_id, user_id, type="withdrawal", amount="5.00",
                        client_request_id=uuid4(), account_id=account_id)

    assert _row_count(c1_database) == 2


# Tests that every invalid linked shape is rejected by the database, names
# the violated constraint, and persists nothing: another user's Account, an
# Account of another currency, a nonexistent Account, a linked opening
# balance, a linked row without a key and a linked row without a date.
# Parameters:
# - c1_database: throwaway database at the C1 revision.
# Returns:
# - None. The test passes if every case is rejected as expected.
def test_invalid_linked_rows_are_rejected(c1_database: Engine) -> None:
    owner = uuid4()
    stranger = uuid4()
    goal_id = _seed_goal(c1_database, owner, "EUR")
    own_account = _seed_account(c1_database, owner, "EUR")
    foreign_account = _seed_account(c1_database, stranger, "EUR")
    usd_account = _seed_account(c1_database, owner, "USD")
    key = uuid4

    _expect_rejection(c1_database, "ForeignKeyViolation", ACCOUNT_FK,
                      goal_id=goal_id, user_id=owner, client_request_id=key(), account_id=foreign_account)
    _expect_rejection(c1_database, "ForeignKeyViolation", ACCOUNT_FK,
                      goal_id=goal_id, user_id=owner, client_request_id=key(), account_id=usd_account)
    _expect_rejection(c1_database, "ForeignKeyViolation", ACCOUNT_FK,
                      goal_id=goal_id, user_id=owner, client_request_id=key(), account_id=uuid4())
    _expect_rejection(c1_database, "CheckViolation", OPENING_CHECK,
                      goal_id=goal_id, user_id=owner, type="opening_balance",
                      client_request_id=key(), account_id=own_account)
    _expect_rejection(c1_database, "CheckViolation", KEY_CHECK,
                      goal_id=goal_id, user_id=owner, client_request_id=None, account_id=own_account)
    _expect_rejection(c1_database, "CheckViolation", DATE_CHECK,
                      goal_id=goal_id, user_id=owner, client_request_id=key(),
                      effective_date=None, account_id=own_account)


# Tests that tracked rows keep the exact B4 shape: a tracked contribution
# with or without a key, a tracked row without effective_date, and a tracked
# opening balance are all still accepted (the linked CHECKs do not apply).
# Parameters:
# - c1_database: throwaway database at the C1 revision.
# Returns:
# - None. The test passes if all four inserts succeed with NULL account_id.
def test_tracked_rows_keep_the_b4_shape(c1_database: Engine) -> None:
    user_id = uuid4()
    goal_id = _seed_goal(c1_database, user_id)

    _insert_transaction(c1_database, goal_id, user_id, client_request_id=uuid4())
    _insert_transaction(c1_database, goal_id, user_id, client_request_id=None)
    _insert_transaction(c1_database, goal_id, user_id, effective_date=None)
    _insert_transaction(c1_database, goal_id, user_id, type="opening_balance",
                        effective_date=None, account_id=None)

    with c1_database.connect() as connection:
        linked = connection.execute(
            text("SELECT count(*) FROM goal_transactions WHERE account_id IS NOT NULL")
        ).scalar_one()
    assert _row_count(c1_database) == 4
    assert linked == 0


# Tests that linked history protects its Account at the database level:
# deleting the referenced Account and changing its currency are both
# rejected (the controlled API 409 belongs to C2), and the row survives.
# Parameters:
# - c1_database: throwaway database at the C1 revision.
# Returns:
# - None. The test passes if both statements are rejected.
def test_referenced_account_cannot_be_deleted_or_change_currency(c1_database: Engine) -> None:
    user_id = uuid4()
    goal_id = _seed_goal(c1_database, user_id)
    account_id = _seed_account(c1_database, user_id)
    _insert_transaction(c1_database, goal_id, user_id, client_request_id=uuid4(), account_id=account_id)

    with pytest.raises(IntegrityError) as delete_error:
        with c1_database.begin() as connection:
            connection.execute(text("DELETE FROM accounts WHERE id = :id"), {"id": str(account_id)})
    # ON DELETE RESTRICT is reported by PostgreSQL as a restrict violation
    # (SQLSTATE 23001), a sibling of the foreign-key violation (23503).
    assert type(delete_error.value.orig).__name__ == "RestrictViolation"
    assert delete_error.value.orig.diag.constraint_name == ACCOUNT_FK

    with pytest.raises(IntegrityError) as update_error:
        with c1_database.begin() as connection:
            connection.execute(text("UPDATE accounts SET currency = 'USD' WHERE id = :id"), {"id": str(account_id)})
    assert type(update_error.value.orig).__name__ in ("ForeignKeyViolation", "RestrictViolation")

    with c1_database.connect() as connection:
        remaining = connection.execute(
            text("SELECT currency FROM accounts WHERE id = :id"), {"id": str(account_id)}
        ).scalar_one()
    assert remaining == "EUR"
    assert _row_count(c1_database) == 1


# Tests that an Account WITHOUT linked history is unaffected: it can still be
# deleted and its currency changed at the database level.
# Parameters:
# - c1_database: throwaway database at the C1 revision.
# Returns:
# - None. The test passes if both statements succeed.
def test_unreferenced_account_is_unaffected(c1_database: Engine) -> None:
    user_id = uuid4()
    goal_id = _seed_goal(c1_database, user_id)
    referenced = _seed_account(c1_database, user_id)
    free = _seed_account(c1_database, user_id)
    _insert_transaction(c1_database, goal_id, user_id, client_request_id=uuid4(), account_id=referenced)

    with c1_database.begin() as connection:
        connection.execute(text("UPDATE accounts SET currency = 'USD' WHERE id = :id"), {"id": str(free)})
        connection.execute(text("DELETE FROM accounts WHERE id = :id"), {"id": str(free)})


# ------------------------------------------------------------------
# Real Alembic downgrade and cycle
# ------------------------------------------------------------------


# Tests the real downgrade to B4 with a linked row present: account_id, the
# Account foreign key, the three CHECKs and the partial index are gone and
# the remaining schema equals a database only ever migrated to B4. The row
# itself survives (amount, currency, dates, key) but its account association
# is lost - the documented consequence of this schema-only reversal.
# Parameters:
# - c1_database: throwaway database at the C1 revision.
# - b4_template: name of the pure B4 template database.
# Returns:
# - None. The test passes if the schema equals B4 and the row is kept.
def test_downgrade_restores_b4_schema_and_loses_only_the_association(
    c1_database: Engine,
    b4_template: str,
) -> None:
    user_id = uuid4()
    goal_id = _seed_goal(c1_database, user_id)
    account_id = _seed_account(c1_database, user_id)
    key = uuid4()
    transaction_id = _insert_transaction(
        c1_database, goal_id, user_id, amount="77.00", client_request_id=key, account_id=account_id,
    )

    result = _alembic(_url_of(c1_database), "downgrade", B4_REVISION)

    assert result.returncode == 0, result.stderr
    assert _revision(c1_database) == B4_REVISION
    template_engine = create_engine(_database_url(b4_template))
    try:
        assert _definitions(c1_database, "goal_transactions") == _definitions(template_engine, "goal_transactions")
        assert _definitions(c1_database, "accounts") == _definitions(template_engine, "accounts")
        assert _columns(c1_database) == _columns(template_engine)
        assert _index_definitions(c1_database) == _index_definitions(template_engine)
    finally:
        template_engine.dispose()
    assert "account_id" not in _columns(c1_database)
    assert LINKED_INDEX not in _index_definitions(c1_database)
    with c1_database.connect() as connection:
        row = connection.execute(
            text("SELECT amount::text, currency, client_request_id::text FROM goal_transactions WHERE id = :id"),
            {"id": str(transaction_id)},
        ).one()
    assert row == ("77.00", "EUR", str(key))


# Tests upgrade -> downgrade -> upgrade on one database with legacy data:
# the final schema equals the first C1 schema and the data is unchanged.
# Parameters:
# - b4_database: throwaway database at the B4 revision.
# Returns:
# - None. The test passes if both C1 snapshots are identical.
def test_upgrade_downgrade_upgrade_cycle(b4_database: Engine) -> None:
    user_id = uuid4()
    goal_id = _seed_goal(b4_database, user_id)
    _insert_transaction(b4_database, goal_id, user_id, client_request_id=uuid4())
    url = _url_of(b4_database)

    assert _alembic(url, "upgrade", C1_REVISION).returncode == 0
    first = (_definitions(b4_database, "goal_transactions"), _columns(b4_database), _index_definitions(b4_database))
    assert _alembic(url, "downgrade", B4_REVISION).returncode == 0
    assert _revision(b4_database) == B4_REVISION
    assert _alembic(url, "upgrade", C1_REVISION).returncode == 0
    second = (_definitions(b4_database, "goal_transactions"), _columns(b4_database), _index_definitions(b4_database))

    assert _revision(b4_database) == C1_REVISION
    assert second == first
    assert _row_count(b4_database) == 1


# ------------------------------------------------------------------
# Rollout bridge and lock order
# ------------------------------------------------------------------


# Tests the C1 rollout rule: the application ORM is deliberately unaware of
# account_id (mapping it before the production migration would break every
# goal_transactions SELECT), so metadata intentionally differs from the C1
# database until C2.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the ORM has no account_id column or constraint.
def test_orm_does_not_map_account_id_in_c1() -> None:
    table = GoalTransactionModel.__table__

    assert "account_id" not in table.columns
    assert not hasattr(GoalTransactionModel, "account_id")
    constraint_names = {constraint.name for constraint in table.constraints}
    assert not (constraint_names & C1_CONSTRAINTS)
    assert LINKED_INDEX not in {index.name for index in table.indexes}


def _load_migration():
    spec = importlib.util.spec_from_file_location("expand_goal_transaction_account_link", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Tests the migration's TABLE-lock order and placement: accounts
# (SHARE ROW EXCLUSIVE) first, goal_transactions (ACCESS EXCLUSIVE) second,
# taken before any other statement in upgrade and downgrade, with no
# hard-coded lock_timeout. (This is not the C2 runtime row-lock order.)
# Parameters:
# - None.
# Returns:
# - None. The test passes if order and placement are as reviewed.
def test_migration_locks_accounts_then_goal_transactions_first() -> None:
    module = _load_migration()
    source = MIGRATION_PATH.read_text()

    assert module.LOCK_TABLES_SQL == (
        "LOCK TABLE accounts IN SHARE ROW EXCLUSIVE MODE",
        "LOCK TABLE goal_transactions IN ACCESS EXCLUSIVE MODE",
    )
    assert "SET lock_timeout" not in source and "SET LOCAL lock_timeout" not in source
    assert "lock_timeout =" not in source
    for function in (module.upgrade, module.downgrade):
        body = inspect.getsource(function).split('"""')[-1]
        assert body.strip().splitlines()[0] == "for lock_statement in LOCK_TABLES_SQL:"
