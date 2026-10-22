import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
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
    _account,
    _admin_engine,
    _alembic,
    _allocation,
    _constraint,
    _count,
    _create_database,
    _digest,
    _drop_database,
    _floor,
    _goal,
    _insert_rule,
    _revision,
    _table_exists,
    _url_of,
)
from tests.schema_drift import exclude_stages_after
from uuid import uuid4 as _uuid4

# VF-020E6 schema-expand tests (revision e0503e9ca9d3): rule_executions,
# rule_execution_items, rule_execution_audit, the hold sequence,
# goal_transactions.rule_execution_id and the replaced linked-origin CHECK.
#
# They run the REAL Alembic CLI against throwaway *_test databases cloned from a
# template migrated to the E4 revision; every database name ends in "_test",
# passes the project's safety guard (inside _create_database) and is dropped
# afterwards. No production database or credential is ever involved.

API_DIR = Path(__file__).resolve().parents[3]
APP_DIR = API_DIR / "app"
E4_REVISION = "861064d31463"
E6_REVISION = "e0503e9ca9d3"
MIGRATION_PATH = API_DIR / "alembic" / "versions" / f"{E6_REVISION}_add_rule_execution_schema.py"

EXECUTIONS = "rule_executions"
ITEMS = "rule_execution_items"
AUDIT = "rule_execution_audit"
SEQUENCE = "rule_execution_hold_sequence"
RESTRICT_SQLSTATES = ("23001", "23503")
NEW_TABLES = (EXECUTIONS, ITEMS, AUDIT)

OLD_CHECK = "ck_goal_transactions_linked_requires_client_request_id"
ORIGIN_CHECK = "ck_goal_transactions_linked_requires_origin"
EXCLUSIVE_CHECK = "ck_goal_transactions_origin_exclusive"
SHAPE_CHECK = "ck_goal_transactions_rule_execution_shape"


@pytest.fixture(scope="module")
def e4_template() -> Generator[str, None, None]:
    name = f"vf020e6_tpl_{uuid4().hex[:10]}_test"
    url = _create_database(name)
    try:
        result = _alembic(url, "upgrade", E4_REVISION)
        assert result.returncode == 0, result.stderr
        yield name
    finally:
        _drop_database(name)


@pytest.fixture
def e4_database(e4_template: str) -> Generator[Engine, None, None]:
    name = f"vf020e6_{uuid4().hex[:10]}_test"
    url = _create_database(name, template=e4_template)
    database_engine = create_engine(url)
    try:
        yield database_engine
    finally:
        database_engine.dispose()
        _drop_database(name)


@pytest.fixture
def e6_database(e4_database: Engine) -> Engine:
    result = _alembic(_url_of(e4_database), "upgrade", E6_REVISION)
    assert result.returncode == 0, result.stderr
    return e4_database


# ---------------- seed helpers (raw SQL; the tables are not used by the app yet) ----------------


class World:
    """One user with an Account, a Goal, an allocation rule and helpers."""

    def __init__(self, database_engine: Engine, user_id: Optional[UUID] = None) -> None:
        self.engine = database_engine
        self.user_id = user_id or uuid4()
        self.account_id = _account(database_engine, self.user_id)
        self.goal_id = _goal(database_engine, self.user_id)
        self.rule_id = _insert_rule(database_engine, _allocation(self.user_id, self.account_id))


def _execution(world: World, **overrides: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "id": uuid4(), "user_id": world.user_id, "rule_id": world.rule_id, "rule_version": 1,
        "params_snapshot": json.dumps({"policy": "FIXED_PER_GOAL"}), "source_type": "income",
        "source_id": uuid4(), "triggering_event_id": uuid4(), "source_amount": Decimal("100.00"),
        "source_currency": "EUR", "source_received_at": date(2026, 10, 20), "source_income_source": "salary",
        "status": "executed",
    }
    values.update(overrides)
    return values


def _insert_execution(database_engine: Engine, values: Dict[str, Any]) -> UUID:
    columns = ", ".join(values)
    placeholders = ", ".join(f"CAST(:{k} AS jsonb)" if k == "params_snapshot" else f":{k}" for k in values)
    with database_engine.begin() as connection:
        connection.execute(text(f"INSERT INTO rule_executions ({columns}) VALUES ({placeholders})"), values)
    return values["id"]


