import importlib.util
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Optional
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database_session import SessionLocal
from app.modules.analytics import analytics_service
from app.modules.goals import goal_repository, goal_service
from app.modules.goals.goal_schemas import GoalCreate, GoalUpdate
from app.modules.goals.goal_transaction_schemas import GoalTransactionCreate

# These tests run against the migrated test schema (the suite always runs
# after `alembic upgrade head`) and verify the VF-020B2 expand revision at
# the database level. The migration's upgrade/downgrade round trip itself is
# verified with the Alembic CLI against the test database, not from inside
# pytest.
MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "1e921a4a4412_expand_goal_ledger_integrity.py"
)


# Loads the VF-020B2 migration module so the backfill test runs exactly the
# migration's own SQL instead of a copy of it.
# Returns:
# - The imported migration module.
def _load_expand_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("expand_goal_ledger_integrity", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Inserts a goal row directly with SQL, bypassing API validation, so the
# database constraints themselves are exercised.
# Parameters:
# - session: active session.
# - user_id: goal owner.
# - currency: stored currency code.
# - status: stored status.
# Returns:
# - The new goal id.
def _insert_goal(
    session: Session,
    user_id: UUID,
    currency: str = "EUR",
    status: str = "active",
) -> UUID:
    goal_id = uuid4()
    session.execute(
        text(
            "INSERT INTO goals (id, user_id, name, target_amount, currency, status) "
            "VALUES (:id, :user_id, 'Goal', 100, :currency, :status)"
        ),
        {
            "id": str(goal_id),
            "user_id": str(user_id),
            "currency": currency,
            "status": status,
        },
    )
    return goal_id


# Inserts a goal transaction row directly with SQL.
# Parameters:
# - session: active session.
# - goal_id: owning goal.
# - user_id: row owner (may deliberately differ from the goal's owner).
# - client_request_id: optional idempotency key.
# - type: transaction type.
# Returns:
# - The new transaction id.
def _insert_goal_transaction(
    session: Session,
    goal_id: UUID,
    user_id: UUID,
    client_request_id: Optional[UUID] = None,
    type: str = "contribution",
) -> UUID:
    transaction_id = uuid4()
    session.execute(
        text(
            "INSERT INTO goal_transactions "
            "(id, goal_id, user_id, type, amount, client_request_id) "
            "VALUES (:id, :goal_id, :user_id, :type, 10, :client_request_id)"
        ),
        {
            "id": str(transaction_id),
            "goal_id": str(goal_id),
            "user_id": str(user_id),
            "type": type,
            "client_request_id": None if client_request_id is None else str(client_request_id),
        },
    )
    return transaction_id


# Returns the expand columns of one goal transaction.
# Parameters:
# - session: active session.
# - transaction_id: goal transaction id.
# Returns:
# - (currency, effective_date, client_request_id).
def _expand_columns(session: Session, transaction_id: UUID) -> tuple:
    return session.execute(
        text(
            "SELECT currency, effective_date, client_request_id "
            "FROM goal_transactions WHERE id = :id"
        ),
        {"id": str(transaction_id)},
    ).one()


# Returns the name of the constraint a failed statement violated.
# Parameters:
# - error: the IntegrityError raised by the statement.
# Returns:
# - The violated constraint name reported by PostgreSQL.
def _violated_constraint(error: IntegrityError) -> str:
    return error.orig.diag.constraint_name


# Tests that the expand revision adds the three goal_transactions columns
# as nullable, default-free columns of the agreed types (VF-020B2).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if every column has the expected shape.
def test_expand_adds_nullable_goal_transaction_columns(clean_database: None) -> None:
    session = SessionLocal()
    try:
        rows = session.execute(
            text(
                "SELECT column_name, data_type, character_maximum_length, "
                "is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_name = 'goal_transactions' "
                "AND column_name IN ('currency', 'effective_date', 'client_request_id')"
            )
        ).all()
    finally:
        session.close()

    columns = {row[0]: tuple(row[1:]) for row in rows}
    assert columns == {
        "currency": ("character varying", 3, "YES", None),
        "effective_date": ("date", None, "YES", None),
        "client_request_id": ("uuid", None, "YES", None),
    }


# Tests that the expand revision adds the agreed constraints and keeps the
# original single-column goal_id foreign key (VF-020B2).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if every constraint has the expected definition.
def test_expand_adds_constraints_and_keeps_simple_goal_fk(clean_database: None) -> None:
    session = SessionLocal()
    try:
        rows = session.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid IN ('goals'::regclass, 'goal_transactions'::regclass) "
                "AND contype IN ('c', 'f', 'u')"
            )
        ).all()
    finally:
        session.close()

    definitions = {name: definition for name, definition in rows}
    assert definitions["uq_goals_id_user_id"] == "UNIQUE (id, user_id)"
    assert "'^[A-Z]{3}$'" in definitions["ck_goals_currency_format"]
    assert "'active'" in definitions["ck_goals_status_valid"]
    assert "'completed'" in definitions["ck_goals_status_valid"]
    assert "'archived'" in definitions["ck_goals_status_valid"]
    assert definitions["fk_goal_transactions_goal_id_user_id"] == (
        "FOREIGN KEY (goal_id, user_id) REFERENCES goals(id, user_id) ON DELETE RESTRICT"
    )
    assert definitions["uq_goal_transactions_user_id_client_request_id"] == (
        "UNIQUE (user_id, client_request_id)"
    )
    single_column_goal_fks = [
        name
        for name, definition in definitions.items()
        if definition == "FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE RESTRICT"
    ]
    assert len(single_column_goal_fks) == 1


