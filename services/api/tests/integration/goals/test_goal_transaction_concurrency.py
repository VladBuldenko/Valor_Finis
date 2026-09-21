import threading
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from app.db.database_session import SessionLocal
from app.modules.goals import goal_repository, goal_transaction_repository
from app.modules.goals import goal_service
from app.modules.goals.goal_errors import GoalInsufficientFundsError
from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_schemas import GoalCreate
from app.modules.goals.goal_transaction_schemas import GoalTransactionCreate


# Tests the critical concurrency invariant (VF-016C): two simultaneous
# withdrawal requests against a Goal with a 100 EUR balance, each for 80
# EUR, must not both succeed.
# This test exists to prove SELECT ... FOR UPDATE actually serializes
# concurrent balance-changing writes at the PostgreSQL level, not merely in
# application code. It uses two real threads, each with its own SQLAlchemy
# Session/connection, synchronized with a Barrier so both requests reach
# create_goal_transaction at essentially the same instant - this is
# genuine concurrency, not two sequential calls to the same service
# function on one connection.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if exactly one withdrawal succeeds, exactly one
#   fails with GoalInsufficientFundsError, and the final ledger/
#   current_amount balance is 20.00.
def test_concurrent_withdrawals_cannot_overdraw_goal(clean_database: None) -> None:
    # Arrange: a goal with a 100 EUR balance, funded through the same
    # atomic write path this test is exercising.
    setup_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = goal_repository.create_goal(
            db_session=setup_session,
            goal_data=GoalCreate(
                name="Emergency fund",
                target_amount=Decimal("1000"),
                currency="EUR",
            ),
            user_id=user_id,
        )
        goal_id = goal.id

        goal_service.create_goal_transaction(
            db_session=setup_session,
            goal_id=goal_id,
            transaction_data=GoalTransactionCreate(
                type="contribution",
                amount=Decimal("100.00"),
            ),
            user_id=user_id,
        )
    finally:
        setup_session.close()

    barrier = threading.Barrier(2)
    results: dict[str, Optional[str]] = {}
    results_lock = threading.Lock()

    def attempt_withdrawal(thread_name: str) -> None:
        db_session = SessionLocal()

        try:
            # Both threads wait here so their SELECT ... FOR UPDATE calls
            # race each other for real, instead of running one fully
            # before the other starts.
            barrier.wait(timeout=10)

            goal_service.create_goal_transaction(
                db_session=db_session,
                goal_id=goal_id,
                transaction_data=GoalTransactionCreate(
                    type="withdrawal",
                    amount=Decimal("80.00"),
                ),
                user_id=user_id,
            )
            outcome = "succeeded"
        except GoalInsufficientFundsError:
            outcome = "insufficient_funds"
        finally:
            db_session.close()

        with results_lock:
            results[thread_name] = outcome

    # Act
    thread_a = threading.Thread(target=attempt_withdrawal, args=("a",))
    thread_b = threading.Thread(target=attempt_withdrawal, args=("b",))

    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    # Assert
    outcomes = list(results.values())
    assert sorted(outcomes) == ["insufficient_funds", "succeeded"]

    verify_session = SessionLocal()

    try:
        final_goal = (
            verify_session.query(GoalModel)
            .filter(GoalModel.id == goal_id)
            .first()
        )
        assert final_goal is not None
        assert final_goal.current_amount == Decimal("20.00")

        ledger_balance = goal_transaction_repository.calculate_ledger_balance(
            db_session=verify_session,
            goal_id=goal_id,
            user_id=user_id,
        )
        assert ledger_balance == Decimal("20.00")

        transactions = goal_transaction_repository.get_transactions_for_goal(
            db_session=verify_session,
            goal_id=goal_id,
            user_id=user_id,
        )
        withdrawal_count = sum(1 for t in transactions if t.type == "withdrawal")
        assert withdrawal_count == 1
    finally:
        verify_session.close()
