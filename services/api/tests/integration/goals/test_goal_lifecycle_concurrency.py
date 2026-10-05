import threading
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.db.database_session import SessionLocal
from app.modules.goals import goal_repository, goal_transaction_repository
from app.modules.goals import goal_service
from app.modules.goals.goal_errors import (
    GoalArchivedError,
    GoalDeletionNotAllowedError,
    GoalNotFoundError,
)
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


# Polls pg_stat_activity until some other backend in this database is
# waiting on a heavyweight lock, or the timeout expires (same approach as
# tests/integration/receipts/test_receipt_confirm_concurrency.py).
# This function exists so the archive-vs-contribution tests observe - rather
# than guess from timing - that the second operation is genuinely blocked
# on the goal row lock while the first one still holds it.
# Parameters:
# - timeout_seconds: maximum time to wait.
# Returns:
# - True when a lock-waiting backend was observed, otherwise False.
def _wait_for_lock_waiter(timeout_seconds: float = 10.0) -> bool:
    observed = threading.Event()
    stop = threading.Event()

    def poll() -> None:
        session = SessionLocal()
        try:
            while not stop.is_set():
                waiting = session.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND wait_event_type = 'Lock' "
                        "AND pid <> pg_backend_pid()"
                    )
                ).scalar_one()
                session.rollback()

                if waiting > 0:
                    observed.set()
                    return

                # Event.wait doubles as a short, bounded poll interval.
                stop.wait(0.05)
        finally:
            session.close()

    poller = threading.Thread(target=poll)
    poller.start()
    observed.wait(timeout=timeout_seconds)
    stop.set()
    poller.join(timeout=5)
    return observed.is_set()


# Creates an active EUR goal holding one 100.00 contribution.
# Parameters:
# - user_id: owner of the goal.
# Returns:
# - The new goal's id.
def _create_goal_with_contribution(user_id: UUID) -> UUID:
    session = SessionLocal()
    try:
        goal = goal_repository.create_goal(
            db_session=session,
            goal_data=GoalCreate(
                name="Vacation", target_amount=Decimal("1000"), currency="EUR",
            ),
            user_id=user_id,
        )
        goal_service.create_goal_transaction(
            db_session=session,
            goal_id=goal.id,
            transaction_data=GoalTransactionCreate(
                type="contribution", amount=Decimal("100.00"),
            ),
            user_id=user_id,
        )
        return goal.id
    finally:
        session.close()


# Archives a goal through the service in its own session.
# Parameters:
# - goal_id: goal to archive.
# - user_id: owner of the goal.
# Returns:
# - "succeeded", or "error:<ExceptionName>" for any failure.
def _archive_goal(goal_id: UUID, user_id: UUID) -> str:
    db_session = SessionLocal()
    try:
        goal_service.update_goal(
            db_session=db_session,
            goal_id=goal_id,
            goal_data=GoalUpdate(status="archived"),
            user_id=user_id,
        )
        return "succeeded"
    except Exception as error:
        return f"error:{type(error).__name__}"
    finally:
        db_session.close()


# Contributes 50.00 to a goal through the service in its own session.
# Parameters:
# - goal_id: goal receiving the contribution.
# - user_id: owner of the goal.
# Returns:
# - "succeeded", "archived_rejected" for GoalArchivedError, or
#   "error:<ExceptionName>" for any other failure.
def _contribute(goal_id: UUID, user_id: UUID) -> str:
    db_session = SessionLocal()
    try:
        goal_service.create_goal_transaction(
            db_session=db_session,
            goal_id=goal_id,
            transaction_data=GoalTransactionCreate(
                type="contribution", amount=Decimal("50.00"),
            ),
            user_id=user_id,
        )
        return "succeeded"
    except GoalArchivedError:
        return "archived_rejected"
    except Exception as error:
        return f"error:{type(error).__name__}"
    finally:
        db_session.close()


# Returns a goal's final status and its number of ledger rows.
# Parameters:
# - goal_id: goal to inspect.
# - user_id: owner of the goal.
# Returns:
# - (status, transaction_count).
def _final_goal_state(goal_id: UUID, user_id: UUID) -> "tuple[str, int]":
    session = SessionLocal()
    try:
        goal = session.query(GoalModel).filter(GoalModel.id == goal_id).one()
        transactions = goal_transaction_repository.get_transactions_for_goal(
            db_session=session, goal_id=goal_id, user_id=user_id,
        )
        return goal.status, len(transactions)
    finally:
        session.close()


