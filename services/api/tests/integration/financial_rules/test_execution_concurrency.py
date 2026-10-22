import threading
from datetime import date
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database_session import SessionLocal, engine
from app.modules.accounts import account_service
from app.modules.accounts.account_schemas import AccountResponse
from app.modules.accounts.account_transaction_schemas import AccountTransactionCreate
from app.modules.financial_events import financial_event_processor as processor
from app.modules.financial_rules import financial_rule_service
from app.modules.financial_rules.financial_rule_schemas import FinancialRuleUpdate
from app.modules.goals import goal_service
from app.modules.goals.goal_errors import GoalReservationCapacityError
from app.modules.goals.goal_transaction_schemas import GoalTransactionCreate
from tests.integration.financial_rules.execution_helpers import (
    enabled_rule,
    funded_account,
    goal_with_target,
    post_income,
    scalar,
)

# VF-020E7 concurrency tests against real PostgreSQL (CT-01..CT-03, CT-08,
# CT-09, CT-10 and Account races). Every AUTO transaction runs under the user
# lock L0 and the Goal -> Account row locks, so each race ends in ONE
# deterministic financial state, never a deadlock, a duplicate or a raw error.

JOIN_TIMEOUT = 60.0
ROUNDS = 5


def _run_in_threads(jobs: list[Callable[[], Any]]) -> list[Any]:
    barrier = threading.Barrier(len(jobs))
    results: list[Any] = [None] * len(jobs)

    def worker(index: int) -> None:
        barrier.wait(timeout=JOIN_TIMEOUT)
        try:
            results[index] = jobs[index]()
        except Exception as error:  # noqa: BLE001 - outcomes are asserted by the tests
            results[index] = error

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(jobs))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=JOIN_TIMEOUT)
        assert not thread.is_alive(), "a worker did not finish (possible deadlock)"
    return results


def _drain(user_id: str) -> Callable[[], processor.DrainSummary]:
    def job() -> processor.DrainSummary:
        with SessionLocal() as session:
            return processor.drain_user_events(session, UUID(user_id))
    return job


def _statuses(user_id: str) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT rule_id, status FROM rule_executions WHERE user_id = :u"), {"u": user_id},
        ).all()
    return {str(rule_id): status for rule_id, status in rows}


def _competing_rules(client: TestClient, user_id: str, opening: str = "600.00"):
    account = funded_account(client, user_id, opening=opening)
    g1 = goal_with_target(client, user_id, "G1", 3000)
    g3 = goal_with_target(client, user_id, "G3", 1000)
    r1 = enabled_rule(client, user_id, account["id"], [g1["id"]], name="R1", execution_order=1,
                      targets=[{"goal_id": g1["id"], "amount_or_cap": "500.00"}])
    r2 = enabled_rule(client, user_id, account["id"], [g3["id"]], name="R2", execution_order=2,
                      targets=[{"goal_id": g3["id"], "amount_or_cap": "400.00"}])
    return account, g1, g3, r1, r2


def test_ct01_s31_parallel_drains_give_the_same_result_on_every_run(
    client: TestClient, clean_database: None,
) -> None:
    for _ in range(ROUNDS):
        user_id = str(uuid4())
        _, _, _, r1, r2 = _competing_rules(client, user_id)
        post_income(client, user_id, "0.01", _account_id(user_id))

        results = _run_in_threads([_drain(user_id) for _ in range(4)])

        assert not [r for r in results if isinstance(r, Exception)], results
        assert sum(r.processed for r in results) == 1  # the event is processed exactly once
        assert _statuses(user_id) == {r1["id"]: "executed", r2["id"]: "skipped"}
        assert scalar(
            "SELECT count(*) FROM goal_transactions WHERE user_id = :u AND rule_execution_id IS NOT NULL", u=user_id,
        ) == 1


def _account_id(user_id: str) -> str:
    return str(scalar("SELECT id FROM accounts WHERE user_id = :u LIMIT 1", u=user_id))


