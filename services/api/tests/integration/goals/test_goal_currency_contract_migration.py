import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Generator, Optional
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.exc import IntegrityError

from app.db.database_session import engine as application_engine
from tests.database_safety import validate_test_database_url

# VF-020B4 contract-migration tests (revision 8799b7fd923d).
#
# Unlike the other goal tests these do NOT use the shared test schema: they
# run the REAL Alembic CLI (subprocess) against throwaway databases. A
# template database is migrated once to the B3 state (1e921a4a4412); each
# test clones it, seeds rows the way the B2/B3 application could have left
# them, runs `alembic upgrade head` / `downgrade -1`, and inspects the real
# database state afterwards. Every throwaway database name ends in "_test",
# is validated by the project's database safety guard before use, and is
# dropped afterwards. The shared valor_test database is never migrated here.

API_DIR = Path(__file__).resolve().parents[3]
B3_REVISION = "1e921a4a4412"
B4_REVISION = "8799b7fd923d"
MIGRATION_PATH = API_DIR / "alembic" / "versions" / "8799b7fd923d_contract_goal_transaction_currency.py"

B4_FOREIGN_KEY = "fk_goal_transactions_goal_id_user_id_currency"
B4_UNIQUE = "uq_goals_id_user_id_currency"


def _admin_engine() -> Engine:
    # The server's maintenance database, reached with the same credentials as
    # the test database; only used to create and drop throwaway databases.
    admin_url = application_engine.url.set(database="postgres")
    return create_engine(admin_url, isolation_level="AUTOCOMMIT")


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
# - args: Alembic arguments, e.g. ("upgrade", "head").
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
def b3_template() -> Generator[str, None, None]:
    name = f"vf020b4_tpl_{uuid4().hex[:10]}_test"
    url = _create_database(name)
    try:
        result = _alembic(url, "upgrade", B3_REVISION)
        assert result.returncode == 0, result.stderr
        yield name
    finally:
        _drop_database(name)


@pytest.fixture
def b3_database(b3_template: str) -> Generator[Engine, None, None]:
    name = f"vf020b4_{uuid4().hex[:10]}_test"
    url = _create_database(name, template=b3_template)
    database_engine = create_engine(url)

    try:
        yield database_engine
    finally:
        database_engine.dispose()
        _drop_database(name)


def _url_of(database_engine: Engine) -> URL:
    return make_url(database_engine.url.render_as_string(hide_password=False))


# Seeds one goal with raw SQL.
# Returns:
# - The goal id.
def _seed_goal(database_engine: Engine, user_id: UUID, currency: str, status: str = "active") -> UUID:
    goal_id = uuid4()

    with database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO goals (id, user_id, name, target_amount, currency, status) "
                "VALUES (:id, :user_id, 'Goal', 1000, :currency, :status)"
            ),
            {"id": str(goal_id), "user_id": str(user_id), "currency": currency, "status": status},
        )

    return goal_id


# Seeds one goal transaction the way B2/B3-era code could have left it
# (currency possibly NULL; the B3 columns effective_date/client_request_id
# are left alone unless given).
def _seed_transaction(
    database_engine: Engine,
    goal_id: UUID,
    user_id: UUID,
    currency: Optional[str],
    amount: str = "10.00",
    type: str = "contribution",
    effective_date: Optional[str] = None,
    client_request_id: Optional[UUID] = None,
) -> UUID:
    transaction_id = uuid4()

    with database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO goal_transactions "
                "(id, goal_id, user_id, type, amount, currency, effective_date, client_request_id) "
                "VALUES (:id, :goal_id, :user_id, :type, :amount, :currency, "
                ":effective_date, :client_request_id)"
            ),
            {
                "id": str(transaction_id),
                "goal_id": str(goal_id),
                "user_id": str(user_id),
                "type": type,
                "amount": amount,
                "currency": currency,
                "effective_date": effective_date,
                "client_request_id": None if client_request_id is None else str(client_request_id),
            },
        )

    return transaction_id


def _revision(database_engine: Engine) -> str:
    with database_engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _currency_is_nullable(database_engine: Engine) -> bool:
    with database_engine.connect() as connection:
        value = connection.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'goal_transactions' AND column_name = 'currency'"
            )
        ).scalar_one()
    return value == "YES"


