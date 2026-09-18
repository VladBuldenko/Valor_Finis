from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text

from app.db.database_session import SessionLocal
from app.modules.goals import goal_repository
from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_schemas import GoalCreate
from app.modules.goals.goal_transaction_models import GoalTransactionModel

# Mirrors the raw SQL backfill in
# alembic/versions/e90a257f987b_add_goal_transactions_and_backfill.py exactly.
# Kept as "equivalent isolated DB verification" (per VF-016B's own test
# requirements) rather than re-running Alembic inside pytest: this proves the
# backfill's semantics against seeded, known Goal rows in a normal test
# transaction. If the migration's SQL ever changes, this copy must change
# with it.
_BACKFILL_SQL = """
    INSERT INTO goal_transactions (
        id, goal_id, user_id, type, amount, description, created_at
    )
    SELECT
        gen_random_uuid(),
        g.id,
        g.user_id,
        'opening_balance',
        g.current_amount,
        NULL,
        g.created_at
    FROM goals g
    WHERE g.current_amount > 0
    AND NOT EXISTS (
        SELECT 1 FROM goal_transactions gt
        WHERE gt.goal_id = g.id AND gt.type = 'opening_balance'
    )
"""


def _create_goal(db_session, user_id, current_amount) -> GoalModel:
    return goal_repository.create_goal(
        db_session=db_session,
        goal_data=GoalCreate(
            name="Emergency fund",
            target_amount=Decimal("1000"),
            current_amount=current_amount,
            currency="EUR",
            target_date=date(2026, 12, 31),
            status="active",
        ),
        user_id=user_id,
    )


def _run_backfill(db_session) -> None:
    db_session.execute(text(_BACKFILL_SQL))
    db_session.commit()


def _opening_balances_for_goal(db_session, goal_id):
    return (
        db_session.query(GoalTransactionModel)
        .filter(
            GoalTransactionModel.goal_id == goal_id,
            GoalTransactionModel.type == "opening_balance",
        )
        .all()
    )


# Tests that a Goal with a zero legacy balance receives no opening_balance
# row from the backfill.
# This test exists to prove the migration never manufactures money for a
# Goal that has nothing to record, per the approved VF-016 architecture.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if no opening_balance row exists after backfill.
def test_backfill_creates_no_opening_balance_for_zero_balance_goal(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, Decimal("0"))

        _run_backfill(db_session)

        assert _opening_balances_for_goal(db_session, goal.id) == []
    finally:
        db_session.close()


# Tests that a Goal with a positive legacy balance receives exactly one
# opening_balance row whose amount matches that legacy balance.
# This test exists to prove the backfill losslessly preserves existing
# balances as ledger history, per the approved VF-016 architecture.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if exactly one row exists with the expected amount.
def test_backfill_creates_exactly_one_opening_balance_matching_legacy_amount(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, Decimal("742.50"))

        _run_backfill(db_session)

        rows = _opening_balances_for_goal(db_session, goal.id)
        assert len(rows) == 1
        assert rows[0].amount == Decimal("742.50")
    finally:
        db_session.close()


# Tests that the backfilled opening_balance row's goal_id and user_id match
# the source Goal exactly.
# This test exists to prove ownership is copied directly from the Goal, not
# inferred any other way, per the approved VF-016 architecture.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if goal_id/user_id match the source Goal.
def test_backfill_opening_balance_ownership_matches_goal(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, Decimal("300"))

        _run_backfill(db_session)

        rows = _opening_balances_for_goal(db_session, goal.id)
        assert len(rows) == 1
        assert rows[0].goal_id == goal.id
        assert rows[0].user_id == user_id
    finally:
        db_session.close()


# Tests that the backfilled opening_balance row's created_at uses the Goal's
# own created_at, not the time the backfill ran.
# This test exists to prove the opening balance represents pre-existing
# state rather than a new event made during deployment.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if created_at matches the Goal's created_at exactly.
def test_backfill_opening_balance_timestamp_matches_goal_created_at(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, Decimal("50"))

        # Rewrites created_at to a distinctive, clearly-not-"now" timestamp so
        # a backfill that mistakenly used NOW() instead of the Goal's own
        # created_at would make this assertion fail.
        historical_created_at = datetime(2020, 1, 15, 9, 30, tzinfo=timezone.utc)
        db_session.execute(
            text("UPDATE goals SET created_at = :created_at WHERE id = :goal_id"),
            {"created_at": historical_created_at, "goal_id": goal.id},
        )
        db_session.commit()

        _run_backfill(db_session)

        rows = _opening_balances_for_goal(db_session, goal.id)
        assert len(rows) == 1
        assert rows[0].created_at == historical_created_at
    finally:
        db_session.close()


# Tests that re-executing the backfill SQL does not create a duplicate
# opening_balance row for the same Goal.
# This test exists to prove the NOT EXISTS guard makes the backfill safe to
# re-run, e.g. during local debugging.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if exactly one opening_balance row exists after two
#   executions.
def test_backfill_reexecution_does_not_duplicate_opening_balance(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, Decimal("120"))

        _run_backfill(db_session)
        _run_backfill(db_session)

        rows = _opening_balances_for_goal(db_session, goal.id)
        assert len(rows) == 1
        assert rows[0].amount == Decimal("120.00")
    finally:
        db_session.close()


# Tests that the backfill handles a mix of zero- and non-zero-balance Goals
# across multiple users correctly in a single pass.
# This test exists to prove the WHERE clause and NOT EXISTS guard behave
# correctly together at more than trivial scale, not just for one Goal.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the funded goals receive opening_balance
#   rows.
def test_backfill_handles_mixed_zero_and_nonzero_goals_across_users(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_one = uuid4()
    user_two = uuid4()

    try:
        funded_goal = _create_goal(db_session, user_one, Decimal("400"))
        unfunded_goal = _create_goal(db_session, user_one, Decimal("0"))
        other_funded_goal = _create_goal(db_session, user_two, Decimal("15.75"))

        _run_backfill(db_session)

        assert len(_opening_balances_for_goal(db_session, funded_goal.id)) == 1
        assert _opening_balances_for_goal(db_session, unfunded_goal.id) == []
        assert len(_opening_balances_for_goal(db_session, other_funded_goal.id)) == 1
    finally:
        db_session.close()
