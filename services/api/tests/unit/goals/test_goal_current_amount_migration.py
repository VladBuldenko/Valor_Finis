from decimal import Decimal
from uuid import uuid4

from sqlalchemy import inspect, text

from app.db.database_session import SessionLocal, engine
from app.modules.goals import goal_repository, goal_transaction_repository
from app.modules.goals.goal_schemas import GoalCreate

# Mirrors the ledger-reconstruction subquery in
# alembic/versions/220b12b15adc_remove_legacy_goal_current_amount_.py's
# downgrade() exactly. Kept as isolated SQL-level verification (the same
# convention the superseded VF-016B backfill test used) rather than
# literally flipping the shared test database's schema with live Alembic
# upgrade/downgrade calls inside the pytest suite, which would risk
# corrupting the schema for every other test in the run if it failed
# partway. If the migration's downgrade SQL ever changes, this copy must
# change with it. The migration's upgrade()/downgrade() round trip itself
# (column + constraint add/drop, and this same reconstruction) was
# separately verified end-to-end via the Alembic CLI against a disposable
# database as part of VF-016G's manual verification.
_RECONSTRUCTION_SQL = """
    SELECT
        SUM(
            CASE
                WHEN type = 'withdrawal' THEN -amount
                ELSE amount
            END
        ) AS balance
    FROM goal_transactions
    WHERE goal_id = :goal_id
"""


def _create_goal(db_session, user_id, target_amount=Decimal("1000")):
    return goal_repository.create_goal(
        db_session=db_session,
        goal_data=GoalCreate(
            name="Vacation",
            target_amount=target_amount,
            currency="EUR",
        ),
        user_id=user_id,
    )


# Tests that goals has no current_amount column and no
# ck_goals_current_amount_non_negative constraint at HEAD.
# This test exists as the live-database counterpart to
# test_goal_model_has_no_current_amount_column (which only checks the ORM
# mapping): it proves the migration's upgrade() effect actually holds in
# the real schema, not merely in SQLAlchemy's in-memory model metadata.
# Parameters:
# - None.
# Returns:
# - None. The test passes if neither the column nor the constraint exist.
def test_goals_table_has_no_current_amount_column_or_constraint() -> None:
    inspector = inspect(engine)

    columns = {column["name"] for column in inspector.get_columns("goals")}
    assert "current_amount" not in columns

    check_constraints = {
        constraint["name"] for constraint in inspector.get_check_constraints("goals")
    }
    assert "ck_goals_current_amount_non_negative" not in check_constraints


# Tests that the migration downgrade's ledger-reconstruction SQL matches
# calculate_ledger_balance's Python-level result for a goal with no
# transaction history.
# This test exists to prove the reconstruction formula stays correct for
# the case the migration itself does not compute at all (it instead relies
# on the newly added column's own server_default of 0 for such goals) -
# regressing this would mean a future schema change silently breaks that
# assumption.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the reconstruction SQL returns NULL (meaning
#   "no ledger rows", the case upgrade()'s downgrade relies on the column
#   default to cover) and the ledger balance is 0.
def test_reconstruction_sql_matches_ledger_balance_for_goal_with_no_transactions(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)

        reconstructed = db_session.execute(
            text(_RECONSTRUCTION_SQL), {"goal_id": goal.id}
        ).scalar()
        assert reconstructed is None

        ledger_balance = goal_transaction_repository.calculate_ledger_balance(
            db_session=db_session, goal_id=goal.id, user_id=user_id
        )
        assert ledger_balance == Decimal("0.00")
    finally:
        db_session.close()


# Tests that the migration downgrade's ledger-reconstruction SQL matches
# calculate_ledger_balance for a goal funded solely by an opening_balance
# transaction (the VF-016B backfill shape).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both values equal 200.00.
def test_reconstruction_sql_matches_ledger_balance_for_opening_balance_only(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        goal_transaction_repository.create_transaction(
            db_session=db_session,
            goal_id=goal.id,
            user_id=user_id,
            type="opening_balance",
            amount=Decimal("200.00"),
            description=None,
        )

        reconstructed = db_session.execute(
            text(_RECONSTRUCTION_SQL), {"goal_id": goal.id}
        ).scalar()
        ledger_balance = goal_transaction_repository.calculate_ledger_balance(
            db_session=db_session, goal_id=goal.id, user_id=user_id
        )

        assert reconstructed == Decimal("200.00")
        assert ledger_balance == Decimal("200.00")
    finally:
        db_session.close()


# Tests that the migration downgrade's ledger-reconstruction SQL matches
# calculate_ledger_balance when contributions and withdrawals both exist,
# including the withdrawal-as-negative direction the SQL's CASE expression
# encodes.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both values equal 70.00 (100 contributed, 30
#   withdrawn).
def test_reconstruction_sql_matches_ledger_balance_for_contribution_and_withdrawal(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        goal_transaction_repository.create_transaction(
            db_session=db_session,
            goal_id=goal.id,
            user_id=user_id,
            type="contribution",
            amount=Decimal("100.00"),
            description=None,
        )
        goal_transaction_repository.create_transaction(
            db_session=db_session,
            goal_id=goal.id,
            user_id=user_id,
            type="withdrawal",
            amount=Decimal("30.00"),
            description=None,
        )

        reconstructed = db_session.execute(
            text(_RECONSTRUCTION_SQL), {"goal_id": goal.id}
        ).scalar()
        ledger_balance = goal_transaction_repository.calculate_ledger_balance(
            db_session=db_session, goal_id=goal.id, user_id=user_id
        )

        assert reconstructed == Decimal("70.00")
        assert ledger_balance == Decimal("70.00")
    finally:
        db_session.close()


# Tests that the migration downgrade's ledger-reconstruction SQL matches
# calculate_ledger_balance for an overfunded goal (balance above
# target_amount), proving the reconstruction never clamps or caps the
# value.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both values equal 150.00 against a 100 target.
def test_reconstruction_sql_matches_ledger_balance_for_overfunded_goal(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, target_amount=Decimal("100"))
        goal_transaction_repository.create_transaction(
            db_session=db_session,
            goal_id=goal.id,
            user_id=user_id,
            type="contribution",
            amount=Decimal("150.00"),
            description=None,
        )

        reconstructed = db_session.execute(
            text(_RECONSTRUCTION_SQL), {"goal_id": goal.id}
        ).scalar()
        ledger_balance = goal_transaction_repository.calculate_ledger_balance(
            db_session=db_session, goal_id=goal.id, user_id=user_id
        )

        assert reconstructed == Decimal("150.00")
        assert ledger_balance == Decimal("150.00")
        assert reconstructed > goal.target_amount
    finally:
        db_session.close()