def _insert_item(database_engine: Engine, execution_id: UUID, user_id: UUID, goal_id: UUID, account_id: UUID,
                 **overrides: Any) -> UUID:
    values: Dict[str, Any] = {
        "id": uuid4(), "user_id": user_id, "execution_id": execution_id, "goal_id": goal_id,
        "account_id": account_id, "position": 0, "planned_amount": Decimal("50.00"),
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join(f":{k}" for k in values)
    with database_engine.begin() as connection:
        connection.execute(text(f"INSERT INTO rule_execution_items ({columns}) VALUES ({placeholders})"), values)
    return values["id"]


def _insert_audit(database_engine: Engine, execution_id: UUID, user_id: UUID, **overrides: Any) -> UUID:
    values: Dict[str, Any] = {"id": uuid4(), "user_id": user_id, "execution_id": execution_id, "code": "applied", "actor": "system"}
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join(f"CAST(:{k} AS jsonb)" if k == "details" else f":{k}" for k in values)
    with database_engine.begin() as connection:
        connection.execute(text(f"INSERT INTO rule_execution_audit ({columns}) VALUES ({placeholders})"), values)
    return values["id"]


def _insert_goal_transaction(database_engine: Engine, user_id: UUID, goal_id: UUID, **overrides: Any) -> UUID:
    values: Dict[str, Any] = {
        "id": uuid4(), "goal_id": goal_id, "user_id": user_id, "type": "contribution", "amount": Decimal("10.00"),
        "currency": "EUR", "effective_date": date(2026, 10, 20),
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join(f":{k}" for k in values)
    with database_engine.begin() as connection:
        connection.execute(text(f"INSERT INTO goal_transactions ({columns}) VALUES ({placeholders})"), values)
    return values["id"]


def _exec_ok(world: World, **overrides: Any) -> UUID:
    return _insert_execution(world.engine, _execution(world, **overrides))


# ------------------------------------------------------------------
# chain and source
# ------------------------------------------------------------------


def test_revision_chain_and_single_head() -> None:
    script = ScriptDirectory.from_config(Config(str(API_DIR / "alembic.ini")))

    assert script.get_heads() == [E6_REVISION]
    assert script.get_revision(E6_REVISION).down_revision == E4_REVISION


def test_migration_source_scope() -> None:
    source = MIGRATION_PATH.read_text()
    body = source.split("def upgrade", 1)[1].split("def downgrade", 1)[0]

    assert "SET LOCAL" not in source and "SET lock_timeout" not in source
    assert "INSERT INTO" not in body and "DELETE FROM" not in body and "UPDATE " not in body.replace("updated_at", "")
    assert re.findall(r'create_table\(\s*"([a-z_]+)"', source) == [EXECUTIONS, ITEMS, AUDIT]
    touched = set(re.findall(r'op\.(?:create|drop)_table\(\s*"([a-z_]+)"', source))
    assert touched == {EXECUTIONS, ITEMS, AUDIT}  # no rule_alerts, no existing table created or dropped
    assert "ALL TABLES IN SCHEMA" not in source and "GRANT" not in source.replace("REVOKE", "")
    # lock order: goals, accounts, financial_rules, goal_transactions
    locks = re.findall(r'"LOCK TABLE (\w+) IN (\w+(?: \w+)*) MODE"', source)
    assert [name for name, _ in locks[:4]] == ["goals", "accounts", "financial_rules", "goal_transactions"]
    assert [mode for _, mode in locks[:4]] == [
        "SHARE ROW EXCLUSIVE", "SHARE ROW EXCLUSIVE", "SHARE ROW EXCLUSIVE", "ACCESS EXCLUSIVE",
    ]


def test_upgrade_creates_only_the_e6_objects(e4_database: Engine) -> None:
    assert not any(_table_exists(e4_database, t) for t in NEW_TABLES)

    result = _alembic(_url_of(e4_database), "upgrade", E6_REVISION)

    assert result.returncode == 0, result.stderr
    assert _revision(e4_database) == E6_REVISION
    assert all(_table_exists(e4_database, t) for t in NEW_TABLES)
    with e4_database.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM pg_class WHERE relname = :s AND relkind = 'S'"), {"s": SEQUENCE}).scalar_one() == 1
        for absent in ("rule_alerts",):
            assert not _table_exists(e4_database, absent)
        assert connection.execute(text(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'accounts' "
            "AND column_name ILIKE '%floor%'")).scalar_one() == 0
        column = connection.execute(text(
            "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
            "WHERE table_name = 'goal_transactions' AND column_name = 'rule_execution_id'")).one()
    assert tuple(column) == ("uuid", "YES", None)


# ------------------------------------------------------------------
# table shape
# ------------------------------------------------------------------

EXECUTION_COLUMNS = {
    "id": ("uuid", "NO", None, None, None), "user_id": ("uuid", "NO", None, None, None),
    "rule_id": ("uuid", "NO", None, None, None), "rule_version": ("integer", "NO", None, 32, 0),
    "params_snapshot": ("jsonb", "NO", None, None, None), "source_type": ("character varying", "NO", 32, None, None),
    "source_id": ("uuid", "NO", None, None, None), "triggering_event_id": ("uuid", "NO", None, None, None),
    "source_amount": ("numeric", "NO", None, 12, 2), "source_currency": ("character varying", "NO", 3, None, None),
    "source_received_at": ("date", "NO", None, None, None), "source_account_id": ("uuid", "YES", None, None, None),
    "source_income_source": ("character varying", "NO", 20, None, None),
    "capacity_reservable": ("numeric", "YES", None, 18, 2), "capacity_floor": ("numeric", "YES", None, 18, 2),
    "capacity_holds": ("numeric", "YES", None, 18, 2), "status": ("character varying", "NO", 24, None, None),
    "reason_code": ("character varying", "YES", 40, None, None), "hold_sequence": ("bigint", "YES", None, 64, 0),
    "expires_at": ("timestamp with time zone", "YES", None, None, None),
    "decided_at": ("timestamp with time zone", "YES", None, None, None),
    "created_at": ("timestamp with time zone", "NO", None, None, None),
    "updated_at": ("timestamp with time zone", "NO", None, None, None),
}
ITEM_COLUMNS = {
    "id": ("uuid", "NO", None, None, None), "user_id": ("uuid", "NO", None, None, None),
    "execution_id": ("uuid", "NO", None, None, None), "goal_id": ("uuid", "NO", None, None, None),
    "account_id": ("uuid", "NO", None, None, None), "position": ("integer", "NO", None, 32, 0),
    "planned_amount": ("numeric", "NO", None, 12, 2), "applied_amount": ("numeric", "YES", None, 12, 2),
    "goal_transaction_id": ("uuid", "YES", None, None, None),
}
AUDIT_COLUMNS = {
    "id": ("uuid", "NO", None, None, None), "user_id": ("uuid", "NO", None, None, None),
    "execution_id": ("uuid", "NO", None, None, None), "code": ("character varying", "NO", 24, None, None),
    "actor": ("character varying", "NO", 8, None, None), "related_event_id": ("uuid", "YES", None, None, None),
    "details": ("jsonb", "YES", None, None, None), "created_at": ("timestamp with time zone", "NO", None, None, None),
}


def _columns(database_engine: Engine, table: str):
    with database_engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT column_name, data_type, is_nullable, character_maximum_length, numeric_precision, numeric_scale, column_default "
            "FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t"), {"t": table}).all()
    return {r[0]: (r[1], r[2], r[3], r[4], r[5]) for r in rows}, {r[0]: r[6] for r in rows if r[6] is not None}


