from datetime import date
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.db.database_session import engine
from tests.helpers import (
    auth_headers,
    create_account,
    create_account_transaction,
    create_budget,
    create_goal,
)
from tests.integration.financial_rules.rule_helpers import (
    account_by_id,
    action,
    allocation_payload,
    budget_alert_payload,
    create_rule,
    delete_rule,
    floor_payload,
    overcommitment_payload,
    patch_rule,
)

# VF-020E5: safety-floor runtime on the Account read model, the advisory manual
# floor warning on POST /goals/{id}/transactions, and the P57 lifecycle
# pre-checks. The floor never changes a balance or capacity figure; the warning
# never blocks, persists or changes a transaction.

WARNING_KEYS = {"code", "minimum_unallocated_floor", "projected_reservable_amount"}


def _count(sql: str, **params: Any) -> int:
    with engine.connect() as connection:
        return connection.execute(text(sql), params).scalar_one()


def _linked(client: TestClient, user_id: str, goal_id: str, account_id: str, amount: str, key: Optional[str] = None,
            type: str = "contribution"):
    return client.post(
        f"/api/v1/goals/{goal_id}/transactions",
        headers=auth_headers(user_id),
        json={"type": type, "amount": amount, "account_id": account_id, "client_request_id": key or str(uuid4())},
    )


def _setup(client: TestClient, balance: str = "1500.00"):
    user_id = str(uuid4())
    account = create_account(client, user_id, currency="EUR", opening_balance=balance)
    goal = create_goal(client, user_id)
    return user_id, account, goal


def _enabled_floor(client: TestClient, user_id: str, account_id: str, amount: str = "1000.00") -> dict:
    rule = create_rule(client, user_id, floor_payload(account_id, amount))
    assert action(client, user_id, rule["id"], "enable").status_code == 200
    return rule


# ------------------------------------------------------------------
# Account read model
# ------------------------------------------------------------------


def test_account_floor_is_zero_without_a_floor_rule(client: TestClient, clean_database: None) -> None:
    user_id, account, _ = _setup(client)

    assert account["minimum_unallocated_floor"] == "0.00"
    assert account_by_id(client, user_id, account["id"])["minimum_unallocated_floor"] == "0.00"


def test_only_an_enabled_floor_contributes(client: TestClient, clean_database: None) -> None:
    user_id, account, _ = _setup(client)
    rule = create_rule(client, user_id, floor_payload(account["id"], "1000.00"))

    assert account_by_id(client, user_id, account["id"])["minimum_unallocated_floor"] == "0.00"  # draft
    action(client, user_id, rule["id"], "enable")
    assert account_by_id(client, user_id, account["id"])["minimum_unallocated_floor"] == "1000.00"
    action(client, user_id, rule["id"], "pause")
    assert account_by_id(client, user_id, account["id"])["minimum_unallocated_floor"] == "0.00"
    action(client, user_id, rule["id"], "enable")
    assert account_by_id(client, user_id, account["id"])["minimum_unallocated_floor"] == "1000.00"
    action(client, user_id, rule["id"], "disable")
    assert account_by_id(client, user_id, account["id"])["minimum_unallocated_floor"] == "0.00"


def test_floor_does_not_change_any_balance_or_capacity_figure(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client)
    _linked(client, user_id, goal["id"], account["id"], "200.00")
    before = account_by_id(client, user_id, account["id"])

    _enabled_floor(client, user_id, account["id"], "900.00")
    after = account_by_id(client, user_id, account["id"])

    unchanged = ("current_balance", "balance_as_of_today", "scheduled_outflows", "planned_transfer_outflows",
                 "reserved_amount", "unallocated_amount", "reservable_amount", "allocation_status", "negative_balance")
    assert {k: after[k] for k in unchanged} == {k: before[k] for k in unchanged}
    assert after["minimum_unallocated_floor"] == "900.00"
    assert "active_rule_holds" not in after and "rule_capacity" not in after and "confirm_capacity" not in after
    goal_after = client.get("/api/v1/goals", headers=auth_headers(user_id)).json()[0]
    assert goal_after["current_amount"] == "200.00"


