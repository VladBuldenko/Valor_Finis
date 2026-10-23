import threading
from datetime import date
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database_session import SessionLocal, engine
from app.modules.accounts import account_service
from app.modules.accounts.account_transaction_schemas import AccountTransactionCreate
from app.modules.financial_events import financial_event_processor as processor
from app.modules.financial_rules import financial_rule_service, rule_proposal_service
from app.modules.financial_rules.financial_rule_errors import RuleProposalStaleError
from app.modules.financial_rules.financial_rule_schemas import FinancialRuleUpdate
from app.modules.goals import goal_service
from app.modules.goals.goal_errors import GoalReservationCapacityError
from app.modules.goals.goal_transaction_schemas import GoalTransactionCreate
from tests.integration.financial_rules.execution_helpers import (
    enabled_rule,
    evaluate,
    funded_account,
    goal_with_target,
    post_income,
    scalar,
)

# VF-020E8 concurrency (CT-04, CT-05, CT-09, CT-11 and Account races): every
# confirm / reject / expiry / drain runs under L0 and the execution-row lock,
# so a race always ends in ONE consistent terminal state and one financial
# effect, never a deadlock or a duplicate.

JOIN_TIMEOUT = 60.0
ROUNDS = 5


def _run(jobs: list[Callable[[], Any]]) -> list[Any]:
    barrier = threading.Barrier(len(jobs))
    results: list[Any] = [None] * len(jobs)

    def worker(index: int) -> None:
        barrier.wait(timeout=JOIN_TIMEOUT)
        try:
            results[index] = jobs[index]()
        except Exception as error:  # noqa: BLE001 - outcomes are asserted
            results[index] = error

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(jobs))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=JOIN_TIMEOUT)
        assert not thread.is_alive(), "a worker did not finish (possible deadlock)"
    return results


def _setup(client: TestClient, amount: str = "500.00"):
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="600.00")
    goal = goal_with_target(client, user_id, "G", 5000)
    rule = enabled_rule(client, user_id, account["id"], [goal["id"]], execution_mode="CONFIRM",
                        targets=[{"goal_id": goal["id"], "amount_or_cap": amount}])
    post_income(client, user_id, "0.01", account["id"])
    evaluate(client, user_id)
    proposal_id = scalar("SELECT id FROM rule_executions WHERE user_id = :u", u=user_id)
    return user_id, account, goal, rule, proposal_id


def _confirm(user_id: str, proposal_id) -> Callable[[], Any]:
    def job():
        with SessionLocal() as session:
            return rule_proposal_service.confirm_proposal(session, UUID(str(proposal_id)), UUID(user_id))
    return job


def _reject(user_id: str, proposal_id) -> Callable[[], Any]:
    def job():
        with SessionLocal() as session:
            return rule_proposal_service.reject_proposal(session, UUID(str(proposal_id)), UUID(user_id))
    return job


def _tx(user_id: str) -> int:
    return scalar("SELECT count(*) FROM goal_transactions WHERE user_id = :u AND rule_execution_id IS NOT NULL", u=user_id)


def test_concurrent_double_confirmation_writes_once(client: TestClient, clean_database: None) -> None:
    for _ in range(ROUNDS):
        user_id, _, _, _, proposal_id = _setup(client)

        results = _run([_confirm(user_id, proposal_id) for _ in range(4)])

        assert not [r for r in results if isinstance(r, Exception)], results
        assert all(r.status == "executed" for r in results)
        assert _tx(user_id) == 1
        assert scalar("SELECT count(*) FROM rule_execution_audit WHERE execution_id = :e AND code = 'confirmed'", e=proposal_id) == 1


def test_confirm_versus_reject_ends_in_exactly_one_terminal_state(client: TestClient, clean_database: None) -> None:
    outcomes = set()
    for _ in range(ROUNDS):
        user_id, _, _, _, proposal_id = _setup(client)

        results = _run([_confirm(user_id, proposal_id), _reject(user_id, proposal_id)])

        assert not [r for r in results if isinstance(r, Exception)], results
        final = scalar("SELECT status FROM rule_executions WHERE id = :e", e=proposal_id)
        assert final in ("executed", "rejected")
        assert results[0].status == results[1].status == final  # both callers see the single stored result
        assert _tx(user_id) == (1 if final == "executed" else 0)
        outcomes.add(final)
    assert outcomes <= {"executed", "rejected"}


def test_confirm_versus_expiry_never_confirms_an_expired_proposal(client: TestClient, clean_database: None) -> None:
    for _ in range(ROUNDS):
        user_id, _, _, _, proposal_id = _setup(client)
        with engine.begin() as connection:
            connection.execute(text("UPDATE rule_executions SET expires_at = now() - interval '1 second'"))

        results = _run([_confirm(user_id, proposal_id), _confirm(user_id, proposal_id)])

        assert not [r for r in results if isinstance(r, Exception)], results
        assert all(r.status == "expired" for r in results)
        assert _tx(user_id) == 0


