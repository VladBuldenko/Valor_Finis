import threading
import time
from decimal import Decimal
from typing import Callable, Optional
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database_session import SessionLocal
from app.modules.accounts import account_service
from app.modules.accounts.account_schemas import AccountCreate
from app.modules.goals import goal_service, goal_user_lock
from app.modules.goals.goal_errors import (
    GoalNotFoundError,
    GoalPriorityGoalArchivedError,
    GoalPrioritySetStaleError,
)
from app.modules.goals.goal_schemas import GoalCreate, GoalUpdate
from app.modules.goals.goal_transaction_schemas import GoalTransactionCreate

# VF-020D3 L0 tests against real PostgreSQL: advisory-lock lifetime, the fact
# that EVERY Goal write waits for another transaction holding L0 (behavioral
# proof, not a comment), that reads / occupied replays / Account lifecycle /
# other users do not, and real-thread races of the priority reorder against
# every other Goal write. Waits are bounded (join timeouts, polling deadlines)
# so a broken lock cannot hang the suite; synchronization uses events and
# pg_stat_activity, never sleeps as the only mechanism.

WAIT = 15.0


def _goal_create(name: str = "Goal", status: str = "active") -> GoalCreate:
    return GoalCreate(name=name, target_amount=Decimal("1000"), currency="EUR", status=status)


def _new_goal(user_id: UUID, name: str = "Goal", status: str = "active") -> UUID:
    with SessionLocal() as session:
        return goal_service.create_goal(session, _goal_create(name, status), user_id).id


def _new_account(user_id: UUID, balance: str = "500.00") -> UUID:
    with SessionLocal() as session:
        return account_service.create_account(
            session,
            AccountCreate(name="Acc", type="checking", currency="EUR", opening_balance=Decimal(balance)),
            user_id,
        ).id


def _tx(goal_id: UUID, user_id: UUID, type: str, amount: str, account_id: Optional[UUID] = None) -> str:
    with SessionLocal() as session:
        result = goal_service.create_or_replay_goal_transaction(
            session,
            goal_id,
            GoalTransactionCreate(
                type=type,
                amount=Decimal(amount),
                account_id=account_id,
                client_request_id=uuid4() if account_id is not None else None,
            ),
            user_id,
        )
        return "created" if result.created else "replayed"


def _ranks(user_id: UUID) -> dict:
    with SessionLocal() as session:
        rows = session.execute(
            text("SELECT id, priority_rank, status FROM goals WHERE user_id = :u"), {"u": str(user_id)},
        ).all()
    return {UUID(str(row[0])): (row[1], row[2]) for row in rows}


def _assert_rank_invariants(user_id: UUID) -> None:
    ranks = _ranks(user_id)
    non_null = [rank for rank, _ in ranks.values() if rank is not None]
    assert len(non_null) == len(set(non_null)), ranks
    assert all(rank is None for rank, status in ranks.values() if status == "archived"), ranks


def _advisory_locks() -> list:
    with SessionLocal() as session:
        rows = session.execute(
            text(
                "SELECT classid, objid, granted FROM pg_locks WHERE locktype = 'advisory' "
                "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
            )
        ).all()
    return [(int(row[0]), int(row[1]), row[2]) for row in rows]


def _key_parts(user_id: UUID) -> tuple:
    key = goal_user_lock.compute_goal_user_lock_key(user_id)
    return ((key >> 32) & 0xFFFFFFFF, key & 0xFFFFFFFF)


def _holds_lock(user_id: UUID) -> bool:
    return any(
        (classid, objid) == _key_parts(user_id) and granted
        for classid, objid, granted in _advisory_locks()
    )


def _wait_for_advisory_waiter(timeout: float = WAIT) -> bool:
    deadline = time.monotonic() + timeout
    with SessionLocal() as session:
        while time.monotonic() < deadline:
            waiting = session.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND wait_event = 'advisory' AND pid <> pg_backend_pid()"
                )
            ).scalar_one()
            session.rollback()
            if waiting > 0:
                return True
            time.sleep(0.02)
    return False


def _run_in_thread(task: Callable[[], str], results: dict, name: str) -> threading.Thread:
    def run() -> None:
        try:
            results[name] = task()
        except Exception as error:  # noqa: BLE001 - labelled and asserted by the caller
            results[name] = f"error:{type(error).__name__}"

    thread = threading.Thread(target=run, name=name)
    thread.start()
    return thread


# ------------------------------------------------------------------
# L0 lifetime (same session/transaction, released by commit and rollback)
# ------------------------------------------------------------------