def test_floors_of_several_accounts_and_archived_account(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    accounts = [create_account(client, user_id, name=f"A{i}") for i in range(3)]
    _enabled_floor(client, user_id, accounts[0]["id"], "10.00")
    _enabled_floor(client, user_id, accounts[2]["id"], "30.50")
    client.patch(f"/api/v1/accounts/{accounts[2]['id']}", headers=auth_headers(user_id), json={"status": "archived"})

    floors = {a["id"]: a["minimum_unallocated_floor"] for a in client.get("/api/v1/accounts", headers=auth_headers(user_id)).json()}

    assert floors == {accounts[0]["id"]: "10.00", accounts[1]["id"]: "0.00", accounts[2]["id"]: "30.50"}


def test_another_users_floor_never_appears(client: TestClient, clean_database: None) -> None:
    user_id, account, _ = _setup(client)
    other = str(uuid4())
    other_account = create_account(client, other)
    _enabled_floor(client, other, other_account["id"], "777.00")

    assert account_by_id(client, user_id, account["id"])["minimum_unallocated_floor"] == "0.00"


def _statements(run) -> list[str]:
    captured: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        captured.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        run()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return captured


def test_floor_query_count_does_not_grow_with_the_number_of_accounts(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    create_account(client, user_id, name="A0")

    def read():
        assert client.get("/api/v1/accounts", headers=auth_headers(user_id)).status_code == 200

    one = [s for s in _statements(read) if "financial_rules" in s]
    for i in range(1, 6):
        create_account(client, user_id, name=f"A{i}")
    six_statements = _statements(read)
    six = [s for s in six_statements if "financial_rules" in s]

    assert len(one) == len(six) == 1  # one grouped query regardless of the Account count
    assert not [s for s in six_statements if "rule_execution" in s or "rule_alerts" in s]


# ------------------------------------------------------------------
# manual floor warning
# ------------------------------------------------------------------


def test_warning_when_projected_reservable_is_below_the_floor(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client, "1500.00")
    _enabled_floor(client, user_id, account["id"], "1000.00")

    response = _linked(client, user_id, goal["id"], account["id"], "800.00")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["amount"] == "800.00" and body["account_id"] == account["id"]
    assert body["warnings"] == [{
        "code": "minimum_unallocated_floor",
        "minimum_unallocated_floor": "1000.00",
        "projected_reservable_amount": "700.00",
    }]
    assert set(body["warnings"][0]) == WARNING_KEYS and "projected_rule_capacity" not in body["warnings"][0]


def test_no_warning_when_projected_equals_the_floor_or_is_above(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client, "1500.00")
    _enabled_floor(client, user_id, account["id"], "1000.00")

    equal = _linked(client, user_id, goal["id"], account["id"], "500.00")  # projected exactly 1000
    assert equal.status_code == 201 and equal.json()["warnings"] == []
    second_user, second_account, second_goal = _setup(client, "1500.00")
    _enabled_floor(client, second_user, second_account["id"], "1000.00")
    above = _linked(client, second_user, second_goal["id"], second_account["id"], "100.00")
    assert above.status_code == 201 and above.json()["warnings"] == []


def test_amount_above_reservable_is_still_409_with_no_transaction(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client, "1500.00")
    _enabled_floor(client, user_id, account["id"], "1000.00")

    response = _linked(client, user_id, goal["id"], account["id"], "1600.00")

    assert response.status_code == 409
    assert "warnings" not in response.json()
    assert _count("SELECT count(*) FROM goal_transactions WHERE goal_id = :g", g=goal["id"]) == 0


def test_zero_reservable_is_still_409(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id)
    goal = create_goal(client, user_id)
    _enabled_floor(client, user_id, account["id"], "10.00")

    assert _linked(client, user_id, goal["id"], account["id"], "1.00").status_code == 409


def test_tracked_contribution_and_linked_withdrawal_have_empty_warnings(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client, "1500.00")
    _enabled_floor(client, user_id, account["id"], "1000.00")

    tracked = client.post(
        f"/api/v1/goals/{goal['id']}/transactions", headers=auth_headers(user_id),
        json={"type": "contribution", "amount": "50.00"},
    )
    assert tracked.status_code == 201 and tracked.json()["warnings"] == []
    contribution = _linked(client, user_id, goal["id"], account["id"], "800.00")
    assert contribution.json()["warnings"]  # a warning exists for the contribution
    release = _linked(client, user_id, goal["id"], account["id"], "300.00", type="withdrawal")
    assert release.status_code == 201 and release.json()["warnings"] == []


def test_non_enabled_floor_gives_no_warning(client: TestClient, clean_database: None) -> None:
    for transition in (None, "pause", "disable"):
        user_id, account, goal = _setup(client, "1500.00")
        rule = create_rule(client, user_id, floor_payload(account["id"], "1400.00"))
        if transition:
            action(client, user_id, rule["id"], "enable")
            action(client, user_id, rule["id"], transition)

        response = _linked(client, user_id, goal["id"], account["id"], "1000.00")

        assert response.status_code == 201 and response.json()["warnings"] == [], transition


def test_warning_is_not_persisted_and_history_is_unchanged(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client, "1500.00")
    _enabled_floor(client, user_id, account["id"], "1000.00")
    created = _linked(client, user_id, goal["id"], account["id"], "800.00").json()

    history = client.get(f"/api/v1/goals/{goal['id']}/transactions", headers=auth_headers(user_id)).json()

    assert len(history) == 1 and history[0]["id"] == created["id"]
    assert "warnings" not in history[0]
    assert _count("SELECT count(*) FROM goal_transactions") == 1
    columns = {r[0] for r in engine.connect().execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'goal_transactions'"))}
    assert not [c for c in columns if "warn" in c]


def test_replay_recomputes_warnings_from_current_state(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client, "1500.00")
    floor = _enabled_floor(client, user_id, account["id"], "1000.00")
    key = str(uuid4())
    first = _linked(client, user_id, goal["id"], account["id"], "800.00", key)
    assert first.status_code == 201 and first.json()["warnings"][0]["projected_reservable_amount"] == "700.00"

    same = _linked(client, user_id, goal["id"], account["id"], "800.00", key)
    assert same.status_code == 200
    assert same.json()["id"] == first.json()["id"]
    assert same.json()["warnings"] == first.json()["warnings"]
    assert _count("SELECT count(*) FROM goal_transactions") == 1

    action(client, user_id, floor["id"], "disable")  # floor disabled -> no warning
    disabled = _linked(client, user_id, goal["id"], account["id"], "800.00", key)
    assert disabled.status_code == 200 and disabled.json()["warnings"] == []

    patch_rule(client, user_id, floor["id"], floor_amount="2000.00")  # edited floor, re-enabled
    action(client, user_id, floor["id"], "enable")
    raised = _linked(client, user_id, goal["id"], account["id"], "800.00", key)
    assert raised.status_code == 200
    assert raised.json()["warnings"] == [{
        "code": "minimum_unallocated_floor", "minimum_unallocated_floor": "2000.00",
        "projected_reservable_amount": "700.00",
    }]

    create_account_transaction(client, user_id, account["id"], amount="300.00", direction="debit")  # capacity changes
    later = _linked(client, user_id, goal["id"], account["id"], "800.00", key)
    assert later.status_code == 200
    assert later.json()["warnings"][0]["projected_reservable_amount"] == "400.00"
    assert later.json()["id"] == first.json()["id"] and later.json()["amount"] == "800.00"
    assert _count("SELECT count(*) FROM goal_transactions") == 1


def test_replay_with_a_different_payload_is_still_409(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client, "1500.00")
    _enabled_floor(client, user_id, account["id"], "1000.00")
    key = str(uuid4())
    _linked(client, user_id, goal["id"], account["id"], "800.00", key)

    assert _linked(client, user_id, goal["id"], account["id"], "100.00", key).status_code == 409


def test_replay_of_a_tracked_transaction_has_empty_warnings(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client)
    _enabled_floor(client, user_id, account["id"], "1400.00")
    key = str(uuid4())
    body = {"type": "contribution", "amount": "10.00", "client_request_id": key}
    first = client.post(f"/api/v1/goals/{goal['id']}/transactions", headers=auth_headers(user_id), json=body)
    replay = client.post(f"/api/v1/goals/{goal['id']}/transactions", headers=auth_headers(user_id), json=body)

    assert first.status_code == 201 and replay.status_code == 200
    assert first.json()["warnings"] == [] and replay.json()["warnings"] == []


def test_warning_does_not_affect_other_users(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client, "1500.00")
    other, other_account, other_goal = _setup(client, "1500.00")
    _enabled_floor(client, other, other_account["id"], "1400.00")

    response = _linked(client, user_id, goal["id"], account["id"], "800.00")

    assert response.json()["warnings"] == []


# ------------------------------------------------------------------
# lifecycle pre-checks (P57)
# ------------------------------------------------------------------


def test_referenced_goal_cannot_be_deleted_or_change_currency_but_can_be_archived(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, goal = _setup(client)
    rule = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))

    delete = client.delete(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id))
    assert delete.status_code == 409 and "referenced by a financial rule" in delete.json()["detail"]
    currency = client.patch(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id), json={"currency": "USD"})
    assert currency.status_code == 409 and "referenced by a financial rule" in currency.json()["detail"]
    same = client.patch(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id), json={"currency": "EUR", "name": "Renamed"})
    assert same.status_code == 200
    archive = client.patch(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id), json={"status": "archived"})
    assert archive.status_code == 200 and archive.json()["status"] == "archived"
    assert _count("SELECT count(*) FROM financial_rule_goal_targets WHERE rule_id = :r", r=rule["id"]) == 1  # untouched
    still = client.get(f"/api/v1/financial-rules/{rule['id']}", headers=auth_headers(user_id)).json()
    assert still["status"] == "draft" and still["version"] == 1


