from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.app_config import settings
from app.db.database_session import engine
from app.modules.financial_events import financial_event_processor
from tests.helpers import auth_headers, create_account
from tests.integration.financial_rules.execution_helpers import (
    account_view,
    enabled_rule,
    evaluate,
    executions,
    funded_account,
    goal_view,
    goal_with_target,
    post_income,
    scalar,
)
from tests.integration.financial_rules.rule_helpers import (
    action,
    allocation_payload,
    create_rule,
    delete_rule,
    floor_payload,
    patch_rule,
)

# VF-020E7: income corrections after execution (§15.2, §15.3, P47), the
# lifecycle 409 pre-checks (P57), the Account capacity read model and the
# best-effort post-response trigger.


def _setup_executed(client: TestClient, opening: str = "2000.00"):
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening=opening)
    goal = goal_with_target(client, user_id, "G", 3000)
    rule = enabled_rule(
        client, user_id, account["id"], [goal["id"]],
        targets=[{"goal_id": goal["id"], "amount_or_cap": "300.00"}],
    )
    income = post_income(client, user_id, "3000.00", account["id"])
    evaluate(client, user_id)
    return user_id, account, goal, rule, income


def _patch_income(client: TestClient, user_id: str, income_id: str, **fields):
    response = client.patch(f"/api/v1/income/{income_id}", headers=auth_headers(user_id), json=fields)
    assert response.status_code == 200, response.text
    return response.json()


def _audit_codes(client: TestClient, user_id: str) -> list[str]:
    return [entry["code"] for entry in executions(client, user_id)["items"][0]["audit"]]


# ------------------------------------------------------------------
# Corrections (S20, S21, S22, S34)
# ------------------------------------------------------------------


def test_s20_amount_correction_annotates_without_changing_reservations(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, goal, _, income = _setup_executed(client)
    reserved_before = account_view(client, user_id, account["id"])["reserved_amount"]

    _patch_income(client, user_id, income["id"], amount="2000.00")
    assert evaluate(client, user_id).json()["processed"] == 1

    body = executions(client, user_id)
    assert body["total"] == 1 and body["items"][0]["status"] == "executed"
    assert _audit_codes(client, user_id) == ["applied", "source_changed"]
    assert body["items"][0]["audit"][1]["details"] == {"changed_fields": ["amount"]}
    assert account_view(client, user_id, account["id"])["reserved_amount"] == reserved_before == "300.00"
    assert scalar("SELECT count(*) FROM goal_transactions WHERE rule_execution_id IS NOT NULL") == 1
    # The stored source snapshot of the execution keeps the amount that was allocated.
    assert body["items"][0]["source_amount"] == "3000.00"


def test_s22_moving_the_income_to_another_account_keeps_the_reservation_on_the_original(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, goal, _, income = _setup_executed(client)
    other = create_account(client, user_id, name="Savings", currency="EUR")

    _patch_income(client, user_id, income["id"], account_id=other["id"])
    evaluate(client, user_id)

    assert _audit_codes(client, user_id) == ["applied", "source_changed"]
    assert executions(client, user_id)["items"][0]["audit"][1]["details"] == {"changed_fields": ["account_id"]}
    assert account_view(client, user_id, account["id"])["reserved_amount"] == "300.00"
    assert account_view(client, user_id, other["id"])["reserved_amount"] == "0.00"
    assert executions(client, user_id)["total"] == 1  # no allocation for the new account


def test_correction_without_snapshot_change_adds_no_annotation(client: TestClient, clean_database: None) -> None:
    user_id, _, _, _, income = _setup_executed(client)

    _patch_income(client, user_id, income["id"], description="note only")
    evaluate(client, user_id)

    assert _audit_codes(client, user_id) == ["applied"]


def test_s21_s34_deleting_the_income_preserves_the_allocation(client: TestClient, clean_database: None) -> None:
    user_id, account, goal, _, income = _setup_executed(client)

    assert client.delete(f"/api/v1/income/{income['id']}", headers=auth_headers(user_id)).status_code == 204
    evaluate(client, user_id)

    assert _audit_codes(client, user_id) == ["applied", "source_deleted"]
    assert account_view(client, user_id, account["id"])["reserved_amount"] == "300.00"
    assert goal_view(client, user_id, goal["id"])["current_amount"] == "300.00"
    assert scalar("SELECT count(*) FROM goal_transactions WHERE rule_execution_id IS NOT NULL") == 1
    assert executions(client, user_id)["items"][0]["status"] == "executed"  # no compensation, no reopening


def test_redelivered_correction_events_do_not_duplicate_annotations(client: TestClient, clean_database: None) -> None:
    user_id, _, _, _, income = _setup_executed(client)
    _patch_income(client, user_id, income["id"], amount="2000.00")
    evaluate(client, user_id)

    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE financial_events SET status = 'pending', processed_at = NULL, outcome_summary = NULL "
            "WHERE event_type = 'income.updated'"))
    evaluate(client, user_id)

    assert _audit_codes(client, user_id) == ["applied", "source_changed"]


