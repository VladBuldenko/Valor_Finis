from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database_session import engine
from tests.helpers import auth_headers
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
    floor_payload,
)

# VF-020E7 AUTO execution tests: real PostgreSQL through the API. Expected
# values are independent literals (§24 scenario matrix, §10.7 examples).


def _reserve(client: TestClient, user_id: str, goal_id: str, account_id: str, amount: str) -> None:
    response = client.post(
        f"/api/v1/goals/{goal_id}/transactions",
        headers=auth_headers(user_id),
        json={
            "type": "contribution", "amount": amount, "account_id": account_id,
            "client_request_id": str(uuid4()),
        },
    )
    assert response.status_code == 201, response.text


def _enabled_floor(client: TestClient, user_id: str, account_id: str, amount: str) -> None:
    rule = create_rule(client, user_id, floor_payload(account_id, amount))
    assert action(client, user_id, rule["id"], "enable").status_code == 200


def _example_a(client: TestClient, user_id: str, floor: str = "1000.00", **rule_overrides: Any):
    """§10.7 setup: CHK 2,000 + salary 3,000 later; 500 already reserved for G1."""
    account = funded_account(client, user_id, opening="2000.00")
    g1 = goal_with_target(client, user_id, "G1", 3000)
    g2 = goal_with_target(client, user_id, "G2", 5000)
    g3 = goal_with_target(client, user_id, "G3", 1000)
    _reserve(client, user_id, g1["id"], account["id"], "500.00")
    _enabled_floor(client, user_id, account["id"], floor)
    rule = enabled_rule(
        client, user_id, account["id"], [g1["id"], g2["id"], g3["id"]],
        policy="PERCENT_OF_INCOME_WATERFALL", percent="20.00",
        targets=[
            {"goal_id": g1["id"], "amount_or_cap": "300.00"},
            {"goal_id": g2["id"], "amount_or_cap": "200.00"},
            {"goal_id": g3["id"]},
        ],
        **rule_overrides,
    )
    return account, (g1, g2, g3), rule


def _items(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["goal_id"]: item for item in body["items"]}


# ------------------------------------------------------------------
# Scenarios S16 / S18 / S19 / S25 (§24, §10.7)
# ------------------------------------------------------------------


