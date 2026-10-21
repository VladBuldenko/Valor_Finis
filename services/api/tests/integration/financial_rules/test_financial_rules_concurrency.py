import threading
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database_session import SessionLocal, engine
from app.modules.accounts import account_service
from app.modules.accounts.account_errors import AccountNotFoundError, AccountReferencedByRuleError
from app.modules.budgets import budget_service
from app.modules.budgets.budget_errors import BudgetNotFoundError, BudgetReferencedByRuleError
from app.modules.financial_rules import financial_rule_service
from app.modules.financial_rules.financial_rule_errors import FinancialRuleAlreadyExistsError
from app.modules.financial_rules.financial_rule_schemas import (
    FinancialRuleUpdate,
    financial_rule_create_adapter,
)
from app.modules.goals import goal_service
from app.modules.goals.goal_errors import GoalNotFoundError, GoalReferencedByRuleError
from tests.helpers import create_account, create_budget, create_goal
from tests.integration.financial_rules.rule_helpers import (
    account_by_id,
    allocation_payload,
    budget_alert_payload,
    create_rule,
    floor_payload,
)

# VF-020E5 concurrency tests against real PostgreSQL: every rule write takes
# the user lock L0 (and the referenced Account / Budget row lock), so races
# between rule writes and with Goal / Account / Budget lifecycle writes end in
# a consistent state and a CONTROLLED error - never a raw IntegrityError.

JOIN_TIMEOUT = 30.0


def _run_in_threads(jobs: list[Callable[[], Any]]) -> list[Any]:
    barrier = threading.Barrier(len(jobs))
    results: list[Any] = [None] * len(jobs)

    def worker(index: int) -> None:
        barrier.wait(timeout=JOIN_TIMEOUT)
        try:
            results[index] = jobs[index]()
        except Exception as error:  # noqa: BLE001 - the outcome is asserted by the tests
            results[index] = error

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(jobs))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=JOIN_TIMEOUT)
        assert not thread.is_alive(), "a rule write did not finish (possible deadlock)"
    return results


def _create(user_id: UUID, payload: dict):
    def job():
        with SessionLocal() as session:
            return financial_rule_service.create_rule(
                session, financial_rule_create_adapter.validate_python(payload), user_id,
            )
    return job


def _count(sql: str, **params: Any) -> int:
    with engine.connect() as connection:
        return connection.execute(text(sql), params).scalar_one()


def test_concurrent_floor_creates_for_one_account_yield_one_rule_and_controlled_conflicts(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id)

    results = _run_in_threads([_create(UUID(user_id), floor_payload(account["id"], "100.00", name=f"f{i}")) for i in range(6)])

    successes = [r for r in results if not isinstance(r, Exception)]
    assert len(successes) == 1
    assert all(isinstance(r, FinancialRuleAlreadyExistsError) for r in results if isinstance(r, Exception))
    assert _count("SELECT count(*) FROM financial_rules WHERE user_id = :u", u=UUID(user_id)) == 1


def test_concurrent_allocation_creates_get_distinct_consecutive_orders(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id)
    goal = create_goal(client, user_id)
    payload = allocation_payload(account["id"], [goal["id"]])

    results = _run_in_threads([_create(UUID(user_id), {**payload, "name": f"r{i}"}) for i in range(8)])

    assert not [r for r in results if isinstance(r, Exception)], results
    assert sorted(r.execution_order for r in results) == list(range(1, 9))  # L0 serialized max+1


def test_concurrent_material_patches_do_not_lose_versions(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id)
    rule = create_rule(client, user_id, floor_payload(account["id"], "1.00"))

    def patch(value: str):
        def job():
            with SessionLocal() as session:
                return financial_rule_service.update_rule(
                    session, UUID(rule["id"]), FinancialRuleUpdate(floor_amount=Decimal(value)), UUID(user_id),
                )
        return job

    results = _run_in_threads([patch(f"{10 + i}.00") for i in range(6)])

    assert not [r for r in results if isinstance(r, Exception)], results
    assert sorted(r.version for r in results) == [2, 3, 4, 5, 6, 7]  # six distinct material edits
    assert _count("SELECT version FROM financial_rules WHERE id = :i", i=UUID(rule["id"])) == 7