def test_table_columns_types_nullability_and_defaults(e6_database: Engine) -> None:
    for table, expected, defaults in (
        (EXECUTIONS, EXECUTION_COLUMNS, {"created_at": "now()", "updated_at": "now()"}),
        (ITEMS, ITEM_COLUMNS, {}),
        (AUDIT, AUDIT_COLUMNS, {"created_at": "now()"}),
    ):
        actual, actual_defaults = _columns(e6_database, table)
        assert actual == expected, table
        assert actual_defaults == defaults, table
    # hold_sequence has NO default: only a CONFIRM proposal takes nextval.
    assert "hold_sequence" not in _columns(e6_database, EXECUTIONS)[1]
    assert "currency" not in " ".join(_columns(e6_database, EXECUTIONS)[0]).replace("source_currency", "")


# ------------------------------------------------------------------
# rule_executions checks, key, hold_sequence
# ------------------------------------------------------------------


@pytest.mark.parametrize("status", ["awaiting_confirmation", "executed", "executed_partial", "skipped", "blocked", "rejected", "expired", "cancelled"])
def test_every_committed_execution_status_is_accepted(e6_database: Engine, status: str) -> None:
    _exec_ok(World(e6_database), status=status)


@pytest.mark.parametrize("status", ["pending", "applied", "failed", "processing", "confirmed", "EXECUTED", ""])
def test_other_statuses_are_rejected(e6_database: Engine, status: str) -> None:
    with pytest.raises(IntegrityError) as error:
        _exec_ok(World(e6_database), status=status)
    assert _constraint(error.value) == "ck_rule_executions_status_valid"


def test_rule_version_and_source_type_checks(e6_database: Engine) -> None:
    world = World(e6_database)
    with pytest.raises(IntegrityError) as error:
        _exec_ok(world, rule_version=0)
    assert _constraint(error.value) == "ck_rule_executions_rule_version_valid"
    with pytest.raises(IntegrityError) as error:
        _exec_ok(world, source_type="expense")
    assert _constraint(error.value) == "ck_rule_executions_source_type_valid"


def test_hold_sequence_and_expires_at_are_paired_not_tied_to_status(e6_database: Engine) -> None:
    world = World(e6_database)
    # never a proposal: both NULL, any terminal status
    _exec_ok(world, status="skipped")
    # a proposal that later became terminal keeps both values (not tied to status)
    for status in ("awaiting_confirmation", "executed", "rejected", "expired", "cancelled"):
        _exec_ok(world, status=status, hold_sequence=_next_hold(e6_database), expires_at="2026-11-01T00:00:00Z")
    # an executed row with NULL hold_sequence is valid, and a proposal can be skipped-free
    for bad in ({"hold_sequence": 5}, {"expires_at": "2026-11-01T00:00:00Z"}):
        with pytest.raises(IntegrityError) as error:
            _exec_ok(world, **bad)
        assert _constraint(error.value) == "ck_rule_executions_hold_sequence_expires_at_paired"


def _next_hold(database_engine: Engine) -> int:
    with database_engine.begin() as connection:
        return connection.execute(text(f"SELECT nextval('{SEQUENCE}')")).scalar_one()


def test_hold_sequence_comes_from_the_sequence_is_monotonic_and_gaps_are_harmless(e6_database: Engine) -> None:
    first = _next_hold(e6_database)
    # a rolled-back transaction burns a value: a gap, harmless
    connection = e6_database.connect()
    transaction = connection.begin()
    burned = connection.execute(text(f"SELECT nextval('{SEQUENCE}')")).scalar_one()
    transaction.rollback()
    connection.close()
    second = _next_hold(e6_database)

    assert first < burned < second
    assert second - first >= 2
    world = World(e6_database)
    _exec_ok(world, status="awaiting_confirmation", hold_sequence=first, expires_at="2026-11-01T00:00:00Z")
    with pytest.raises(IntegrityError) as error:  # unique: one proposal per value
        _exec_ok(world, status="awaiting_confirmation", hold_sequence=first, expires_at="2026-11-01T00:00:00Z")
    assert _constraint(error.value) == "uq_rule_executions_hold_sequence"


def test_hold_sequence_is_retained_when_a_proposal_becomes_terminal(e6_database: Engine) -> None:
    world = World(e6_database)
    hold = _next_hold(e6_database)
    execution_id = _exec_ok(world, status="awaiting_confirmation", hold_sequence=hold, expires_at="2026-11-01T00:00:00Z")

    with e6_database.begin() as connection:
        connection.execute(text("UPDATE rule_executions SET status = 'executed', decided_at = now() WHERE id = :i"), {"i": execution_id})

    assert _count(e6_database, "SELECT hold_sequence FROM rule_executions WHERE id = :i", i=execution_id) == hold


