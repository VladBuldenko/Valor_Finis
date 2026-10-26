import threading
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
    _budget,
    _budget_alert,
    _constraint,
    _count,
    _create_database,
    _digest,
    _drop_database,
    _floor,
    _insert_rule,
    _overcommitment,
    _revision,
    _table_exists,
    _url_of,
)
from tests.schema_drift import exclude_stages_after

# VF-020E9A schema-expand tests (revision a7c3e91d5b24): the rule_alerts table.
#
# They run the REAL Alembic CLI against throwaway *_test databases cloned from a
# template migrated to the E6 revision; every database name ends in "_test",
# passes the project's safety guard (inside _create_database) and is dropped
# afterwards. No production database or credential is ever involved.

API_DIR = Path(__file__).resolve().parents[3]
APP_DIR = API_DIR / "app"
E6_REVISION = "e0503e9ca9d3"
E9A_REVISION = "a7c3e91d5b24"
MIGRATION_PATH = API_DIR / "alembic" / "versions" / f"{E9A_REVISION}_add_rule_alerts_schema.py"
TABLE = "rule_alerts"

FLOOR = "MINIMUM_UNALLOCATED_FLOOR"
OVER = "OVERCOMMITMENT_ALERT"
BUDGET = "BUDGET_ALERT"


@pytest.fixture(scope="module")
def e6_template() -> Generator[str, None, None]:
    name = f"vf020e9a_tpl_{uuid4().hex[:10]}_test"
    url = _create_database(name)
    try:
        result = _alembic(url, "upgrade", E6_REVISION)
        assert result.returncode == 0, result.stderr
        yield name
    finally:
        _drop_database(name)


@pytest.fixture
def e6_database(e6_template: str) -> Generator[Engine, None, None]:
    name = f"vf020e9a_{uuid4().hex[:10]}_test"
    url = _create_database(name, template=e6_template)
    database_engine = create_engine(url)
    try:
        yield database_engine
    finally:
        database_engine.dispose()
        _drop_database(name)


@pytest.fixture
def e9a_database(e6_database: Engine) -> Engine:
    result = _alembic(_url_of(e6_database), "upgrade", E9A_REVISION)
    assert result.returncode == 0, result.stderr
    return e6_database


class World:
    """One user with an Account, a Budget and one rule of each alert type."""

    def __init__(self, database_engine: Engine, user_id: Optional[UUID] = None) -> None:
        self.engine = database_engine
        self.user_id = user_id or uuid4()
        self.account_id = _account(database_engine, self.user_id)
        self.budget_id = _budget(database_engine, self.user_id)
        self.floor_rule = _insert_rule(database_engine, _floor(self.user_id, self.account_id))
        self.over_rule = _insert_rule(database_engine, _overcommitment(self.user_id, self.account_id))
        self.budget_rule = _insert_rule(database_engine, _budget_alert(self.user_id, self.budget_id))


def _budget_row(world: World, **overrides: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "id": uuid4(), "user_id": world.user_id, "rule_id": world.budget_rule, "rule_type": BUDGET,
        "subject_type": "budget", "subject_id": world.budget_id, "period_key": "2026-10-01", "level": "watch",
    }
    values.update(overrides)
    return values


def _account_row(world: World, rule_type: str = FLOOR, **overrides: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "id": uuid4(), "user_id": world.user_id,
        "rule_id": world.floor_rule if rule_type == FLOOR else world.over_rule, "rule_type": rule_type,
        "subject_type": "account", "subject_id": world.account_id, "period_key": "E1", "level": "breached",
    }
    values.update(overrides)
    return values


def _insert(database_engine: Engine, values: Dict[str, Any]) -> UUID:
    columns = ", ".join(values)
    placeholders = ", ".join(f":{name}" for name in values)
    with database_engine.begin() as connection:
        connection.execute(text(f"INSERT INTO rule_alerts ({columns}) VALUES ({placeholders})"), values)
    return values["id"]