def test_lock_is_held_by_the_transaction_and_released_by_commit(clean_database: None) -> None:
    user_id = uuid4()
    session = SessionLocal()
    try:
        assert not _holds_lock(user_id)
        goal_user_lock.acquire_goal_user_lock(session, user_id)
        assert _holds_lock(user_id)  # visible from another connection while open
        session.commit()
        assert not _holds_lock(user_id)
    finally:
        session.close()


def test_lock_is_released_by_rollback(clean_database: None) -> None:
    user_id = uuid4()
    session = SessionLocal()
    try:
        goal_user_lock.acquire_goal_user_lock(session, user_id)
        assert _holds_lock(user_id)
        session.rollback()
        assert not _holds_lock(user_id)
    finally:
        session.close()


def test_lock_is_released_when_a_service_write_fails(clean_database: None) -> None:
    user_id = uuid4()
    with SessionLocal() as session:
        with pytest.raises(GoalNotFoundError):
            goal_service.update_goal(session, uuid4(), GoalUpdate(name="x"), user_id)

    assert not _holds_lock(user_id)


# ------------------------------------------------------------------
# Every Goal write waits for L0; nothing else does
# ------------------------------------------------------------------


def _write_scenarios(user_id: UUID) -> dict:
    goal_a = _new_goal(user_id, "A")
    goal_b = _new_goal(user_id, "B")
    account_id = _new_account(user_id)
    _tx(goal_a, user_id, "contribution", "100.00")
    _tx(goal_a, user_id, "contribution", "100.00", account_id)

    def update(**fields) -> Callable[[Session], str]:
        def run(session: Session) -> str:
            goal_service.update_goal(session, goal_b, GoalUpdate(**fields), user_id)
            return "ok"
        return run

    return {
        "create": lambda s: (goal_service.create_goal(s, _goal_create("N"), user_id), "ok")[1],
        "patch_metadata": update(name="Renamed"),
        "status_transition": update(status="completed"),
        "delete": lambda s: (goal_service.delete_goal(s, goal_b, user_id), "ok")[1],
        "tracked_contribution": lambda s: (goal_service.create_or_replay_goal_transaction(
            s, goal_a, GoalTransactionCreate(type="contribution", amount=Decimal("1.00")), user_id), "ok")[1],
        "tracked_withdrawal": lambda s: (goal_service.create_or_replay_goal_transaction(
            s, goal_a, GoalTransactionCreate(type="withdrawal", amount=Decimal("1.00")), user_id), "ok")[1],
        "linked_contribution": lambda s: (goal_service.create_or_replay_goal_transaction(
            s, goal_a, GoalTransactionCreate(
                type="contribution", amount=Decimal("1.00"), account_id=account_id, client_request_id=uuid4()),
            user_id), "ok")[1],
        "linked_release": lambda s: (goal_service.create_or_replay_goal_transaction(
            s, goal_a, GoalTransactionCreate(
                type="withdrawal", amount=Decimal("1.00"), account_id=account_id, client_request_id=uuid4()),
            user_id), "ok")[1],
        "reorder": lambda s: (goal_service.reorder_goal_priorities(s, [goal_b, goal_a], user_id), "ok")[1],
    }


@pytest.mark.parametrize(
    "scenario",
    [
        "create", "patch_metadata", "status_transition", "delete", "tracked_contribution",
        "tracked_withdrawal", "linked_contribution", "linked_release", "reorder",
    ],
)
def test_every_goal_write_waits_for_a_held_l0_and_completes_after_release(
    clean_database: None, scenario: str,
) -> None:
    user_id = uuid4()
    action = _write_scenarios(user_id)[scenario]
    holder = SessionLocal()
    results: dict = {}

    def write() -> str:
        with SessionLocal() as session:
            return action(session)

    try:
        goal_user_lock.acquire_goal_user_lock(holder, user_id)
        thread = _run_in_thread(write, results, scenario)
        assert _wait_for_advisory_waiter(), f"{scenario} never waited for L0"
        assert scenario not in results, f"{scenario} finished while L0 was held"
    finally:
        holder.rollback()
        holder.close()

    thread.join(timeout=WAIT)
    assert results == {scenario: "ok"}, results
    assert not _holds_lock(user_id)