def test_the_sequence_is_owned_by_the_column(e6_database: Engine) -> None:
    with e6_database.connect() as connection:
        owner = connection.execute(text(
            "SELECT t.relname, a.attname FROM pg_depend d JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S' "
            "JOIN pg_class t ON t.oid = d.refobjid JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid "
            "WHERE s.relname = :s AND d.deptype = 'a'"), {"s": SEQUENCE}).one()
    assert tuple(owner) == (EXECUTIONS, "hold_sequence")


def test_execution_idempotency_key_excludes_the_rule_version(e6_database: Engine) -> None:
    world = World(e6_database)
    source = uuid4()
    _exec_ok(world, source_id=source, rule_version=1)

    with pytest.raises(IntegrityError) as error:
        _exec_ok(world, source_id=source, rule_version=2)  # a new version cannot re-execute the source
    assert _constraint(error.value) == "uq_rule_executions_user_id_rule_id_source_type_source_id"
    other_rule = _insert_rule(e6_database, _allocation(world.user_id, world.account_id, execution_order=2))
    _insert_execution(e6_database, _execution(world, source_id=source, rule_id=other_rule))  # another rule: fine
    _exec_ok(world, source_id=uuid4())  # another source: fine


def test_capacity_snapshots_are_wider_than_a_canonical_money_row_by_design(e6_database: Engine) -> None:
    # Explicit, documented exception to NUMERIC(12,2) (contract section 19.3):
    # reservable / floor / holds are AGGREGATES (sums over arbitrarily many ledger
    # rows, like AccountResponse.current_balance, which has no max_digits for the
    # same reason), so they can exceed the range of one canonical money row. Every
    # canonical amount column stays NUMERIC(12,2).
    world = World(e6_database)
    wide = Decimal("12345678901.23")  # 11 integer digits: out of range for NUMERIC(12,2)
    execution_id = _exec_ok(world, capacity_reservable=wide, capacity_floor=Decimal("1000.00"), capacity_holds=-wide)

    assert _count(e6_database, "SELECT capacity_reservable FROM rule_executions WHERE id = :i", i=execution_id) == wide
    assert _count(e6_database, "SELECT capacity_holds FROM rule_executions WHERE id = :i", i=execution_id) == -wide

    with pytest.raises(Exception) as error:  # numeric field overflow (DataError), not a silent truncation
        _exec_ok(world, source_amount=wide)
    assert "numeric field overflow" in str(error.value)
    for override in ({"planned_amount": wide}, {"applied_amount": wide}):
        with pytest.raises(Exception) as error:
            _insert_item(e6_database, execution_id, world.user_id, world.goal_id, world.account_id, **override)
        assert "numeric field overflow" in str(error.value)
    actual, _ = _columns(e6_database, EXECUTIONS)
    assert [actual[c][3:] for c in ("capacity_reservable", "capacity_floor", "capacity_holds")] == [(18, 2)] * 3
    assert actual["source_amount"][3:] == (12, 2)


def test_sources_are_soft_references(e6_database: Engine) -> None:
    with e6_database.connect() as connection:
        fks = connection.execute(text(
            "SELECT conname FROM pg_constraint WHERE contype = 'f' AND conrelid = 'public.rule_executions'::regclass")).all()
    assert [r[0] for r in fks] == ["fk_rule_executions_rule_id_user_id"]  # no Income / event FK
    world = World(e6_database)
    _exec_ok(world, source_id=uuid4(), triggering_event_id=uuid4())  # sources need not exist


# ------------------------------------------------------------------
# ownership foreign keys and RESTRICT
# ------------------------------------------------------------------


def test_execution_cannot_reference_another_users_rule(e6_database: Engine) -> None:
    owner, intruder = World(e6_database), uuid4()

    with pytest.raises(IntegrityError) as error:
        _insert_execution(e6_database, _execution(owner, user_id=intruder))

    assert _constraint(error.value) == "fk_rule_executions_rule_id_user_id"


def test_item_foreign_keys_enforce_ownership(e6_database: Engine) -> None:
    owner, other = World(e6_database), World(e6_database)
    execution_id = _exec_ok(owner)

    for kwargs, constraint in (
        ({"user_id": other.user_id, "execution_id": execution_id, "goal_id": other.goal_id, "account_id": other.account_id},
         "fk_rule_execution_items_execution_id_user_id"),
        ({"user_id": owner.user_id, "execution_id": execution_id, "goal_id": other.goal_id, "account_id": owner.account_id},
         "fk_rule_execution_items_goal_id_user_id"),
        ({"user_id": owner.user_id, "execution_id": execution_id, "goal_id": owner.goal_id, "account_id": other.account_id},
         "fk_rule_execution_items_account_id_user_id"),
    ):
        with pytest.raises(IntegrityError) as error:
            _insert_item(e6_database, kwargs.pop("execution_id"), kwargs.pop("user_id"), kwargs.pop("goal_id"), kwargs.pop("account_id"))
        assert _constraint(error.value) == constraint