def test_s16_percent_waterfall_example_a(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account, (g1, g2, g3), _ = _example_a(client, user_id)

    post_income(client, user_id, "3000.00", account["id"])
    summary = evaluate(client, user_id).json()

    assert summary["processed"] == 1 and summary["outcomes"] == {"executed": 1}

    execution = executions(client, user_id)["items"][0]
    by_goal = _items(execution)

    assert execution["status"] == "executed" and execution["reason_code"] is None
    assert by_goal[g1["id"]]["applied_amount"] == "300.00"
    assert by_goal[g2["id"]]["applied_amount"] == "200.00"
    assert by_goal[g3["id"]]["applied_amount"] == "100.00"
    # Capacity snapshot of the moment the rule ran: reservable 3,500 + floor 1,000.
    assert (execution["capacity_reservable"], execution["capacity_floor"], execution["capacity_holds"]) == (
        "4500.00", "1000.00", "0.00",
    )

    after = account_view(client, user_id, account["id"])
    assert after["reserved_amount"] == "1100.00" and after["unallocated_amount"] == "3900.00"
    assert after["balance_as_of_today"] == "5000.00"  # reservations never move money
    assert [a["code"] for a in execution["audit"]] == ["applied"]


def test_s18_floor_makes_the_rule_skip_and_partial_allocates_to_capacity(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account, (g1, g2, g3), _ = _example_a(client, user_id, floor="4200.00")

    post_income(client, user_id, "3000.00", account["id"])
    evaluate(client, user_id)

    execution = executions(client, user_id)["items"][0]
    assert (execution["status"], execution["reason_code"]) == ("skipped", "insufficient_capacity")
    # The plan is kept for explanation, but nothing was applied or written.
    assert [item["planned_amount"] for item in execution["items"]] == ["300.00", "200.00", "100.00"]
    assert all(item["applied_amount"] is None and item["goal_transaction_id"] is None for item in execution["items"])
    assert account_view(client, user_id, account["id"])["reserved_amount"] == "500.00"
    assert scalar(
        "SELECT count(*) FROM goal_transactions WHERE rule_execution_id IS NOT NULL"
    ) == 0

    # The same scenario with allow_partial: capacity 300 -> G1 300, G2/G3 nothing.
    other = str(uuid4())
    account2, (h1, h2, h3), _ = _example_a(client, other, floor="4200.00", allow_partial=True)
    post_income(client, other, "3000.00", account2["id"])
    evaluate(client, other)

    partial = executions(client, other)["items"][0]
    by_goal = _items(partial)
    assert partial["status"] == "executed_partial"
    assert by_goal[h1["id"]]["applied_amount"] == "300.00"
    assert by_goal[h2["id"]]["applied_amount"] is None and by_goal[h2["id"]]["goal_transaction_id"] is None
    assert by_goal[h2["id"]]["planned_amount"] == "200.00"
    assert [a["code"] for a in partial["audit"]] == ["applied_partial"]


def test_s19_percentage_rounds_down_to_cents_and_leaves_the_remainder(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G1", 3000)
    enabled_rule(
        client, user_id, account["id"], [goal["id"]], policy="PERCENT_OF_INCOME_WATERFALL",
        percent="7.00",
    )

    post_income(client, user_id, "3333.33", account["id"])
    evaluate(client, user_id)

    item = executions(client, user_id)["items"][0]["items"][0]
    assert item["planned_amount"] == "233.33" and item["applied_amount"] == "233.33"


def test_s25_competing_rules_higher_order_wins_and_partial_takes_the_rest(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    # RS 600: opening 600 and no income account link needed for the capacity.
    account = funded_account(client, user_id, opening="600.00")
    g1 = goal_with_target(client, user_id, "G1", 3000)
    g3 = goal_with_target(client, user_id, "G3", 1000)
    r1 = enabled_rule(
        client, user_id, account["id"], [g1["id"]],
        targets=[{"goal_id": g1["id"], "amount_or_cap": "500.00"}], name="R1", execution_order=1,
    )
    r2 = enabled_rule(
        client, user_id, account["id"], [g3["id"]],
        targets=[{"goal_id": g3["id"], "amount_or_cap": "400.00"}], name="R2", execution_order=2,
    )

    # An Income of 0.01 on the account is enough to trigger both rules.
    post_income(client, user_id, "0.01", account["id"])
    evaluate(client, user_id)

    by_rule = {row["rule_id"]: row for row in executions(client, user_id)["items"]}
    assert by_rule[r1["id"]]["status"] == "executed"
    assert (by_rule[r2["id"]]["status"], by_rule[r2["id"]]["reason_code"]) == ("skipped", "insufficient_capacity")
    # R2 saw the capacity R1 already consumed: 600.01 - 500.00.
    assert by_rule[r2["id"]]["capacity_reservable"] == "100.01"

    # With allow_partial on R2 the remaining 100.01 is allocated.
    user2 = str(uuid4())
    account2 = funded_account(client, user2, opening="600.00")
    h1 = goal_with_target(client, user2, "G1", 3000)
    h3 = goal_with_target(client, user2, "G3", 1000)
    enabled_rule(client, user2, account2["id"], [h1["id"]],
                 targets=[{"goal_id": h1["id"], "amount_or_cap": "500.00"}], execution_order=1)
    r2b = enabled_rule(client, user2, account2["id"], [h3["id"]], allow_partial=True,
                       targets=[{"goal_id": h3["id"], "amount_or_cap": "400.00"}], execution_order=2)
    post_income(client, user2, "0.01", account2["id"])
    evaluate(client, user2)
    second = {row["rule_id"]: row for row in executions(client, user2)["items"]}[r2b["id"]]
    assert second["status"] == "executed_partial"
    assert second["items"][0]["applied_amount"] == "100.01"


def test_rule_order_ties_follow_created_at_then_id(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="300.00")
    g1 = goal_with_target(client, user_id, "G1", 3000)
    g2 = goal_with_target(client, user_id, "G2", 3000)
    first = enabled_rule(client, user_id, account["id"], [g1["id"]],
                         targets=[{"goal_id": g1["id"], "amount_or_cap": "250.00"}], execution_order=1)
    second = enabled_rule(client, user_id, account["id"], [g2["id"]],
                          targets=[{"goal_id": g2["id"], "amount_or_cap": "250.00"}], execution_order=1)

    post_income(client, user_id, "10.00", account["id"])
    evaluate(client, user_id)

    by_rule = {row["rule_id"]: row["status"] for row in executions(client, user_id)["items"]}
    assert by_rule == {first["id"]: "executed", second["id"]: "skipped"}


# ------------------------------------------------------------------
# Fixed policy, caps, Goal priority
# ------------------------------------------------------------------


def test_fixed_policy_follows_current_goal_priority_not_target_position(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="250.00")
    g1 = goal_with_target(client, user_id, "G1", 3000)  # rank 1
    g2 = goal_with_target(client, user_id, "G2", 3000)  # rank 2
    # Configuration position puts G2 first, but the Goal priority puts G1 first.
    rule = enabled_rule(
        client, user_id, account["id"], [g2["id"], g1["id"]], allow_partial=True,
        targets=[
            {"goal_id": g2["id"], "amount_or_cap": "200.00", "position": 0},
            {"goal_id": g1["id"], "amount_or_cap": "200.00", "position": 1},
        ],
    )

    post_income(client, user_id, "10.00", account["id"])
    evaluate(client, user_id)

    by_goal = _items(executions(client, user_id)["items"][0])
    assert by_goal[g1["id"]]["applied_amount"] == "200.00"
    assert by_goal[g2["id"]]["applied_amount"] == "60.00"
    assert rule["status"] == "enabled"


def test_reordering_goals_changes_the_next_execution_only(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="250.00")
    g1 = goal_with_target(client, user_id, "G1", 3000)
    g2 = goal_with_target(client, user_id, "G2", 3000)
    enabled_rule(
        client, user_id, account["id"], [g1["id"], g2["id"]], allow_partial=True,
        targets=[
            {"goal_id": g1["id"], "amount_or_cap": "200.00"},
            {"goal_id": g2["id"], "amount_or_cap": "200.00"},
        ],
    )
    reorder = client.put(
        "/api/v1/goals/priorities", headers=auth_headers(user_id),
        json={"goal_ids": [g2["id"], g1["id"]]},
    )
    assert reorder.status_code == 200, reorder.text

    post_income(client, user_id, "10.00", account["id"])
    evaluate(client, user_id)

    by_goal = _items(executions(client, user_id)["items"][0])
    assert by_goal[g2["id"]]["applied_amount"] == "200.00"
    assert by_goal[g1["id"]]["applied_amount"] == "60.00"


def test_cap_at_target_limits_to_the_remaining_target_and_completed_goals_are_allowed(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    near = goal_with_target(client, user_id, "Near", 1000)
    full = goal_with_target(client, user_id, "Full", 100)
    _reserve(client, user_id, near["id"], account["id"], "900.00")
    _reserve(client, user_id, full["id"], account["id"], "100.00")
    assert client.patch(
        f"/api/v1/goals/{full['id']}", headers=auth_headers(user_id), json={"status": "completed"},
    ).status_code == 200
    enabled_rule(
        client, user_id, account["id"], [near["id"], full["id"]],
        targets=[
            {"goal_id": near["id"], "amount_or_cap": "300.00"},
            {"goal_id": full["id"], "amount_or_cap": "50.00"},
        ],
    )

    post_income(client, user_id, "10.00", account["id"])
    evaluate(client, user_id)

    execution = executions(client, user_id)["items"][0]
    by_goal = _items(execution)
    assert execution["status"] == "executed"
    # "Near" only needs 100 more; "Full" has nothing left so it gets no item.
    assert by_goal[near["id"]]["planned_amount"] == "100.00"
    assert full["id"] not in by_goal


def test_without_cap_at_target_the_goal_can_exceed_its_target(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "Small", 100)
    enabled_rule(
        client, user_id, account["id"], [goal["id"]], cap_at_target=False,
        targets=[{"goal_id": goal["id"], "amount_or_cap": "300.00"}],
    )

    post_income(client, user_id, "10.00", account["id"])
    evaluate(client, user_id)

    assert executions(client, user_id)["items"][0]["items"][0]["applied_amount"] == "300.00"


def test_everything_already_at_target_is_skipped_with_a_stable_reason(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "Done", 100)
    _reserve(client, user_id, goal["id"], account["id"], "100.00")
    enabled_rule(client, user_id, account["id"], [goal["id"]])

    post_income(client, user_id, "10.00", account["id"])
    evaluate(client, user_id)

    execution = executions(client, user_id)["items"][0]
    assert (execution["status"], execution["reason_code"]) == ("skipped", "nothing_to_allocate")


# ------------------------------------------------------------------
# Blocked outcomes (E8/E9, P37)
# ------------------------------------------------------------------


def test_archived_target_goal_blocks_without_pausing_the_rule(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    rule = enabled_rule(client, user_id, account["id"], [goal["id"]])
    assert client.patch(
        f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id), json={"status": "archived"},
    ).status_code == 200

    post_income(client, user_id, "10.00", account["id"])
    evaluate(client, user_id)

    execution = executions(client, user_id)["items"][0]
    assert (execution["status"], execution["reason_code"]) == ("blocked", "target_goal_archived")
    assert execution["items"] == [] and [a["code"] for a in execution["audit"]] == ["blocked"]
    assert client.get(f"/api/v1/financial-rules/{rule['id']}", headers=auth_headers(user_id)).json()["status"] == "enabled"


def test_archived_source_account_blocks(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]])
    income = post_income(client, user_id, "10.00", account["id"])
    assert income["id"]
    archived = client.patch(
        f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id), json={"status": "archived"},
    )
    assert archived.status_code == 200, archived.text

    evaluate(client, user_id)

    execution = executions(client, user_id)["items"][0]
    assert (execution["status"], execution["reason_code"]) == ("blocked", "source_account_archived")


def test_currency_mismatch_in_the_event_snapshot_blocks(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]])
    post_income(client, user_id, "10.00", account["id"])
    with engine.begin() as connection:
        connection.execute(text("UPDATE financial_events SET snap_currency = 'USD'"))

    evaluate(client, user_id)

    execution = executions(client, user_id)["items"][0]
    assert (execution["status"], execution["reason_code"]) == ("blocked", "currency_mismatch")


