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

# VF-GOALS-PLANNING-002C2 schema stage (revision a3f9d7c25e84): the
# future_obligation_expense_links table. These tests run the REAL Alembic CLI on
# throwaway *_test databases cloned from a template at the previous revision; no
# production database or credential is involved, and the shared valor_test database
# is never migrated by them.

API_DIR = Path(__file__).resolve().parents[3]
PREVIOUS_REVISION = "e4a8c2d91b36"
REVISION = "a3f9d7c25e84"
MIGRATION_PATH = API_DIR / "alembic" / "versions" / f"{REVISION}_add_future_obligation_expense_links.py"
TABLE = "future_obligation_expense_links"
OWNER_UNIQUE = "uq_future_obligations_id_user_id"


@pytest.fixture(scope="module")
def previous_template() -> Generator[str, None, None]:
    name = f"vf002c2_tpl_{uuid4().hex[:10]}_test"
    url = _create_database(name)
    try:
        result = _alembic(url, "upgrade", PREVIOUS_REVISION)
        assert result.returncode == 0, result.stderr
        yield name
    finally:
        _drop_database(name)


@pytest.fixture
def previous_database(previous_template: str) -> Generator[Engine, None, None]:
    name = f"vf002c2_{uuid4().hex[:10]}_test"
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


def _expense(database_engine: Engine, user_id: UUID) -> UUID:
    expense_id = uuid4()

    with database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO expenses (id, user_id, title, amount, expense_date) "
                "VALUES (:i, :u, 'Rent', 950.00, DATE '2026-11-01')"
            ),
            {"i": expense_id, "u": user_id},
        )

    return expense_id


def _obligation(database_engine: Engine, user_id: UUID) -> UUID:
    obligation_id = uuid4()

    with database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO future_obligations (id, user_id, name, schedule, amount, currency, first_due_date) "
                "VALUES (:i, :u, 'Rent', 'monthly', 950.00, 'EUR', DATE '2026-10-31')"
            ),
            {"i": obligation_id, "u": user_id},
        )

    return obligation_id


def _insert_link(database_engine: Engine, **values: Any) -> None:
    values.setdefault("id", uuid4())
    columns = ", ".join(values)
    placeholders = ", ".join(f":{name}" for name in values)

    with database_engine.begin() as connection:
        connection.execute(text(f"INSERT INTO {TABLE} ({columns}) VALUES ({placeholders})"), values)


def _rejected(database_engine: Engine, **values: Any) -> str:
    with pytest.raises(IntegrityError) as caught:
        _insert_link(database_engine, **values)

    return _constraint(caught.value) or ""


def _owned_pair(database_engine: Engine) -> tuple[UUID, UUID, UUID]:
    user = uuid4()

    return user, _obligation(database_engine, user), _expense(database_engine, user)


def test_revision_chain_has_one_head_directly_on_top_of_the_previous_revision() -> None:
    script = ScriptDirectory.from_config(Config(str(API_DIR / "alembic.ini")))

    assert len(script.get_heads()) == 1
    assert script.get_revision(REVISION).down_revision == PREVIOUS_REVISION


def test_upgrade_downgrade_and_upgrade_again_touch_only_the_new_objects(previous_database: Engine) -> None:
    url = _url_of(previous_database)
    _owned_pair(previous_database)
    watched = ("accounts", "goals", "goal_transactions", "expenses", "income", "budgets", "future_obligations")
    before = {table: _digest(previous_database, table) for table in watched}
    assert not _table_exists(previous_database, TABLE)

    assert _alembic(url, "upgrade", REVISION).returncode == 0
    assert _revision(previous_database) == REVISION and _table_exists(previous_database, TABLE)
    assert {table: _digest(previous_database, table) for table in watched} == before

    down = _alembic(url, "downgrade", PREVIOUS_REVISION)
    assert down.returncode == 0, down.stderr
    assert _revision(previous_database) == PREVIOUS_REVISION and not _table_exists(previous_database, TABLE)
    assert {table: _digest(previous_database, table) for table in watched} == before

    with previous_database.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM pg_constraint WHERE conname = :n"), {"n": OWNER_UNIQUE}
        ).scalar_one() == 0

    assert _alembic(url, "upgrade", REVISION).returncode == 0
    assert _table_exists(previous_database, TABLE)