def test_audit_and_goal_transaction_foreign_keys_enforce_ownership(e6_database: Engine) -> None:
    owner, other = World(e6_database), World(e6_database)
    execution_id = _exec_ok(owner)

    with pytest.raises(IntegrityError) as error:
        _insert_audit(e6_database, execution_id, other.user_id)
    assert _constraint(error.value) == "fk_rule_execution_audit_execution_id_user_id"
    with pytest.raises(IntegrityError) as error:  # another user's goal transaction cannot be linked to the item
        foreign_tx = _insert_goal_transaction(e6_database, other.user_id, other.goal_id)
        _insert_item(e6_database, execution_id, owner.user_id, owner.goal_id, owner.account_id,
                     goal_transaction_id=foreign_tx, applied_amount=Decimal("10.00"))
    assert _constraint(error.value) == "fk_rule_execution_items_goal_transaction_id_user_id"
    with pytest.raises(IntegrityError) as error:
        _insert_goal_transaction(e6_database, other.user_id, other.goal_id, account_id=other.account_id,
                                 rule_execution_id=execution_id)
    assert _constraint(error.value) == "fk_goal_transactions_rule_execution_id_user_id"


def test_execution_history_is_restricted_against_deletes(e6_database: Engine) -> None:
    world = World(e6_database)
    execution_id = _exec_ok(world)
    transaction_id = _insert_goal_transaction(
        e6_database, world.user_id, world.goal_id, account_id=world.account_id, rule_execution_id=execution_id,
    )
    _insert_item(e6_database, execution_id, world.user_id, world.goal_id, world.account_id,
                 goal_transaction_id=transaction_id, applied_amount=Decimal("10.00"))
    _insert_audit(e6_database, execution_id, world.user_id)

    def blocked(sql: str, constraint: Any, **params: Any) -> None:
        accepted = constraint if isinstance(constraint, (set, frozenset)) else {constraint}
        with pytest.raises(IntegrityError) as error:
            with e6_database.begin() as connection:
                connection.execute(text(sql), params)
        # A violated ON DELETE RESTRICT is reported as 23001 (restrict_violation) or
        # 23503 (foreign_key_violation) depending on the PostgreSQL version
        # (observed: 18 -> 23001, 16 -> 23503); both mean the FK held.
        assert error.value.orig.pgcode in RESTRICT_SQLSTATES, error.value.orig.pgcode
        assert constraint is None or _constraint(error.value) in accepted

    blocked("DELETE FROM financial_rules WHERE id = :i", "fk_rule_executions_rule_id_user_id", i=world.rule_id)
    # the execution is referenced by an item, an audit row AND a rule-generated transaction;
    # PostgreSQL reports whichever RESTRICT it checks first
    blocked("DELETE FROM rule_executions WHERE id = :i",
            {"fk_goal_transactions_rule_execution_id_user_id", "fk_rule_execution_items_execution_id_user_id",
             "fk_rule_execution_audit_execution_id_user_id"}, i=execution_id)
    blocked("DELETE FROM goal_transactions WHERE id = :i", "fk_rule_execution_items_goal_transaction_id_user_id", i=transaction_id)
    blocked("DELETE FROM goals WHERE id = :i", None, i=world.goal_id)  # several FKs reference the goal
    blocked("DELETE FROM accounts WHERE id = :i", None, i=world.account_id)  # several FKs reference the account


def test_item_and_audit_block_execution_delete_without_transactions(e6_database: Engine) -> None:
    world = World(e6_database)
    execution_id = _exec_ok(world)
    _insert_item(e6_database, execution_id, world.user_id, world.goal_id, world.account_id)

    with pytest.raises(IntegrityError) as error:
        with e6_database.begin() as connection:
            connection.execute(text("DELETE FROM rule_executions WHERE id = :i"), {"i": execution_id})
    assert _constraint(error.value) == "fk_rule_execution_items_execution_id_user_id"

    with e6_database.begin() as connection:
        connection.execute(text("DELETE FROM rule_execution_items WHERE execution_id = :i"), {"i": execution_id})
    _insert_audit(e6_database, execution_id, world.user_id)
    with pytest.raises(IntegrityError) as error:
        with e6_database.begin() as connection:
            connection.execute(text("DELETE FROM rule_executions WHERE id = :i"), {"i": execution_id})
    assert _constraint(error.value) == "fk_rule_execution_audit_execution_id_user_id"


def test_item_goal_and_account_references_are_restricted(e6_database: Engine) -> None:
    world = World(e6_database)
    second_goal = _goal(e6_database, world.user_id, 2)
    second_account = _account(e6_database, world.user_id)
    execution_id = _exec_ok(world)
    _insert_item(e6_database, execution_id, world.user_id, second_goal, second_account)

    for table, key, constraint in (
        ("goals", second_goal, "fk_rule_execution_items_goal_id_user_id"),
        ("accounts", second_account, "fk_rule_execution_items_account_id_user_id"),
    ):
        with pytest.raises(IntegrityError) as error:
            with e6_database.begin() as connection:
                connection.execute(text(f"DELETE FROM {table} WHERE id = :i"), {"i": key})
        assert _constraint(error.value) == constraint


# ------------------------------------------------------------------
# items and audit
# ------------------------------------------------------------------


