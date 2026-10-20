import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
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
from tests.schema_drift import exclude_stages_after

# VF-020D5 contract-migration tests (revision 7c1e5a9b3d28): rollout
# stragglers (non-archived Goals with a NULL priority_rank) are appended after
# each user's own maximum rank by created_at ASC, id ASC, then the lifecycle
# CHECK (status = 'archived') = (priority_rank IS NULL) is added.
#
# They run the REAL Alembic CLI against throwaway *_test databases cloned from
# a template migrated to the D2 revision (the C1/D2 pattern); every database
# name ends in "_test", passes the project's safety guard and is dropped
# afterwards. The shared valor_test database is not migrated by these tests.

API_DIR = Path(__file__).resolve().parents[3]
D2_REVISION = "4d2f7b91a6c3"
D5_REVISION = "7c1e5a9b3d28"

LIFECYCLE_CHECK = "ck_goals_priority_rank_lifecycle"
POSITIVE_CHECK = "ck_goals_priority_rank_positive"
UNIQUE_NAME = "uq_goals_user_id_priority_rank"

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


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


@pytest.fixture(scope="module")
def d2_template() -> Generator[str, None, None]:
    name = f"vf020d5_tpl_{uuid4().hex[:10]}_test"
    url = _create_database(name)
    try:
        result = _alembic(url, "upgrade", D2_REVISION)
        assert result.returncode == 0, result.stderr
        yield name
    finally:
        _drop_database(name)


@pytest.fixture
def d2_database(d2_template: str) -> Generator[Engine, None, None]:
    name = f"vf020d5_{uuid4().hex[:10]}_test"
    url = _create_database(name, template=d2_template)
    database_engine = create_engine(url)
    try:
        yield database_engine
    finally:
        database_engine.dispose()
        _drop_database(name)


@pytest.fixture
def d5_database(d2_database: Engine) -> Engine:
    result = _alembic(_url_of(d2_database), "upgrade", D5_REVISION)
    assert result.returncode == 0, result.stderr
    return d2_database


def _seed(
    database_engine: Engine,
    user_id: UUID,
    status: str,
    rank: Optional[int],
    offset_days: int = 0,
    goal_id: Optional[UUID] = None,
) -> UUID:
    goal_id = goal_id or uuid4()
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO goals (id, user_id, name, target_amount, currency, status, created_at, priority_rank) "
                "VALUES (:id, :u, :name, 100, 'EUR', :s, :c, :r)"
            ),
            {
                "id": str(goal_id), "u": str(user_id), "name": f"goal-{offset_days}", "s": status,
                "c": BASE_TIME + timedelta(days=offset_days), "r": rank,
            },
        )
    return goal_id


def _ranks(database_engine: Engine, user_id: UUID) -> dict:
    with database_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, priority_rank FROM goals WHERE user_id = :u"), {"u": str(user_id)},
        ).all()
    return {UUID(str(row[0])): row[1] for row in rows}


def _revision(database_engine: Engine) -> str:
    with database_engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


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
# Normalization (A-H)
# ------------------------------------------------------------------


# Tests the exact normalization contract over pre-D5 data: existing ranks and
# their gaps are untouched, stragglers are appended after the user's MAX
# (1 and 3 + three stragglers -> 4, 5, 6, never 2), ordered by created_at
# ASC then id ASC, completed and active alike, archived NULL stays NULL.
def test_stragglers_are_appended_after_max_in_created_at_then_id_order(d2_database: Engine) -> None:
    user_id = uuid4()
    first = _seed(d2_database, user_id, "active", 1, offset_days=10)
    third = _seed(d2_database, user_id, "completed", 3, offset_days=20)
    late = _seed(d2_database, user_id, "active", None, offset_days=50)
    tie_high = _seed(d2_database, user_id, "completed", None, offset_days=30, goal_id=_uuid(9))
    tie_low = _seed(d2_database, user_id, "active", None, offset_days=30, goal_id=_uuid(2))
    archived = _seed(d2_database, user_id, "archived", None, offset_days=1)

    result = _alembic(_url_of(d2_database), "upgrade", D5_REVISION)

    assert result.returncode == 0, result.stderr
    ranks = _ranks(d2_database, user_id)
    assert ranks[first] == 1 and ranks[third] == 3     # existing ranks and gap unchanged
    assert ranks[tie_low] == 4                          # created_at ASC, then id ASC
    assert ranks[tie_high] == 5                         # a completed straggler is ranked
    assert ranks[late] == 6
    assert ranks[archived] is None                      # archived stays NULL