def test_constraints_indexes_and_delete_rules_are_exactly_the_documented_set(migrated_database: Engine) -> None:
    with migrated_database.connect() as connection:
        constraints = {
            name: (kind, delete_rule)
            for name, kind, delete_rule in connection.execute(
                text(
                    "SELECT conname, contype, confdeltype FROM pg_constraint "
                    "WHERE conrelid = CAST(:t AS regclass) AND contype <> 'n'"
                ),
                {"t": TABLE},
            )
        }
        indexes = {name for (name,) in connection.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = :t"), {"t": TABLE})}

    # 'r' is RESTRICT: neither a linked Expense nor a linked obligation can disappear silently.
    assert constraints == {
        "future_obligation_expense_links_pkey": ("p", " "),
        "fk_future_obligation_links_obligation_owner": ("f", "r"),
        "fk_future_obligation_links_expense_owner": ("f", "r"),
        "uq_future_obligation_links_expense_id": ("u", " "),
        "uq_future_obligation_links_obligation_id_due_date": ("u", " "),
        "ck_future_obligation_links_due_date_range": ("c", " "),
    }
    assert indexes == {
        "future_obligation_expense_links_pkey",
        "uq_future_obligation_links_expense_id",
        "uq_future_obligation_links_obligation_id_due_date",
        "ix_future_obligation_links_user_id_due_date",
    }


def test_a_link_cannot_join_records_of_two_different_users(migrated_database: Engine) -> None:
    user, obligation_id, expense_id = _owned_pair(migrated_database)
    stranger = uuid4()
    foreign_expense = _expense(migrated_database, stranger)
    foreign_obligation = _obligation(migrated_database, stranger)

    # The link's owner must own BOTH records: every mixed combination is refused.
    assert _rejected(migrated_database, user_id=user, obligation_id=obligation_id, expense_id=foreign_expense, due_date="2026-11-30") == "fk_future_obligation_links_expense_owner"
    assert _rejected(migrated_database, user_id=user, obligation_id=foreign_obligation, expense_id=expense_id, due_date="2026-11-30") == "fk_future_obligation_links_obligation_owner"
    assert _rejected(migrated_database, user_id=stranger, obligation_id=obligation_id, expense_id=expense_id, due_date="2026-11-30") != ""

    _insert_link(migrated_database, user_id=user, obligation_id=obligation_id, expense_id=expense_id, due_date="2026-11-30")


def test_one_expense_one_link_and_one_occurrence_one_link(migrated_database: Engine) -> None:
    user, obligation_id, expense_id = _owned_pair(migrated_database)
    other_expense = _expense(migrated_database, user)
    other_obligation = _obligation(migrated_database, user)
    _insert_link(migrated_database, user_id=user, obligation_id=obligation_id, expense_id=expense_id, due_date="2026-11-30")

    # The same Expense cannot be linked to a second occurrence (of this or another obligation).
    assert _rejected(migrated_database, user_id=user, obligation_id=obligation_id, expense_id=expense_id, due_date="2026-12-31") == "uq_future_obligation_links_expense_id"
    assert _rejected(migrated_database, user_id=user, obligation_id=other_obligation, expense_id=expense_id, due_date="2026-11-30") == "uq_future_obligation_links_expense_id"
    # The same occurrence cannot have a second Expense, while another month or bill is free.
    assert _rejected(migrated_database, user_id=user, obligation_id=obligation_id, expense_id=other_expense, due_date="2026-11-30") == "uq_future_obligation_links_obligation_id_due_date"
    _insert_link(migrated_database, user_id=user, obligation_id=obligation_id, expense_id=other_expense, due_date="2026-12-31")


def test_a_linked_expense_or_obligation_cannot_be_deleted(migrated_database: Engine) -> None:
    user, obligation_id, expense_id = _owned_pair(migrated_database)
    _insert_link(migrated_database, user_id=user, obligation_id=obligation_id, expense_id=expense_id, due_date="2026-11-30")

    for statement in (
        "DELETE FROM expenses WHERE id = :i",
        "DELETE FROM future_obligations WHERE id = :o",
    ):
        with pytest.raises(IntegrityError):
            with migrated_database.begin() as connection:
                connection.execute(text(statement), {"i": expense_id, "o": obligation_id})

    assert _count(migrated_database, f"SELECT count(*) FROM {TABLE} WHERE user_id = :u", u=user) == 1


def test_due_date_must_be_inside_the_supported_range(migrated_database: Engine) -> None:
    user, obligation_id, expense_id = _owned_pair(migrated_database)

    for bad in ("1999-12-31", "2101-01-01"):
        assert _rejected(migrated_database, user_id=user, obligation_id=obligation_id, expense_id=expense_id, due_date=bad) == "ck_future_obligation_links_due_date_range"


def test_the_downgrade_refuses_to_destroy_hand_made_links(migrated_database: Engine) -> None:
    user, obligation_id, expense_id = _owned_pair(migrated_database)
    _insert_link(migrated_database, user_id=user, obligation_id=obligation_id, expense_id=expense_id, due_date="2026-11-30")

    down = _alembic(_url_of(migrated_database), "downgrade", PREVIOUS_REVISION)

    assert down.returncode != 0 and "Refusing to downgrade" in down.stderr
    assert _revision(migrated_database) == REVISION
    assert _count(migrated_database, f"SELECT count(*) FROM {TABLE} WHERE user_id = :u", u=user) == 1


def test_the_migration_has_no_data_statements() -> None:
    source = MIGRATION_PATH.read_text()
    upgrade_body = source.split("def upgrade")[1].split("def downgrade")[0]

    for forbidden in ("INSERT INTO", "UPDATE ", "DELETE FROM"):
        assert forbidden not in upgrade_body


def test_the_orm_matches_the_migrated_schema(migrated_database: Engine) -> None:
    import_database_models()

    with migrated_database.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert [difference for difference in differences if "future_obligation" in repr(difference)] == []


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
                        text(f"SELECT has_table_privilege(:r, 'public.{TABLE}', :p)"), {"r": role, "p": privilege}
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
