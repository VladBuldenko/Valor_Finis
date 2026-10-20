import importlib.util
import inspect
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.exc import IntegrityError

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.db.database_base import Base
from app.db.database_models import import_database_models
from app.db.database_session import engine as application_engine
from tests.database_safety import validate_test_database_url

# VF-020D2 schema-expand tests (revision 4d2f7b91a6c3): goals gains a
# nullable priority_rank INTEGER, a positive CHECK, a DEFERRABLE INITIALLY
# DEFERRED UNIQUE (user_id, priority_rank) constraint and a deterministic
# backfill. There is deliberately NO runtime in D2, so every test is a
# schema/migration/database test.
#
# They run the REAL Alembic CLI (subprocess) against throwaway *_test
# databases (the VF-020C1 pattern): a template database is migrated once to
# the C1 revision, each test clones it, seeds pre-D2 rows with raw SQL, runs
# the migration and inspects the real database afterwards. Every database
# name ends in "_test", is validated by the project's safety guard before use
# and is dropped afterwards. The shared valor_test database is never migrated
# by these tests.

API_DIR = Path(__file__).resolve().parents[3]
C1_REVISION = "98acdc7016d2"
D2_REVISION = "4d2f7b91a6c3"
MIGRATION_PATH = API_DIR / "alembic" / "versions" / "4d2f7b91a6c3_expand_goal_priority_rank.py"

CHECK_NAME = "ck_goals_priority_rank_positive"
UNIQUE_NAME = "uq_goals_user_id_priority_rank"


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
        cwd=str(API_DIR),
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _url_of(database_engine: Engine) -> URL:
    return make_url(database_engine.url.render_as_string(hide_password=False))


@pytest.fixture(scope="module")
def c1_template() -> Generator[str, None, None]:
    name = f"vf020d2_tpl_{uuid4().hex[:10]}_test"
    url = _create_database(name)
    try:
        result = _alembic(url, "upgrade", C1_REVISION)
        assert result.returncode == 0, result.stderr
        yield name
    finally:
        _drop_database(name)


@pytest.fixture
def c1_database(c1_template: str) -> Generator[Engine, None, None]:
    name = f"vf020d2_{uuid4().hex[:10]}_test"
    url = _create_database(name, template=c1_template)
    database_engine = create_engine(url)
    try:
        yield database_engine
    finally:
        database_engine.dispose()
        _drop_database(name)


@pytest.fixture
def d2_database(c1_database: Engine) -> Engine:
    result = _alembic(_url_of(c1_database), "upgrade", D2_REVISION)
    assert result.returncode == 0, result.stderr
    return c1_database


def _seed_goal(
    database_engine: Engine,
    user_id: UUID,
    status: str = "active",
    created_at: Optional[datetime] = None,
    goal_id: Optional[UUID] = None,
    priority_rank: Optional[int] = None,
    with_rank_column: bool = False,
) -> UUID:
    goal_id = goal_id or uuid4()
    created_at = created_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
    columns = "id, user_id, name, target_amount, currency, status, created_at"
    values = ":id, :user_id, 'Goal', 1000, 'EUR', :status, :created_at"
    parameters = {
        "id": str(goal_id), "user_id": str(user_id), "status": status, "created_at": created_at,
    }
    if with_rank_column:
        columns += ", priority_rank"
        values += ", :priority_rank"
        parameters["priority_rank"] = priority_rank
    with database_engine.begin() as connection:
        connection.execute(text(f"INSERT INTO goals ({columns}) VALUES ({values})"), parameters)
    return goal_id


def _seed_transaction(database_engine: Engine, goal_id: UUID, user_id: UUID) -> None:
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO goal_transactions (id, goal_id, user_id, type, amount, currency, effective_date) "
                "VALUES (:id, :goal_id, :user_id, 'contribution', 25.00, 'EUR', '2026-10-01')"
            ),
            {"id": str(uuid4()), "goal_id": str(goal_id), "user_id": str(user_id)},
        )


def _ranks(database_engine: Engine, user_id: UUID) -> dict:
    with database_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, priority_rank FROM goals WHERE user_id = :u"), {"u": str(user_id)},
        ).all()
    return {UUID(str(row[0])): row[1] for row in rows}


def _revision(database_engine: Engine) -> str:
    with database_engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _goal_columns(database_engine: Engine) -> dict:
    with database_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'goals'"
            )
        ).all()
    return {row[0]: tuple(row[1:]) for row in rows}


