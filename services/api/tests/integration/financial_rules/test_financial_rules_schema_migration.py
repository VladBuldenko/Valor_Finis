import hashlib
import os
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
from uuid import UUID, uuid4

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

# VF-020E4 schema-expand tests (revision 861064d31463): financial_rules,
# financial_rule_goal_targets and UNIQUE (budgets.id, budgets.user_id).
#
# They run the REAL Alembic CLI against throwaway *_test databases cloned from
# a template migrated to the E2 revision (the C1/D2/D5/E2 pattern); every
# database name ends in "_test", passes the project's safety guard and is
# dropped afterwards. The shared valor_test database is not migrated by these
# tests, and no production database or credential is ever involved.

API_DIR = Path(__file__).resolve().parents[3]
APP_DIR = API_DIR / "app"
E2_REVISION = "115998e2e795"
E4_REVISION = "861064d31463"
MIGRATION_PATH = API_DIR / "alembic" / "versions" / f"{E4_REVISION}_add_financial_rules.py"

RULES = "financial_rules"
TARGETS = "financial_rule_goal_targets"
DATA_API_ROLES = ("anon", "authenticated", "service_role")

ALL_INCOME_SOURCES = ["salary", "freelance", "refund", "gift", "other"]


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


def _table_exists(database_engine: Engine, table: str) -> bool:
    with database_engine.connect() as connection:
        return connection.execute(
            text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"public.{table}"},
        ).scalar_one()


@pytest.fixture(scope="module")
def e2_template() -> Generator[str, None, None]:
    name = f"vf020e4_tpl_{uuid4().hex[:10]}_test"
    url = _create_database(name)
    try:
        result = _alembic(url, "upgrade", E2_REVISION)
        assert result.returncode == 0, result.stderr
        yield name
    finally:
        _drop_database(name)


@pytest.fixture
def e2_database(e2_template: str) -> Generator[Engine, None, None]:
    name = f"vf020e4_{uuid4().hex[:10]}_test"
    url = _create_database(name, template=e2_template)
    database_engine = create_engine(url)
    try:
        yield database_engine
    finally:
        database_engine.dispose()
        _drop_database(name)


@pytest.fixture
def e4_database(e2_database: Engine) -> Engine:
    result = _alembic(_url_of(e2_database), "upgrade", E4_REVISION)
    assert result.returncode == 0, result.stderr
    return e2_database


# ---------- seed helpers (raw SQL, no ORM mapping of the new tables) ----------


def _account(database_engine: Engine, user_id: UUID, currency: str = "EUR", status: str = "active") -> UUID:
    account_id = uuid4()
    with database_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO accounts (id, user_id, name, type, currency, status) VALUES (:i, :u, 'A', 'checking', :c, :s)"),
            {"i": account_id, "u": user_id, "c": currency, "s": status},
        )
    return account_id


def _goal(database_engine: Engine, user_id: UUID, rank: int = 1) -> UUID:
    goal_id = uuid4()
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO goals (id, user_id, name, target_amount, currency, status, priority_rank) "
                "VALUES (:i, :u, 'g', 100, 'EUR', 'active', :r)"
            ),
            {"i": goal_id, "u": user_id, "r": rank},
        )
    return goal_id


def _budget(database_engine: Engine, user_id: UUID, name: str = "b") -> UUID:
    budget_id = uuid4()
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO budgets (id, user_id, name, limit_amount, currency, period, start_date) "
                "VALUES (:i, :u, :n, 100, 'EUR', 'monthly', '2026-01-01')"
            ),
            {"i": budget_id, "u": user_id, "n": name},
        )
    return budget_id


def _allocation(user_id: UUID, account_id: UUID, **overrides: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "id": uuid4(), "user_id": user_id, "name": "Save", "rule_type": "INCOME_ALLOCATION",
        "source_account_id": account_id, "execution_mode": "AUTO", "execution_order": 1,
        "policy": "FIXED_PER_GOAL", "income_sources": ["salary"], "cap_at_target": True,
        "allow_partial": False,
    }
    values.update(overrides)
    return values


def _floor(user_id: UUID, account_id: UUID, **overrides: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "id": uuid4(), "user_id": user_id, "name": "Floor", "rule_type": "MINIMUM_UNALLOCATED_FLOOR",
        "source_account_id": account_id, "floor_amount": Decimal("1000.00"),
    }
    values.update(overrides)
    return values


def _overcommitment(user_id: UUID, account_id: UUID, **overrides: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "id": uuid4(), "user_id": user_id, "name": "Over", "rule_type": "OVERCOMMITMENT_ALERT",
        "source_account_id": account_id,
    }
    values.update(overrides)
    return values


def _budget_alert(user_id: UUID, budget_id: UUID, **overrides: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "id": uuid4(), "user_id": user_id, "name": "Budget", "rule_type": "BUDGET_ALERT",
        "budget_id": budget_id,
    }
    values.update(overrides)
    return values


def _insert_rule(database_engine: Engine, values: Dict[str, Any]) -> UUID:
    columns = ", ".join(values)
    placeholders = ", ".join(f":{name}" for name in values)
    with database_engine.begin() as connection:
        connection.execute(text(f"INSERT INTO financial_rules ({columns}) VALUES ({placeholders})"), values)
    return values["id"]