# ------------------------------------------------------------------
# Item <-> GoalTransaction linkage and money invariants
# ------------------------------------------------------------------


def test_items_link_real_transactions_and_nothing_else_is_created(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account, (g1, g2, g3), _ = _example_a(client, user_id)
    post_income(client, user_id, "3000.00", account["id"])
    ledger_before = scalar("SELECT count(*) FROM account_transactions")
    income_before = scalar("SELECT count(*) FROM income")
    expenses_before = scalar("SELECT count(*) FROM expenses")

    evaluate(client, user_id)

    assert scalar("SELECT count(*) FROM account_transactions") == ledger_before
    assert scalar("SELECT count(*) FROM income") == income_before
    assert scalar("SELECT count(*) FROM expenses") == expenses_before

    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT i.applied_amount, t.amount, t.type, t.account_id, i.account_id, t.goal_id, i.goal_id, "
            "t.client_request_id, t.rule_execution_id, i.execution_id, t.effective_date, t.currency, "
            "t.user_id, i.user_id "
            "FROM rule_execution_items i JOIN goal_transactions t ON t.id = i.goal_transaction_id"
        )).all()

    assert len(rows) == 3
    for row in rows:
        assert row[0] == row[1] and row[2] == "contribution"
        assert row[3] == row[4] and row[5] == row[6]
        assert row[7] is None and row[8] == row[9]
        assert row[10] == date.today() and row[11] == "EUR" and row[12] == row[13]

    # Goal balances never go negative and each Goal got exactly its allocation.
    assert goal_view(client, user_id, g1["id"])["current_amount"] == "800.00"
    assert goal_view(client, user_id, g2["id"])["current_amount"] == "200.00"
    assert goal_view(client, user_id, g3["id"])["current_amount"] == "100.00"