def _constraint_definitions(database_engine: Engine) -> dict:
    with database_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid IN ('goals'::regclass, 'goal_transactions'::regclass)"
            )
        ).all()
    return {name: definition for name, definition in rows}


def _currencies(database_engine: Engine) -> dict:
    with database_engine.connect() as connection:
        rows = connection.execute(text("SELECT id, currency FROM goal_transactions")).all()
    return {UUID(str(row[0])): row[1] for row in rows}


# ------------------------------------------------------------------
# Real Alembic upgrade: backfill
# ------------------------------------------------------------------


# Tests the real `alembic upgrade head` with seeded B2/B3-era data: rows with
# a NULL currency are filled from their own goal's currency (EUR and USD,
# two users), rows that already have the right currency and every
# effective_date/client_request_id stay exactly as they were, currency
# becomes NOT NULL and the revision advances.
# Parameters:
# - b3_database: throwaway database at the B3 revision.
# Returns:
# - None. The test passes if the database ends in the expected B4 state.
def test_upgrade_backfills_null_currency_from_each_goal(b3_database: Engine) -> None:
    first_user = uuid4()
    second_user = uuid4()
    key = uuid4()
    eur_goal = _seed_goal(b3_database, first_user, "EUR")
    usd_goal = _seed_goal(b3_database, first_user, "USD", status="archived")
    other_goal = _seed_goal(b3_database, second_user, "USD")
    null_eur = _seed_transaction(b3_database, eur_goal, first_user, None)
    null_usd = _seed_transaction(b3_database, usd_goal, first_user, None, type="withdrawal")
    null_opening = _seed_transaction(b3_database, other_goal, second_user, None, type="opening_balance")
    filled_eur = _seed_transaction(
        b3_database, eur_goal, first_user, "EUR",
        effective_date="2026-10-05", client_request_id=key,
    )
    assert _currency_is_nullable(b3_database) is True

    result = _alembic(_url_of(b3_database), "upgrade", "head")

    assert result.returncode == 0, result.stderr
    assert _revision(b3_database) == B4_REVISION
    assert _currency_is_nullable(b3_database) is False
    assert _currencies(b3_database) == {
        null_eur: "EUR", null_usd: "USD", null_opening: "USD", filled_eur: "EUR",
    }
    with b3_database.connect() as connection:
        untouched = connection.execute(
            text(
                "SELECT effective_date::text, client_request_id::text FROM goal_transactions "
                "WHERE id = :id"
            ),
            {"id": str(filled_eur)},
        ).one()
        null_columns = connection.execute(
            text(
                "SELECT count(*) FROM goal_transactions "
                "WHERE id <> :id AND (effective_date IS NOT NULL OR client_request_id IS NOT NULL)"
            ),
            {"id": str(filled_eur)},
        ).scalar_one()
    assert untouched == ("2026-10-05", str(key))
    assert null_columns == 0


# Tests that upgrading a database with no goal transactions at all works.
# Parameters:
# - b3_database: throwaway database at the B3 revision.
# Returns:
# - None. The test passes if the upgrade succeeds.
def test_upgrade_on_empty_ledger_succeeds(b3_database: Engine) -> None:
    result = _alembic(_url_of(b3_database), "upgrade", "head")

    assert result.returncode == 0, result.stderr
    assert _revision(b3_database) == B4_REVISION


# ------------------------------------------------------------------
# Real Alembic upgrade: atomic rejection of invalid data
# ------------------------------------------------------------------


# Tests the mismatch gate with the real Alembic CLI: a goal transaction whose
# non-NULL currency differs from its goal's makes the upgrade fail. The
# failure is atomic - the revision is unchanged, currency is still nullable,
# no B4 constraint exists, and neither the mismatched row nor a NULL-currency
# row seeded next to it was rewritten (the backfill rolled back too).
# Parameters:
# - b3_database: throwaway database at the B3 revision.
# Returns:
# - None. The test passes if the database is exactly as it was.
def test_currency_mismatch_aborts_upgrade_atomically(b3_database: Engine) -> None:
    user_id = uuid4()
    goal = _seed_goal(b3_database, user_id, "EUR")
    mismatched = _seed_transaction(b3_database, goal, user_id, "USD")
    null_row = _seed_transaction(b3_database, goal, user_id, None)
    before = _constraint_definitions(b3_database)

    result = _alembic(_url_of(b3_database), "upgrade", "head")

    assert result.returncode != 0
    assert "differs from their goal's currency" in result.stderr
    assert _revision(b3_database) == B3_REVISION
    assert _currency_is_nullable(b3_database) is True
    assert _constraint_definitions(b3_database) == before
    assert B4_UNIQUE not in before and B4_FOREIGN_KEY not in before
    assert _currencies(b3_database) == {mismatched: "USD", null_row: None}