def _insert_target(
    database_engine: Engine, rule_id: UUID, user_id: UUID, goal_id: UUID,
    position: int = 0, amount: Optional[Decimal] = None,
) -> UUID:
    target_id = uuid4()
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO financial_rule_goal_targets (id, rule_id, user_id, goal_id, amount_or_cap, position) "
                "VALUES (:i, :r, :u, :g, :a, :p)"
            ),
            {"i": target_id, "r": rule_id, "u": user_id, "g": goal_id, "a": amount, "p": position},
        )
    return target_id


def _constraint(error: IntegrityError) -> Optional[str]:
    return error.orig.diag.constraint_name


def _count(database_engine: Engine, sql: str, **params: Any) -> int:
    with database_engine.connect() as connection:
        return connection.execute(text(sql), params).scalar_one()


# ------------------------------------------------------------------
# A. chain
# ------------------------------------------------------------------


def test_revision_chain_and_single_head() -> None:
    script = ScriptDirectory.from_config(Config(str(API_DIR / "alembic.ini")))

    heads = script.get_heads()
    assert len(heads) == 1
    assert script.get_revision(E4_REVISION).down_revision == E2_REVISION
    # E4 stays in the ancestry of the single head (later stages build on it).
    assert E4_REVISION in {r.revision for r in script.walk_revisions(base="base", head=heads[0])}


def test_migration_source_has_no_lock_timeout_and_no_data_changes() -> None:
    source = MIGRATION_PATH.read_text()
    body = source.split("def upgrade", 1)[1]

    assert "SET LOCAL" not in source and "SET lock_timeout" not in source
    assert "INSERT INTO" not in body and "DELETE FROM" not in body
    assert "UPDATE " not in body.replace("updated_at", "")
    created_tables = re.findall(r'create_table\(\s*"([a-z_]+)"', source)
    assert created_tables == [RULES, TARGETS]
    assert not re.findall(r'sa\.Column\(\s*"(rule_execution_id|hold_sequence|currency)"', source)
    # GOAL_DEADLINE_ALERT is not a supported type: it never appears as a quoted literal.
    assert "'GOAL_DEADLINE_ALERT'" not in source


def test_upgrade_creates_only_the_e4_objects(e2_database: Engine) -> None:
    assert not _table_exists(e2_database, RULES) and not _table_exists(e2_database, TARGETS)

    result = _alembic(_url_of(e2_database), "upgrade", E4_REVISION)

    assert result.returncode == 0, result.stderr
    assert _revision(e2_database) == E4_REVISION
    assert _table_exists(e2_database, RULES) and _table_exists(e2_database, TARGETS)
    for absent in ("rule_alerts", "rule_executions", "rule_execution_items", "rule_execution_audit"):
        assert not _table_exists(e2_database, absent)
    with e2_database.connect() as connection:
        assert not connection.execute(
            text(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND "
                "((table_name = 'accounts' AND column_name ILIKE '%floor%') OR "
                "(table_name = 'goal_transactions' AND column_name = 'rule_execution_id'))"
            )
        ).scalar_one()


# ------------------------------------------------------------------
# B. table shape
# ------------------------------------------------------------------

RULE_COLUMNS = {
    "id": ("uuid", "NO", None, None, None),
    "user_id": ("uuid", "NO", None, None, None),
    "name": ("character varying", "NO", 150, None, None),
    "description": ("character varying", "YES", 255, None, None),
    "rule_type": ("character varying", "NO", 32, None, None),
    "status": ("character varying", "NO", 16, None, None),
    "version": ("integer", "NO", None, 32, 0),
    "active_since": ("timestamp with time zone", "YES", None, None, None),
    "source_account_id": ("uuid", "YES", None, None, None),
    "budget_id": ("uuid", "YES", None, None, None),
    "execution_mode": ("character varying", "YES", 16, None, None),
    "execution_order": ("integer", "YES", None, 32, 0),
    "effective_from": ("date", "YES", None, None, None),
    "policy": ("character varying", "YES", 40, None, None),
    "percent": ("numeric", "YES", None, 5, 2),
    "cap_at_target": ("boolean", "YES", None, None, None),
    "allow_partial": ("boolean", "YES", None, None, None),
    "income_sources": ("ARRAY", "YES", None, None, None),
    "floor_amount": ("numeric", "YES", None, 12, 2),
    "created_at": ("timestamp with time zone", "NO", None, None, None),
    "updated_at": ("timestamp with time zone", "NO", None, None, None),
}
TARGET_COLUMNS = {
    "id": ("uuid", "NO", None, None, None),
    "rule_id": ("uuid", "NO", None, None, None),
    "user_id": ("uuid", "NO", None, None, None),
    "goal_id": ("uuid", "NO", None, None, None),
    "amount_or_cap": ("numeric", "YES", None, 12, 2),
    "position": ("integer", "NO", None, 32, 0),
}


def _columns(database_engine: Engine, table: str):
    with database_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT column_name, data_type, is_nullable, character_maximum_length, numeric_precision, "
                "numeric_scale, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t"
            ),
            {"t": table},
        ).all()
    return (
        {r[0]: (r[1], r[2], r[3], r[4], r[5]) for r in rows},
        {r[0]: r[6] for r in rows if r[6] is not None},
    )