def test_ct03_many_events_are_each_processed_once_in_fifo_order(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="10000.00")
    goal = goal_with_target(client, user_id, "G", 100000)
    enabled_rule(client, user_id, account["id"], [goal["id"]], targets=[{"goal_id": goal["id"], "amount_or_cap": "10.00"}])
    for _ in range(8):
        post_income(client, user_id, "5.00", account["id"])

    results = _run_in_threads([_drain(user_id) for _ in range(4)])

    assert not [r for r in results if isinstance(r, Exception)], results
    assert sum(r.processed for r in results) == 8
    assert scalar("SELECT count(*) FROM rule_executions WHERE user_id = :u", u=user_id) == 8
    assert scalar("SELECT count(DISTINCT source_id) FROM rule_executions WHERE user_id = :u", u=user_id) == 8
    assert scalar("SELECT count(*) FROM financial_events WHERE user_id = :u AND status = 'processed' AND attempts = 1", u=user_id) == 8
    # FIFO: the events were completed in their (occurred_at, id) order.
    with engine.connect() as connection:
        completed = [row[0] for row in connection.execute(
            text("SELECT processed_at FROM financial_events WHERE user_id = :u ORDER BY occurred_at, id"), {"u": user_id})]
    assert completed == sorted(completed)


def test_ct02_manual_reservation_and_auto_execution_never_both_win_the_same_money(
    client: TestClient, clean_database: None,
) -> None:
    outcomes = set()

    for _ in range(ROUNDS):
        user_id = str(uuid4())
        account = funded_account(client, user_id, opening="600.00")
        auto_goal = goal_with_target(client, user_id, "Auto", 3000)
        manual_goal = goal_with_target(client, user_id, "Manual", 3000)
        rule = enabled_rule(client, user_id, account["id"], [auto_goal["id"]],
                            targets=[{"goal_id": auto_goal["id"], "amount_or_cap": "500.00"}])
        post_income(client, user_id, "0.01", account["id"])

        def manual():
            with SessionLocal() as session:
                return goal_service.create_or_replay_goal_transaction(
                    session, UUID(manual_goal["id"]),
                    GoalTransactionCreate(type="contribution", amount=Decimal("400.00"),
                                          account_id=UUID(account["id"]), client_request_id=uuid4()),
                    UUID(user_id),
                )

        results = _run_in_threads([_drain(user_id), manual])

        auto_status = _statuses(user_id)[rule["id"]]
        manual_ok = not isinstance(results[1], Exception)
        if not manual_ok:
            assert isinstance(results[1], GoalReservationCapacityError), results[1]
        # 500 + 400 cannot both fit in 600.01: exactly one of them wins.
        assert (auto_status == "executed") != manual_ok
        outcomes.add((auto_status, manual_ok))
        reserved = scalar("SELECT COALESCE(SUM(amount), 0) FROM goal_transactions WHERE user_id = :u", u=user_id)
        assert reserved in (Decimal("500.00"), Decimal("400.00"))

    assert outcomes <= {("executed", False), ("skipped", True)}


def test_account_debit_and_auto_execution_serialize_on_the_account(client: TestClient, clean_database: None) -> None:
    for _ in range(ROUNDS):
        user_id = str(uuid4())
        account = funded_account(client, user_id, opening="600.00")
        goal = goal_with_target(client, user_id, "G", 3000)
        rule = enabled_rule(client, user_id, account["id"], [goal["id"]],
                            targets=[{"goal_id": goal["id"], "amount_or_cap": "500.00"}])
        post_income(client, user_id, "0.01", account["id"])

        def debit():
            with SessionLocal() as session:
                return account_service.create_account_transaction(
                    session, UUID(account["id"]),
                    AccountTransactionCreate(direction="debit", amount=Decimal("300.00"), transaction_date=date.today()),
                    UUID(user_id),
                )

        results = _run_in_threads([_drain(user_id), debit])

        assert not [r for r in results if isinstance(r, Exception)], results
        status = _statuses(user_id)[rule["id"]]
        reserved = scalar("SELECT COALESCE(SUM(amount), 0) FROM goal_transactions WHERE user_id = :u", u=user_id)
        # Debit first -> 300.01 < 500 -> skipped; AUTO first -> executed (the debit may then overcommit, P05).
        assert (status, reserved) in {("executed", Decimal("500.00")), ("skipped", Decimal("0"))}


