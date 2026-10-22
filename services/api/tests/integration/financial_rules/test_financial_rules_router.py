from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database_session import engine
from tests.helpers import auth_headers, create_account, create_budget, create_goal
from tests.integration.financial_rules.rule_helpers import (
    RULES_URL,
    action,
    allocation_payload,
    budget_alert_payload,
    create_rule,
    delete_rule,
    floor_payload,
    get_rule,
    overcommitment_payload,
    patch_rule,
    post_rule,
)

# VF-020E5 rules CRUD tests (real PostgreSQL through the API). Rules are
# configuration only: nothing here executes a rule or creates a money row.


def _count(sql: str, **params: Any) -> int:
    with engine.connect() as connection:
        return connection.execute(text(sql), params).scalar_one()


def _setup(client: TestClient):
    user_id = str(uuid4())
    account = create_account(client, user_id, currency="EUR")
    goal = create_goal(client, user_id)
    return user_id, account, goal


# ------------------------------------------------------------------
# create / read for all four types
# ------------------------------------------------------------------


def test_create_floor_rule_returns_201_draft_version_one(client: TestClient, clean_database: None) -> None:
    user_id, account, _ = _setup(client)

    body = create_rule(client, user_id, floor_payload(account["id"], "1000.00"))

    assert body["rule_type"] == "MINIMUM_UNALLOCATED_FLOOR"
    assert (body["status"], body["version"], body["active_since"]) == ("draft", 1, None)
    assert body["floor_amount"] == "1000.00" and body["source_account_id"] == account["id"]
    assert body["user_id"] == user_id
    assert "targets" not in body and "execution_mode" not in body and "budget_id" not in body


def test_create_allocation_rule_defaults_and_targets(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client)

    body = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))

    assert body["rule_type"] == "INCOME_ALLOCATION"
    assert (body["status"], body["version"]) == ("draft", 1)
    assert body["cap_at_target"] is True and body["allow_partial"] is False
    assert body["income_sources"] == ["salary", "freelance", "gift", "other"]  # refund excluded (P35)
    assert body["execution_order"] == 1 and body["execution_mode"] == "AUTO"
    assert body["percent"] is None and body["effective_from"] is None
    assert len(body["targets"]) == 1
    assert body["targets"][0]["goal_id"] == goal["id"]
    assert body["targets"][0]["amount_or_cap"] == "100.00" and body["targets"][0]["position"] == 0


def test_create_percent_allocation_with_optional_cap_and_refund_opt_in(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, goal = _setup(client)
    payload = allocation_payload(
        account["id"], [goal["id"]], policy="PERCENT_OF_INCOME_WATERFALL",
        income_sources=["salary", "refund"], allow_partial=True, cap_at_target=False,
    )

    body = create_rule(client, user_id, payload)

    assert body["policy"] == "PERCENT_OF_INCOME_WATERFALL" and body["percent"] == "20.00"
    assert body["income_sources"] == ["salary", "refund"]
    assert body["allow_partial"] is True and body["cap_at_target"] is False
    assert body["targets"][0]["amount_or_cap"] is None


def test_create_alert_rules(client: TestClient, clean_database: None) -> None:
    user_id, account, _ = _setup(client)
    budget = create_budget(client, user_id)

    over = create_rule(client, user_id, overcommitment_payload(account["id"]))
    alert = create_rule(client, user_id, budget_alert_payload(budget["id"]))

    assert over["rule_type"] == "OVERCOMMITMENT_ALERT" and over["status"] == "draft"
    assert "targets" not in over and "floor_amount" not in over
    assert alert["rule_type"] == "BUDGET_ALERT" and alert["budget_id"] == budget["id"]
    assert "source_account_id" not in alert and "targets" not in alert


def test_get_list_and_detail_round_trip(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client)
    floor = create_rule(client, user_id, floor_payload(account["id"]))
    allocation = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))

    listing = client.get(RULES_URL, headers=auth_headers(user_id)).json()

    assert [r["id"] for r in listing] == [allocation["id"], floor["id"]]  # allocation first
    assert get_rule(client, user_id, floor["id"]).json() == floor
    detail = get_rule(client, user_id, allocation["id"]).json()
    assert detail == allocation and detail["targets"]