def test_goal_with_history_keeps_the_existing_error_precedence(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client)
    client.post(f"/api/v1/goals/{goal['id']}/transactions", headers=auth_headers(user_id), json={"type": "contribution", "amount": "5.00"})
    create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))

    delete = client.delete(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id))
    currency = client.patch(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id), json={"currency": "USD"})

    assert delete.status_code == 409 and "transaction history" in delete.json()["detail"]
    assert currency.status_code == 409 and "transaction history" in currency.json()["detail"]


def test_unreferenced_goal_delete_is_unchanged_and_rule_delete_frees_the_goal(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client)
    rule = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))
    free_goal = create_goal(client, user_id, name="Free")

    assert client.delete(f"/api/v1/goals/{free_goal['id']}", headers=auth_headers(user_id)).status_code == 204
    assert client.delete(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id)).status_code == 409
    assert delete_rule(client, user_id, rule["id"]).status_code == 204
    assert client.delete(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id)).status_code == 204


def test_referenced_account_cannot_be_deleted_or_change_currency_but_can_be_archived(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = create_account(client, user_id)  # no history at all
    rule = create_rule(client, user_id, floor_payload(account["id"], "5.00"))

    delete = client.delete(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id))
    assert delete.status_code == 409 and "referenced by a financial rule" in delete.json()["detail"]
    currency = client.patch(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id), json={"currency": "USD"})
    assert currency.status_code == 409 and "referenced by a financial rule" in currency.json()["detail"]
    same = client.patch(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id), json={"currency": "EUR", "name": "Renamed"})
    assert same.status_code == 200
    archived = client.patch(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id), json={"status": "archived"})
    assert archived.status_code == 200 and archived.json()["status"] == "archived"
    assert archived.json()["minimum_unallocated_floor"] == "0.00"  # draft floor
    assert client.get(f"/api/v1/financial-rules/{rule['id']}", headers=auth_headers(user_id)).json()["status"] == "draft"