def test_ct08_goal_reorder_and_processing_use_one_consistent_priority(
    client: TestClient, clean_database: None,
) -> None:
    for _ in range(ROUNDS):
        user_id = str(uuid4())
        account = funded_account(client, user_id, opening="250.00")
        g1 = goal_with_target(client, user_id, "G1", 3000)
        g2 = goal_with_target(client, user_id, "G2", 3000)
        enabled_rule(client, user_id, account["id"], [g1["id"], g2["id"]], allow_partial=True,
                     targets=[{"goal_id": g1["id"], "amount_or_cap": "200.00"},
                              {"goal_id": g2["id"], "amount_or_cap": "200.00"}])
        post_income(client, user_id, "10.00", account["id"])

        def reorder():
            with SessionLocal() as session:
                return goal_service.reorder_goal_priorities(session, [UUID(g2["id"]), UUID(g1["id"])], UUID(user_id))

        results = _run_in_threads([_drain(user_id), reorder])

        assert not [r for r in results if isinstance(r, Exception)], results
        with engine.connect() as connection:
            applied = {
                str(goal_id): amount for goal_id, amount in connection.execute(
                    text("SELECT goal_id, applied_amount FROM rule_execution_items WHERE user_id = :u"), {"u": user_id})
            }
        # Either the old order (G1 first) or the new order (G2 first), never a mix.
        assert applied in (
            {g1["id"]: Decimal("200.00"), g2["id"]: Decimal("60.00")},
            {g2["id"]: Decimal("200.00"), g1["id"]: Decimal("60.00")},
        )


def test_ct09_rule_edit_and_processing_record_a_consistent_version(client: TestClient, clean_database: None) -> None:
    for _ in range(ROUNDS):
        user_id = str(uuid4())
        account = funded_account(client, user_id, opening="2000.00")
        goal = goal_with_target(client, user_id, "G", 3000)
        rule = enabled_rule(client, user_id, account["id"], [goal["id"]],
                            targets=[{"goal_id": goal["id"], "amount_or_cap": "100.00"}])
        post_income(client, user_id, "10.00", account["id"])

        def edit():
            with SessionLocal() as session:
                return financial_rule_service.update_rule(
                    session, UUID(rule["id"]), FinancialRuleUpdate(allow_partial=True), UUID(user_id),
                )

        results = _run_in_threads([_drain(user_id), edit])

        assert not [r for r in results if isinstance(r, Exception)], results
        with engine.connect() as connection:
            version, snapshot = connection.execute(
                text("SELECT rule_version, params_snapshot->>'allow_partial' FROM rule_executions WHERE user_id = :u"),
                {"u": user_id},
            ).one()
        # The version and the parameter snapshot always belong together.
        assert (version, snapshot) in {(1, "false"), (2, "true")}


def test_ct10_two_users_drain_independently_in_parallel(client: TestClient, clean_database: None) -> None:
    users = []
    for _ in range(2):
        user_id = str(uuid4())
        account = funded_account(client, user_id, opening="2000.00")
        goal = goal_with_target(client, user_id, "G", 3000)
        enabled_rule(client, user_id, account["id"], [goal["id"]])
        post_income(client, user_id, "10.00", account["id"])
        users.append(user_id)

    results = _run_in_threads([_drain(user_id) for user_id in users])

    assert [r.processed for r in results] == [1, 1]
    for user_id in users:
        assert scalar("SELECT count(*) FROM rule_executions WHERE user_id = :u", u=user_id) == 1


def test_parallel_drains_with_a_failing_user_do_not_affect_the_other(
    client: TestClient, clean_database: None, monkeypatch,
) -> None:
    ok_user, bad_user = str(uuid4()), str(uuid4())
    for user_id in (ok_user, bad_user):
        account = funded_account(client, user_id, opening="2000.00")
        goal = goal_with_target(client, user_id, "G", 3000)
        enabled_rule(client, user_id, account["id"], [goal["id"]])
        post_income(client, user_id, "10.00", account["id"])

    from app.modules.financial_rules import rule_execution_service

    original = rule_execution_service.process_event

    def selective(db_session, user_id, event):
        if str(user_id) == bad_user:
            raise RuntimeError("injected technical failure")
        return original(db_session, user_id, event)

    monkeypatch.setattr(rule_execution_service, "process_event", selective)

    results = _run_in_threads([_drain(ok_user), _drain(bad_user)])

    assert results[0].processed == 1 and results[1].failed_retryable == 1
    assert scalar("SELECT count(*) FROM rule_executions WHERE user_id = :u", u=ok_user) == 1
    assert scalar("SELECT count(*) FROM rule_executions WHERE user_id = :u", u=bad_user) == 0


def test_account_response_model_includes_the_capacity_fields() -> None:
    assert {"active_rule_holds", "rule_capacity"} <= set(AccountResponse.model_fields)