def test_rule_generated_rows_use_decimal_strings_and_two_places(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="100.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]], policy="PERCENT_OF_INCOME_WATERFALL", percent="12.50")

    post_income(client, user_id, "0.07", account["id"])
    evaluate(client, user_id)

    item = executions(client, user_id)["items"][0]
    # 0.07 * 12.5% = 0.00875 -> rounded DOWN to 0.00 -> nothing to allocate.
    assert (item["status"], item["reason_code"]) == ("skipped", "nothing_to_allocate")


# ------------------------------------------------------------------
# Eligibility (E2, E4-E7), provenance and activation
# ------------------------------------------------------------------


def test_income_not_linked_to_the_rule_account_is_not_eligible(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    other = funded_account(client, user_id, opening="10.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]])

    post_income(client, user_id, "10.00", other["id"])
    post_income(client, user_id, "10.00", None)
    evaluate(client, user_id)

    assert executions(client, user_id)["total"] == 0
    assert scalar(
        "SELECT count(*) FROM financial_events WHERE status = 'processed' "
        "AND outcome_summary->'not_eligible'->>'income_account_mismatch' = '1'"
    ) == 2


def test_income_source_outside_the_rule_sources_is_not_eligible(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]])

    post_income(client, user_id, "10.00", account["id"], source="refund")  # refund excluded by default
    evaluate(client, user_id)

    assert executions(client, user_id)["total"] == 0


def test_s37_historical_income_is_never_executed(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]])

    post_income(client, user_id, "10.00", account["id"], received_at=date.today() - timedelta(days=8))
    evaluate(client, user_id)

    assert executions(client, user_id)["total"] == 0
    assert scalar(
        "SELECT outcome_summary->'not_eligible'->>'provenance_not_live' FROM financial_events"
    ) == "1"