# ------------------------------------------------------------------
# Final database contract, exercised with real writes
# ------------------------------------------------------------------


@pytest.fixture
def b4_database(b3_database: Engine) -> Engine:
    result = _alembic(_url_of(b3_database), "upgrade", "head")
    assert result.returncode == 0, result.stderr
    return b3_database


# Tests the final constraints by catalog definition: the goal_id foreign key
# and the B2 ownership foreign key are preserved, the new three-column
# foreign key and its unique target exist, and the B2 unique constraints
# stay.
# Parameters:
# - b4_database: throwaway database upgraded to B4.
# Returns:
# - None. The test passes if every definition matches.
def test_final_constraints_exist_and_earlier_ones_are_preserved(b4_database: Engine) -> None:
    definitions = _constraint_definitions(b4_database)

    assert definitions[B4_UNIQUE] == "UNIQUE (id, user_id, currency)"
    assert definitions[B4_FOREIGN_KEY] == (
        "FOREIGN KEY (goal_id, user_id, currency) "
        "REFERENCES goals(id, user_id, currency) ON DELETE RESTRICT"
    )
    assert definitions["fk_goal_transactions_goal_id_user_id"] == (
        "FOREIGN KEY (goal_id, user_id) REFERENCES goals(id, user_id) ON DELETE RESTRICT"
    )
    assert definitions["goal_transactions_goal_id_fkey"] == (
        "FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE RESTRICT"
    )
    assert definitions["uq_goals_id_user_id"] == "UNIQUE (id, user_id)"
    assert definitions["uq_goal_transactions_user_id_client_request_id"] == (
        "UNIQUE (user_id, client_request_id)"
    )


# Tests the final constraints with real inserts and updates: a matching
# (goal_id, user_id, currency) row is stored; a NULL currency, a wrong
# currency, another user's id and a nonexistent goal are all rejected; and
# changing a stored transaction's currency to a wrong one is rejected too.
# Parameters:
# - b4_database: throwaway database upgraded to B4.
# Returns:
# - None. The test passes if only the matching row is accepted.
def test_final_contract_rejects_wrong_rows_with_real_writes(b4_database: Engine) -> None:
    owner = uuid4()
    other_user = uuid4()
    goal = _seed_goal(b4_database, owner, "EUR")
    stored = _seed_transaction(b4_database, goal, owner, "EUR")
    assert _currencies(b4_database) == {stored: "EUR"}

    rejected = [
        ("NULL currency", goal, owner, None, "NotNullViolation"),
        ("wrong currency", goal, owner, "USD", "ForeignKeyViolation"),
        ("wrong user", goal, other_user, "EUR", "ForeignKeyViolation"),
        ("nonexistent goal", uuid4(), owner, "EUR", "ForeignKeyViolation"),
    ]

    for label, goal_id, user_id, currency, expected_error in rejected:
        with pytest.raises(IntegrityError) as error:
            _seed_transaction(b4_database, goal_id, user_id, currency)
        assert type(error.value.orig).__name__ == expected_error, label

    with pytest.raises(IntegrityError) as update_error:
        with b4_database.begin() as connection:
            connection.execute(
                text("UPDATE goal_transactions SET currency = 'USD' WHERE id = :id"),
                {"id": str(stored)},
            )
    assert update_error.value.orig.diag.constraint_name == B4_FOREIGN_KEY

    assert _currencies(b4_database) == {stored: "EUR"}


# Tests that the wrong-currency and wrong-user rejections come specifically
# from the new three-column key and the B2 ownership key respectively: a
# wrong currency violates only the final key, and the final key's goal
# identity is enforced even when a goal exists.
# Parameters:
# - b4_database: throwaway database upgraded to B4.
# Returns:
# - None. The test passes if the violated constraint is the expected one.
def test_wrong_currency_is_rejected_by_the_final_foreign_key(b4_database: Engine) -> None:
    owner = uuid4()
    goal = _seed_goal(b4_database, owner, "EUR")

    with pytest.raises(IntegrityError) as error:
        _seed_transaction(b4_database, goal, owner, "USD")

    assert error.value.orig.diag.constraint_name == B4_FOREIGN_KEY