def test_financial_rules_columns_types_nullability_and_defaults(e4_database: Engine) -> None:
    actual, defaults = _columns(e4_database, RULES)

    assert actual == RULE_COLUMNS
    assert defaults == {
        "status": "'draft'::character varying", "version": "1",
        "created_at": "now()", "updated_at": "now()",
    }
    assert "currency" not in actual and not any("currency" in name for name in actual)


def test_goal_targets_columns_types_nullability_and_defaults(e4_database: Engine) -> None:
    actual, defaults = _columns(e4_database, TARGETS)

    assert actual == TARGET_COLUMNS
    assert defaults == {}
    assert "fixed_amount" not in actual and "cap_amount" not in actual and "priority_rank" not in actual


def test_new_rule_defaults_to_draft_version_one(e4_database: Engine) -> None:
    user_id = uuid4()
    rule_id = _insert_rule(e4_database, _floor(user_id, _account(e4_database, user_id)))

    with e4_database.connect() as connection:
        row = connection.execute(
            text("SELECT status, version, active_since, created_at IS NOT NULL FROM financial_rules WHERE id = :i"),
            {"i": rule_id},
        ).one()
    assert tuple(row) == ("draft", 1, None, True)


# ------------------------------------------------------------------
# C / D. enumerations and value checks
# ------------------------------------------------------------------


def test_the_four_rule_types_are_accepted(e4_database: Engine) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)
    other_account = _account(e4_database, user_id)
    third_account = _account(e4_database, user_id)
    budget_id = _budget(e4_database, user_id)

    _insert_rule(e4_database, _allocation(user_id, account_id))
    _insert_rule(e4_database, _floor(user_id, other_account))
    _insert_rule(e4_database, _overcommitment(user_id, third_account))
    _insert_rule(e4_database, _budget_alert(user_id, budget_id))

    assert _count(e4_database, "SELECT count(*) FROM financial_rules WHERE user_id = :u", u=user_id) == 4


@pytest.mark.parametrize("rule_type", ["GOAL_DEADLINE_ALERT", "SOMETHING_ELSE", "income_allocation", ""])
def test_unsupported_rule_types_are_rejected(e4_database: Engine, rule_type: str) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)

    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, _floor(user_id, account_id, rule_type=rule_type))

    assert _constraint(error.value) == "ck_financial_rules_rule_type_valid"


@pytest.mark.parametrize("status", ["draft", "enabled", "paused", "disabled"])
def test_statuses_are_accepted(e4_database: Engine, status: str) -> None:
    user_id = uuid4()
    _insert_rule(e4_database, _floor(user_id, _account(e4_database, user_id), status=status))


@pytest.mark.parametrize("status", ["active", "archived", "pending", "ENABLED", ""])
def test_invalid_statuses_are_rejected(e4_database: Engine, status: str) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)

    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, _floor(user_id, account_id, status=status))

    assert _constraint(error.value) == "ck_financial_rules_status_valid"


@pytest.mark.parametrize("mode, accepted", [("AUTO", True), ("CONFIRM", True), ("MANUAL", False), ("auto", False)])
def test_execution_mode_values(e4_database: Engine, mode: str, accepted: bool) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)
    values = _allocation(user_id, account_id, execution_mode=mode)

    if accepted:
        _insert_rule(e4_database, values)
        return
    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, values)
    assert _constraint(error.value) == "ck_financial_rules_execution_mode_valid"


@pytest.mark.parametrize(
    "policy, accepted",
    [("FIXED_PER_GOAL", True), ("PERCENT_OF_INCOME_WATERFALL", True), ("PROPORTIONAL", False), ("fixed_per_goal", False)],
)
def test_policy_values(e4_database: Engine, policy: str, accepted: bool) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)
    values = _allocation(user_id, account_id, policy=policy)

    if accepted:
        _insert_rule(e4_database, values)
        return
    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, values)
    assert _constraint(error.value) == "ck_financial_rules_policy_valid"


@pytest.mark.parametrize(
    "percent, accepted",
    [("0.01", True), ("20.00", True), ("100.00", True), ("0", False), ("0.00", False), ("-1", False), ("100.01", False), ("250", False)],
)
def test_percent_range(e4_database: Engine, percent: str, accepted: bool) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)
    values = _allocation(user_id, account_id, policy="PERCENT_OF_INCOME_WATERFALL", percent=Decimal(percent))

    if accepted:
        rule_id = _insert_rule(e4_database, values)
        stored = _count(e4_database, "SELECT percent FROM financial_rules WHERE id = :i", i=rule_id)
        assert stored == Decimal(percent)
        return
    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, values)
    assert _constraint(error.value) == "ck_financial_rules_percent_valid"


@pytest.mark.parametrize(
    "sources, accepted",
    [
        (["salary"], True), (ALL_INCOME_SOURCES, True), (["refund", "gift"], True),
        (["bonus"], False), (["salary", "bonus"], False), ([], False), (["Salary"], False),
    ],
)
def test_income_sources_are_a_non_empty_subset_of_the_closed_set(
    e4_database: Engine, sources: List[str], accepted: bool,
) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)
    values = _allocation(user_id, account_id, income_sources=sources)

    if accepted:
        _insert_rule(e4_database, values)
        return
    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, values)
    assert _constraint(error.value) == "ck_financial_rules_income_sources_valid"