def test_allocation_list_order_is_execution_order_created_at_id(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client)
    third = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]], name="c", execution_order=5))
    first = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]], name="a", execution_order=2))
    second = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]], name="b", execution_order=2))

    listing = client.get(RULES_URL, headers=auth_headers(user_id)).json()

    assert [r["id"] for r in listing] == [first["id"], second["id"], third["id"]]


# ------------------------------------------------------------------
# ownership and 404
# ------------------------------------------------------------------


def test_rules_are_isolated_per_user_and_foreign_ids_are_indistinguishable_404(
    client: TestClient, clean_database: None,
) -> None:
    owner, account, _ = _setup(client)
    intruder = str(uuid4())
    rule = create_rule(client, owner, floor_payload(account["id"]))

    assert client.get(RULES_URL, headers=auth_headers(intruder)).json() == []
    foreign = get_rule(client, intruder, rule["id"])
    missing = get_rule(client, intruder, str(uuid4()))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    for response in (
        patch_rule(client, intruder, rule["id"], name="x"),
        action(client, intruder, rule["id"], "enable"),
        action(client, intruder, rule["id"], "pause"),
        action(client, intruder, rule["id"], "disable"),
        delete_rule(client, intruder, rule["id"]),
    ):
        assert response.status_code == 404 and response.json() == missing.json()
    assert get_rule(client, owner, rule["id"]).json()["name"] == "Floor"


def test_unauthenticated_requests_are_rejected(client: TestClient, clean_database: None) -> None:
    assert client.get(RULES_URL).status_code in (401, 403)
    assert client.post(RULES_URL, json={}).status_code in (401, 403)


def test_foreign_or_missing_subjects_are_404(client: TestClient, clean_database: None) -> None:
    owner, account, goal = _setup(client)
    intruder = str(uuid4())
    budget = create_budget(client, owner)

    assert post_rule(client, intruder, floor_payload(account["id"])).status_code == 404
    assert post_rule(client, owner, floor_payload(str(uuid4()))).status_code == 404
    assert post_rule(client, intruder, overcommitment_payload(account["id"])).status_code == 404
    assert post_rule(client, intruder, budget_alert_payload(budget["id"])).status_code == 404
    assert post_rule(client, owner, budget_alert_payload(str(uuid4()))).status_code == 404
    assert post_rule(client, intruder, allocation_payload(account["id"], [goal["id"]])).status_code == 404
    other_goal = create_goal(client, str(uuid4()))
    assert post_rule(client, owner, allocation_payload(account["id"], [other_goal["id"]])).status_code == 404
    assert _count("SELECT count(*) FROM financial_rules") == 0


# ------------------------------------------------------------------
# request validation
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra", [
        {"user_id": str(uuid4())}, {"version": 5}, {"status": "enabled"}, {"active_since": "2026-01-01T00:00:00Z"},
        {"created_at": "2026-01-01T00:00:00Z"}, {"unknown": 1},
    ],
)
def test_clients_cannot_write_server_owned_fields(client: TestClient, clean_database: None, extra: dict) -> None:
    user_id, account, _ = _setup(client)

    response = post_rule(client, user_id, {**floor_payload(account["id"]), **extra})

    assert response.status_code == 422
    assert _count("SELECT count(*) FROM financial_rules") == 0


def test_unsupported_rule_types_are_rejected(client: TestClient, clean_database: None) -> None:
    user_id, account, _ = _setup(client)

    for rule_type in ("GOAL_DEADLINE_ALERT", "SOMETHING"):
        assert post_rule(client, user_id, {"rule_type": rule_type, "name": "x", "source_account_id": account["id"]}).status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"policy": "FIXED_PER_GOAL", "targets": [{"goal_id": "G", "amount_or_cap": None}]},
        {"policy": "FIXED_PER_GOAL", "percent": "10.00"},
        {"policy": "PERCENT_OF_INCOME_WATERFALL"},  # percent missing
        {"policy": "PERCENT_OF_INCOME_WATERFALL", "percent": "0"},
        {"policy": "PERCENT_OF_INCOME_WATERFALL", "percent": "100.01"},
        {"income_sources": []},
        {"income_sources": ["bonus"]},
        {"income_sources": ["salary", "salary"]},
        {"targets": []},
        {"execution_mode": "MANUAL"},
        {"execution_order": 0},
    ],
)
def test_invalid_allocation_shapes_are_422(client: TestClient, clean_database: None, overrides: dict) -> None:
    user_id, account, goal = _setup(client)
    payload = allocation_payload(account["id"], [goal["id"]])
    if "targets" in overrides:
        overrides = {**overrides, "targets": [{**t, "goal_id": goal["id"]} for t in overrides["targets"]]}
    if overrides.get("policy") == "PERCENT_OF_INCOME_WATERFALL":
        payload["targets"] = [{"goal_id": goal["id"]}]
    payload.update(overrides)

    response = post_rule(client, user_id, payload)

    assert response.status_code == 422, response.text
    assert _count("SELECT count(*) FROM financial_rules") == 0


