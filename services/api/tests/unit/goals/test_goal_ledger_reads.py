from decimal import Decimal
from uuid import uuid4

from sqlalchemy import event

from app.db.database_session import SessionLocal, engine
from app.modules.goals import goal_repository, goal_service, goal_transaction_repository
from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_schemas import GoalCreate, GoalUpdate
from app.modules.goals.goal_transaction_schemas import GoalTransactionCreate


def _create_goal(db_session, user_id, target_amount=Decimal("2000")) -> GoalModel:
    return goal_repository.create_goal(
        db_session=db_session,
        goal_data=GoalCreate(
            name="Vacation",
            target_amount=target_amount,
            currency="EUR",
        ),
        user_id=user_id,
    )


def _add_transaction(db_session, goal_id, user_id, type, amount) -> None:
    goal_transaction_repository.create_transaction(
        db_session=db_session,
        goal_id=goal_id,
        user_id=user_id,
        type=type,
        amount=amount,
        description=None,
    )


# ------------------------------------------------------------------
# Repository: get_ledger_balances_for_user
# ------------------------------------------------------------------


# Tests that a user with no goal transactions gets an empty balance mapping.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the mapping is empty.
def test_get_ledger_balances_for_user_returns_empty_mapping_when_no_transactions(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        _create_goal(db_session, user_id)

        balances = goal_transaction_repository.get_ledger_balances_for_user(
            db_session=db_session,
            user_id=user_id,
        )

        assert balances == {}
    finally:
        db_session.close()


# Tests that the bulk balance mapping computes correct per-goal balances
# across multiple goals in a single call, including opening_balance,
# contribution, and withdrawal math.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if each goal's balance is exactly correct.
def test_get_ledger_balances_for_user_computes_correct_balances_for_multiple_goals(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal_a = _create_goal(db_session, user_id)
        goal_b = _create_goal(db_session, user_id)
        goal_c = _create_goal(db_session, user_id)

        _add_transaction(db_session, goal_a.id, user_id, "opening_balance", Decimal("100.00"))
        _add_transaction(db_session, goal_a.id, user_id, "contribution", Decimal("50.00"))
        _add_transaction(db_session, goal_a.id, user_id, "withdrawal", Decimal("30.00"))

        _add_transaction(db_session, goal_b.id, user_id, "contribution", Decimal("999.99"))
        # goal_c has no transactions at all.

        balances = goal_transaction_repository.get_ledger_balances_for_user(
            db_session=db_session,
            user_id=user_id,
        )

        assert balances[goal_a.id] == Decimal("120.00")
        assert balances[goal_b.id] == Decimal("999.99")
        assert goal_c.id not in balances
    finally:
        db_session.close()


# Tests that another user's goal transactions never appear in this user's
# balance mapping.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the requesting user's goal is present.
def test_get_ledger_balances_for_user_ownership_isolation(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        other_goal = _create_goal(db_session, other_user_id)

        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("10.00"))
        _add_transaction(db_session, other_goal.id, other_user_id, "contribution", Decimal("999.00"))

        balances = goal_transaction_repository.get_ledger_balances_for_user(
            db_session=db_session,
            user_id=user_id,
        )

        assert balances == {goal.id: Decimal("10.00")}
    finally:
        db_session.close()


# ------------------------------------------------------------------
# Service: goal_service.get_goals / create_goal / update_goal
# ------------------------------------------------------------------


# Tests that a newly created goal (no transactions) reports current_amount
# 0.00 via the same ledger-derived read path as every other Goal response.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if current_amount is exactly Decimal("0.00").
def test_create_goal_reports_zero_current_amount(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        response = goal_service.create_goal(
            db_session=db_session,
            goal_data=GoalCreate(name="Vacation", target_amount=Decimal("2000"), currency="EUR"),
            user_id=user_id,
        )

        assert response.current_amount == Decimal("0.00")
    finally:
        db_session.close()


# Tests that get_goals reports a ledger-derived balance combining
# opening_balance, contribution, and withdrawal for exact Decimal math.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if current_amount matches the ledger sum exactly.
def test_get_goals_reports_exact_ledger_derived_balance(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        _add_transaction(db_session, goal.id, user_id, "opening_balance", Decimal("100.00"))
        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("50.00"))
        _add_transaction(db_session, goal.id, user_id, "withdrawal", Decimal("30.00"))

        goals = goal_service.get_goals(db_session=db_session, user_id=user_id)

        assert len(goals) == 1
        assert goals[0].current_amount == Decimal("120.00")
    finally:
        db_session.close()


# Tests that an overfunded goal's response current_amount exceeds
# target_amount.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if current_amount > target_amount.
def test_get_goals_reports_overfunded_balance_above_target(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, target_amount=Decimal("100"))
        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("150.00"))

        goals = goal_service.get_goals(db_session=db_session, user_id=user_id)

        assert goals[0].current_amount == Decimal("150.00")
        assert goals[0].current_amount > goals[0].target_amount
    finally:
        db_session.close()


# Tests that a zero-transaction goal remains visible in get_goals, with a
# 0.00 balance, alongside a funded goal.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both goals appear with correct balances.
def test_get_goals_zero_transaction_goal_remains_visible(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        funded_goal = _create_goal(db_session, user_id)
        _add_transaction(db_session, funded_goal.id, user_id, "contribution", Decimal("40.00"))
        unfunded_goal = _create_goal(db_session, user_id)

        goals = goal_service.get_goals(db_session=db_session, user_id=user_id)

        by_id = {goal.id: goal for goal in goals}
        assert len(goals) == 2
        assert by_id[funded_goal.id].current_amount == Decimal("40.00")
        assert by_id[unfunded_goal.id].current_amount == Decimal("0.00")
    finally:
        db_session.close()


# Tests that get_goals ordering remains created_at DESC, unaffected by the
# ledger-balance lookup.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if goals are returned newest-first.
def test_get_goals_ordering_remains_created_at_desc(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        first_goal = _create_goal(db_session, user_id)
        second_goal = _create_goal(db_session, user_id)
        third_goal = _create_goal(db_session, user_id)

        goals = goal_service.get_goals(db_session=db_session, user_id=user_id)

        assert [goal.id for goal in goals] == [
            third_goal.id,
            second_goal.id,
            first_goal.id,
        ]
    finally:
        db_session.close()


# Tests that get_goals never reports another user's ledger balance.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the requesting user's balance is used.
def test_get_goals_ownership_isolation(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id)
        other_goal = _create_goal(db_session, other_user_id)

        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("10.00"))
        _add_transaction(db_session, other_goal.id, other_user_id, "contribution", Decimal("999.00"))

        goals = goal_service.get_goals(db_session=db_session, user_id=user_id)

        assert len(goals) == 1
        assert goals[0].current_amount == Decimal("10.00")
    finally:
        db_session.close()


# ------------------------------------------------------------------
# Authoritative ledger / drift
# ------------------------------------------------------------------


# Tests the critical VF-016D invariant: when the transitional
# goals.current_amount column disagrees with the ledger, get_goals must
# trust the ledger, and must not repair the stale column as a side effect
# of reading it.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the response reflects the ledger (150.00),
#   the corrupted column (999.00) is never returned, and the column
#   remains corrupted in the database after the read.
def test_get_goals_ignores_stale_current_amount_column(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, target_amount=Decimal("1000"))
        _add_transaction(db_session, goal.id, user_id, "opening_balance", Decimal("100.00"))
        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("50.00"))

        # Corrupt the transitional column directly, bypassing every
        # application write path.
        goal.current_amount = Decimal("999.00")
        db_session.commit()

        # Act
        goals = goal_service.get_goals(db_session=db_session, user_id=user_id)

        # Assert: the ledger value (150.00) wins, not the corrupted column.
        assert goals[0].current_amount == Decimal("150.00")

        # Assert: reading did not repair the stale column.
        verify_session = SessionLocal()
        try:
            raw_goal = (
                verify_session.query(GoalModel)
                .filter(GoalModel.id == goal.id)
                .first()
            )
            assert raw_goal.current_amount == Decimal("999.00")
        finally:
            verify_session.close()
    finally:
        db_session.close()


# Tests that update_goal's response also trusts the ledger over a stale
# current_amount column, even when the PATCH itself only touches an
# unrelated field (name).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the response reflects the ledger, not the
#   corrupted column.
def test_update_goal_ignores_stale_current_amount_column(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = _create_goal(db_session, user_id, target_amount=Decimal("1000"))
        _add_transaction(db_session, goal.id, user_id, "opening_balance", Decimal("100.00"))
        _add_transaction(db_session, goal.id, user_id, "contribution", Decimal("50.00"))

        goal.current_amount = Decimal("999.00")
        db_session.commit()

        # Act
        response = goal_service.update_goal(
            db_session=db_session,
            goal_id=goal.id,
            goal_data=GoalUpdate(name="Renamed vacation"),
            user_id=user_id,
        )

        # Assert
        assert response.name == "Renamed vacation"
        assert response.current_amount == Decimal("150.00")
    finally:
        db_session.close()


# ------------------------------------------------------------------
# Query behavior: no N+1
# ------------------------------------------------------------------


# Tests that get_goals issues a bounded, small number of SQL statements
# regardless of how many goals the user has.
# This test exists to prove the ledger-balance lookup is a single grouped
# query, not one query per goal (VF-016D). Five goals with transactions
# must not issue more queries than a single goal would.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the query count stays at or below 2
#   (one goals query + one grouped balance query) for five goals.
def test_get_goals_does_not_n_plus_1_query_ledger_balances(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        for index in range(5):
            goal = _create_goal(db_session, user_id)
            _add_transaction(
                db_session, goal.id, user_id, "contribution", Decimal(f"{10 + index}.00"),
            )

        query_count = 0

        def count_queries(conn, cursor, statement, parameters, context, executemany):
            nonlocal query_count
            query_count += 1

        event.listen(engine, "before_cursor_execute", count_queries)
        try:
            goals = goal_service.get_goals(db_session=db_session, user_id=user_id)
        finally:
            event.remove(engine, "before_cursor_execute", count_queries)

        assert len(goals) == 5
        assert query_count <= 2
    finally:
        db_session.close()