def test_an_old_income_cannot_become_eligible_through_an_edit(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]])
    historical = post_income(
        client, user_id, "10.00", None, received_at=date.today() - timedelta(days=30),
    )
    evaluate(client, user_id)

    _patch_income(client, user_id, historical["id"], account_id=account["id"])
    evaluate(client, user_id)

    assert executions(client, user_id)["total"] == 0  # historical creation provenance is permanent


def test_income_created_before_activation_stays_ineligible_after_an_edit(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    rule = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))
    income = post_income(client, user_id, "10.00", account["id"])
    assert action(client, user_id, rule["id"], "enable").status_code == 200

    _patch_income(client, user_id, income["id"], amount="20.00")
    evaluate(client, user_id)

    assert executions(client, user_id)["total"] == 0


def test_a_live_income_can_become_eligible_by_linking_the_rule_account(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]])
    income = post_income(client, user_id, "10.00", None)  # live creation, not linked
    evaluate(client, user_id)
    assert executions(client, user_id)["total"] == 0

    _patch_income(client, user_id, income["id"], account_id=account["id"])
    evaluate(client, user_id)

    body = executions(client, user_id)
    assert body["total"] == 1 and body["items"][0]["status"] == "executed"
    triggering = scalar("SELECT event_type FROM financial_events WHERE id = :id", id=body["items"][0]["triggering_event_id"])
    assert triggering == "income.updated"


# ------------------------------------------------------------------
# Lifecycle pre-checks (P57): controlled 409, never a raw FK error
# ------------------------------------------------------------------


def test_rule_with_execution_history_cannot_be_deleted(client: TestClient, clean_database: None) -> None:
    user_id, _, _, rule, _ = _setup_executed(client)
    assert action(client, user_id, rule["id"], "disable").status_code == 200

    response = delete_rule(client, user_id, rule["id"])

    assert response.status_code == 409
    assert scalar("SELECT count(*) FROM financial_rules WHERE id = :id", id=rule["id"]) == 1
    assert executions(client, user_id)["total"] == 1


@pytest.mark.parametrize("outcome", ["skipped", "blocked"])
def test_skipped_and_blocked_executions_also_keep_the_rule(
    client: TestClient, clean_database: None, outcome: str,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="10.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    rule = enabled_rule(client, user_id, account["id"], [goal["id"]])
    post_income(client, user_id, "1.00", account["id"])
    if outcome == "blocked":
        client.patch(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id), json={"status": "archived"})
    evaluate(client, user_id)
    assert executions(client, user_id)["items"][0]["status"] == outcome
    action(client, user_id, rule["id"], "disable")

    assert delete_rule(client, user_id, rule["id"]).status_code == 409


def test_rule_without_history_is_still_deletable_and_foreign_ids_stay_404(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="10.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    rule = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))

    assert delete_rule(client, str(uuid4()), rule["id"]).status_code == 404  # foreign: indistinguishable
    assert delete_rule(client, user_id, str(uuid4())).status_code == 404
    assert delete_rule(client, user_id, rule["id"]).status_code == 204


def test_goal_and_account_with_execution_items_are_protected(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="10.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    rule = enabled_rule(client, user_id, account["id"], [goal["id"]], targets=[{"goal_id": goal["id"], "amount_or_cap": "300.00"}])
    post_income(client, user_id, "1.00", account["id"])
    evaluate(client, user_id)  # skipped: items exist but no GoalTransaction was written
    assert scalar("SELECT count(*) FROM goal_transactions") == 0
    assert scalar("SELECT count(*) FROM rule_execution_items") == 1
    assert action(client, user_id, rule["id"], "disable").status_code == 200
    other_goal = goal_with_target(client, user_id, "Other", 100)
    assert patch_rule(client, user_id, rule["id"], targets=[{"goal_id": other_goal["id"], "amount_or_cap": "5.00"}]).status_code == 200

    # The rule no longer targets the Goal, but the execution history still does.
    assert client.delete(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id)).status_code == 409
    assert client.patch(
        f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id), json={"currency": "USD"},
    ).status_code == 409
    assert client.delete(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id)).status_code == 409
    assert client.patch(
        f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id), json={"currency": "USD"},
    ).status_code == 409


# ------------------------------------------------------------------
# Account capacity read model and warnings
# ------------------------------------------------------------------


