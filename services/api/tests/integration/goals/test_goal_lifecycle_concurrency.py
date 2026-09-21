import threading
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from app.db.database_session import SessionLocal
from app.modules.goals import goal_repository, goal_transaction_repository
from app.modules.goals import goal_service
from app.modules.goals.goal_errors import GoalDeletionNotAllowedError, GoalNotFoundError
from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_schemas import GoalCreate, GoalUpdate
from app.modules.goals.goal_transaction_schemas import GoalTransactionCreate


# Tests the VF-016E concurrency invariant for currency change vs. the
# first contribution: whichever operation locks the Goal row first via
# SELECT ... FOR UPDATE determines the outcome for the other, and the two
# outcomes never mix inconsistently.
# This test exists to prove the race is genuinely resolved by the database
# row lock, not by application-level luck - it uses two real threads, each
# with its own SQLAlchemy Session/connection, synchronized with a Barrier
# so both requests reach their respective service calls at essentially the
# same instant.
#
# Valid final states (exactly one must hold):
# - currency change succeeded => final currency is USD (proves it ran
#   before the contribution's lock acquisition, since a later run would
#   have seen history and been rejected).
# - currency change was rejected => final currency is still EUR, and the
#   contribution must have succeeded (it never depends on currency).
# The contribution itself must always succeed in both cases - nothing in
# the currency-immutability rule can ever block a transaction write.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the two outcomes are mutually consistent and
#   the contribution always succeeds.
def test_concurrent_currency_change_vs_first_contribution(clean_database: None) -> None:
    # Arrange
    setup_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = goal_repository.create_goal(
            db_session=setup_session,
            goal_data=GoalCreate(
                name="Vacation", target_amount=Decimal("1000"), currency="EUR",
            ),
            user_id=user_id,
        )
        goal_id = goal.id
    finally:
        setup_session.close()

    barrier = threading.Barrier(2)
    results: dict[str, Optional[str]] = {}
    results_lock = threading.Lock()

    def attempt_currency_change() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            goal_service.update_goal(
                db_session=db_session,
                goal_id=goal_id,
                goal_data=GoalUpdate(currency="USD"),
                user_id=user_id,
            )
            outcome = "succeeded"
        except Exception:
            outcome = "rejected"
        finally:
            db_session.close()

        with results_lock:
            results["currency_change"] = outcome

    def attempt_contribution() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            goal_service.create_goal_transaction(
                db_session=db_session,
                goal_id=goal_id,
                transaction_data=GoalTransactionCreate(
                    type="contribution", amount=Decimal("50.00"),
                ),
                user_id=user_id,
            )
            outcome = "succeeded"
        except Exception:
            outcome = "failed"
        finally:
            db_session.close()

        with results_lock:
            results["contribution"] = outcome

    # Act
    thread_a = threading.Thread(target=attempt_currency_change)
    thread_b = threading.Thread(target=attempt_contribution)

    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    # Assert: the contribution never depends on currency, so it must
    # always succeed regardless of lock order.
    assert results["contribution"] == "succeeded"

    verify_session = SessionLocal()
    try:
        final_goal = (
            verify_session.query(GoalModel).filter(GoalModel.id == goal_id).first()
        )
        assert final_goal is not None

        if results["currency_change"] == "succeeded":
            # Proves the currency change ran (and committed) before the
            # contribution established history.
            assert final_goal.currency == "USD"
        else:
            # Proves the contribution's history existed by the time the
            # currency change was evaluated.
            assert final_goal.currency == "EUR"

        # Either way, the contribution's history must be present.
        assert goal_transaction_repository.has_transactions_for_goal(
            db_session=verify_session, goal_id=goal_id, user_id=user_id,
        )
    finally:
        verify_session.close()


# Tests the VF-016E concurrency invariant for DELETE vs. the first
# contribution: exactly one of two legitimate lock-order outcomes must
# hold, and no inconsistent state (an orphaned transaction, a deleted Goal
# with surviving history references, or a raw IntegrityError/500) is ever
# produced.
# This test exists to prove the race is genuinely resolved by the database
# row lock, using two real threads with their own Sessions/connections,
# synchronized with a Barrier.
#
# Valid final states (exactly one must hold):
# - DELETE succeeded (Goal locked/deleted first) => the contribution must
#   fail with GoalNotFoundError, since the Goal row no longer exists for it
#   to lock.
# - DELETE was rejected with GoalDeletionNotAllowedError => the
#   contribution must have succeeded (it committed the history that
#   DELETE's lock-order-later check observed).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the two outcomes are mutually consistent and
#   no third, inconsistent outcome occurs.
def test_concurrent_delete_vs_first_contribution(clean_database: None) -> None:
    # Arrange
    setup_session = SessionLocal()
    user_id = uuid4()

    try:
        goal = goal_repository.create_goal(
            db_session=setup_session,
            goal_data=GoalCreate(
                name="Vacation", target_amount=Decimal("1000"), currency="EUR",
            ),
            user_id=user_id,
        )
        goal_id = goal.id
    finally:
        setup_session.close()

    barrier = threading.Barrier(2)
    results: dict[str, Optional[str]] = {}
    results_lock = threading.Lock()

    def attempt_delete() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            goal_service.delete_goal(db_session=db_session, goal_id=goal_id, user_id=user_id)
            outcome = "succeeded"
        except GoalDeletionNotAllowedError:
            outcome = "rejected_has_history"
        except Exception:
            outcome = "error"
        finally:
            db_session.close()

        with results_lock:
            results["delete"] = outcome

    def attempt_contribution() -> None:
        db_session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            goal_service.create_goal_transaction(
                db_session=db_session,
                goal_id=goal_id,
                transaction_data=GoalTransactionCreate(
                    type="contribution", amount=Decimal("50.00"),
                ),
                user_id=user_id,
            )
            outcome = "succeeded"
        except GoalNotFoundError:
            outcome = "not_found"
        except Exception:
            outcome = "error"
        finally:
            db_session.close()

        with results_lock:
            results["contribution"] = outcome

    # Act
    thread_a = threading.Thread(target=attempt_delete)
    thread_b = threading.Thread(target=attempt_contribution)

    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    # Assert: only the two legitimate outcome pairs are acceptable.
    outcome_pair = (results["delete"], results["contribution"])
    assert outcome_pair in [
        ("succeeded", "not_found"),
        ("rejected_has_history", "succeeded"),
    ], outcome_pair

    # Cross-check final database state matches the observed outcome.
    verify_session = SessionLocal()
    try:
        final_goal = (
            verify_session.query(GoalModel).filter(GoalModel.id == goal_id).first()
        )

        if outcome_pair == ("succeeded", "not_found"):
            assert final_goal is None
        else:
            assert final_goal is not None
            assert goal_transaction_repository.has_transactions_for_goal(
                db_session=verify_session, goal_id=goal_id, user_id=user_id,
            )
    finally:
        verify_session.close()