# Tests that the migration's currency backfill copies each goal's currency
# onto its transactions, leaves effective_date and client_request_id NULL,
# and changes nothing when run again (VF-020B2).
# It also shows the expand/contract window: transactions created by the
# current application code get NULL in all three columns until backfilled.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if every row ends with its goal's currency.
def test_backfill_copies_goal_currency_and_leaves_other_columns_null(
    clean_database: None,
) -> None:
    migration = _load_expand_migration()
    session = SessionLocal()
    user_id = uuid4()

    try:
        eur_goal = goal_repository.create_goal(
            db_session=session,
            goal_data=GoalCreate(name="Trip", target_amount=Decimal("500"), currency="EUR"),
            user_id=user_id,
        )
        usd_goal = goal_repository.create_goal(
            db_session=session,
            goal_data=GoalCreate(name="Laptop", target_amount=Decimal("900"), currency="USD"),
            user_id=user_id,
        )
        eur_transaction = goal_service.create_goal_transaction(
            db_session=session,
            goal_id=eur_goal.id,
            transaction_data=GoalTransactionCreate(type="contribution", amount=Decimal("50")),
            user_id=user_id,
        )
        usd_transaction = goal_service.create_goal_transaction(
            db_session=session,
            goal_id=usd_goal.id,
            transaction_data=GoalTransactionCreate(type="contribution", amount=Decimal("70")),
            user_id=user_id,
        )
        opening_balance_id = _insert_goal_transaction(
            session, usd_goal.id, user_id, type="opening_balance",
        )
        session.commit()

        assert _expand_columns(session, eur_transaction.id) == (None, None, None)
        assert _expand_columns(session, usd_transaction.id) == (None, None, None)

        session.execute(text(migration.BACKFILL_GOAL_TRANSACTION_CURRENCY_SQL))
        session.commit()

        assert _expand_columns(session, eur_transaction.id) == ("EUR", None, None)
        assert _expand_columns(session, usd_transaction.id) == ("USD", None, None)
        assert _expand_columns(session, opening_balance_id) == ("USD", None, None)

        rerun = session.execute(text(migration.BACKFILL_GOAL_TRANSACTION_CURRENCY_SQL))
        session.commit()
        assert rerun.rowcount == 0
    finally:
        session.close()


# Tests that ck_goals_currency_format accepts exactly three ASCII uppercase
# letters at the database level, even for values that bypass the API
# (VF-020B2).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - currency: stored currency candidate.
# - accepted: whether PostgreSQL must accept it.
# Returns:
# - None. The test passes if the insert succeeds or fails as expected.
@pytest.mark.parametrize(
    ("currency", "accepted"),
    [
        ("EUR", True),
        ("USD", True),
        ("eur", False),
        ("12$", False),
        ("E1R", False),
        ("ÉUR", False),
        ("ıNR", False),
        ("ÄÖÜ", False),
        ("EU", False),
    ],
)
def test_goal_currency_check_accepts_only_ascii_uppercase(
    clean_database: None,
    currency: str,
    accepted: bool,
) -> None:
    session = SessionLocal()
    try:
        if accepted:
            _insert_goal(session, uuid4(), currency=currency)
            session.commit()
        else:
            with pytest.raises(IntegrityError) as error:
                _insert_goal(session, uuid4(), currency=currency)
            session.rollback()
            assert _violated_constraint(error.value) == "ck_goals_currency_format"
    finally:
        session.close()