def _rejected(database_engine: Engine, values: Dict[str, Any]) -> str:
    with pytest.raises(IntegrityError) as caught:
        _insert(database_engine, values)
    return _constraint(caught.value) or ""


# ------------------------------------------------------------------
# Revision history, upgrade, downgrade
# ------------------------------------------------------------------


def test_revision_chain_has_one_head_and_the_expected_parent() -> None:
    script = ScriptDirectory.from_config(Config(str(API_DIR / "alembic.ini")))

    assert script.get_heads() == [E9A_REVISION]
    assert script.get_revision(E9A_REVISION).down_revision == E6_REVISION


def test_upgrade_creates_the_table_and_downgrade_removes_only_it(e6_database: Engine) -> None:
    url = _url_of(e6_database)
    assert not _table_exists(e6_database, TABLE)
    world = World(e6_database)
    before = {t: _digest(e6_database, t) for t in ("accounts", "budgets", "financial_rules", "goals", "goal_transactions")}

    assert _alembic(url, "upgrade", E9A_REVISION).returncode == 0
    assert _revision(e6_database) == E9A_REVISION and _table_exists(e6_database, TABLE)
    assert {t: _digest(e6_database, t) for t in before} == before  # nothing existing was touched

    down = _alembic(url, "downgrade", E6_REVISION)
    assert down.returncode == 0, down.stderr
    assert _revision(e6_database) == E6_REVISION and not _table_exists(e6_database, TABLE)
    assert {t: _digest(e6_database, t) for t in before} == before
    assert _table_exists(e6_database, "rule_executions") and world.user_id

    assert _alembic(url, "upgrade", E9A_REVISION).returncode == 0  # upgrade after downgrade
    assert _table_exists(e6_database, TABLE)


def test_downgrade_refuses_to_destroy_alert_history(e9a_database: Engine) -> None:
    world = World(e9a_database)
    _insert(e9a_database, _budget_row(world))

    result = _alembic(_url_of(e9a_database), "downgrade", E6_REVISION)

    assert result.returncode != 0 and "rule alerts exist" in result.stderr
    assert _revision(e9a_database) == E9A_REVISION and _count(e9a_database, "SELECT count(*) FROM rule_alerts") == 1


def test_migration_takes_only_the_referenced_table_lock_and_no_backfill() -> None:
    source = MIGRATION_PATH.read_text()

    assert 'UPGRADE_LOCKS = ("LOCK TABLE financial_rules IN SHARE ROW EXCLUSIVE MODE",)' in source
    assert "SET LOCAL" not in source and "SET lock_timeout" not in source  # the operator sets it at run time
    for forbidden in ("UPDATE ", "INSERT INTO", "DELETE FROM", "NUMERIC", "numeric"):
        assert forbidden not in source.split("def upgrade")[1].split("def downgrade")[0]


# ------------------------------------------------------------------
# Columns, constraints, indexes
# ------------------------------------------------------------------


def test_columns_types_nullability_and_defaults(e9a_database: Engine) -> None:
    with e9a_database.connect() as connection:
        rows = connection.execute(text(
            "SELECT column_name, data_type, character_maximum_length, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = 'rule_alerts' ORDER BY ordinal_position"
        )).all()

    assert [tuple(row) for row in rows] == [
        ("id", "uuid", None, "NO", None),
        ("user_id", "uuid", None, "NO", None),
        ("rule_id", "uuid", None, "YES", None),
        ("rule_type", "character varying", 32, "NO", None),
        ("subject_type", "character varying", 16, "NO", None),
        ("subject_id", "uuid", None, "NO", None),
        ("period_key", "character varying", 40, "NO", None),
        ("level", "character varying", 16, "NO", None),
        ("created_at", "timestamp with time zone", None, "NO", "now()"),
        ("acknowledged_at", "timestamp with time zone", None, "YES", None),
        ("resolved_at", "timestamp with time zone", None, "YES", None),
    ]