def test_s42_seven_day_boundary_is_inclusive(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]], effective_from=(date.today() - timedelta(days=30)).isoformat())

    post_income(client, user_id, "10.00", account["id"], received_at=date.today() - timedelta(days=7))
    post_income(client, user_id, "10.00", account["id"], received_at=date.today() - timedelta(days=8))
    evaluate(client, user_id)

    assert executions(client, user_id)["total"] == 1


def test_s23_effective_from_is_a_separate_check(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]], effective_from=(date.today() - timedelta(days=2)).isoformat())

    post_income(client, user_id, "10.00", account["id"], received_at=date.today() - timedelta(days=1))  # eligible
    post_income(client, user_id, "10.00", account["id"], received_at=date.today() - timedelta(days=3))  # live but before effective_from
    evaluate(client, user_id)

    assert executions(client, user_id)["total"] == 1
    assert scalar(
        "SELECT count(*) FROM financial_events WHERE outcome_summary->'not_eligible'->>'received_before_effective_from' = '1'"
    ) == 1


def test_income_created_before_the_rule_was_enabled_is_never_executed(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    rule = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))
    post_income(client, user_id, "10.00", account["id"])  # before activation
    assert action(client, user_id, rule["id"], "enable").status_code == 200

    evaluate(client, user_id)

    assert executions(client, user_id)["total"] == 0


def test_pause_and_re_enable_does_not_pick_up_income_from_the_paused_period(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    rule = enabled_rule(client, user_id, account["id"], [goal["id"]])
    assert action(client, user_id, rule["id"], "pause").status_code == 200

    post_income(client, user_id, "10.00", account["id"])  # while paused
    assert action(client, user_id, rule["id"], "enable").status_code == 200
    evaluate(client, user_id)

    assert executions(client, user_id)["total"] == 0


def test_pre_e3_income_without_a_creation_event_is_never_eligible(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]])
    income = post_income(client, user_id, "10.00", account["id"])
    with engine.begin() as connection:  # simulate "no creation event ever existed"
        connection.execute(text("DELETE FROM financial_events WHERE event_type = 'income.created'"))
    patched = client.patch(
        f"/api/v1/income/{income['id']}", headers=auth_headers(user_id), json={"amount": "20.00"},
    )
    assert patched.status_code == 200, patched.text

    evaluate(client, user_id)

    assert executions(client, user_id)["total"] == 0
    assert scalar(
        "SELECT outcome_summary->'not_eligible'->>'no_creation_event' FROM financial_events "
        "WHERE event_type = 'income.updated'"
    ) == "1"


def test_future_dated_income_is_deferred_until_its_date(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]])
    post_income(client, user_id, "10.00", account["id"], received_at=date.today() + timedelta(days=3))

    summary = evaluate(client, user_id).json()

    assert summary["processed"] == 0 and summary["blocked"] is False
    assert executions(client, user_id)["total"] == 0
    assert scalar("SELECT status FROM financial_events") == "pending"


# ------------------------------------------------------------------
# Exactly once, isolation, enable rules
# ------------------------------------------------------------------