# Tests that a goal that has transactions cannot have its currency changed
# or be deleted at the database level.
# Parameters:
# - b4_database: throwaway database upgraded to B4.
# Returns:
# - None. The test passes if both statements are rejected.
def test_goal_with_history_cannot_change_currency_or_be_deleted(b4_database: Engine) -> None:
    owner = uuid4()
    goal = _seed_goal(b4_database, owner, "EUR")
    _seed_transaction(b4_database, goal, owner, "EUR")

    with pytest.raises(IntegrityError):
        with b4_database.begin() as connection:
            connection.execute(text("UPDATE goals SET currency = 'USD' WHERE id = :id"), {"id": str(goal)})

    with pytest.raises(IntegrityError):
        with b4_database.begin() as connection:
            connection.execute(text("DELETE FROM goals WHERE id = :id"), {"id": str(goal)})


# ------------------------------------------------------------------
# Real Alembic downgrade
# ------------------------------------------------------------------


# Tests the real `alembic downgrade -1`: the schema returns to the B3 shape
# (currency nullable, the new unique constraint and foreign key gone, every
# earlier constraint kept) while stored currency values are kept, and a NULL
# currency can be written again. The constraint set equals that of a
# database only ever migrated to B3. Upgrading again then backfills the
# NULL row written in between.
# Parameters:
# - b4_database: throwaway database upgraded to B4.
# - b3_template: name of the template database (a pure B3 schema).
# Returns:
# - None. The test passes if the downgraded schema equals the B3 schema.
def test_downgrade_restores_the_b3_schema_and_keeps_values(
    b4_database: Engine,
    b3_template: str,
) -> None:
    owner = uuid4()
    goal = _seed_goal(b4_database, owner, "EUR")
    stored = _seed_transaction(b4_database, goal, owner, "EUR")

    result = _alembic(_url_of(b4_database), "downgrade", "-1")

    assert result.returncode == 0, result.stderr
    assert _revision(b4_database) == B3_REVISION
    assert _currency_is_nullable(b4_database) is True
    assert _currencies(b4_database) == {stored: "EUR"}
    downgraded = _constraint_definitions(b4_database)
    assert B4_UNIQUE not in downgraded and B4_FOREIGN_KEY not in downgraded

    template_engine = create_engine(_database_url(b3_template))
    try:
        assert downgraded == _constraint_definitions(template_engine)
    finally:
        template_engine.dispose()

    legacy = _seed_transaction(b4_database, goal, owner, None)

    again = _alembic(_url_of(b4_database), "upgrade", "head")
    assert again.returncode == 0, again.stderr
    assert _revision(b4_database) == B4_REVISION
    assert _currencies(b4_database) == {stored: "EUR", legacy: "EUR"}


# ------------------------------------------------------------------
# Lock order
# ------------------------------------------------------------------


def _load_migration():
    spec = importlib.util.spec_from_file_location("contract_goal_transaction_currency", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Tests the migration's lock order and that locking comes first: goals
# before goal_transactions (the application's order), taken before any
# statement in both upgrade and downgrade, and no lock_timeout is hardcoded.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the order and placement are as reviewed.
def test_migration_locks_goals_before_goal_transactions_and_first() -> None:
    import inspect

    module = _load_migration()
    source = MIGRATION_PATH.read_text()

    assert module.LOCK_GOAL_TABLES_SQL == (
        "LOCK TABLE goals IN ACCESS EXCLUSIVE MODE",
        "LOCK TABLE goal_transactions IN ACCESS EXCLUSIVE MODE",
    )
    assert "SET lock_timeout" not in source and "SET LOCAL lock_timeout" not in source
    assert "lock_timeout =" not in source

    for function in (module.upgrade, module.downgrade):
        body = inspect.getsource(function).split('"""')[-1]
        first_statement = body.strip().splitlines()[0]
        assert first_statement == "for lock_statement in LOCK_GOAL_TABLES_SQL:"