@pytest.mark.parametrize("amount, accepted", [("0.00", True), ("4200.00", True), ("-0.01", False)])
def test_floor_amount_is_non_negative(e4_database: Engine, amount: str, accepted: bool) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)
    values = _floor(user_id, account_id, floor_amount=Decimal(amount))

    if accepted:
        _insert_rule(e4_database, values)
        return
    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, values)
    assert _constraint(error.value) == "ck_financial_rules_floor_amount_valid"


def test_version_must_be_at_least_one(e4_database: Engine) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)

    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, _floor(user_id, account_id, version=0))

    assert _constraint(error.value) == "ck_financial_rules_version_valid"


# ------------------------------------------------------------------
# E. per-type structural shape
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        {"source_account_id": None},
        {"execution_mode": None},
        {"execution_order": None},
        {"policy": None},
        {"income_sources": None},
        {"cap_at_target": None},
        {"allow_partial": None},
        {"floor_amount": Decimal("10.00")},
        {"__budget__": True},
    ],
)
def test_allocation_shape_violations_are_rejected(e4_database: Engine, mutation: Dict[str, Any]) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)
    mutation = dict(mutation)
    if mutation.pop("__budget__", False):
        mutation["budget_id"] = _budget(e4_database, user_id)

    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, _allocation(user_id, account_id, **mutation))

    assert _constraint(error.value) == "ck_financial_rules_allocation_shape"


@pytest.mark.parametrize(
    "mutation",
    [
        {"floor_amount": None}, {"source_account_id": None}, {"execution_mode": "AUTO"},
        {"execution_order": 1}, {"policy": "FIXED_PER_GOAL"}, {"percent": Decimal("10")},
        {"cap_at_target": True}, {"allow_partial": False}, {"income_sources": ["salary"]},
        {"effective_from": "2026-10-01"},
    ],
)
def test_floor_shape_violations_are_rejected(e4_database: Engine, mutation: Dict[str, Any]) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)

    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, _floor(user_id, account_id, **mutation))

    assert _constraint(error.value) == "ck_financial_rules_floor_shape"


def test_floor_cannot_carry_a_budget(e4_database: Engine) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)
    budget_id = _budget(e4_database, user_id)

    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, _floor(user_id, account_id, budget_id=budget_id))

    assert _constraint(error.value) == "ck_financial_rules_floor_shape"


@pytest.mark.parametrize(
    "mutation",
    [
        {"source_account_id": None}, {"floor_amount": Decimal("1.00")}, {"execution_mode": "AUTO"},
        {"execution_order": 3}, {"policy": "FIXED_PER_GOAL"}, {"income_sources": ["gift"]},
        {"allow_partial": False},
    ],
)
def test_overcommitment_shape_violations_are_rejected(e4_database: Engine, mutation: Dict[str, Any]) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)

    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, _overcommitment(user_id, account_id, **mutation))

    assert _constraint(error.value) == "ck_financial_rules_overcommitment_shape"


@pytest.mark.parametrize(
    "mutation",
    [
        {"budget_id": None}, {"floor_amount": Decimal("1.00")}, {"execution_mode": "CONFIRM"},
        {"execution_order": 2}, {"policy": "FIXED_PER_GOAL"}, {"percent": Decimal("5")},
        {"__account__": True},
    ],
)
def test_budget_alert_shape_violations_are_rejected(e4_database: Engine, mutation: Dict[str, Any]) -> None:
    user_id = uuid4()
    budget_id = _budget(e4_database, user_id)
    mutation = dict(mutation)
    if mutation.pop("__account__", False):
        mutation["source_account_id"] = _account(e4_database, user_id)

    with pytest.raises(IntegrityError) as error:
        values = _budget_alert(user_id, budget_id)
        values.update(mutation)
        _insert_rule(e4_database, values)

    assert _constraint(error.value) == "ck_financial_rules_budget_alert_shape"


def test_allocation_allows_optional_effective_from_and_percent(e4_database: Engine) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)

    _insert_rule(e4_database, _allocation(user_id, account_id, effective_from="2026-10-20", description="x"))
    _insert_rule(
        e4_database,
        _allocation(user_id, account_id, execution_order=2, policy="PERCENT_OF_INCOME_WATERFALL", percent=Decimal("20")),
    )


# ------------------------------------------------------------------
# F. ownership foreign keys
# ------------------------------------------------------------------


def test_rule_cannot_reference_another_users_account(e4_database: Engine) -> None:
    owner, intruder = uuid4(), uuid4()
    account_id = _account(e4_database, owner)

    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, _floor(intruder, account_id))

    assert _constraint(error.value) == "fk_financial_rules_source_account_id_user_id"


def test_rule_cannot_reference_a_nonexistent_account(e4_database: Engine) -> None:
    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, _floor(uuid4(), uuid4()))

    assert _constraint(error.value) == "fk_financial_rules_source_account_id_user_id"


def test_budget_alert_cannot_reference_another_users_budget(e4_database: Engine) -> None:
    owner, intruder = uuid4(), uuid4()
    budget_id = _budget(e4_database, owner)

    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, _budget_alert(intruder, budget_id))

    assert _constraint(error.value) == "fk_financial_rules_budget_id_user_id"