def test_user_without_ranked_goals_gets_1_to_n(d2_database: Engine) -> None:
    user_id = uuid4()
    older = _seed(d2_database, user_id, "active", None, offset_days=1)
    newer = _seed(d2_database, user_id, "completed", None, offset_days=2)

    assert _alembic(_url_of(d2_database), "upgrade", D5_REVISION).returncode == 0

    assert _ranks(d2_database, user_id) == {older: 1, newer: 2}


def test_users_are_normalized_independently(d2_database: Engine) -> None:
    user_a, user_b = uuid4(), uuid4()
    a_ranked = _seed(d2_database, user_a, "active", 7, offset_days=1)
    a_straggler = _seed(d2_database, user_a, "active", None, offset_days=2)
    b_first = _seed(d2_database, user_b, "active", None, offset_days=5)
    b_second = _seed(d2_database, user_b, "active", None, offset_days=6)

    assert _alembic(_url_of(d2_database), "upgrade", D5_REVISION).returncode == 0

    assert _ranks(d2_database, user_a) == {a_ranked: 7, a_straggler: 8}
    assert _ranks(d2_database, user_b) == {b_first: 1, b_second: 2}


def test_already_ranked_goals_are_unchanged_and_nothing_else_is_written(d2_database: Engine) -> None:
    user_id = uuid4()
    _seed(d2_database, user_id, "active", 5, offset_days=1)
    _seed(d2_database, user_id, "completed", 2, offset_days=2)
    _seed(d2_database, user_id, "active", None, offset_days=3)
    _seed(d2_database, user_id, "archived", None, offset_days=4)
    goal_id = _seed(d2_database, user_id, "active", 9, offset_days=5)
    with d2_database.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO goal_transactions (id, goal_id, user_id, type, amount, currency, effective_date) "
                "VALUES (:id, :g, :u, 'contribution', 25.00, 'EUR', '2026-10-01')"
            ),
            {"id": str(uuid4()), "g": str(goal_id), "u": str(user_id)},
        )
    columns = "id, user_id, name, target_amount, currency, target_date, status, created_at, updated_at"
    ledger = "SELECT * FROM goal_transactions ORDER BY id"
    with d2_database.connect() as connection:
        before = connection.execute(text(f"SELECT {columns} FROM goals ORDER BY id")).all()
        ranks_before = dict(connection.execute(text("SELECT id, priority_rank FROM goals")).all())
        ledger_before = connection.execute(text(ledger)).all()

    assert _alembic(_url_of(d2_database), "upgrade", D5_REVISION).returncode == 0

    with d2_database.connect() as connection:
        assert connection.execute(text(f"SELECT {columns} FROM goals ORDER BY id")).all() == before
        ranks_after = dict(connection.execute(text("SELECT id, priority_rank FROM goals")).all())
        assert connection.execute(text(ledger)).all() == ledger_before
    changed = {goal for goal in ranks_after if ranks_after[goal] != ranks_before[goal]}
    assert len(changed) == 1  # only the one straggler
    assert all(ranks_before[goal] is None for goal in changed)


def test_upgrade_on_empty_goals_succeeds(d2_database: Engine) -> None:
    result = _alembic(_url_of(d2_database), "upgrade", D5_REVISION)

    assert result.returncode == 0, result.stderr
    assert _revision(d2_database) == D5_REVISION


# An archived Goal that unexpectedly carries a rank is NOT repaired: the
# lifecycle CHECK makes the migration fail loudly and the schema is untouched.
def test_corrupt_archived_rank_fails_the_migration_instead_of_being_hidden(d2_database: Engine) -> None:
    user_id = uuid4()
    _seed(d2_database, user_id, "archived", 3, offset_days=1)
    straggler = _seed(d2_database, user_id, "active", None, offset_days=2)

    result = _alembic(_url_of(d2_database), "upgrade", D5_REVISION)

    assert result.returncode != 0
    assert _revision(d2_database) == D2_REVISION
    assert LIFECYCLE_CHECK not in _constraints(d2_database)
    assert _ranks(d2_database, user_id)[straggler] is None  # transaction rolled back


# ------------------------------------------------------------------
# Lifecycle CHECK
# ------------------------------------------------------------------