def test_ct11_manual_reservation_versus_confirmation_never_both_win_the_same_money(
    client: TestClient, clean_database: None,
) -> None:
    for _ in range(ROUNDS):
        user_id, account, _, _, proposal_id = _setup(client)
        manual_goal = goal_with_target(client, user_id, "Manual", 5000)

        def manual():
            with SessionLocal() as session:
                return goal_service.create_or_replay_goal_transaction(
                    session, UUID(manual_goal["id"]),
                    GoalTransactionCreate(type="contribution", amount=Decimal("300.00"),
                                          account_id=UUID(account["id"]), client_request_id=uuid4()),
                    UUID(user_id),
                )

        results = _run([_confirm(user_id, proposal_id), manual])

        confirm_ok = not isinstance(results[0], Exception)
        manual_ok = not isinstance(results[1], Exception)
        if not manual_ok:
            assert isinstance(results[1], GoalReservationCapacityError), results[1]
        if not confirm_ok:
            assert isinstance(results[0], RuleProposalStaleError), results[0]
        # 500 + 300 > 600.01: exactly one of them wins.
        assert confirm_ok != manual_ok
        assert scalar("SELECT status FROM rule_executions WHERE id = :e", e=proposal_id) == ("executed" if confirm_ok else "cancelled")


def test_account_debit_versus_confirmation_is_serialized(client: TestClient, clean_database: None) -> None:
    for _ in range(ROUNDS):
        user_id, account, _, _, proposal_id = _setup(client)

        def debit():
            with SessionLocal() as session:
                return account_service.create_account_transaction(
                    session, UUID(account["id"]),
                    AccountTransactionCreate(direction="debit", amount=Decimal("300.00"), transaction_date=date.today()),
                    UUID(user_id),
                )

        results = _run([_confirm(user_id, proposal_id), debit])

        assert not isinstance(results[1], Exception), results[1]
        confirmed = not isinstance(results[0], Exception)
        # Confirm first -> executed (the debit may then overcommit, P05); debit first -> 300.01 < 500 -> stale.
        assert scalar("SELECT status FROM rule_executions WHERE id = :e", e=proposal_id) == ("executed" if confirmed else "cancelled")
        assert _tx(user_id) == (1 if confirmed else 0)


def test_ct09_rule_edit_versus_confirmation(client: TestClient, clean_database: None) -> None:
    for _ in range(ROUNDS):
        user_id, _, _, rule, proposal_id = _setup(client)

        def edit():
            with SessionLocal() as session:
                return financial_rule_service.update_rule(
                    session, UUID(rule["id"]), FinancialRuleUpdate(allow_partial=True), UUID(user_id),
                )

        results = _run([_confirm(user_id, proposal_id), edit])

        assert not isinstance(results[1], Exception), results[1]
        status = scalar("SELECT status FROM rule_executions WHERE id = :e", e=proposal_id)
        # Confirm first: executed (the edit then only bumps the version). Edit first: superseded.
        assert status in ("executed", "cancelled")
        assert _tx(user_id) == (1 if status == "executed" else 0)
        if status == "cancelled":
            assert scalar("SELECT reason_code FROM rule_executions WHERE id = :e", e=proposal_id) == "superseded"
            assert isinstance(results[0], Exception) is False  # the stored cancelled state is returned, not an error


def test_pause_versus_confirmation(client: TestClient, clean_database: None) -> None:
    for _ in range(ROUNDS):
        user_id, _, _, rule, proposal_id = _setup(client)

        def pause():
            with SessionLocal() as session:
                return financial_rule_service.pause_rule(session, UUID(rule["id"]), UUID(user_id))

        results = _run([_confirm(user_id, proposal_id), pause])

        assert not isinstance(results[1], Exception), results[1]
        status = scalar("SELECT status FROM rule_executions WHERE id = :e", e=proposal_id)
        assert status in ("executed", "cancelled")
        assert _tx(user_id) == (1 if status == "executed" else 0)


def test_ct05_income_update_event_versus_confirmation(client: TestClient, clean_database: None) -> None:
    for _ in range(ROUNDS):
        user_id, _, _, _, proposal_id = _setup(client)
        income_id = scalar("SELECT id FROM income WHERE user_id = :u", u=user_id)
        response = client.patch(f"/api/v1/income/{income_id}", headers={"X-User-Id": user_id}, json={"description": "note only"})
        assert response.status_code == 200, response.text

        def drain():
            with SessionLocal() as session:
                return processor.drain_user_events(session, UUID(user_id))

        results = _run([_confirm(user_id, proposal_id), drain])

        assert not isinstance(results[1], Exception), results[1]
        status = scalar("SELECT status FROM rule_executions WHERE id = :e", e=proposal_id)
        # Confirm first -> executed + a source_changed annotation; the update first -> cancelled(source_changed).
        assert status in ("executed", "cancelled")
        if status == "cancelled":
            assert scalar("SELECT reason_code FROM rule_executions WHERE id = :e", e=proposal_id) == "source_changed"
            assert _tx(user_id) == 0
        else:
            assert _tx(user_id) == 1
            # A description-only edit leaves the snapshot unchanged: a completed
            # execution gets no annotation (snapshot-based), and is never re-run.
            assert scalar("SELECT count(*) FROM rule_execution_audit WHERE execution_id = :e AND code = 'source_changed'", e=proposal_id) == 0


def test_two_users_confirm_independently(client: TestClient, clean_database: None) -> None:
    first = _setup(client)
    second = _setup(client)

    results = _run([_confirm(first[0], first[4]), _confirm(second[0], second[4])])

    assert [r.status for r in results] == ["executed", "executed"]
    assert _tx(first[0]) == 1 and _tx(second[0]) == 1