def test_reads_replays_account_lifecycle_and_other_users_do_not_wait_for_l0(clean_database: None) -> None:
    user_id, other_user = uuid4(), uuid4()
    goal_id = _new_goal(user_id)
    unused_account = _new_account(user_id, "0.00")
    key = uuid4()
    with SessionLocal() as session:
        goal_service.create_or_replay_goal_transaction(
            session, goal_id,
            GoalTransactionCreate(type="contribution", amount=Decimal("10.00"), client_request_id=key),
            user_id,
        )
    holder = SessionLocal()
    results: dict = {}

    def read() -> str:
        with SessionLocal() as session:
            goal_service.get_goals(session, user_id)
            goal_service.get_goal_transactions(session, goal_id, user_id)
        return "ok"

    def replay() -> str:
        with SessionLocal() as session:
            result = goal_service.create_or_replay_goal_transaction(
                session, goal_id,
                GoalTransactionCreate(type="contribution", amount=Decimal("10.00"), client_request_id=key),
                user_id,
            )
        return "replayed" if not result.created else "created"

    def delete_account() -> str:
        with SessionLocal() as session:
            account_service.delete_account(session, unused_account, user_id)
        return "ok"

    def other_user_create() -> str:
        with SessionLocal() as session:
            goal_service.create_goal(session, _goal_create("Other"), other_user)
        return "ok"

    try:
        goal_user_lock.acquire_goal_user_lock(holder, user_id)
        threads = [
            _run_in_thread(read, results, "read"),
            _run_in_thread(replay, results, "replay"),
            _run_in_thread(delete_account, results, "account_delete"),
            _run_in_thread(other_user_create, results, "other_user"),
        ]
        for thread in threads:
            thread.join(timeout=WAIT)
        finished_while_held = dict(results)
    finally:
        holder.rollback()
        holder.close()

    assert finished_while_held == {
        "read": "ok", "replay": "replayed", "account_delete": "ok", "other_user": "ok",
    }


# ------------------------------------------------------------------
# Races: reorder (and other writers) against every Goal write
# ------------------------------------------------------------------


def _race(first: Callable[[], str], second: Callable[[], str]) -> dict:
    barrier = threading.Barrier(2)
    results: dict = {}

    def wrap(task: Callable[[], str], name: str) -> threading.Thread:
        def run() -> None:
            try:
                barrier.wait(timeout=WAIT)
                results[name] = task()
            except Exception as error:  # noqa: BLE001
                results[name] = f"error:{type(error).__name__}"

        thread = threading.Thread(target=run, name=name)
        thread.start()
        return thread

    threads = [wrap(first, "first"), wrap(second, "second")]
    for thread in threads:
        thread.join(timeout=30)
    assert set(results) == {"first", "second"}, f"a task hung or deadlocked: {results}"
    return results


def _outcome(call: Callable[[Session], object], accepted: dict) -> Callable[[], str]:
    def run() -> str:
        with SessionLocal() as session:
            try:
                call(session)
                return "ok"
            except tuple(accepted) as error:
                return accepted[type(error)]
    return run


def _reorder_task(user_id: UUID, goal_ids: list) -> Callable[[], str]:
    return _outcome(
        lambda s: goal_service.reorder_goal_priorities(s, goal_ids, user_id),
        {
            GoalPrioritySetStaleError: "stale",
            GoalPriorityGoalArchivedError: "archived",
            GoalNotFoundError: "not_found",
        },
    )


def test_reorder_vs_reorder_leaves_exactly_one_complete_order(clean_database: None) -> None:
    user_id = uuid4()
    goals = [_new_goal(user_id, name) for name in "ABC"]

    results = _race(
        _reorder_task(user_id, [goals[2], goals[1], goals[0]]),
        _reorder_task(user_id, [goals[1], goals[0], goals[2]]),
    )

    assert results == {"first": "ok", "second": "ok"}
    ranks = {goal_id: rank for goal_id, (rank, _) in _ranks(user_id).items()}
    assert sorted(ranks.values()) == [1, 2, 3]
    assert ranks in (
        {goals[2]: 1, goals[1]: 2, goals[0]: 3},
        {goals[1]: 1, goals[0]: 2, goals[2]: 3},
    )


def test_reorder_vs_create(clean_database: None) -> None:
    user_id = uuid4()
    goals = [_new_goal(user_id, name) for name in "AB"]

    results = _race(
        _reorder_task(user_id, [goals[1], goals[0]]),
        _outcome(lambda s: goal_service.create_goal(s, _goal_create("N"), user_id), {}),
    )

    assert results["second"] == "ok"
    assert results["first"] in ("ok", "stale")  # create first makes the client's set stale
    _assert_rank_invariants(user_id)
    assert len(_ranks(user_id)) == 3