def test_target_cannot_reference_another_users_goal(e4_database: Engine) -> None:
    owner, intruder = uuid4(), uuid4()
    goal_id = _goal(e4_database, owner)
    intruder_account = _account(e4_database, intruder)
    rule_id = _insert_rule(e4_database, _allocation(intruder, intruder_account))

    with pytest.raises(IntegrityError) as error:
        _insert_target(e4_database, rule_id, intruder, goal_id)

    assert _constraint(error.value) == "fk_financial_rule_goal_targets_goal_id_user_id"


def test_target_cannot_reference_another_users_rule(e4_database: Engine) -> None:
    owner, intruder = uuid4(), uuid4()
    rule_id = _insert_rule(e4_database, _allocation(owner, _account(e4_database, owner)))
    goal_id = _goal(e4_database, intruder)

    with pytest.raises(IntegrityError) as error:
        _insert_target(e4_database, rule_id, intruder, goal_id)

    assert _constraint(error.value) == "fk_financial_rule_goal_targets_rule_id_user_id"


# ------------------------------------------------------------------
# G. delete behavior (database level; controlled 409s are E5 runtime)
# ------------------------------------------------------------------


def test_referenced_account_cannot_be_deleted(e4_database: Engine) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)
    _insert_rule(e4_database, _floor(user_id, account_id))

    with pytest.raises(IntegrityError) as error:
        with e4_database.begin() as connection:
            connection.execute(text("DELETE FROM accounts WHERE id = :i"), {"i": account_id})

    assert _constraint(error.value) == "fk_financial_rules_source_account_id_user_id"
    assert _count(e4_database, "SELECT count(*) FROM accounts WHERE id = :i", i=account_id) == 1


def test_referenced_budget_cannot_be_deleted(e4_database: Engine) -> None:
    user_id = uuid4()
    budget_id = _budget(e4_database, user_id)
    _insert_rule(e4_database, _budget_alert(user_id, budget_id))

    with pytest.raises(IntegrityError) as error:
        with e4_database.begin() as connection:
            connection.execute(text("DELETE FROM budgets WHERE id = :i"), {"i": budget_id})

    assert _constraint(error.value) == "fk_financial_rules_budget_id_user_id"


def test_referenced_goal_cannot_be_deleted(e4_database: Engine) -> None:
    user_id = uuid4()
    goal_id = _goal(e4_database, user_id)
    rule_id = _insert_rule(e4_database, _allocation(user_id, _account(e4_database, user_id)))
    _insert_target(e4_database, rule_id, user_id, goal_id)

    with pytest.raises(IntegrityError) as error:
        with e4_database.begin() as connection:
            connection.execute(text("DELETE FROM goals WHERE id = :i"), {"i": goal_id})

    assert _constraint(error.value) == "fk_financial_rule_goal_targets_goal_id_user_id"


def test_unreferenced_account_budget_and_goal_remain_deletable(e4_database: Engine) -> None:
    user_id = uuid4()
    account_id, budget_id, goal_id = _account(e4_database, user_id), _budget(e4_database, user_id), _goal(e4_database, user_id)

    with e4_database.begin() as connection:
        connection.execute(text("DELETE FROM accounts WHERE id = :i"), {"i": account_id})
        connection.execute(text("DELETE FROM budgets WHERE id = :i"), {"i": budget_id})
        connection.execute(text("DELETE FROM goals WHERE id = :i"), {"i": goal_id})


def test_deleting_a_rule_cascades_its_targets_and_keeps_goals(e4_database: Engine) -> None:
    user_id = uuid4()
    first, second = _goal(e4_database, user_id, 1), _goal(e4_database, user_id, 2)
    rule_id = _insert_rule(e4_database, _allocation(user_id, _account(e4_database, user_id)))
    _insert_target(e4_database, rule_id, user_id, first, position=0)
    _insert_target(e4_database, rule_id, user_id, second, position=1)

    with e4_database.begin() as connection:
        connection.execute(text("DELETE FROM financial_rules WHERE id = :i"), {"i": rule_id})

    assert _count(e4_database, "SELECT count(*) FROM financial_rule_goal_targets WHERE rule_id = :i", i=rule_id) == 0
    assert _count(e4_database, "SELECT count(*) FROM goals WHERE user_id = :u", u=user_id) == 2


# ------------------------------------------------------------------
# H. partial uniqueness
# ------------------------------------------------------------------


def test_duplicate_floor_for_the_same_user_and_account_is_rejected(e4_database: Engine) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)
    _insert_rule(e4_database, _floor(user_id, account_id))

    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, _floor(user_id, account_id, name="Floor 2", status="enabled"))

    assert _constraint(error.value) == "uq_financial_rules_floor_user_id_source_account_id"


def test_duplicate_overcommitment_alert_for_the_same_user_and_account_is_rejected(e4_database: Engine) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)
    _insert_rule(e4_database, _overcommitment(user_id, account_id))

    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, _overcommitment(user_id, account_id))

    assert _constraint(error.value) == "uq_financial_rules_overcommitment_user_id_source_account_id"


def test_duplicate_budget_alert_for_the_same_user_and_budget_is_rejected(e4_database: Engine) -> None:
    user_id = uuid4()
    budget_id = _budget(e4_database, user_id)
    _insert_rule(e4_database, _budget_alert(user_id, budget_id))

    with pytest.raises(IntegrityError) as error:
        _insert_rule(e4_database, _budget_alert(user_id, budget_id))

    assert _constraint(error.value) == "uq_financial_rules_budget_alert_user_id_budget_id"