def test_item_value_checks_and_uniques(e6_database: Engine) -> None:
    world = World(e6_database)
    second_goal = _goal(e6_database, world.user_id, 2)
    execution_id = _exec_ok(world)
    _insert_item(e6_database, execution_id, world.user_id, world.goal_id, world.account_id, position=3, planned_amount=Decimal("0.01"))

    for overrides, constraint in (
        ({"planned_amount": Decimal("0.00")}, "ck_rule_execution_items_planned_amount_positive"),
        ({"planned_amount": Decimal("-1.00")}, "ck_rule_execution_items_planned_amount_positive"),
        ({"applied_amount": Decimal("0.00")}, "ck_rule_execution_items_applied_amount_positive"),
        ({"position": -1}, "ck_rule_execution_items_position_non_negative"),
    ):
        with pytest.raises(IntegrityError) as error:
            _insert_item(e6_database, execution_id, world.user_id, second_goal, world.account_id, **overrides)
        assert _constraint(error.value) == constraint
    with pytest.raises(IntegrityError) as error:  # one item per Goal per execution
        _insert_item(e6_database, execution_id, world.user_id, world.goal_id, world.account_id)
    assert _constraint(error.value) == "uq_rule_execution_items_execution_id_goal_id"
    _insert_item(e6_database, execution_id, world.user_id, second_goal, world.account_id, position=3)  # duplicate position is fine
    assert _count(e6_database, "SELECT planned_amount FROM rule_execution_items WHERE position = 3 AND goal_id = :g", g=world.goal_id) == Decimal("0.01")


def test_item_to_goal_transaction_link_is_exactly_once(e6_database: Engine) -> None:
    world = World(e6_database)
    second_goal = _goal(e6_database, world.user_id, 2)
    execution_id = _exec_ok(world)
    transaction_id = _insert_goal_transaction(
        e6_database, world.user_id, world.goal_id, account_id=world.account_id, rule_execution_id=execution_id,
    )
    _insert_item(e6_database, execution_id, world.user_id, world.goal_id, world.account_id,
                 goal_transaction_id=transaction_id, applied_amount=Decimal("10.00"))

    with pytest.raises(IntegrityError) as error:  # one transaction can be linked from one item only
        _insert_item(e6_database, execution_id, world.user_id, second_goal, world.account_id,
                     goal_transaction_id=transaction_id, applied_amount=Decimal("10.00"))
    assert _constraint(error.value) == "uq_rule_execution_items_goal_transaction_id"
    with pytest.raises(IntegrityError) as error:  # a linked transaction needs an applied amount
        _insert_item(e6_database, execution_id, world.user_id, second_goal, world.account_id, goal_transaction_id=_insert_goal_transaction(
            e6_database, world.user_id, second_goal, account_id=world.account_id, rule_execution_id=execution_id))
    assert _constraint(error.value) == "ck_rule_execution_items_transaction_requires_applied_amount"
    # planned-only items (a pending proposal / skipped plan) have no link
    _insert_item(e6_database, execution_id, world.user_id, _goal(e6_database, world.user_id, 3), world.account_id)


@pytest.mark.parametrize("code", ["proposed", "applied", "applied_partial", "skipped", "blocked", "confirmed", "rejected",
                                  "expired", "cancelled", "source_changed", "source_deleted"])
def test_approved_audit_codes_are_accepted(e6_database: Engine, code: str) -> None:
    world = World(e6_database)
    execution_id = _exec_ok(world)

    _insert_audit(e6_database, execution_id, world.user_id, code=code, actor="user", related_event_id=uuid4(),
                  details=json.dumps({"reason": "x"}))


@pytest.mark.parametrize("overrides, constraint", [
    ({"code": "executed"}, "ck_rule_execution_audit_code_valid"),
    ({"code": "superseded"}, "ck_rule_execution_audit_code_valid"),
    ({"actor": "admin"}, "ck_rule_execution_audit_actor_valid"),
])
def test_other_audit_values_are_rejected(e6_database: Engine, overrides: Dict[str, Any], constraint: str) -> None:
    world = World(e6_database)
    execution_id = _exec_ok(world)

    with pytest.raises(IntegrityError) as error:
        _insert_audit(e6_database, execution_id, world.user_id, **overrides)
    assert _constraint(error.value) == constraint


# ------------------------------------------------------------------
# goal_transactions provenance CHECKs
# ------------------------------------------------------------------


def test_linked_origin_checks_accept_every_legacy_shape_and_the_rule_shape(e6_database: Engine) -> None:
    world = World(e6_database)
    execution_id = _exec_ok(world)

    _insert_goal_transaction(e6_database, world.user_id, world.goal_id)                                       # tracked, no key
    _insert_goal_transaction(e6_database, world.user_id, world.goal_id, client_request_id=uuid4())            # tracked with key
    _insert_goal_transaction(e6_database, world.user_id, world.goal_id, account_id=world.account_id,
                             client_request_id=uuid4())                                                       # manual linked
    _insert_goal_transaction(e6_database, world.user_id, world.goal_id, type="withdrawal", account_id=world.account_id,
                             client_request_id=uuid4())                                                       # manual release
    _insert_goal_transaction(e6_database, world.user_id, world.goal_id, type="opening_balance", effective_date=None)
    _insert_goal_transaction(e6_database, world.user_id, world.goal_id, account_id=world.account_id,
                             rule_execution_id=execution_id)                                                  # rule-generated


@pytest.mark.parametrize("overrides, constraint", [
    ({"account_id": "A"}, ORIGIN_CHECK),                                  # linked with neither key nor execution
    ({"account_id": "A", "client_request_id": "K", "rule_execution_id": "E"}, EXCLUSIVE_CHECK),
    ({"client_request_id": "K", "rule_execution_id": "E"}, EXCLUSIVE_CHECK),
    ({"type": "withdrawal", "account_id": "A", "rule_execution_id": "E"}, SHAPE_CHECK),
    ({"rule_execution_id": "E"}, SHAPE_CHECK),                           # rule row without an Account
])
def test_provenance_check_violations(e6_database: Engine, overrides: Dict[str, Any], constraint: str) -> None:
    world = World(e6_database)
    execution_id = _exec_ok(world)
    mapping = {"A": world.account_id, "K": uuid4(), "E": execution_id}
    values = {k: mapping.get(v, v) if isinstance(v, str) and v in mapping else v for k, v in overrides.items()}

    with pytest.raises(IntegrityError) as error:
        _insert_goal_transaction(e6_database, world.user_id, world.goal_id, **values)

    assert _constraint(error.value) == constraint