def test_duplicate_goal_target_is_422_and_duplicate_positions_are_allowed(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, goal = _setup(client)
    second = create_goal(client, user_id, name="Second")

    duplicate = allocation_payload(account["id"], [goal["id"], goal["id"]])
    assert post_rule(client, user_id, duplicate).status_code == 422

    payload = allocation_payload(account["id"], [goal["id"], second["id"]])
    payload["targets"][0]["position"] = 3
    payload["targets"][1]["position"] = 3
    body = create_rule(client, user_id, payload)
    assert [t["position"] for t in body["targets"]] == [3, 3]


def test_floor_amount_validation_and_exact_decimal(client: TestClient, clean_database: None) -> None:
    user_id, account, _ = _setup(client)
    second = create_account(client, user_id, name="Second")

    assert post_rule(client, user_id, floor_payload(account["id"], "-0.01")).status_code == 422
    assert post_rule(client, user_id, floor_payload(account["id"], "10.001")).status_code == 422
    assert create_rule(client, user_id, floor_payload(account["id"], "0.00"))["floor_amount"] == "0.00"
    assert create_rule(client, user_id, floor_payload(second["id"], "1234.50"))["floor_amount"] == "1234.50"


def test_allocation_currency_and_archived_subject_validation(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client)
    usd_goal = client.post(
        "/api/v1/goals", headers=auth_headers(user_id),
        json={"name": "USD", "target_amount": 100, "currency": "USD", "status": "active"},
    ).json()
    archived = create_goal(client, user_id, name="Old")
    client.patch(f"/api/v1/goals/{archived['id']}", headers=auth_headers(user_id), json={"status": "archived"})
    completed = create_goal(client, user_id, name="Done")
    client.patch(f"/api/v1/goals/{completed['id']}", headers=auth_headers(user_id), json={"status": "completed"})

    assert post_rule(client, user_id, allocation_payload(account["id"], [usd_goal["id"]])).status_code == 422
    assert post_rule(client, user_id, allocation_payload(account["id"], [archived["id"]])).status_code == 409
    assert post_rule(client, user_id, allocation_payload(account["id"], [completed["id"]])).status_code == 201  # P11

    client.patch(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id), json={"status": "archived"})
    assert post_rule(client, user_id, allocation_payload(account["id"], [goal["id"]])).status_code == 409


# ------------------------------------------------------------------
# execution_order
# ------------------------------------------------------------------


def test_omitted_execution_order_appends_max_plus_one_and_duplicates_are_allowed(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, goal = _setup(client)

    first = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))
    jump = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]], execution_order=10))
    after_gap = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))
    duplicate = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]], execution_order=10))

    assert [first["execution_order"], jump["execution_order"], after_gap["execution_order"], duplicate["execution_order"]] == [1, 10, 11, 10]
    other_user = str(uuid4())
    other_account = create_account(client, other_user)
    other_goal = create_goal(client, other_user)
    assert create_rule(client, other_user, allocation_payload(other_account["id"], [other_goal["id"]]))["execution_order"] == 1


# ------------------------------------------------------------------
# uniqueness conflicts
# ------------------------------------------------------------------


def test_duplicate_floor_and_alert_subjects_are_controlled_conflicts(client: TestClient, clean_database: None) -> None:
    user_id, account, _ = _setup(client)
    budget = create_budget(client, user_id)
    create_rule(client, user_id, floor_payload(account["id"]))
    create_rule(client, user_id, overcommitment_payload(account["id"]))
    create_rule(client, user_id, budget_alert_payload(budget["id"]))

    for payload in (floor_payload(account["id"], name="again"), overcommitment_payload(account["id"]), budget_alert_payload(budget["id"])):
        response = post_rule(client, user_id, payload)
        assert response.status_code == 409
        assert "constraint" not in response.text.lower() and "uq_" not in response.text

    # different rule types on the same Account, and other users, are fine
    assert _count("SELECT count(*) FROM financial_rules WHERE user_id = :u", u=user_id) == 3