def test_different_subjects_users_and_types_are_allowed_together(e4_database: Engine) -> None:
    first_user, second_user = uuid4(), uuid4()
    first_account, second_account = _account(e4_database, first_user), _account(e4_database, first_user)
    other_users_account = _account(e4_database, second_user)
    budget_a, budget_b = _budget(e4_database, first_user, "a"), _budget(e4_database, first_user, "b")

    # same Account: floor + overcommitment + several allocation rules
    _insert_rule(e4_database, _floor(first_user, first_account))
    _insert_rule(e4_database, _overcommitment(first_user, first_account))
    _insert_rule(e4_database, _allocation(first_user, first_account, execution_order=1))
    _insert_rule(e4_database, _allocation(first_user, first_account, execution_order=2))
    # different Account, different user, different Budget
    _insert_rule(e4_database, _floor(first_user, second_account))
    _insert_rule(e4_database, _floor(second_user, other_users_account))
    _insert_rule(e4_database, _budget_alert(first_user, budget_a))
    _insert_rule(e4_database, _budget_alert(first_user, budget_b))

    assert _count(e4_database, "SELECT count(*) FROM financial_rules") == 8


def test_floor_uniqueness_ignores_non_floor_rules_and_status(e4_database: Engine) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)
    _insert_rule(e4_database, _floor(user_id, account_id, status="disabled"))

    with pytest.raises(IntegrityError):
        _insert_rule(e4_database, _floor(user_id, account_id, status="enabled"))


# ------------------------------------------------------------------
# I. execution_order has no uniqueness
# ------------------------------------------------------------------


def test_duplicate_execution_orders_and_gaps_are_accepted(e4_database: Engine) -> None:
    user_id = uuid4()
    account_id = _account(e4_database, user_id)
    for order in (1, 1, 1, 5, 100, 5):
        _insert_rule(e4_database, _allocation(user_id, account_id, execution_order=order))

    assert _count(e4_database, "SELECT count(*) FROM financial_rules WHERE execution_order = 1 AND user_id = :u", u=user_id) == 3


def test_no_unique_constraint_or_index_covers_execution_order(e4_database: Engine) -> None:
    with e4_database.connect() as connection:
        indexes = connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'financial_rules'")
        ).all()
        constraints = connection.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'public.financial_rules'::regclass AND contype = 'u'")
        ).all()

    assert not [row[0] for row in indexes if "execution_order" in row[0]]
    assert not [row[0] for row in constraints if "execution_order" in row[0]]


# ------------------------------------------------------------------
# J. targets
# ------------------------------------------------------------------


def test_duplicate_goal_in_the_same_rule_is_rejected(e4_database: Engine) -> None:
    user_id = uuid4()
    goal_id = _goal(e4_database, user_id)
    rule_id = _insert_rule(e4_database, _allocation(user_id, _account(e4_database, user_id)))
    _insert_target(e4_database, rule_id, user_id, goal_id)

    with pytest.raises(IntegrityError) as error:
        _insert_target(e4_database, rule_id, user_id, goal_id, position=1)

    assert _constraint(error.value) == "uq_financial_rule_goal_targets_rule_id_goal_id"


def test_same_goal_may_be_targeted_by_different_rules_and_positions_may_repeat(e4_database: Engine) -> None:
    user_id = uuid4()
    first, second = _goal(e4_database, user_id, 1), _goal(e4_database, user_id, 2)
    account_id = _account(e4_database, user_id)
    rule_a = _insert_rule(e4_database, _allocation(user_id, account_id, execution_order=1))
    rule_b = _insert_rule(e4_database, _allocation(user_id, account_id, execution_order=2))

    _insert_target(e4_database, rule_a, user_id, first, position=0)
    _insert_target(e4_database, rule_a, user_id, second, position=0)  # position is UI order only
    _insert_target(e4_database, rule_b, user_id, first, position=3)

    assert _count(e4_database, "SELECT count(*) FROM financial_rule_goal_targets WHERE user_id = :u", u=user_id) == 3


@pytest.mark.parametrize("amount", ["0.01", "1234.50", "9999999999.99"])
def test_amount_or_cap_is_exact_numeric(e4_database: Engine, amount: str) -> None:
    user_id = uuid4()
    goal_id = _goal(e4_database, user_id)
    rule_id = _insert_rule(e4_database, _allocation(user_id, _account(e4_database, user_id)))

    target_id = _insert_target(e4_database, rule_id, user_id, goal_id, amount=Decimal(amount))

    assert _count(e4_database, "SELECT amount_or_cap FROM financial_rule_goal_targets WHERE id = :i", i=target_id) == Decimal(amount)


def test_amount_or_cap_may_be_null_but_not_non_positive(e4_database: Engine) -> None:
    user_id = uuid4()
    first, second = _goal(e4_database, user_id, 1), _goal(e4_database, user_id, 2)
    rule_id = _insert_rule(e4_database, _allocation(user_id, _account(e4_database, user_id)))

    _insert_target(e4_database, rule_id, user_id, first, amount=None)
    for bad in (Decimal("0.00"), Decimal("-1.00")):
        with pytest.raises(IntegrityError) as error:
            _insert_target(e4_database, rule_id, user_id, second, amount=bad)
        assert _constraint(error.value) == "ck_financial_rule_goal_targets_amount_or_cap_positive"