def test_every_rule_type_protects_its_account(client: TestClient, clean_database: None) -> None:
    for build in (
        lambda c, u, a, g: floor_payload(a["id"]),
        lambda c, u, a, g: overcommitment_payload(a["id"]),
        lambda c, u, a, g: allocation_payload(a["id"], [g["id"]]),
    ):
        user_id = str(uuid4())
        account = create_account(client, user_id)
        goal = create_goal(client, user_id)
        create_rule(client, user_id, build(client, user_id, account, goal))
        assert client.delete(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id)).status_code == 409


def test_account_history_checks_keep_precedence_over_the_rule_check(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client, "100.00")  # ledger history
    create_rule(client, user_id, floor_payload(account["id"]))

    delete = client.delete(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id))
    currency = client.patch(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id), json={"currency": "USD"})

    assert delete.status_code == 409 and "transaction history" in delete.json()["detail"]
    assert currency.status_code == 409 and "transaction history" in currency.json()["detail"]


def test_unreferenced_account_delete_still_works_and_rule_delete_frees_it(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    free = create_account(client, user_id, name="Free")
    used = create_account(client, user_id, name="Used")
    rule = create_rule(client, user_id, floor_payload(used["id"]))

    assert client.delete(f"/api/v1/accounts/{free['id']}", headers=auth_headers(user_id)).status_code == 204
    assert client.delete(f"/api/v1/accounts/{used['id']}", headers=auth_headers(user_id)).status_code == 409
    assert delete_rule(client, user_id, rule["id"]).status_code == 204
    assert client.delete(f"/api/v1/accounts/{used['id']}", headers=auth_headers(user_id)).status_code == 204


def test_referenced_budget_cannot_be_deleted(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    budget = create_budget(client, user_id)
    free = create_budget(client, user_id, name="Free")
    rule = create_rule(client, user_id, budget_alert_payload(budget["id"]))

    blocked = client.delete(f"/api/v1/budgets/{budget['id']}", headers=auth_headers(user_id))
    assert blocked.status_code == 409 and "referenced by a financial rule" in blocked.json()["detail"]
    assert client.delete(f"/api/v1/budgets/{free['id']}", headers=auth_headers(user_id)).status_code == 204
    assert client.delete(f"/api/v1/budgets/{uuid4()}", headers=auth_headers(user_id)).status_code == 404
    assert client.delete(f"/api/v1/budgets/{budget['id']}", headers=auth_headers(str(uuid4()))).status_code == 404
    assert _count("SELECT count(*) FROM budgets WHERE id = :i", i=budget["id"]) == 1
    assert delete_rule(client, user_id, rule["id"]).status_code == 204
    assert client.delete(f"/api/v1/budgets/{budget['id']}", headers=auth_headers(user_id)).status_code == 204


# ------------------------------------------------------------------
# no future-stage queries
# ------------------------------------------------------------------


def test_no_statement_touches_execution_alert_or_hold_tables(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client, "1500.00")
    budget = create_budget(client, user_id)

    def run():
        floor = create_rule(client, user_id, floor_payload(account["id"], "1000.00"))
        action(client, user_id, floor["id"], "enable")
        create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))
        create_rule(client, user_id, budget_alert_payload(budget["id"]))
        patch_rule(client, user_id, floor["id"], floor_amount="900.00")
        client.get("/api/v1/financial-rules", headers=auth_headers(user_id))
        client.get("/api/v1/accounts", headers=auth_headers(user_id))
        _linked(client, user_id, goal["id"], account["id"], "700.00")
        action(client, user_id, floor["id"], "pause")
        action(client, user_id, floor["id"], "disable")
        delete_rule(client, user_id, floor["id"])

    statements = _statements(run)

    assert statements
    assert not [s for s in statements if any(
        word in s for word in ("rule_executions", "rule_execution_items", "rule_execution_audit", "rule_alerts"))]