def test_patch_and_status_transition_race_ends_consistent(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id)
    rule = create_rule(client, user_id, floor_payload(account["id"], "1.00"))

    def patch():
        with SessionLocal() as session:
            return financial_rule_service.update_rule(
                session, UUID(rule["id"]), FinancialRuleUpdate(floor_amount=Decimal("50.00")), UUID(user_id),
            )

    def enable():
        with SessionLocal() as session:
            return financial_rule_service.enable_rule(session, UUID(rule["id"]), UUID(user_id))

    results = _run_in_threads([patch, enable])

    assert not [r for r in results if isinstance(r, Exception)], results
    final = account_by_id(client, user_id, account["id"])
    assert final["minimum_unallocated_floor"] == "50.00"  # enabled, with the patched amount
    assert _count("SELECT version FROM financial_rules WHERE id = :i", i=UUID(rule["id"])) == 2


def test_goal_delete_versus_target_rule_create_is_consistent(client: TestClient, clean_database: None) -> None:
    for _ in range(8):
        user_id = str(uuid4())
        account = create_account(client, user_id)
        goal = create_goal(client, user_id)

        def delete_goal():
            with SessionLocal() as session:
                return goal_service.delete_goal(session, UUID(goal["id"]), UUID(user_id))

        results = _run_in_threads([
            _create(UUID(user_id), allocation_payload(account["id"], [goal["id"]])), delete_goal,
        ])

        created, deleted = results
        goal_exists = _count("SELECT count(*) FROM goals WHERE id = :i", i=UUID(goal["id"])) == 1
        targets = _count("SELECT count(*) FROM financial_rule_goal_targets WHERE goal_id = :i", i=UUID(goal["id"]))
        if isinstance(created, Exception):
            assert isinstance(created, GoalNotFoundError), created  # the delete won
            assert deleted is None and not goal_exists and targets == 0
        else:
            assert isinstance(deleted, GoalReferencedByRuleError), deleted  # the rule won
            assert goal_exists and targets == 1


def test_account_delete_versus_floor_create_is_consistent(client: TestClient, clean_database: None) -> None:
    for _ in range(8):
        user_id = str(uuid4())
        account = create_account(client, user_id)

        def delete_account():
            with SessionLocal() as session:
                return account_service.delete_account(session, UUID(account["id"]), UUID(user_id))

        created, deleted = _run_in_threads([_create(UUID(user_id), floor_payload(account["id"])), delete_account])

        account_exists = _count("SELECT count(*) FROM accounts WHERE id = :i", i=UUID(account["id"])) == 1
        rules = _count("SELECT count(*) FROM financial_rules WHERE source_account_id = :i", i=UUID(account["id"]))
        if isinstance(created, Exception):
            assert isinstance(created, AccountNotFoundError), created
            assert deleted is None and not account_exists and rules == 0
        else:
            assert isinstance(deleted, AccountReferencedByRuleError), deleted
            assert account_exists and rules == 1


def test_budget_delete_versus_budget_alert_create_is_consistent(client: TestClient, clean_database: None) -> None:
    for _ in range(8):
        user_id = str(uuid4())
        budget = create_budget(client, user_id)

        def delete_budget():
            with SessionLocal() as session:
                return budget_service.delete_budget(session, UUID(budget["id"]), UUID(user_id))

        created, deleted = _run_in_threads([_create(UUID(user_id), budget_alert_payload(budget["id"])), delete_budget])

        budget_exists = _count("SELECT count(*) FROM budgets WHERE id = :i", i=UUID(budget["id"])) == 1
        rules = _count("SELECT count(*) FROM financial_rules WHERE budget_id = :i", i=UUID(budget["id"]))
        if isinstance(created, Exception):
            assert isinstance(created, BudgetNotFoundError), created
            assert deleted is None and not budget_exists and rules == 0
        else:
            assert isinstance(deleted, BudgetReferencedByRuleError), deleted
            assert budget_exists and rules == 1