def test_moving_a_floor_onto_an_occupied_account_is_a_conflict(client: TestClient, clean_database: None) -> None:
    user_id, account, _ = _setup(client)
    second = create_account(client, user_id, name="B")
    create_rule(client, user_id, floor_payload(account["id"]))
    movable = create_rule(client, user_id, floor_payload(second["id"]))

    response = patch_rule(client, user_id, movable["id"], source_account_id=account["id"])

    assert response.status_code == 409
    assert get_rule(client, user_id, movable["id"]).json()["version"] == 1


# ------------------------------------------------------------------
# PATCH and versioning
# ------------------------------------------------------------------


def test_non_material_edits_do_not_bump_version(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client)
    rule = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))

    for fields in ({"name": "Renamed"}, {"description": "note"}, {"execution_order": 7}):
        response = patch_rule(client, user_id, rule["id"], **fields)
        assert response.status_code == 200, response.text
        assert response.json()["version"] == 1

    body = get_rule(client, user_id, rule["id"]).json()
    assert (body["name"], body["description"], body["execution_order"]) == ("Renamed", "note", 7)


def test_same_value_patch_does_not_bump_version(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client)
    rule = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))
    floor = create_rule(client, user_id, floor_payload(account["id"], "500.00"))

    same = patch_rule(
        client, user_id, rule["id"], execution_mode="AUTO", policy="FIXED_PER_GOAL",
        cap_at_target=True, allow_partial=False, source_account_id=account["id"],
        income_sources=["gift", "other", "salary", "freelance"],
        targets=[{"goal_id": goal["id"], "amount_or_cap": "100.00"}],
    )
    assert same.status_code == 200 and same.json()["version"] == 1
    assert patch_rule(client, user_id, floor["id"], floor_amount="500.00").json()["version"] == 1


@pytest.mark.parametrize(
    "fields",
    [
        {"execution_mode": "CONFIRM"},
        {"allow_partial": True},
        {"cap_at_target": False},
        {"effective_from": "2026-12-01"},
        {"income_sources": ["salary"]},
        {"targets": [{"goal_id": "G", "amount_or_cap": "250.00"}]},
    ],
)
def test_material_allocation_edits_increment_version_once(client: TestClient, clean_database: None, fields: dict) -> None:
    user_id, account, goal = _setup(client)
    rule = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))
    fields = {k: ([{**t, "goal_id": goal["id"]} for t in v] if k == "targets" else v) for k, v in fields.items()}

    response = patch_rule(client, user_id, rule["id"], **fields)

    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2


def test_policy_and_percent_edits_are_material(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client)
    rule = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]], policy="PERCENT_OF_INCOME_WATERFALL"))

    percent = patch_rule(client, user_id, rule["id"], percent="25.00")
    assert percent.status_code == 200 and percent.json()["version"] == 2 and percent.json()["percent"] == "25.00"
    policy = patch_rule(
        client, user_id, rule["id"], policy="FIXED_PER_GOAL", percent=None,
        targets=[{"goal_id": goal["id"], "amount_or_cap": "50.00"}],
    )
    assert policy.status_code == 200, policy.text
    assert policy.json()["version"] == 3 and policy.json()["policy"] == "FIXED_PER_GOAL"


def test_target_replacement_adds_removes_and_position_only_is_not_material(client: TestClient, clean_database: None) -> None:
    user_id, account, first = _setup(client)
    second = create_goal(client, user_id, name="Second")
    third = create_goal(client, user_id, name="Third")
    rule = create_rule(client, user_id, allocation_payload(account["id"], [first["id"], second["id"]]))
    original_ids = {t["goal_id"]: t["id"] for t in rule["targets"]}

    reordered = patch_rule(client, user_id, rule["id"], targets=[
        {"goal_id": second["id"], "amount_or_cap": "100.00", "position": 0},
        {"goal_id": first["id"], "amount_or_cap": "100.00", "position": 1},
    ])
    assert reordered.status_code == 200 and reordered.json()["version"] == 1  # position is not financial
    assert [t["goal_id"] for t in reordered.json()["targets"]] == [second["id"], first["id"]]
    assert {t["goal_id"]: t["id"] for t in reordered.json()["targets"]} == original_ids  # rows kept

    replaced = patch_rule(client, user_id, rule["id"], targets=[
        {"goal_id": first["id"], "amount_or_cap": "100.00"}, {"goal_id": third["id"], "amount_or_cap": "75.00"},
    ])
    assert replaced.status_code == 200 and replaced.json()["version"] == 2
    assert {t["goal_id"] for t in replaced.json()["targets"]} == {first["id"], third["id"]}
    assert _count("SELECT count(*) FROM financial_rule_goal_targets") == 2