# Tests that ck_goals_status_valid accepts exactly the three goal statuses
# at the database level (VF-020B2).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - status: stored status candidate.
# - accepted: whether PostgreSQL must accept it.
# Returns:
# - None. The test passes if the insert succeeds or fails as expected.
@pytest.mark.parametrize(
    ("status", "accepted"),
    [
        ("active", True),
        ("completed", True),
        ("archived", True),
        ("paused", False),
        ("ACTIVE", False),
    ],
)
def test_goal_status_check_accepts_only_known_statuses(
    clean_database: None,
    status: str,
    accepted: bool,
) -> None:
    session = SessionLocal()
    try:
        if accepted:
            _insert_goal(session, uuid4(), status=status)
            session.commit()
        else:
            with pytest.raises(IntegrityError) as error:
                _insert_goal(session, uuid4(), status=status)
            session.rollback()
            assert _violated_constraint(error.value) == "ck_goals_status_valid"
    finally:
        session.close()


# Tests that a goal transaction must have the same owner as its goal at the
# database level (VF-020B2 composite ownership FK).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the same-owner row is stored and the
#   cross-user row is rejected by fk_goal_transactions_goal_id_user_id.
def test_goal_transaction_owner_must_match_goal_owner(clean_database: None) -> None:
    session = SessionLocal()
    owner_id = uuid4()
    other_user_id = uuid4()

    try:
        goal_id = _insert_goal(session, owner_id)
        _insert_goal_transaction(session, goal_id, owner_id)
        session.commit()

        with pytest.raises(IntegrityError) as error:
            _insert_goal_transaction(session, goal_id, other_user_id)
        session.rollback()

        assert _violated_constraint(error.value) == "fk_goal_transactions_goal_id_user_id"
    finally:
        session.close()


# Tests the database semantics of uq_goal_transactions_user_id_client_request_id
# (VF-020B2): a non-null key is unique per user, the same key is allowed for
# another user, and any number of rows may have no key.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the same-user duplicate key is rejected.
def test_client_request_id_is_unique_per_user(clean_database: None) -> None:
    session = SessionLocal()
    user_a = uuid4()
    user_b = uuid4()
    key = uuid4()

    try:
        goal_a = _insert_goal(session, user_a)
        goal_b = _insert_goal(session, user_b)
        _insert_goal_transaction(session, goal_a, user_a, client_request_id=key)
        _insert_goal_transaction(session, goal_b, user_b, client_request_id=key)
        _insert_goal_transaction(session, goal_a, user_a)
        _insert_goal_transaction(session, goal_a, user_a)
        session.commit()

        with pytest.raises(IntegrityError) as error:
            _insert_goal_transaction(session, goal_a, user_a, client_request_id=key)
        session.rollback()

        assert _violated_constraint(error.value) == (
            "uq_goal_transactions_user_id_client_request_id"
        )
    finally:
        session.close()


# Tests that the current application code keeps working on the expanded
# schema (VF-020B2 compatibility invariant): goal create, update and list,
# contributions, withdrawals, transaction history and goal analytics, with
# every new transaction leaving the three expand columns NULL.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if every operation succeeds with the expected values.
def test_application_goal_flows_work_on_expanded_schema(clean_database: None) -> None:
    session = SessionLocal()
    user_id = uuid4()

    try:
        goal = goal_service.create_goal(
            db_session=session,
            goal_data=GoalCreate(name="Emergency", target_amount=Decimal("1000"), currency="EUR"),
            user_id=user_id,
        )
        renamed = goal_service.update_goal(
            db_session=session,
            goal_id=goal.id,
            goal_data=GoalUpdate(name="Emergency fund"),
            user_id=user_id,
        )
        contribution = goal_service.create_goal_transaction(
            db_session=session,
            goal_id=goal.id,
            transaction_data=GoalTransactionCreate(type="contribution", amount=Decimal("300")),
            user_id=user_id,
        )
        withdrawal = goal_service.create_goal_transaction(
            db_session=session,
            goal_id=goal.id,
            transaction_data=GoalTransactionCreate(type="withdrawal", amount=Decimal("100")),
            user_id=user_id,
        )

        goals = goal_service.get_goals(db_session=session, user_id=user_id)
        history = goal_service.get_goal_transactions(
            db_session=session, goal_id=goal.id, user_id=user_id,
        )
        progress = analytics_service.get_goal_progress(db_session=session, user_id=user_id)

        assert renamed.name == "Emergency fund"
        assert [(g.id, g.current_amount) for g in goals] == [(goal.id, Decimal("200.00"))]
        assert {t.id for t in history} == {withdrawal.id, contribution.id}
        assert [(p.goal_id, p.current_amount) for p in progress] == [(goal.id, Decimal("200.00"))]
        assert _expand_columns(session, contribution.id) == (None, None, None)
        assert _expand_columns(session, withdrawal.id) == (None, None, None)
    finally:
        session.close()