def test_negative_position_is_rejected(e4_database: Engine) -> None:
    user_id = uuid4()
    goal_id = _goal(e4_database, user_id)
    rule_id = _insert_rule(e4_database, _allocation(user_id, _account(e4_database, user_id)))

    with pytest.raises(IntegrityError) as error:
        _insert_target(e4_database, rule_id, user_id, goal_id, position=-1)

    assert _constraint(error.value) == "ck_financial_rule_goal_targets_position_non_negative"


# ------------------------------------------------------------------
# budgets composite unique
# ------------------------------------------------------------------


def test_budgets_composite_unique_exists_and_other_budget_constraints_are_unchanged(e2_database: Engine) -> None:
    def budget_constraints(database_engine: Engine) -> Dict[str, str]:
        with database_engine.connect() as connection:
            return dict(connection.execute(
                text("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'public.budgets'::regclass")
            ).all())

    before = budget_constraints(e2_database)
    assert "uq_budgets_id_user_id" not in before

    assert _alembic(_url_of(e2_database), "upgrade", E4_REVISION).returncode == 0

    after = budget_constraints(e2_database)
    assert after.pop("uq_budgets_id_user_id") == "UNIQUE (id, user_id)"
    assert after == before


# ------------------------------------------------------------------
# indexes
# ------------------------------------------------------------------


def test_partial_unique_index_definitions(e4_database: Engine) -> None:
    with e4_database.connect() as connection:
        definitions = dict(connection.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'financial_rules'")
        ).all())

    floor = definitions["uq_financial_rules_floor_user_id_source_account_id"]
    assert "UNIQUE" in floor and "(user_id, source_account_id)" in floor and "MINIMUM_UNALLOCATED_FLOOR" in floor
    over = definitions["uq_financial_rules_overcommitment_user_id_source_account_id"]
    assert "UNIQUE" in over and "(user_id, source_account_id)" in over and "OVERCOMMITMENT_ALERT" in over
    alert = definitions["uq_financial_rules_budget_alert_user_id_budget_id"]
    assert "UNIQUE" in alert and "(user_id, budget_id)" in alert and "BUDGET_ALERT" in alert
    assert set(definitions) == {
        "pk_financial_rules", "uq_financial_rules_id_user_id",
        "uq_financial_rules_floor_user_id_source_account_id",
        "uq_financial_rules_overcommitment_user_id_source_account_id",
        "uq_financial_rules_budget_alert_user_id_budget_id",
        "ix_financial_rules_user_id_rule_type_status",
        "ix_financial_rules_source_account_id", "ix_financial_rules_budget_id",
    }


def test_no_foreign_key_other_than_the_approved_ownership_keys(e4_database: Engine) -> None:
    with e4_database.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE contype = 'f' AND conrelid IN ('public.financial_rules'::regclass, 'public.financial_rule_goal_targets'::regclass) "
                "ORDER BY conname"
            )
        ).all()

    assert {row[1] for row in rows} == {
        "fk_financial_rules_source_account_id_user_id", "fk_financial_rules_budget_id_user_id",
        "fk_financial_rule_goal_targets_rule_id_user_id", "fk_financial_rule_goal_targets_goal_id_user_id",
    }
    definitions = {row[1]: row[2] for row in rows}
    assert "REFERENCES accounts(id, user_id) ON DELETE RESTRICT" in definitions["fk_financial_rules_source_account_id_user_id"]
    assert "REFERENCES budgets(id, user_id) ON DELETE RESTRICT" in definitions["fk_financial_rules_budget_id_user_id"]
    assert "REFERENCES financial_rules(id, user_id) ON DELETE CASCADE" in definitions["fk_financial_rule_goal_targets_rule_id_user_id"]
    assert "REFERENCES goals(id, user_id) ON DELETE RESTRICT" in definitions["fk_financial_rule_goal_targets_goal_id_user_id"]


# ------------------------------------------------------------------
# K. Data API
# ------------------------------------------------------------------


def test_migration_revokes_with_the_established_guarded_pattern() -> None:
    source = MIGRATION_PATH.read_text()

    assert 'FINANCIAL_RULES_TABLE_SQL = "public.financial_rules"' in source
    assert 'FINANCIAL_RULE_GOAL_TARGETS_TABLE_SQL = "public.financial_rule_goal_targets"' in source
    assert "REVOKE ALL PRIVILEGES ON TABLE %s FROM %I" in source
    assert "ARRAY['anon', 'authenticated', 'service_role']" in source
    assert "SELECT 1 FROM pg_roles WHERE rolname = target_role" in source
    assert "ALL TABLES IN SCHEMA" not in source
    assert "GRANT" not in source.replace("REVOKE", "")