def _constraints(database_engine: Engine) -> dict:
    with database_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT conname, contype, condeferrable, condeferred, pg_get_constraintdef(oid) "
                "FROM pg_constraint WHERE conrelid = 'goals'::regclass"
            )
        ).all()
    return {row[0]: tuple(row[1:]) for row in rows}


def _uuid(last: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{last:012d}")


# ------------------------------------------------------------------
# A. Schema
# ------------------------------------------------------------------


# Tests the exact D2 schema: priority_rank is a nullable INTEGER with no
# server default, the positive CHECK exists, and the unique is a real
# UNIQUE CONSTRAINT on (user_id, priority_rank), DEFERRABLE INITIALLY
# DEFERRED, backed by a non-partial index.
def test_upgrade_creates_the_expected_schema(d2_database: Engine) -> None:
    column = _goal_columns(d2_database)["priority_rank"]
    assert column == ("integer", "YES", None)

    constraints = _constraints(d2_database)
    contype, deferrable, deferred, definition = constraints[UNIQUE_NAME]
    assert contype == "u" and deferrable is True and deferred is True
    assert "(user_id, priority_rank)" in definition
    assert "DEFERRABLE INITIALLY DEFERRED" in definition

    check_type, _, _, check_definition = constraints[CHECK_NAME]
    assert check_type == "c"
    assert "priority_rank IS NULL" in check_definition and "priority_rank >= 1" in check_definition

    with d2_database.connect() as connection:
        index = connection.execute(
            text(
                "SELECT i.indisunique, i.indpred IS NULL FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = :name"
            ),
            {"name": UNIQUE_NAME},
        ).one()
    assert index == (True, True)  # unique, no partial predicate

    assert _revision(d2_database) == D2_REVISION


# Tests the lifecycle invariant is NOT part of D2: no constraint references
# both status and priority_rank, and the column is nullable.
def test_lifecycle_check_is_not_present(d2_database: Engine) -> None:
    for name, (_, _, _, definition) in _constraints(d2_database).items():
        assert not ("status" in definition and "priority_rank" in definition), name


# ------------------------------------------------------------------
# B-F. Backfill
# ------------------------------------------------------------------


# Tests the backfill over pre-D2 data: active and completed Goals are
# ranked per user newest first, archived Goals stay NULL, an equal
# created_at is resolved by id ASC, and each user restarts at 1.
def test_backfill_ranks_active_and_completed_newest_first(c1_database: Engine) -> None:
    user_a, user_b = uuid4(), uuid4()
    same = datetime(2026, 3, 1, tzinfo=timezone.utc)
    oldest = _seed_goal(c1_database, user_a, "active", datetime(2026, 1, 1, tzinfo=timezone.utc))
    middle = _seed_goal(c1_database, user_a, "archived", datetime(2026, 2, 1, tzinfo=timezone.utc))
    tie_high = _seed_goal(c1_database, user_a, "completed", same, goal_id=_uuid(9))
    tie_low = _seed_goal(c1_database, user_a, "active", same, goal_id=_uuid(2))
    newest = _seed_goal(c1_database, user_a, "active", datetime(2026, 4, 1, tzinfo=timezone.utc))
    b_old = _seed_goal(c1_database, user_b, "active", datetime(2026, 1, 1, tzinfo=timezone.utc))
    b_new = _seed_goal(c1_database, user_b, "completed", datetime(2026, 5, 1, tzinfo=timezone.utc))
    b_archived = _seed_goal(c1_database, user_b, "archived", datetime(2026, 6, 1, tzinfo=timezone.utc))

    result = _alembic(_url_of(c1_database), "upgrade", D2_REVISION)

    assert result.returncode == 0, result.stderr
    ranks_a = _ranks(c1_database, user_a)
    assert ranks_a[newest] == 1
    assert ranks_a[tie_low] == 2      # equal created_at: id ASC wins
    assert ranks_a[tie_high] == 3     # completed Goals are ranked
    assert ranks_a[oldest] == 4
    assert ranks_a[middle] is None    # archived stays NULL
    ranks_b = _ranks(c1_database, user_b)
    assert ranks_b[b_new] == 1        # completed, newest
    assert ranks_b[b_old] == 2
    assert ranks_b[b_archived] is None


# Tests the migration writes only goals.priority_rank: ledger rows and every
# other Goal column are unchanged, and the downgrade/upgrade is lossless for
# them.
def test_backfill_changes_nothing_else(c1_database: Engine) -> None:
    user_id = uuid4()
    goal_id = _seed_goal(c1_database, user_id, "active")
    _seed_transaction(c1_database, goal_id, user_id)
    query = (
        "SELECT id, user_id, name, target_amount, currency, target_date, status, created_at, updated_at "
        "FROM goals ORDER BY id"
    )
    ledger = "SELECT * FROM goal_transactions ORDER BY id"
    with c1_database.connect() as connection:
        goals_before = connection.execute(text(query)).all()
        ledger_before = connection.execute(text(ledger)).all()

    result = _alembic(_url_of(c1_database), "upgrade", D2_REVISION)

    assert result.returncode == 0, result.stderr
    with c1_database.connect() as connection:
        assert connection.execute(text(query)).all() == goals_before
        assert connection.execute(text(ledger)).all() == ledger_before


# Tests the upgrade over an empty goals table.
def test_upgrade_on_empty_goals_succeeds(c1_database: Engine) -> None:
    result = _alembic(_url_of(c1_database), "upgrade", D2_REVISION)

    assert result.returncode == 0, result.stderr
    assert _revision(c1_database) == D2_REVISION


# ------------------------------------------------------------------
# G. Positive CHECK
# ------------------------------------------------------------------


@pytest.mark.parametrize("rank", [0, -1])
def test_check_rejects_non_positive_rank(d2_database: Engine, rank: int) -> None:
    with pytest.raises(IntegrityError) as error:
        _seed_goal(d2_database, uuid4(), "active", with_rank_column=True, priority_rank=rank)

    assert error.value.orig.diag.constraint_name == CHECK_NAME


def test_check_accepts_null_and_positive_rank(d2_database: Engine) -> None:
    user_id = uuid4()
    null_goal = _seed_goal(d2_database, user_id, "archived", with_rank_column=True, priority_rank=None)
    ranked = _seed_goal(d2_database, user_id, "active", with_rank_column=True, priority_rank=1)

    ranks = _ranks(d2_database, user_id)
    assert ranks[null_goal] is None and ranks[ranked] == 1


# ------------------------------------------------------------------
# H. Deferred uniqueness
# ------------------------------------------------------------------


# Tests deferred uniqueness: swapping ranks 1 and 2 in one statement and in
# two statements of one transaction succeeds because only the final state is
# checked.
def test_swap_inside_one_transaction_succeeds(d2_database: Engine) -> None:
    user_id = uuid4()
    first = _seed_goal(d2_database, user_id, "active", with_rank_column=True, priority_rank=1)
    second = _seed_goal(d2_database, user_id, "active", with_rank_column=True, priority_rank=2)

    with d2_database.begin() as connection:
        connection.execute(
            text("UPDATE goals SET priority_rank = 3 - priority_rank WHERE user_id = :u AND priority_rank IN (1, 2)"),
            {"u": str(user_id)},
        )
    assert _ranks(d2_database, user_id) == {first: 2, second: 1}

    with d2_database.begin() as connection:
        connection.execute(text("UPDATE goals SET priority_rank = 2 WHERE id = :id"), {"id": str(second)})
        connection.execute(text("UPDATE goals SET priority_rank = 1 WHERE id = :id"), {"id": str(first)})
    assert _ranks(d2_database, user_id) == {first: 1, second: 2}


# Tests a transaction whose FINAL state has a duplicate non-NULL rank for
# one user is rejected at commit, naming the unique constraint, and nothing
# is persisted.
def test_duplicate_final_state_fails_at_commit(d2_database: Engine) -> None:
    user_id = uuid4()
    first = _seed_goal(d2_database, user_id, "active", with_rank_column=True, priority_rank=1)
    second = _seed_goal(d2_database, user_id, "active", with_rank_column=True, priority_rank=2)

    connection = d2_database.connect()
    try:
        transaction = connection.begin()
        connection.execute(text("UPDATE goals SET priority_rank = 1 WHERE id = :id"), {"id": str(second)})
        with pytest.raises(IntegrityError) as error:
            transaction.commit()
    finally:
        connection.close()

    assert error.value.orig.diag.constraint_name == UNIQUE_NAME
    assert _ranks(d2_database, user_id) == {first: 1, second: 2}


# Tests uniqueness is per user (the same rank for different users is valid)
# and that any number of NULL ranks may coexist for one user.
def test_same_rank_for_different_users_and_multiple_nulls(d2_database: Engine) -> None:
    user_a, user_b = uuid4(), uuid4()
    _seed_goal(d2_database, user_a, "active", with_rank_column=True, priority_rank=1)
    _seed_goal(d2_database, user_b, "active", with_rank_column=True, priority_rank=1)
    _seed_goal(d2_database, user_a, "archived", with_rank_column=True, priority_rank=None)
    _seed_goal(d2_database, user_a, "archived", with_rank_column=True, priority_rank=None)

    assert sorted(_ranks(d2_database, user_a).values(), key=lambda v: (v is None, v)) == [1, None, None]


# ------------------------------------------------------------------
# I. Rollout straggler compatibility
# ------------------------------------------------------------------


# Tests the unaware runtime keeps working after D2: an INSERT that does not
# name priority_rank (exactly what the current application writes) succeeds
# for active, completed and archived Goals, several of them with NULL rank.
def test_goals_inserted_by_the_unaware_runtime_are_valid(d2_database: Engine) -> None:
    user_id = uuid4()
    active = _seed_goal(d2_database, user_id, "active")
    completed = _seed_goal(d2_database, user_id, "completed")
    archived = _seed_goal(d2_database, user_id, "archived")
    another_active = _seed_goal(d2_database, user_id, "active")

    ranks = _ranks(d2_database, user_id)
    assert ranks[active] is None and ranks[completed] is None
    assert ranks[archived] is None and ranks[another_active] is None


# ------------------------------------------------------------------
# J. Downgrade / re-upgrade
# ------------------------------------------------------------------


# Tests the real downgrade to the C1 revision removes the column and both
# constraints, leaves the Goal rows, and that a re-upgrade backfills again.
def test_downgrade_and_reupgrade(c1_database: Engine) -> None:
    user_id = uuid4()
    older = _seed_goal(c1_database, user_id, "active", datetime(2026, 1, 1, tzinfo=timezone.utc))
    newer = _seed_goal(c1_database, user_id, "completed", datetime(2026, 2, 1, tzinfo=timezone.utc))
    url = _url_of(c1_database)

    assert _alembic(url, "upgrade", D2_REVISION).returncode == 0
    downgrade = _alembic(url, "downgrade", C1_REVISION)

    assert downgrade.returncode == 0, downgrade.stderr
    assert _revision(c1_database) == C1_REVISION
    assert "priority_rank" not in _goal_columns(c1_database)
    constraints = _constraints(c1_database)
    assert CHECK_NAME not in constraints and UNIQUE_NAME not in constraints
    with c1_database.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM goals")).scalar_one() == 2

    reupgrade = _alembic(url, "upgrade", D2_REVISION)

    assert reupgrade.returncode == 0, reupgrade.stderr
    assert _ranks(c1_database, user_id) == {newer: 1, older: 2}


# Tests the migration module declares the expected identity and keeps the
# table lock first in both directions, with no lock_timeout baked in.
def test_migration_declares_revision_chain_and_lock_first() -> None:
    spec = importlib.util.spec_from_file_location("expand_goal_priority_rank", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == D2_REVISION
    assert module.down_revision == C1_REVISION
    assert module.LOCK_SQL == "LOCK TABLE goals IN ACCESS EXCLUSIVE MODE"
    for function in (module.upgrade, module.downgrade):
        body = inspect.getsource(function).split('"""')[-1]
        assert body.strip().splitlines()[0] == "op.execute(LOCK_SQL)"
    source = MIGRATION_PATH.read_text()
    assert "SET lock_timeout" not in source and "SET LOCAL lock_timeout" not in source
    assert "lock_timeout =" not in source


# Tests that, since VF-020D3 maps goals.priority_rank, Alembic's own comparison
# of the ORM metadata against a database at the D2 revision reports NO
# difference at all (the ORM and the D2 schema are in sync; the CHECK is not
# compared by Alembic and is covered by the behavior tests above).
def test_orm_metadata_matches_d2_database_exactly(d2_database: Engine) -> None:
    import_database_models()

    with d2_database.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
        # Later stages (VF-020E2/E3) added the financial_events table and its
        # indexes after this revision; they are not part of this revision's contract.
        differences = [
            difference for difference in differences
            if 'financial_events' not in repr(difference)
        ]

    assert differences == []