def test_floor_edits(client: TestClient, clean_database: None) -> None:
    user_id, account, _ = _setup(client)
    other_account = create_account(client, user_id, name="B")
    floor = create_rule(client, user_id, floor_payload(account["id"], "100.00"))

    assert patch_rule(client, user_id, floor["id"], name="Renamed").json()["version"] == 1
    assert patch_rule(client, user_id, floor["id"], floor_amount="250.00").json()["version"] == 2
    moved = patch_rule(client, user_id, floor["id"], source_account_id=other_account["id"])
    assert moved.status_code == 200 and moved.json()["version"] == 3
    assert moved.json()["source_account_id"] == other_account["id"]


def test_invalid_patches(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client)
    floor = create_rule(client, user_id, floor_payload(account["id"]))
    allocation = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))

    assert patch_rule(client, user_id, floor["id"], status="enabled").status_code == 422  # status is not PATCHable
    assert patch_rule(client, user_id, floor["id"], version=9).status_code == 422
    assert client.patch(
        f"{RULES_URL}/{floor['id']}", headers=auth_headers(user_id), json={"user_id": str(uuid4())},
    ).status_code == 422
    assert patch_rule(client, user_id, floor["id"], policy="FIXED_PER_GOAL").status_code == 422  # not a floor field
    assert patch_rule(client, user_id, floor["id"], name=None).status_code == 422
    assert patch_rule(client, user_id, allocation["id"], policy="PERCENT_OF_INCOME_WATERFALL").status_code == 422  # percent missing
    assert patch_rule(client, user_id, allocation["id"], floor_amount="1.00").status_code == 422
    assert patch_rule(client, user_id, floor["id"], floor_amount="-1").status_code == 422
    assert get_rule(client, user_id, floor["id"]).json()["version"] == 1


def test_patch_target_rules_currency_and_archived_goal(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client)
    usd_goal = client.post(
        "/api/v1/goals", headers=auth_headers(user_id),
        json={"name": "USD", "target_amount": 100, "currency": "USD", "status": "active"},
    ).json()
    archived = create_goal(client, user_id, name="Old")
    client.patch(f"/api/v1/goals/{archived['id']}", headers=auth_headers(user_id), json={"status": "archived"})
    rule = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))

    assert patch_rule(client, user_id, rule["id"], targets=[{"goal_id": usd_goal["id"], "amount_or_cap": "1.00"}]).status_code == 422
    assert patch_rule(client, user_id, rule["id"], targets=[{"goal_id": archived["id"], "amount_or_cap": "1.00"}]).status_code == 409
    assert patch_rule(client, user_id, rule["id"], targets=[{"goal_id": str(uuid4()), "amount_or_cap": "1.00"}]).status_code == 404
    assert get_rule(client, user_id, rule["id"]).json()["version"] == 1


# ------------------------------------------------------------------
# status machine (E5)
# ------------------------------------------------------------------