def _hold(user_id: str, account_id: str, rule_id: str, goal_id: str, amount: str, expires: str) -> None:
    with engine.begin() as connection:
        execution_id = connection.execute(
            text(
                "INSERT INTO rule_executions (id, user_id, rule_id, rule_version, params_snapshot, source_type, "
                "source_id, triggering_event_id, source_amount, source_currency, source_received_at, "
                "source_income_source, status, hold_sequence, expires_at) "
                "VALUES (gen_random_uuid(), :u, :r, 1, '{}', 'income', gen_random_uuid(), gen_random_uuid(), "
                "1, 'EUR', CURRENT_DATE, 'salary', 'awaiting_confirmation', nextval('rule_execution_hold_sequence'), "
                f"now() + interval '{expires}') RETURNING id"
            ),
            {"u": user_id, "r": rule_id},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO rule_execution_items (id, user_id, execution_id, goal_id, account_id, position, planned_amount) "
                "VALUES (gen_random_uuid(), :u, :e, :g, :a, 0, :amount)"
            ),
            {"u": user_id, "e": execution_id, "g": goal_id, "a": account_id, "amount": amount},
        )


def test_rule_capacity_subtracts_floor_and_only_unexpired_holds(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="1500.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    floor = create_rule(client, user_id, floor_payload(account["id"], "1000.00"))
    action(client, user_id, floor["id"], "enable")
    rule = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))

    _hold(user_id, account["id"], rule["id"], goal["id"], "120.00", "7 days")
    _hold(user_id, account["id"], rule["id"], goal["id"], "30.00", "1 day")
    _hold(user_id, account["id"], rule["id"], goal["id"], "999.00", "-1 second")  # expired: excluded

    view = account_view(client, user_id, account["id"])

    assert view["active_rule_holds"] == "150.00"
    assert view["reservable_amount"] == "1500.00"  # holds are not reserved money
    assert view["reserved_amount"] == "0.00" and view["balance_as_of_today"] == "1500.00"
    assert view["rule_capacity"] == "350.00"  # 1500 - 1000 - 150


def test_holds_never_trigger_the_manual_floor_warning_but_appear_in_the_projection(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="1500.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    floor = create_rule(client, user_id, floor_payload(account["id"], "1000.00"))
    action(client, user_id, floor["id"], "enable")
    rule = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))
    _hold(user_id, account["id"], rule["id"], goal["id"], "400.00", "7 days")

    def reserve(amount: str):
        return client.post(
            f"/api/v1/goals/{goal['id']}/transactions", headers=auth_headers(user_id),
            json={"type": "contribution", "amount": amount, "account_id": account["id"], "client_request_id": str(uuid4())},
        )

    first = reserve("400.00")  # projected 1100 >= floor 1000: holds alone do not warn
    assert first.status_code == 201 and first.json()["warnings"] == []

    second = reserve("300.00")  # projected 800 < 1000 -> warning, projection includes the 400 hold
    assert second.status_code == 201
    assert second.json()["warnings"] == [{
        "code": "minimum_unallocated_floor", "minimum_unallocated_floor": "1000.00",
        "projected_reservable_amount": "800.00", "projected_rule_capacity": "-600.00",
    }]


def test_occupied_key_replay_does_not_subtract_the_committed_contribution_twice(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="1500.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    floor = create_rule(client, user_id, floor_payload(account["id"], "1000.00"))
    action(client, user_id, floor["id"], "enable")
    key = str(uuid4())
    payload = {"type": "contribution", "amount": "800.00", "account_id": account["id"], "client_request_id": key}
    first = client.post(f"/api/v1/goals/{goal['id']}/transactions", headers=auth_headers(user_id), json=payload)
    replay = client.post(f"/api/v1/goals/{goal['id']}/transactions", headers=auth_headers(user_id), json=payload)

    assert first.status_code == 201 and replay.status_code == 200
    assert replay.json()["warnings"] == first.json()["warnings"]
    assert replay.json()["warnings"][0]["projected_rule_capacity"] == "-300.00"  # 700 - 1000, once


# ------------------------------------------------------------------
# Best-effort post-response trigger
# ------------------------------------------------------------------


def test_income_write_triggers_a_best_effort_drain_when_enabled(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rule_event_background_dispatch", True)
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]])

    post_income(client, user_id, "10.00", account["id"])

    assert executions(client, user_id)["total"] == 1
    assert scalar("SELECT status FROM financial_events") == "processed"


def test_a_failing_background_drain_never_affects_the_income_response(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rule_event_background_dispatch", True)

    def explode(*_args, **_kwargs):
        raise RuntimeError("drain failed")

    monkeypatch.setattr(financial_event_processor, "drain_user_events", explode)
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")

    created = post_income(client, user_id, "10.00", account["id"])

    assert created["id"]
    assert scalar("SELECT status FROM financial_events") == "pending"  # still durable for the next drain


def test_background_drain_is_off_by_default_in_the_suite(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")

    post_income(client, user_id, "10.00", account["id"])

    assert scalar("SELECT status FROM financial_events") == "pending"