# Tests the VF-020B1 archive-first ordering: a contribution that waits on
# the goal row lock held by an in-flight archive is rejected once the
# archive commits, and writes nothing.
# Determinism: apply_goal_update is gated so the archive stops AFTER
# acquiring the goal row lock but BEFORE committing. The contribution is
# started only then, and the test waits until PostgreSQL reports a backend
# blocked on a lock before releasing the archive.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to gate apply_goal_update.
# Returns:
# - None. The test passes if the archive succeeds, the contribution is
#   rejected with GoalArchivedError, and only the original row exists.
def test_contribution_waiting_on_archive_is_rejected(
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    goal_id = _create_goal_with_contribution(user_id)
    original_apply_goal_update = goal_repository.apply_goal_update
    archive_holds_lock = threading.Event()
    release_archive = threading.Event()

    def gated_apply_goal_update(**kwargs):
        archive_holds_lock.set()
        assert release_archive.wait(timeout=15)
        return original_apply_goal_update(**kwargs)

    monkeypatch.setattr(goal_repository, "apply_goal_update", gated_apply_goal_update)
    results: dict = {}

    archive_thread = threading.Thread(
        target=lambda: results.__setitem__("archive", _archive_goal(goal_id, user_id)),
    )
    contribution_thread = threading.Thread(
        target=lambda: results.__setitem__("contribution", _contribute(goal_id, user_id)),
    )

    archive_thread.start()
    assert archive_holds_lock.wait(timeout=10)
    contribution_thread.start()
    lock_waiter_observed = _wait_for_lock_waiter()
    release_archive.set()
    archive_thread.join(timeout=15)
    contribution_thread.join(timeout=15)

    assert lock_waiter_observed, "the contribution never blocked on the goal row lock"
    assert not archive_thread.is_alive() and not contribution_thread.is_alive()
    assert results == {"archive": "succeeded", "contribution": "archived_rejected"}
    assert _final_goal_state(goal_id, user_id) == ("archived", 1)


# Tests the VF-020B1 contribution-first ordering: an archive that waits on
# the goal row lock held by an in-flight contribution succeeds after the
# contribution commits.
# Determinism: create_transaction is gated so the contribution stops AFTER
# acquiring the goal row lock and passing the archived/balance checks, but
# BEFORE writing. The archive is started only then, and the test waits
# until PostgreSQL reports a backend blocked on a lock before releasing
# the contribution.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to gate create_transaction.
# Returns:
# - None. The test passes if both operations succeed, the goal ends
#   archived, and the ledger holds both contributions.
def test_archive_waiting_on_contribution_succeeds_after_it(
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    goal_id = _create_goal_with_contribution(user_id)
    original_create_transaction = goal_transaction_repository.create_transaction
    contribution_holds_lock = threading.Event()
    release_contribution = threading.Event()

    def gated_create_transaction(**kwargs):
        contribution_holds_lock.set()
        assert release_contribution.wait(timeout=15)
        return original_create_transaction(**kwargs)

    monkeypatch.setattr(
        goal_transaction_repository, "create_transaction", gated_create_transaction,
    )
    results: dict = {}

    contribution_thread = threading.Thread(
        target=lambda: results.__setitem__("contribution", _contribute(goal_id, user_id)),
    )
    archive_thread = threading.Thread(
        target=lambda: results.__setitem__("archive", _archive_goal(goal_id, user_id)),
    )

    contribution_thread.start()
    assert contribution_holds_lock.wait(timeout=10)
    archive_thread.start()
    lock_waiter_observed = _wait_for_lock_waiter()
    release_contribution.set()
    contribution_thread.join(timeout=15)
    archive_thread.join(timeout=15)

    assert lock_waiter_observed, "the archive never blocked on the goal row lock"
    assert not archive_thread.is_alive() and not contribution_thread.is_alive()
    assert results == {"archive": "succeeded", "contribution": "succeeded"}
    assert _final_goal_state(goal_id, user_id) == ("archived", 2)


# Tests the VF-020B1 archive-vs-contribution race without any gating: two
# real threads, each with its own Session/connection, released together by
# a Barrier, repeated several times so both lock orders can occur.
# Valid outcomes (exactly one per round):
# - the contribution won the lock => it succeeded and the goal holds two
#   rows (the setup contribution plus this one);
# - the archive won the lock => the contribution was rejected with
#   GoalArchivedError and the goal still holds one row.
# The archive itself always succeeds and the goal always ends archived.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if every round ends in one of the two valid states.
def test_concurrent_archive_vs_contribution_is_serialized(clean_database: None) -> None:
    for _ in range(5):
        user_id = uuid4()
        goal_id = _create_goal_with_contribution(user_id)
        barrier = threading.Barrier(2)
        results: dict = {}

        def run_archive() -> None:
            barrier.wait(timeout=10)
            results["archive"] = _archive_goal(goal_id, user_id)

        def run_contribution() -> None:
            barrier.wait(timeout=10)
            results["contribution"] = _contribute(goal_id, user_id)

        archive_thread = threading.Thread(target=run_archive)
        contribution_thread = threading.Thread(target=run_contribution)
        archive_thread.start()
        contribution_thread.start()
        archive_thread.join(timeout=15)
        contribution_thread.join(timeout=15)

        assert not archive_thread.is_alive() and not contribution_thread.is_alive()
        assert results["archive"] == "succeeded"
        assert results["contribution"] in ("succeeded", "archived_rejected")

        expected_rows = 2 if results["contribution"] == "succeeded" else 1
        assert _final_goal_state(goal_id, user_id) == ("archived", expected_rows)