def test_floor_status_machine_and_active_since(client: TestClient, clean_database: None) -> None:
    user_id, account, _ = _setup(client)
    rule = create_rule(client, user_id, floor_payload(account["id"]))

    assert action(client, user_id, rule["id"], "pause").status_code == 409  # draft -> paused not allowed
    assert action(client, user_id, rule["id"], "disable").status_code == 409
    enabled = action(client, user_id, rule["id"], "enable")
    assert enabled.status_code == 200 and enabled.json()["status"] == "enabled"
    first_active_since = enabled.json()["active_since"]
    assert first_active_since is not None and enabled.json()["version"] == 1  # status never bumps version
    assert action(client, user_id, rule["id"], "enable").status_code == 409  # already enabled

    paused = action(client, user_id, rule["id"], "pause").json()
    assert paused["status"] == "paused" and paused["active_since"] == first_active_since
    assert action(client, user_id, rule["id"], "pause").status_code == 409
    re_enabled = action(client, user_id, rule["id"], "enable").json()
    assert re_enabled["active_since"] > first_active_since  # reset on every enable

    disabled = action(client, user_id, rule["id"], "disable").json()
    assert disabled["status"] == "disabled"
    assert action(client, user_id, rule["id"], "disable").status_code == 409
    assert action(client, user_id, rule["id"], "pause").status_code == 409
    assert action(client, user_id, rule["id"], "enable").json()["active_since"] > re_enabled["active_since"]
    assert action(client, user_id, rule["id"], "disable").json()["version"] == 1
    assert action(client, user_id, rule["id"], "bogus").status_code in (404, 405)


def test_paused_floor_can_be_disabled(client: TestClient, clean_database: None) -> None:
    user_id, account, _ = _setup(client)
    rule = create_rule(client, user_id, floor_payload(account["id"]))
    action(client, user_id, rule["id"], "enable")
    action(client, user_id, rule["id"], "pause")

    assert action(client, user_id, rule["id"], "disable").json()["status"] == "disabled"


def test_confirm_allocation_and_alert_rules_cannot_be_enabled_before_their_stages(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, goal = _setup(client)
    budget = create_budget(client, user_id)
    rules = [
        create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]], execution_mode="CONFIRM")),
        create_rule(client, user_id, overcommitment_payload(account["id"])),
        create_rule(client, user_id, budget_alert_payload(budget["id"])),
    ]

    for rule in rules:
        response = action(client, user_id, rule["id"], "enable")
        assert response.status_code == 409
        assert action(client, user_id, rule["id"], "pause").status_code == 409
        assert action(client, user_id, rule["id"], "disable").status_code == 409
        body = get_rule(client, user_id, rule["id"]).json()
        assert body["status"] == "draft" and body["active_since"] is None


# ------------------------------------------------------------------
# delete
# ------------------------------------------------------------------


def test_delete_follows_the_state_machine_and_cascades_targets(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client)
    allocation = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))
    floor = create_rule(client, user_id, floor_payload(account["id"]))

    assert delete_rule(client, user_id, allocation["id"]).status_code == 204  # draft
    assert _count("SELECT count(*) FROM financial_rule_goal_targets") == 0
    assert get_rule(client, user_id, allocation["id"]).status_code == 404

    action(client, user_id, floor["id"], "enable")
    assert delete_rule(client, user_id, floor["id"]).status_code == 409  # enabled
    action(client, user_id, floor["id"], "pause")
    assert delete_rule(client, user_id, floor["id"]).status_code == 409  # paused
    action(client, user_id, floor["id"], "disable")
    assert delete_rule(client, user_id, floor["id"]).status_code == 204  # disabled
    assert delete_rule(client, user_id, floor["id"]).status_code == 404
    assert _count("SELECT count(*) FROM goals WHERE user_id = :u", u=user_id) == 1  # goals untouched


def test_rules_never_create_money_rows_or_events(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _setup(client)
    tables = ("goal_transactions", "account_transactions", "account_transfers", "income", "expenses", "financial_events")
    before = {t: _count(f"SELECT count(*) FROM {t}") for t in tables}

    floor = create_rule(client, user_id, floor_payload(account["id"]))
    action(client, user_id, floor["id"], "enable")
    patch_rule(client, user_id, floor["id"], floor_amount="5.00")
    action(client, user_id, floor["id"], "pause")
    action(client, user_id, floor["id"], "disable")
    create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))

    assert {t: _count(f"SELECT count(*) FROM {t}") for t in tables} == before
    assert Decimal(client.get("/api/v1/accounts", headers=auth_headers(user_id)).json()[0]["current_balance"]) == Decimal("0.00")


def test_future_stage_endpoints_do_not_exist(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    for method, path in (
        ("post", f"{RULES_URL}/{uuid4()}/preview"),
        ("get", "/api/v1/rule-proposals"), ("get", "/api/v1/rule-alerts"),
    ):
        response = getattr(client, method)(path, headers=auth_headers(user_id))
        assert response.status_code in (404, 405, 422), (method, path, response.status_code)