def test_the_only_foreign_key_is_the_composite_ownership_key_that_nulls_rule_id(e9a_database: Engine) -> None:
    with e9a_database.connect() as connection:
        rows = connection.execute(text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'rule_alerts'::regclass AND contype = 'f'"
        )).all()

    assert len(rows) == 1 and rows[0][0] == "fk_rule_alerts_rule_id_user_id"
    definition = rows[0][1]
    assert "FOREIGN KEY (rule_id, user_id) REFERENCES financial_rules(id, user_id)" in definition
    assert "ON DELETE SET NULL (rule_id)" in definition
    assert "accounts" not in definition and "budgets" not in definition  # the subject is a soft reference


def test_indexes_and_predicates(e9a_database: Engine) -> None:
    with e9a_database.connect() as connection:
        rows = {name: definition for name, definition in connection.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'rule_alerts'"))}

    assert set(rows) == {
        "rule_alerts_pkey", "uq_rule_alerts_alert_key", "uq_rule_alerts_open_account_episode",
        "ix_rule_alerts_user_id_unacknowledged", "ix_rule_alerts_rule_id",
    }
    assert "UNIQUE" in rows["uq_rule_alerts_alert_key"]
    assert "(user_id, rule_type, subject_id, period_key, level)" in rows["uq_rule_alerts_alert_key"]
    open_episode = rows["uq_rule_alerts_open_account_episode"]
    assert "UNIQUE" in open_episode and "(user_id, rule_type, subject_id)" in open_episode
    assert "resolved_at IS NULL" in open_episode and "rule_type" in open_episode.split("WHERE")[1]
    assert "WHERE (acknowledged_at IS NULL)" in rows["ix_rule_alerts_user_id_unacknowledged"]
    assert "WHERE (rule_id IS NOT NULL)" in rows["ix_rule_alerts_rule_id"]


# ------------------------------------------------------------------
# Allowed / forbidden values
# ------------------------------------------------------------------


def test_every_allowed_combination_is_accepted(e9a_database: Engine) -> None:
    world = World(e9a_database)

    for level in ("watch", "at_risk", "exceeded"):
        _insert(e9a_database, _budget_row(world, level=level))
    _insert(e9a_database, _account_row(world, FLOOR))
    _insert(e9a_database, _account_row(world, OVER))

    assert _count(e9a_database, "SELECT count(*) FROM rule_alerts") == 5


@pytest.mark.parametrize(
    ("builder", "overrides", "constraint"),
    [
        ("budget", {"rule_type": "INCOME_ALLOCATION"}, "ck_rule_alerts_rule_type_valid"),
        ("budget", {"subject_type": "goal"}, "ck_rule_alerts_subject_type_valid"),
        ("budget", {"level": "critical"}, "ck_rule_alerts_level_valid"),
        ("budget", {"level": "breached"}, "ck_rule_alerts_type_shape"),
        ("budget", {"subject_type": "account"}, "ck_rule_alerts_type_shape"),
        ("budget", {"period_key": "E1"}, "ck_rule_alerts_type_shape"),
        ("budget", {"period_key": "2026-10"}, "ck_rule_alerts_type_shape"),
        ("budget", {"resolved_at": "2030-01-01"}, "ck_rule_alerts_type_shape"),
        ("account", {"level": "watch"}, "ck_rule_alerts_type_shape"),
        ("account", {"subject_type": "budget"}, "ck_rule_alerts_type_shape"),
        ("account", {"period_key": "2026-10-01"}, "ck_rule_alerts_type_shape"),
        ("account", {"period_key": "E0"}, "ck_rule_alerts_type_shape"),
        ("account", {"period_key": "E"}, "ck_rule_alerts_type_shape"),
        ("account", {"rule_type": BUDGET}, "ck_rule_alerts_type_shape"),
    ],
)
def test_forbidden_values_and_combinations_are_rejected(
    e9a_database: Engine, builder: str, overrides: Dict[str, Any], constraint: str,
) -> None:
    world = World(e9a_database)
    values = _budget_row(world, **overrides) if builder == "budget" else _account_row(world, **overrides)

    assert _rejected(e9a_database, values) == constraint


def test_acknowledgement_and_resolution_timestamps_cannot_precede_creation(e9a_database: Engine) -> None:
    world = World(e9a_database)

    assert _rejected(e9a_database, _budget_row(world, acknowledged_at="2000-01-01")) == "ck_rule_alerts_acknowledged_at_valid"
    assert _rejected(e9a_database, _account_row(world, resolved_at="2000-01-01")) == "ck_rule_alerts_resolved_at_valid"

    alert = _insert(e9a_database, _budget_row(world))
    with e9a_database.begin() as connection:  # acknowledgement is a plain, repeatable-safe UPDATE
        connection.execute(text("UPDATE rule_alerts SET acknowledged_at = now() WHERE id = :i"), {"i": alert})
    assert _count(e9a_database, "SELECT count(*) FROM rule_alerts WHERE acknowledged_at IS NOT NULL") == 1


# ------------------------------------------------------------------
# Ownership
# ------------------------------------------------------------------


def test_an_alert_cannot_reference_another_users_rule(e9a_database: Engine) -> None:
    owner, stranger = World(e9a_database), World(e9a_database)

    code = _rejected(e9a_database, _budget_row(stranger, rule_id=owner.budget_rule))

    assert code == "fk_rule_alerts_rule_id_user_id"
    _insert(e9a_database, _budget_row(stranger))  # its own rule is fine


def test_an_alert_without_a_rule_is_accepted_for_any_user(e9a_database: Engine) -> None:
    _insert(e9a_database, _budget_row(World(e9a_database), rule_id=None))


# ------------------------------------------------------------------
# Deduplication and transitions
# ------------------------------------------------------------------


def test_budget_levels_are_alerted_once_per_period(e9a_database: Engine) -> None:
    world = World(e9a_database)
    _insert(e9a_database, _budget_row(world, level="watch"))

    assert _rejected(e9a_database, _budget_row(world, level="watch")) == "uq_rule_alerts_alert_key"
    _insert(e9a_database, _budget_row(world, level="at_risk"))  # an escalation re-alerts
    _insert(e9a_database, _budget_row(world, level="exceeded"))
    _insert(e9a_database, _budget_row(world, level="watch", period_key="2026-11-01"))  # next period starts clean
    assert _rejected(e9a_database, _budget_row(world, level="exceeded")) == "uq_rule_alerts_alert_key"
    # A de-escalation followed by the same level again inside the period never re-alerts:
    assert _rejected(e9a_database, _budget_row(world, level="at_risk")) == "uq_rule_alerts_alert_key"


def test_the_key_is_per_user_and_per_alert_type(e9a_database: Engine) -> None:
    first, second = World(e9a_database), World(e9a_database)
    shared_subject = uuid4()

    _insert(e9a_database, _budget_row(first, subject_id=shared_subject))
    _insert(e9a_database, _budget_row(second, subject_id=shared_subject))  # another user, same subject id
    _insert(e9a_database, _account_row(first, FLOOR, subject_id=shared_subject))
    _insert(e9a_database, _account_row(first, OVER, subject_id=shared_subject))  # floor breach != overcommitment


def test_concurrent_duplicate_inserts_have_exactly_one_winner(e9a_database: Engine) -> None:
    world = World(e9a_database)
    outcomes: List[Any] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait(timeout=30)
        try:
            _insert(e9a_database, _budget_row(world))
            outcomes.append("ok")
        except IntegrityError as error:
            outcomes.append(_constraint(error))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert outcomes.count("ok") == 1
    assert [o for o in outcomes if o != "ok"] == ["uq_rule_alerts_alert_key"] * 7
    assert _count(e9a_database, "SELECT count(*) FROM rule_alerts") == 1


def test_account_breach_recovery_and_rebreach_are_separate_episodes(e9a_database: Engine) -> None:
    world = World(e9a_database)
    first = _insert(e9a_database, _account_row(world, FLOOR, period_key="E1"))

    # While episode E1 is open no second open episode may exist for the Account and type.
    assert _rejected(e9a_database, _account_row(world, FLOOR, period_key="E2")) == "uq_rule_alerts_open_account_episode"
    assert _rejected(e9a_database, _account_row(world, FLOOR, period_key="E1")) == "uq_rule_alerts_alert_key"

    with e9a_database.begin() as connection:  # the Account recovers
        connection.execute(text("UPDATE rule_alerts SET resolved_at = now() WHERE id = :i"), {"i": first})

    _insert(e9a_database, _account_row(world, FLOOR, period_key="E2"))  # the later breach is a new episode
    assert _rejected(e9a_database, _account_row(world, FLOOR, period_key="E3")) == "uq_rule_alerts_open_account_episode"
    assert _rejected(e9a_database, _account_row(world, FLOOR, period_key="E1")) == "uq_rule_alerts_alert_key"

    # A floor episode never blocks an overcommitment episode of the same Account.
    _insert(e9a_database, _account_row(world, OVER, period_key="E1"))
    assert _count(e9a_database, "SELECT count(*) FROM rule_alerts WHERE rule_type = :t", t=FLOOR) == 2


def test_concurrent_new_episodes_have_exactly_one_winner(e9a_database: Engine) -> None:
    world = World(e9a_database)
    outcomes: List[Any] = []
    barrier = threading.Barrier(6)

    def worker(index: int) -> None:
        barrier.wait(timeout=30)
        try:
            _insert(e9a_database, _account_row(world, FLOOR, period_key=f"E{index + 1}"))
            outcomes.append("ok")
        except IntegrityError as error:
            outcomes.append(_constraint(error))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert outcomes.count("ok") == 1
    assert set(outcomes) - {"ok"} == {"uq_rule_alerts_open_account_episode"}


# ------------------------------------------------------------------
# Lifecycle: alerts never block deletion and survive it (P57)
# ------------------------------------------------------------------


def test_deleting_the_rule_keeps_the_alert_and_nulls_only_rule_id(e9a_database: Engine) -> None:
    world = World(e9a_database)
    alert = _insert(e9a_database, _budget_row(world))

    with e9a_database.begin() as connection:  # a rule without executions stays deletable
        connection.execute(text("DELETE FROM financial_rules WHERE id = :i"), {"i": world.budget_rule})

    with e9a_database.connect() as connection:
        row = connection.execute(text(
            "SELECT rule_id, user_id, rule_type, subject_id FROM rule_alerts WHERE id = :i"), {"i": alert}).one()
    assert row[0] is None and row[1] == world.user_id and row[2] == BUDGET and row[3] == world.budget_id


def test_the_alert_key_still_deduplicates_after_the_rule_is_replaced(e9a_database: Engine) -> None:
    world = World(e9a_database)
    _insert(e9a_database, _budget_row(world))
    with e9a_database.begin() as connection:
        connection.execute(text("DELETE FROM financial_rules WHERE id = :i"), {"i": world.budget_rule})
    replacement = _insert_rule(e9a_database, _budget_alert(world.user_id, world.budget_id))

    assert _rejected(e9a_database, _budget_row(world, rule_id=replacement)) == "uq_rule_alerts_alert_key"


def test_account_and_budget_deletion_is_never_blocked_by_alerts(e9a_database: Engine) -> None:
    world = World(e9a_database)
    _insert(e9a_database, _budget_row(world))
    _insert(e9a_database, _account_row(world, FLOOR))
    with e9a_database.begin() as connection:
        connection.execute(text("DELETE FROM financial_rules WHERE user_id = :u"), {"u": world.user_id})
        connection.execute(text("DELETE FROM accounts WHERE id = :i"), {"i": world.account_id})
        connection.execute(text("DELETE FROM budgets WHERE id = :i"), {"i": world.budget_id})

    assert _count(e9a_database, "SELECT count(*) FROM rule_alerts") == 2  # history survives its subjects


# ------------------------------------------------------------------
# Data API security
# ------------------------------------------------------------------


def test_migration_revokes_with_the_established_guarded_pattern() -> None:
    source = MIGRATION_PATH.read_text()

    assert 'RULE_ALERTS_TABLE_SQL = "public.rule_alerts"' in source
    assert "REVOKE ALL PRIVILEGES ON TABLE {RULE_ALERTS_TABLE_SQL} FROM %I" in source
    assert "ARRAY['anon', 'authenticated', 'service_role']" in source
    assert "SELECT 1 FROM pg_roles WHERE rolname = target_role" in source
    assert "CREATE SEQUENCE" not in source  # a UUID key: no sequence whose privileges could leak


def test_revoke_takes_effect_against_default_privileges_granted_to_data_api_roles(e6_database: Engine) -> None:
    created_roles: List[str] = []
    admin = _admin_engine()
    database_name = e6_database.url.database
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
        with e6_database.begin() as connection:
            connection.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {grantees}"))
            connection.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {grantees}"))
            connection.execute(text("CREATE TABLE public.control_table (id integer)"))

        result = _alembic(_url_of(e6_database), "upgrade", E9A_REVISION)
        assert result.returncode == 0, result.stderr

        with e6_database.connect() as connection:
            for role in DATA_API_ROLES:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    assert connection.execute(text("SELECT has_table_privilege(:r, 'public.control_table', :p)"),
                                              {"r": role, "p": privilege}).scalar_one() is True, ("control", role, privilege)
                    assert connection.execute(text("SELECT has_table_privilege(:r, 'public.rule_alerts', :p)"),
                                              {"r": role, "p": privilege}).scalar_one() is False, (role, privilege)
            assert connection.execute(text("SELECT count(*) FROM pg_sequences WHERE sequencename LIKE 'rule_alert%'")).scalar_one() == 0
    finally:
        e6_database.dispose()
        try:
            if created_roles:
                _drop_database(database_name)
                with admin.connect() as connection:
                    for role in created_roles:
                        connection.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        finally:
            admin.dispose()


# ------------------------------------------------------------------
# ORM mapping, drift and staged compatibility
# ------------------------------------------------------------------


def test_orm_metadata_matches_the_e9a_schema_exactly(e9a_database: Engine) -> None:
    import_database_models()
    assert TABLE in Base.metadata.tables

    with e9a_database.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_older_revision_differs_only_by_the_e9a_table(e6_database: Engine) -> None:
    import_database_models()
    with e6_database.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences  # the ORM already knows rule_alerts
    assert exclude_stages_after(differences, E6_REVISION) == []


def test_rule_alert_persistence_is_confined_to_the_model_and_the_repository() -> None:
    # E9A shipped the schema with no runtime use; since VF-020E9B the table is
    # read and written ONLY through rule_alert_repository (the service, router and
    # rule service go through it and never name the table or model).
    referencing = sorted(
        str(path.relative_to(API_DIR))
        for path in APP_DIR.rglob("*.py")
        if any(word in path.read_text(encoding="utf-8") for word in ("RuleAlertModel", "rule_alert_models"))
    )

    assert referencing == [
        "app/db/database_models.py",
        "app/modules/financial_rules/rule_alert_models.py",
        "app/modules/financial_rules/rule_alert_repository.py",
    ]


def test_the_previous_runtime_cleanup_works_without_the_table(e6_database: Engine) -> None:
    # The deployed E8 runtime and the shared test cleanup must keep working on
    # the pre-migration schema, where rule_alerts does not exist.
    from tests.conftest import OPTIONAL_E6_TABLES

    assert "rule_alerts" in OPTIONAL_E6_TABLES and not _table_exists(e6_database, TABLE)
    World(e6_database)  # E8 tables are fully usable at E6
