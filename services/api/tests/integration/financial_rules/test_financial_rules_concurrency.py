import threading
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, text

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


# ------------------------------------------------------------------
# The response of a write is the state that write COMMITTED
# (VF-RULE-VERSION-RESPONSE-RACE-001)
# ------------------------------------------------------------------
#
# A write takes the user lock L0 and the rule row lock, but both end at COMMIT. If the
# response were read AFTER the commit, a concurrent write could commit in between and the
# first caller would receive the SECOND write's state (a duplicated version, "paused" for
# an enable, ...), although the database itself is correct. The threaded test above can
# only hit that window by luck, so these tests force it: a listener on the first
# request's own session runs a second request to completion right after the first one's
# commit has released its locks and before it builds its response.


def _after_first_commit(session, action: Callable[[], Any]) -> None:
    fired: list[bool] = []

    def listener(_session) -> None:  # noqa: ANN001
        if not fired:
            fired.append(True)
            action()

    event.listen(session, "after_commit", listener)


def _stored(rule_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT version, status, floor_amount::text AS floor_amount FROM financial_rules WHERE id = :i"),
            {"i": UUID(rule_id)},
        ).one()

    return {"version": row.version, "status": row.status, "floor_amount": row.floor_amount}


def test_a_patch_returns_its_own_committed_version_even_if_another_patch_commits_right_after(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id)
    rule = create_rule(client, user_id, floor_payload(account["id"], "1.00"))
    second: list[Any] = []

    def second_patch() -> None:
        with SessionLocal() as other:
            second.append(financial_rule_service.update_rule(
                other, UUID(rule["id"]), FinancialRuleUpdate(floor_amount=Decimal("20.00")), UUID(user_id),
            ))

    with SessionLocal() as session:
        _after_first_commit(session, second_patch)
        first = financial_rule_service.update_rule(
            session, UUID(rule["id"]), FinancialRuleUpdate(floor_amount=Decimal("10.00")), UUID(user_id),
        )

    # Each response is the state its own write committed ...
    assert (first.version, first.floor_amount) == (2, Decimal("10.00"))
    assert (second[0].version, second[0].floor_amount) == (3, Decimal("20.00"))
    # ... and nothing was lost or incremented twice: two material edits, version 3.
    assert _stored(rule["id"]) == {"version": 3, "status": "draft", "floor_amount": "20.00"}


def test_a_status_transition_returns_the_status_it_committed_even_if_another_transition_follows(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id)
    rule = create_rule(client, user_id, floor_payload(account["id"], "1.00"))
    second: list[Any] = []

    def pause() -> None:
        with SessionLocal() as other:
            second.append(financial_rule_service.pause_rule(other, UUID(rule["id"]), UUID(user_id)))

    with SessionLocal() as session:
        _after_first_commit(session, pause)
        first = financial_rule_service.enable_rule(session, UUID(rule["id"]), UUID(user_id))

    assert first.status == "enabled"
    assert second[0].status == "paused"
    assert _stored(rule["id"])["status"] == "paused"


def test_a_create_returns_the_rule_it_committed_even_if_it_is_edited_right_after(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id)
    second: list[Any] = []

    def edit_the_new_rule() -> None:
        with SessionLocal() as other:
            rule_id = other.execute(text("SELECT id FROM financial_rules WHERE user_id = :u"), {"u": UUID(user_id)}).scalar_one()
            second.append(financial_rule_service.update_rule(
                other, rule_id, FinancialRuleUpdate(floor_amount=Decimal("20.00")), UUID(user_id),
            ))

    with SessionLocal() as session:
        _after_first_commit(session, edit_the_new_rule)
        created = financial_rule_service.create_rule(
            session, financial_rule_create_adapter.validate_python(floor_payload(account["id"], "1.00")), UUID(user_id),
        )

    assert (created.version, created.floor_amount) == (1, Decimal("1.00"))
    assert (second[0].version, second[0].floor_amount) == (2, Decimal("20.00"))
    assert _stored(str(created.id))["version"] == 2


def test_concurrent_material_patches_each_return_their_own_committed_state(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id)
    rule = create_rule(client, user_id, floor_payload(account["id"], "1.00"))
    values = [f"{10 + i}.00" for i in range(8)]

    def patch(value: str):
        def job():
            with SessionLocal() as session:
                return value, financial_rule_service.update_rule(
                    session, UUID(rule["id"]), FinancialRuleUpdate(floor_amount=Decimal(value)), UUID(user_id),
                )
        return job

    results = _run_in_threads([patch(value) for value in values])

    assert not [r for r in results if isinstance(r, Exception)], results
    # Every caller gets the amount IT wrote, at a version no other caller got ...
    assert all(response.floor_amount == Decimal(value) for value, response in results)
    assert sorted(response.version for _, response in results) == list(range(2, 10))
    # ... and the stored rule is the last of the eight serialized edits: nothing lost, nothing doubled.
    stored = _stored(rule["id"])
    assert stored["version"] == 9
    assert stored["floor_amount"] == max(results, key=lambda item: item[1].version)[0]


def test_a_non_material_patch_keeps_its_version_even_if_a_material_patch_commits_right_after(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id)
    rule = create_rule(client, user_id, floor_payload(account["id"], "1.00", name="Before"))
    second: list[Any] = []

    def material_patch() -> None:
        with SessionLocal() as other:
            second.append(financial_rule_service.update_rule(
                other, UUID(rule["id"]), FinancialRuleUpdate(floor_amount=Decimal("20.00")), UUID(user_id),
            ))

    with SessionLocal() as session:
        _after_first_commit(session, material_patch)
        first = financial_rule_service.update_rule(session, UUID(rule["id"]), FinancialRuleUpdate(name="After"), UUID(user_id))

    # A rename is not a material edit: version unchanged, and it reports its own state.
    assert (first.name, first.version, first.floor_amount) == ("After", 1, Decimal("1.00"))
    assert (second[0].version, second[0].floor_amount, second[0].name) == (2, Decimal("20.00"), "After")
    assert _stored(rule["id"]) == {"version": 2, "status": "draft", "floor_amount": "20.00"}


def test_a_failing_commit_rolls_back_and_returns_no_response(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id)
    rule = create_rule(client, user_id, floor_payload(account["id"], "1.00"))

    def failing_commit(_session) -> None:  # noqa: ANN001
        raise RuntimeError("commit refused")

    with SessionLocal() as session:
        event.listen(session, "before_commit", failing_commit)
        try:
            financial_rule_service.update_rule(
                session, UUID(rule["id"]), FinancialRuleUpdate(floor_amount=Decimal("10.00")), UUID(user_id),
            )
        except RuntimeError as error:
            assert str(error) == "commit refused"
        else:
            raise AssertionError("a response was returned for a write that did not commit")

    assert _stored(rule["id"]) == {"version": 1, "status": "draft", "floor_amount": "1.00"}

    # The locks were released by the rollback: the next write goes straight through.
    with SessionLocal() as session:
        again = financial_rule_service.update_rule(
            session, UUID(rule["id"]), FinancialRuleUpdate(floor_amount=Decimal("11.00")), UUID(user_id),
        )

    assert (again.version, again.floor_amount) == (2, Decimal("11.00"))