def test_existing_data_api_roles_have_no_privileges_on_the_new_tables(e4_database: Engine) -> None:
    with e4_database.connect() as connection:
        roles = [r[0] for r in connection.execute(
            text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles)"), {"roles": list(DATA_API_ROLES)})]
        for role in roles:
            for table in (RULES, TARGETS):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    assert connection.execute(
                        text("SELECT has_table_privilege(:r, :t, :p)"),
                        {"r": role, "t": f"public.{table}", "p": privilege},
                    ).scalar_one() is False, (role, table, privilege)


def test_revoke_takes_effect_against_default_privileges_granted_to_data_api_roles(e2_database: Engine) -> None:
    created_roles: List[str] = []
    admin = _admin_engine()
    database_name = e2_database.url.database
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
        with e2_database.begin() as connection:
            connection.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {grantees}"))
            connection.execute(text("CREATE TABLE public.control_table (id integer)"))

        result = _alembic(_url_of(e2_database), "upgrade", E4_REVISION)
        assert result.returncode == 0, result.stderr

        with e2_database.connect() as connection:
            for role in DATA_API_ROLES:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert connection.execute(
                        text("SELECT has_table_privilege(:r, 'public.control_table', :p)"), {"r": role, "p": privilege},
                    ).scalar_one() is True, ("control", role, privilege)
                    for table in (RULES, TARGETS):
                        assert connection.execute(
                            text("SELECT has_table_privilege(:r, :t, :p)"),
                            {"r": role, "t": f"public.{table}", "p": privilege},
                        ).scalar_one() is False, (role, table, privilege)
    finally:
        e2_database.dispose()
        try:
            if created_roles:
                _drop_database(database_name)
                with admin.connect() as connection:
                    for role in created_roles:
                        connection.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        finally:
            admin.dispose()


# ------------------------------------------------------------------
# L. existing rows / M. cycle
# ------------------------------------------------------------------


def _digest(database_engine: Engine, table: str) -> str:
    with database_engine.connect() as connection:
        rows = connection.execute(text(f"SELECT t::text FROM {table} AS t ORDER BY t::text")).all()
    return hashlib.sha256("\n".join(row[0] for row in rows).encode()).hexdigest()


def test_migration_and_downgrade_do_not_mutate_existing_data(e2_database: Engine) -> None:
    user_id = uuid4()
    account_id, goal_id, budget_id = _account(e2_database, user_id), _goal(e2_database, user_id), _budget(e2_database, user_id)
    with e2_database.begin() as connection:
        connection.execute(
            text("INSERT INTO income (id, user_id, amount, currency, received_at, source) VALUES (:i, :u, 250.00, 'EUR', '2025-01-01', 'salary')"),
            {"i": uuid4(), "u": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO financial_events (id, user_id, event_type, aggregate_type, aggregate_id, origin, ingestion_mode, "
                "snap_amount, snap_currency, snap_received_at, snap_income_source, snap_aggregate_updated_at) "
                "VALUES (:i, :u, 'income.created', 'income', :a, 'manual', 'live', 1.00, 'EUR', '2025-01-01', 'salary', now())"
            ),
            {"i": uuid4(), "u": user_id, "a": uuid4()},
        )
    tables = ("accounts", "goals", "budgets", "income", "financial_events")
    before = {table: _digest(e2_database, table) for table in tables}
    url = _url_of(e2_database)

    assert _alembic(url, "upgrade", E4_REVISION).returncode == 0
    assert {table: _digest(e2_database, table) for table in tables} == before
    assert _count(e2_database, "SELECT count(*) FROM financial_rules") == 0

    assert _alembic(url, "downgrade", E2_REVISION).returncode == 0
    assert {table: _digest(e2_database, table) for table in tables} == before
    del account_id, goal_id, budget_id


def test_upgrade_downgrade_upgrade_cycle(e2_database: Engine) -> None:
    url = _url_of(e2_database)

    assert _alembic(url, "upgrade", E4_REVISION).returncode == 0
    assert _table_exists(e2_database, RULES)

    downgrade = _alembic(url, "downgrade", E2_REVISION)
    assert downgrade.returncode == 0, downgrade.stderr
    assert _revision(e2_database) == E2_REVISION
    assert not _table_exists(e2_database, RULES) and not _table_exists(e2_database, TARGETS)
    with e2_database.connect() as connection:
        leftovers = connection.execute(
            text(
                "SELECT relname FROM pg_class WHERE relname LIKE 'financial_rule%' "
                "OR relname LIKE '%financial_rules%' OR relname = 'uq_budgets_id_user_id'"
            )
        ).all()
        budget_unique = connection.execute(
            text("SELECT count(*) FROM pg_constraint WHERE conname = 'uq_budgets_id_user_id'")
        ).scalar_one()
        events_intact = connection.execute(text("SELECT to_regclass('public.financial_events') IS NOT NULL")).scalar_one()
    assert leftovers == [] and budget_unique == 0 and events_intact is True

    again = _alembic(url, "upgrade", E4_REVISION)
    assert again.returncode == 0, again.stderr
    assert _revision(e2_database) == E4_REVISION
    user_id = uuid4()
    _insert_rule(e2_database, _floor(user_id, _account(e2_database, user_id)))


# ------------------------------------------------------------------
# ORM / runtime boundary and metadata drift
# ------------------------------------------------------------------


def test_orm_metadata_matches_the_e4_schema_exactly(e4_database: Engine) -> None:
    # VF-020E5 maps the two E4 tables; the ORM metadata must equal the E4
    # database with no remaining difference.
    import_database_models()
    assert RULES in Base.metadata.tables and TARGETS in Base.metadata.tables

    with e4_database.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert exclude_stages_after(differences, E4_REVISION) == []