def test_the_old_check_is_replaced(e6_database: Engine) -> None:
    with e6_database.connect() as connection:
        names = {r[0] for r in connection.execute(text(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'public.goal_transactions'::regclass AND contype = 'c'"))}
    assert OLD_CHECK not in names
    assert {ORIGIN_CHECK, EXCLUSIVE_CHECK, SHAPE_CHECK} <= names
    assert "ck_goal_transactions_linked_requires_effective_date" in names  # still applies to rule rows


def test_rule_generated_row_still_needs_an_effective_date(e6_database: Engine) -> None:
    world = World(e6_database)
    execution_id = _exec_ok(world)

    with pytest.raises(IntegrityError) as error:
        _insert_goal_transaction(e6_database, world.user_id, world.goal_id, account_id=world.account_id,
                                 rule_execution_id=execution_id, effective_date=None)

    assert _constraint(error.value) == "ck_goal_transactions_linked_requires_effective_date"


def test_the_client_key_unique_still_allows_any_number_of_rule_rows(e6_database: Engine) -> None:
    world = World(e6_database)
    execution_id = _exec_ok(world)
    for _ in range(3):
        _insert_goal_transaction(e6_database, world.user_id, world.goal_id, account_id=world.account_id, rule_execution_id=execution_id)

    assert _count(e6_database, "SELECT count(*) FROM goal_transactions WHERE rule_execution_id = :e", e=execution_id) == 3


# ------------------------------------------------------------------
# existing data, downgrade guard, cycle
# ------------------------------------------------------------------


def _seed_legacy(database_engine: Engine) -> World:
    world = World(database_engine)
    with database_engine.begin() as connection:
        for values in (
            {"client_request_id": None, "account_id": None},
            {"client_request_id": uuid4(), "account_id": None},
            {"client_request_id": uuid4(), "account_id": world.account_id},
        ):
            connection.execute(text(
                "INSERT INTO goal_transactions (id, goal_id, user_id, type, amount, currency, effective_date, client_request_id, account_id) "
                "VALUES (:i, :g, :u, 'contribution', 10.00, 'EUR', '2026-10-01', :c, :a)"),
                {"i": uuid4(), "g": world.goal_id, "u": world.user_id, "c": values["client_request_id"], "a": values["account_id"]})
    return world


def test_existing_rows_are_unchanged_by_upgrade_and_downgrade(e4_database: Engine) -> None:
    _seed_legacy(e4_database)
    tables = ("accounts", "goals", "budgets", "income", "financial_events", "financial_rules", "financial_rule_goal_targets")
    before = {t: _digest(e4_database, t) for t in tables}
    legacy_before = _count(e4_database, "SELECT md5(string_agg(g::text, '|' ORDER BY id)) FROM goal_transactions g")
    url = _url_of(e4_database)

    assert _alembic(url, "upgrade", E6_REVISION).returncode == 0
    assert {t: _digest(e4_database, t) for t in tables} == before
    with e4_database.connect() as connection:
        # every pre-E6 row is preserved; only the new column exists, NULL for all
        assert connection.execute(text("SELECT count(*) FROM goal_transactions WHERE rule_execution_id IS NOT NULL")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM goal_transactions")).scalar_one() == 3
    assert all(_count(e4_database, f"SELECT count(*) FROM {t}") == 0 for t in NEW_TABLES)

    assert _alembic(url, "downgrade", E4_REVISION).returncode == 0
    assert {t: _digest(e4_database, t) for t in tables} == before
    assert _count(e4_database, "SELECT md5(string_agg(g::text, '|' ORDER BY id)) FROM goal_transactions g") == legacy_before


def test_downgrade_refuses_to_destroy_execution_history(e6_database: Engine) -> None:
    world = World(e6_database)
    _exec_ok(world)

    result = _alembic(_url_of(e6_database), "downgrade", E4_REVISION)

    assert result.returncode != 0
    assert "Refusing to downgrade" in result.stderr
    assert _revision(e6_database) == E6_REVISION
    assert _table_exists(e6_database, EXECUTIONS)
    assert _count(e6_database, "SELECT count(*) FROM rule_executions") == 1


def test_downgrade_refuses_when_a_rule_generated_transaction_exists(e6_database: Engine) -> None:
    world = World(e6_database)
    execution_id = _exec_ok(world)
    _insert_goal_transaction(e6_database, world.user_id, world.goal_id, account_id=world.account_id, rule_execution_id=execution_id)
    with e6_database.begin() as connection:
        connection.execute(text("DELETE FROM rule_executions WHERE false"))

    result = _alembic(_url_of(e6_database), "downgrade", E4_REVISION)

    assert result.returncode != 0 and "Refusing to downgrade" in result.stderr
    assert _revision(e6_database) == E6_REVISION


def test_upgrade_downgrade_upgrade_cycle(e4_database: Engine) -> None:
    url = _url_of(e4_database)

    assert _alembic(url, "upgrade", E6_REVISION).returncode == 0
    downgrade = _alembic(url, "downgrade", E4_REVISION)
    assert downgrade.returncode == 0, downgrade.stderr
    assert _revision(e4_database) == E4_REVISION
    with e4_database.connect() as connection:
        leftovers = connection.execute(text(
            "SELECT relname FROM pg_class WHERE relname LIKE 'rule_execution%' OR relname LIKE '%rule_execution%' "
            "OR relname = 'uq_goal_transactions_id_user_id'")).all()
        constraints = {r[0] for r in connection.execute(text(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'public.goal_transactions'::regclass"))}
        column = connection.execute(text(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = 'goal_transactions' AND column_name = 'rule_execution_id'")).scalar_one()
        sequences = connection.execute(text("SELECT count(*) FROM pg_class WHERE relname = :s"), {"s": SEQUENCE}).scalar_one()
    assert leftovers == [] and column == 0 and sequences == 0
    assert OLD_CHECK in constraints
    assert not {ORIGIN_CHECK, EXCLUSIVE_CHECK, SHAPE_CHECK, "uq_goal_transactions_id_user_id"} & constraints
    assert _table_exists(e4_database, "financial_rules") and _table_exists(e4_database, "financial_events")

    assert _alembic(url, "upgrade", E6_REVISION).returncode == 0
    assert _revision(e4_database) == E6_REVISION
    _exec_ok(World(e4_database))


# ------------------------------------------------------------------
# Data API security
# ------------------------------------------------------------------


def test_migration_revokes_with_the_established_guarded_pattern() -> None:
    source = MIGRATION_PATH.read_text()

    for constant in ('RULE_EXECUTIONS_TABLE_SQL = "public.rule_executions"',
                     'RULE_EXECUTION_ITEMS_TABLE_SQL = "public.rule_execution_items"',
                     'RULE_EXECUTION_AUDIT_TABLE_SQL = "public.rule_execution_audit"'):
        assert constant in source
    assert "REVOKE ALL PRIVILEGES ON TABLE %s FROM %I" in source
    assert "REVOKE ALL PRIVILEGES ON SEQUENCE" in source
    assert "ARRAY['anon', 'authenticated', 'service_role']" in source
    assert "SELECT 1 FROM pg_roles WHERE rolname = target_role" in source


def test_revoke_takes_effect_against_default_privileges_granted_to_data_api_roles(e4_database: Engine) -> None:
    created_roles: List[str] = []
    admin = _admin_engine()
    database_name = e4_database.url.database
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
        with e4_database.begin() as connection:
            connection.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {grantees}"))
            connection.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {grantees}"))
            connection.execute(text("CREATE TABLE public.control_table (id integer)"))
            connection.execute(text("CREATE SEQUENCE public.control_sequence"))

        result = _alembic(_url_of(e4_database), "upgrade", E6_REVISION)
        assert result.returncode == 0, result.stderr

        with e4_database.connect() as connection:
            for role in DATA_API_ROLES:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert connection.execute(text("SELECT has_table_privilege(:r, 'public.control_table', :p)"),
                                              {"r": role, "p": privilege}).scalar_one() is True, ("control", role, privilege)
                    for table in NEW_TABLES:
                        assert connection.execute(text("SELECT has_table_privilege(:r, :t, :p)"),
                                                  {"r": role, "t": f"public.{table}", "p": privilege}).scalar_one() is False, (role, table, privilege)
                for privilege in ("USAGE", "SELECT", "UPDATE"):
                    assert connection.execute(text("SELECT has_sequence_privilege(:r, 'public.control_sequence', :p)"),
                                              {"r": role, "p": privilege}).scalar_one() is True, ("control", role, privilege)
                    assert connection.execute(text("SELECT has_sequence_privilege(:r, :s, :p)"),
                                              {"r": role, "s": f"public.{SEQUENCE}", "p": privilege}).scalar_one() is False, (role, privilege)
    finally:
        e4_database.dispose()
        try:
            if created_roles:
                _drop_database(database_name)
                with admin.connect() as connection:
                    for role in created_roles:
                        connection.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        finally:
            admin.dispose()


# ------------------------------------------------------------------
# ORM mapping, drift and the schema-only boundary
# ------------------------------------------------------------------


def test_orm_metadata_matches_the_e6_schema_exactly(e6_database: Engine) -> None:
    import_database_models()
    assert all(t in Base.metadata.tables for t in NEW_TABLES)

    with e6_database.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    # Since VF-020E7 the ORM maps every E6 object, including the
    # goal_transactions column, keys and CHECKs: no difference remains.
    assert differences == []
    assert exclude_stages_after(differences, E6_REVISION) == []


def test_older_revisions_expect_the_e6_objects_only_through_the_drift_helper(e4_database: Engine) -> None:
    import_database_models()
    with e4_database.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences  # the ORM already knows the E6 objects
    assert exclude_stages_after(differences, E4_REVISION) == []


def test_goal_transaction_model_maps_the_e6_execution_link() -> None:
    from app.modules.goals.goal_transaction_models import GoalTransactionModel

    table = GoalTransactionModel.__table__
    assert "rule_execution_id" in table.c
    assert table.c.rule_execution_id.nullable is True
    constraint_names = {constraint.name for constraint in table.constraints}
    assert {
        "ck_goal_transactions_linked_requires_origin",
        "ck_goal_transactions_origin_exclusive",
        "ck_goal_transactions_rule_execution_shape",
        "uq_goal_transactions_id_user_id",
        "fk_goal_transactions_rule_execution_id_user_id",
    } <= constraint_names
    assert OLD_CHECK not in constraint_names