def test_reorder_vs_archive(clean_database: None) -> None:
    user_id = uuid4()
    goals = [_new_goal(user_id, name) for name in "AB"]

    results = _race(
        _reorder_task(user_id, [goals[1], goals[0]]),
        _outcome(
            lambda s: goal_service.update_goal(s, goals[0], GoalUpdate(status="archived"), user_id), {},
        ),
    )

    assert results["second"] == "ok"
    assert results["first"] in ("ok", "archived", "stale")
    _assert_rank_invariants(user_id)
    assert _ranks(user_id)[goals[0]][1] == "archived"


def test_reorder_vs_reactivate(clean_database: None) -> None:
    user_id = uuid4()
    active = _new_goal(user_id, "A")
    archived = _new_goal(user_id, "B", "archived")

    results = _race(
        _reorder_task(user_id, [active]),
        _outcome(
            lambda s: goal_service.update_goal(s, archived, GoalUpdate(status="active"), user_id), {},
        ),
    )

    assert results["second"] == "ok"
    assert results["first"] in ("ok", "stale")
    _assert_rank_invariants(user_id)
    ranks = _ranks(user_id)
    assert ranks[archived][0] is not None  # reactivated Goals are ranked (appended last)


def test_reorder_vs_delete(clean_database: None) -> None:
    user_id = uuid4()
    goals = [_new_goal(user_id, name) for name in "AB"]

    results = _race(
        _reorder_task(user_id, [goals[1], goals[0]]),
        _outcome(lambda s: goal_service.delete_goal(s, goals[0], user_id), {}),
    )

    assert results["second"] == "ok"
    assert results["first"] in ("ok", "not_found", "stale")
    _assert_rank_invariants(user_id)
    assert goals[0] not in _ranks(user_id)


@pytest.mark.parametrize("kind", ["tracked_contribution", "tracked_withdrawal", "linked_contribution", "linked_release"])
def test_reorder_vs_goal_transactions(clean_database: None, kind: str) -> None:
    user_id = uuid4()
    goals = [_new_goal(user_id, name) for name in "AB"]
    account_id = _new_account(user_id)
    _tx(goals[0], user_id, "contribution", "100.00")
    _tx(goals[0], user_id, "contribution", "100.00", account_id)
    specs = {
        "tracked_contribution": ("contribution", None),
        "tracked_withdrawal": ("withdrawal", None),
        "linked_contribution": ("contribution", account_id),
        "linked_release": ("withdrawal", account_id),
    }
    type_, linked = specs[kind]

    results = _race(
        _reorder_task(user_id, [goals[1], goals[0]]),
        lambda: _tx(goals[0], user_id, type_, "10.00", linked),
    )

    assert results == {"first": "ok", "second": "created"}
    _assert_rank_invariants(user_id)
    with SessionLocal() as session:
        rows = session.execute(
            text("SELECT count(*) FROM goal_transactions WHERE goal_id = :g"), {"g": str(goals[0])},
        ).scalar_one()
    assert rows == 3


def test_create_vs_create_assigns_distinct_ranks(clean_database: None) -> None:
    user_id = uuid4()
    _new_goal(user_id, "Seed")

    results = _race(
        _outcome(lambda s: goal_service.create_goal(s, _goal_create("X"), user_id), {}),
        _outcome(lambda s: goal_service.create_goal(s, _goal_create("Y"), user_id), {}),
    )

    assert results == {"first": "ok", "second": "ok"}
    assert sorted(rank for rank, _ in _ranks(user_id).values()) == [1, 2, 3]


def test_reactivate_vs_create_assigns_distinct_ranks(clean_database: None) -> None:
    user_id = uuid4()
    _new_goal(user_id, "Seed")
    archived = _new_goal(user_id, "Arch", "archived")

    results = _race(
        _outcome(lambda s: goal_service.update_goal(s, archived, GoalUpdate(status="active"), user_id), {}),
        _outcome(lambda s: goal_service.create_goal(s, _goal_create("New"), user_id), {}),
    )

    assert results == {"first": "ok", "second": "ok"}
    assert sorted(rank for rank, _ in _ranks(user_id).values()) == [1, 2, 3]


def test_different_users_progress_independently(clean_database: None) -> None:
    first_user, second_user = uuid4(), uuid4()
    holder = SessionLocal()
    results: dict = {}

    try:
        goal_user_lock.acquire_goal_user_lock(holder, first_user)
        thread = _run_in_thread(
            lambda: (_new_goal(second_user, "Independent"), "ok")[1], results, "second_user",
        )
        thread.join(timeout=WAIT)
        assert results == {"second_user": "ok"}
    finally:
        holder.rollback()
        holder.close()