def test_s24_s30_duplicate_delivery_has_exactly_one_financial_effect(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account, (g1, _g2, _g3), _ = _example_a(client, user_id)
    post_income(client, user_id, "3000.00", account["id"])
    evaluate(client, user_id)
    first = executions(client, user_id)["items"][0]["id"]

    for _ in range(3):
        with engine.begin() as connection:  # simulate redelivery of the same event
            connection.execute(text(
                "UPDATE financial_events SET status = 'pending', processed_at = NULL, outcome_summary = NULL"
            ))
        assert evaluate(client, user_id).json()["processed"] == 1

    body = executions(client, user_id)
    assert body["total"] == 1 and body["items"][0]["id"] == first
    assert scalar("SELECT count(*) FROM goal_transactions WHERE rule_execution_id IS NOT NULL") == 3
    assert scalar("SELECT outcome_summary->>'replayed' FROM financial_events") == "1"
    assert account_view(client, user_id, account["id"])["reserved_amount"] == "1100.00"


def test_evaluate_and_executions_are_scoped_to_the_caller(client: TestClient, clean_database: None) -> None:
    owner, other = str(uuid4()), str(uuid4())
    account = funded_account(client, owner, opening="2000.00")
    goal = goal_with_target(client, owner, "G", 3000)
    enabled_rule(client, owner, account["id"], [goal["id"]])
    post_income(client, owner, "10.00", account["id"])

    foreign = evaluate(client, other).json()
    assert foreign["processed"] == 0
    assert scalar("SELECT status FROM financial_events") == "pending"
    assert executions(client, other)["total"] == 0

    assert evaluate(client, owner).json()["processed"] == 1
    assert executions(client, other)["total"] == 0
    assert executions(client, owner)["total"] == 1


def test_evaluate_requires_authentication_and_bounds_the_limit(client: TestClient, clean_database: None) -> None:
    assert client.post("/api/v1/financial-rules/evaluate").status_code == 401
    assert client.get("/api/v1/rule-executions").status_code == 401
    user_id = str(uuid4())
    assert evaluate(client, user_id, limit=0).status_code == 422
    assert evaluate(client, user_id, limit=101).status_code == 422


def test_evaluate_drains_at_most_limit_events(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]])
    for _ in range(3):
        post_income(client, user_id, "10.00", account["id"])

    assert evaluate(client, user_id, limit=2).json()["processed"] == 2
    assert evaluate(client, user_id, limit=2).json()["processed"] == 1
    assert evaluate(client, user_id).json()["processed"] == 0


def test_two_incomes_use_the_capacity_left_by_the_first(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="300.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    enabled_rule(client, user_id, account["id"], [goal["id"]], targets=[{"goal_id": goal["id"], "amount_or_cap": "200.00"}])
    post_income(client, user_id, "10.00", account["id"])
    post_income(client, user_id, "10.00", account["id"])

    evaluate(client, user_id)

    statuses = [row["status"] for row in reversed(executions(client, user_id)["items"])]
    assert statuses == ["executed", "skipped"]  # 310 - 200 = 110 < 200


def test_enable_rules_auto_confirm_and_alerts(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)

    confirm = create_rule(
        client, user_id, allocation_payload(account["id"], [goal["id"]], execution_mode="CONFIRM"),
    )
    assert action(client, user_id, confirm["id"], "enable").status_code == 200  # CONFIRM ships with E8

    auto = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]], name="Auto"))
    enabled = action(client, user_id, auto["id"], "enable").json()
    assert enabled["status"] == "enabled" and enabled["active_since"] is not None
    assert enabled["effective_from"] == date.today().isoformat()

    paused = action(client, user_id, auto["id"], "pause").json()
    assert paused["status"] == "paused"
    again = action(client, user_id, auto["id"], "enable").json()
    assert again["effective_from"] == date.today().isoformat() and again["version"] == enabled["version"]

    alert = create_rule(client, user_id, {"rule_type": "OVERCOMMITMENT_ALERT", "name": "A", "source_account_id": account["id"]})
    assert action(client, user_id, alert["id"], "enable").status_code == 200  # E9B, schema present


def test_enable_revalidates_an_archived_target_goal(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    rule = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]]))
    assert client.patch(
        f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id), json={"status": "archived"},
    ).status_code == 200

    assert action(client, user_id, rule["id"], "enable").status_code == 409


def test_executions_endpoint_filters_and_paginates(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="300.00")
    goal = goal_with_target(client, user_id, "G", 3000)
    rule = enabled_rule(client, user_id, account["id"], [goal["id"]], targets=[{"goal_id": goal["id"], "amount_or_cap": "200.00"}])
    post_income(client, user_id, "10.00", account["id"])
    post_income(client, user_id, "10.00", account["id"])
    evaluate(client, user_id)

    assert executions(client, user_id, status="executed")["total"] == 1
    assert executions(client, user_id, status="skipped")["total"] == 1
    assert executions(client, user_id, rule_id=rule["id"], limit=1)["items"].__len__() == 1
    assert executions(client, user_id, limit=1, offset=1)["total"] == 2
    assert client.get("/api/v1/rule-executions?status=bogus", headers=auth_headers(user_id)).status_code == 422
    assert Decimal(executions(client, user_id)["items"][0]["source_amount"]) == Decimal("10.00")