def test_lifecycle_check_metadata(d5_database: Engine) -> None:
    contype, deferrable, deferred, definition = _constraints(d5_database)[LIFECYCLE_CHECK]

    assert contype == "c" and deferrable is False and deferred is False
    assert "status" in definition and "archived" in definition
    assert "priority_rank IS NULL" in definition


@pytest.mark.parametrize(
    ("status", "rank", "accepted"),
    [
        ("active", 1, True),
        ("completed", 2, True),
        ("archived", None, True),
        ("active", None, False),
        ("completed", None, False),
        ("archived", 1, False),
    ],
)
def test_lifecycle_check_behavior(d5_database: Engine, status: str, rank: Optional[int], accepted: bool) -> None:
    user_id = uuid4()

    if accepted:
        goal_id = _seed(d5_database, user_id, status, rank)
        assert goal_id in _ranks(d5_database, user_id)
        return

    with pytest.raises(IntegrityError) as error:
        _seed(d5_database, user_id, status, rank)

    assert error.value.orig.diag.constraint_name == LIFECYCLE_CHECK
    assert _ranks(d5_database, user_id) == {}


# ------------------------------------------------------------------
# D2 objects preserved
# ------------------------------------------------------------------


def test_d2_column_check_and_unique_are_preserved(d5_database: Engine) -> None:
    with d5_database.connect() as connection:
        column = connection.execute(
            text(
                "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_name = 'goals' AND column_name = 'priority_rank'"
            )
        ).one()
        index = connection.execute(
            text(
                "SELECT i.indisunique, i.indpred IS NULL FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = :name"
            ),
            {"name": UNIQUE_NAME},
        ).one()
    assert tuple(column) == ("integer", "YES", None)
    assert tuple(index) == (True, True)

    constraints = _constraints(d5_database)
    contype, deferrable, deferred, definition = constraints[UNIQUE_NAME]
    assert (contype, deferrable, deferred) == ("u", True, True)
    assert "(user_id, priority_rank)" in definition
    assert POSITIVE_CHECK in constraints and ">= 1" in constraints[POSITIVE_CHECK][3]


# ------------------------------------------------------------------
# Downgrade / re-upgrade, metadata
# ------------------------------------------------------------------


# Tests the real downgrade removes ONLY the lifecycle CHECK (the D2 objects
# stay, normalized ranks stay and NULL stragglers are allowed again), and that
# a re-upgrade restores the CHECK deterministically.
def test_downgrade_removes_only_the_lifecycle_check_and_reupgrade_restores_it(d2_database: Engine) -> None:
    user_id = uuid4()
    straggler = _seed(d2_database, user_id, "active", None, offset_days=1)
    url = _url_of(d2_database)
    assert _alembic(url, "upgrade", D5_REVISION).returncode == 0
    assert _ranks(d2_database, user_id)[straggler] == 1

    downgrade = _alembic(url, "downgrade", D2_REVISION)

    assert downgrade.returncode == 0, downgrade.stderr
    assert _revision(d2_database) == D2_REVISION
    constraints = _constraints(d2_database)
    assert LIFECYCLE_CHECK not in constraints
    assert POSITIVE_CHECK in constraints and UNIQUE_NAME in constraints
    assert _ranks(d2_database, user_id)[straggler] == 1          # normalized rank remains
    _seed(d2_database, user_id, "active", None, offset_days=2)   # NULL stragglers allowed again

    reupgrade = _alembic(url, "upgrade", D5_REVISION)

    assert reupgrade.returncode == 0, reupgrade.stderr
    assert LIFECYCLE_CHECK in _constraints(d2_database)
    assert sorted(_ranks(d2_database, user_id).values()) == [1, 2]


# Tests that, at the D5 head, Alembic's own comparison of the ORM metadata
# against the database reports no difference (the CHECK is not compared by
# Alembic itself; its definition is asserted through pg_constraint above and
# its presence in the ORM here).
def test_orm_matches_the_d5_database_and_declares_the_lifecycle_check(d5_database: Engine) -> None:
    import_database_models()

    with d5_database.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
        # Objects added by later stages (revision-aware, named explicitly).
        differences = exclude_stages_after(differences, "7c1e5a9b3d28")

    assert differences == []
    orm_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in Base.metadata.tables["goals"].constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    }
    assert orm_checks[LIFECYCLE_CHECK] == "(status = 'archived') = (priority_rank IS NULL)"
    assert POSITIVE_CHECK in orm_checks
