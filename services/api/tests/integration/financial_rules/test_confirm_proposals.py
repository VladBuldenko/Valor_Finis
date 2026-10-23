from datetime import date
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

import pytest
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
    patch_rule,
)
from tests.integration.financial_rules.test_auto_execution import _example_a, _reserve

# VF-020E8 CONFIRM tests: proposals, soft holds, hold order, confirmation,
# stale / reject / expiry, corrections and lifecycle. Real PostgreSQL through
# the API; expected values are independent literals from the scenario matrix.

PROPOSALS_URL = "/api/v1/rule-proposals"


def _proposals(client: TestClient, user_id: str, **params: Any) -> dict[str, Any]:
    response = client.get(PROPOSALS_URL, headers=auth_headers(user_id), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _confirm(client: TestClient, user_id: str, proposal_id: str):
    return client.post(f"{PROPOSALS_URL}/{proposal_id}/confirm", headers=auth_headers(user_id))


def _reject(client: TestClient, user_id: str, proposal_id: str):
    return client.post(f"{PROPOSALS_URL}/{proposal_id}/reject", headers=auth_headers(user_id))


def _proposal(client: TestClient, user_id: str, proposal_id: str) -> dict[str, Any]:
    response = client.get(f"{PROPOSALS_URL}/{proposal_id}", headers=auth_headers(user_id))
    assert response.status_code == 200, response.text
    return response.json()


def _tx_count(user_id: str) -> int:
    return scalar(
        "SELECT count(*) FROM goal_transactions WHERE user_id = :u AND rule_execution_id IS NOT NULL", u=user_id,
    )


def _debit(client: TestClient, user_id: str, account_id: str, amount: str) -> None:
    response = client.post(
        f"/api/v1/accounts/{account_id}/transactions", headers=auth_headers(user_id),
        json={"direction": "debit", "amount": amount, "transaction_date": date.today().isoformat()},
    )
    assert response.status_code == 201, response.text


def _rs_setup(client: TestClient, rules: list[tuple[str, int, str, str]], opening: str = "600.00", floor: Optional[str] = None):
    """RS = opening + 0.01 once the trigger income is posted. rules = (name, order, mode, amount)."""
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening=opening)
    if floor is not None:
        from tests.integration.financial_rules.rule_helpers import floor_payload
        floor_rule = create_rule(client, user_id, floor_payload(account["id"], floor))
        assert action(client, user_id, floor_rule["id"], "enable").status_code == 200
    created = []
    for index, (name, order, mode, amount) in enumerate(rules):
        goal = goal_with_target(client, user_id, f"G{index + 1}", 5000)
        rule = enabled_rule(
            client, user_id, account["id"], [goal["id"]], name=name, execution_order=order,
            execution_mode=mode, targets=[{"goal_id": goal["id"], "amount_or_cap": amount}],
        )
        created.append((rule, goal))
    post_income(client, user_id, "0.01", account["id"])
    return user_id, account, created


# ------------------------------------------------------------------
# S17: proposal creation writes nothing but the soft hold
# ------------------------------------------------------------------


def test_s17_confirm_rule_creates_a_proposal_with_a_hold_and_no_financial_write(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account, (g1, g2, g3), rule = _example_a(client, user_id, execution_mode="CONFIRM")
    post_income(client, user_id, "3000.00", account["id"])
    ledger_before = scalar("SELECT count(*) FROM account_transactions")
    income_before = scalar("SELECT count(*) FROM income")

    summary = evaluate(client, user_id).json()

    assert summary["outcomes"] == {"awaiting_confirmation": 1}
    body = _proposals(client, user_id)
    assert body["total"] == 1
    proposal = body["items"][0]
    assert proposal["status"] == "awaiting_confirmation" and proposal["partial"] is False
    assert proposal["planned_total"] == "600.00" and proposal["currency"] == "EUR"
    assert [(i["goal_id"], i["planned_amount"]) for i in proposal["items"]] == [
        (g1["id"], "300.00"), (g2["id"], "200.00"), (g3["id"], "100.00"),
    ]
    assert proposal["confirm_capacity"] == "3500.00"  # 4,500 reservable - 1,000 floor - 0 prior holds
    assert proposal["items"][0]["current_amount"] == "500.00" and proposal["items"][0]["expected_amount"] == "800.00"
    assert proposal["hold_sequence"] > 0 and proposal["expires_at"]
    assert _tx_count(user_id) == 0
    assert scalar("SELECT count(*) FROM account_transactions") == ledger_before
    assert scalar("SELECT count(*) FROM income") == income_before

    view = account_view(client, user_id, account["id"])
    assert view["reserved_amount"] == "500.00" and view["balance_as_of_today"] == "5000.00"
    assert view["reservable_amount"] == "4500.00"  # a hold is not reserved money
    assert view["active_rule_holds"] == "600.00" and view["rule_capacity"] == "2900.00"

    execution = executions(client, user_id)["items"][0]
    assert execution["status"] == "awaiting_confirmation" and [a["code"] for a in execution["audit"]] == ["proposed"]
    assert scalar("SELECT expires_at - created_at FROM rule_executions") == scalar("SELECT interval '7 days'")


def test_redelivery_never_creates_a_second_proposal(client: TestClient, clean_database: None) -> None:
    user_id, account, _ = _rs_setup(client, [("R1", 1, "CONFIRM", "100.00")])
    evaluate(client, user_id)
    for _ in range(2):
        with engine.begin() as connection:
            connection.execute(text("UPDATE financial_events SET status = 'pending', processed_at = NULL"))
        evaluate(client, user_id)

    assert _proposals(client, user_id)["total"] == 1
    assert scalar("SELECT count(*) FROM rule_executions") == 1


# ------------------------------------------------------------------
# Confirm
# ------------------------------------------------------------------


def test_confirm_writes_the_planned_transactions_exactly_once(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account, (g1, g2, g3), _ = _example_a(client, user_id, execution_mode="CONFIRM")
    post_income(client, user_id, "3000.00", account["id"])
    evaluate(client, user_id)
    proposal_id = _proposals(client, user_id)["items"][0]["id"]
    sequence = _proposals(client, user_id)["items"][0]["hold_sequence"]

    response = _confirm(client, user_id, proposal_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "executed" and body["hold_sequence"] == sequence
    assert all(item["goal_transaction_id"] and item["applied_amount"] == item["planned_amount"] for item in body["items"])
    assert body["confirm_capacity"] is None
    assert _tx_count(user_id) == 3
    after = account_view(client, user_id, account["id"])
    assert after["reserved_amount"] == "1100.00" and after["unallocated_amount"] == "3900.00"
    assert after["active_rule_holds"] == "0.00"  # the hold ended with the confirmation
    assert goal_view(client, user_id, g1["id"])["current_amount"] == "800.00"
    assert [a["code"] for a in executions(client, user_id)["items"][0]["audit"]] == ["proposed", "confirmed", "applied"]
    assert scalar("SELECT status FROM rule_executions") == "executed"

    with engine.connect() as connection:  # provenance: item <-> transaction agree
        rows = connection.execute(text(
            "SELECT i.applied_amount, t.amount, t.type, t.account_id, i.account_id, t.goal_id, i.goal_id, "
            "t.client_request_id, t.rule_execution_id, i.execution_id, t.user_id, i.user_id, t.effective_date "
            "FROM rule_execution_items i JOIN goal_transactions t ON t.id = i.goal_transaction_id")).all()
    assert len(rows) == 3
    for row in rows:
        assert row[0] == row[1] and row[2] == "contribution" and row[3] == row[4] and row[5] == row[6]
        assert row[7] is None and row[8] == row[9] and row[10] == row[11] and row[12] == date.today()

    for _ in range(2):  # repeated confirm / reject return the stored state, no second effect
        assert _confirm(client, user_id, proposal_id).json()["status"] == "executed"
        assert _reject(client, user_id, proposal_id).json()["status"] == "executed"
    assert _tx_count(user_id) == 3


def test_s38_confirm_capacity_excludes_the_own_hold_and_the_auto_rule_sees_the_hold(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, ((r1, g1), (r2, g3)) = _rs_setup(
        client, [("R1", 1, "CONFIRM", "500.00"), ("R2", 2, "AUTO", "400.00")],
    )

    evaluate(client, user_id)

    by_rule = {row["rule_id"]: row for row in executions(client, user_id)["items"]}
    assert by_rule[r1["id"]]["status"] == "awaiting_confirmation"
    assert (by_rule[r2["id"]]["status"], by_rule[r2["id"]]["reason_code"]) == ("skipped", "insufficient_capacity")
    assert by_rule[r2["id"]]["capacity_holds"] == "500.00"  # R2 saw the new hold at once
    proposal = _proposals(client, user_id)["items"][0]
    assert proposal["confirm_capacity"] == "600.01"  # own hold excluded

    assert _confirm(client, user_id, proposal["id"]).json()["status"] == "executed"
    assert account_view(client, user_id, account["id"])["reserved_amount"] == "500.00"
    assert account_view(client, user_id, account["id"])["active_rule_holds"] == "0.00"


def test_mixed_rules_run_in_one_deterministic_order_not_auto_first(client: TestClient, clean_database: None) -> None:
    user_id, account, ((r1, _), (r2, _), (r3, _)) = _rs_setup(
        client,
        [("A", 1, "AUTO", "100.00"), ("C", 2, "CONFIRM", "300.00"), ("B", 3, "AUTO", "250.00")],
    )

    evaluate(client, user_id)

    by_rule = {row["rule_id"]: row for row in executions(client, user_id)["items"]}
    assert by_rule[r1["id"]]["status"] == "executed"
    assert by_rule[r2["id"]]["status"] == "awaiting_confirmation"
    # B runs AFTER the proposal: 600.01 - 100 (A) - 300 (hold) = 200.01 < 250.
    assert (by_rule[r3["id"]]["status"], by_rule[r3["id"]]["reason_code"]) == ("skipped", "insufficient_capacity")
    assert by_rule[r3["id"]]["capacity_reservable"] == "500.01" and by_rule[r3["id"]]["capacity_holds"] == "300.00"


def test_holds_never_block_manual_operations_and_s39_makes_the_proposal_stale(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, ((r1, g1),) = _rs_setup(client, [("R1", 1, "CONFIRM", "500.00")])
    evaluate(client, user_id)
    proposal = _proposals(client, user_id)["items"][0]
    other_goal = goal_with_target(client, user_id, "Manual", 5000)

    _reserve(client, user_id, other_goal["id"], account["id"], "300.00")  # allowed despite the 500 hold

    assert account_view(client, user_id, account["id"])["reservable_amount"] == "300.01"
    response = _confirm(client, user_id, proposal["id"])
    assert response.status_code == 409
    stored = _proposal(client, user_id, proposal["id"])
    assert (stored["status"], stored["reason_code"]) == ("cancelled", "stale")  # committed despite the 409
    assert _tx_count(user_id) == 0
    assert account_view(client, user_id, account["id"])["active_rule_holds"] == "0.00"
    assert [a["code"] for a in executions(client, user_id)["items"][0]["audit"]] == ["proposed", "cancelled"]
    again = _confirm(client, user_id, proposal["id"])  # terminal: stored state, no second effect
    assert again.status_code == 200 and again.json()["status"] == "cancelled"


def test_s26_s35_an_expense_after_the_proposal_makes_confirmation_stale(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, ((r1, g1),) = _rs_setup(client, [("R1", 1, "CONFIRM", "500.00")])
    evaluate(client, user_id)
    proposal = _proposals(client, user_id)["items"][0]

    _debit(client, user_id, account["id"], "550.00")  # RS 600.01 -> 50.01

    assert _confirm(client, user_id, proposal["id"]).status_code == 409
    assert _proposal(client, user_id, proposal["id"])["reason_code"] == "stale"
    assert _tx_count(user_id) == 0


def test_s26_the_floor_applies_to_confirmation(client: TestClient, clean_database: None) -> None:
    user_id, account, ((r1, g1),) = _rs_setup(client, [("R1", 1, "CONFIRM", "100.00")], floor="400.00")
    evaluate(client, user_id)
    proposal = _proposals(client, user_id)["items"][0]
    assert proposal["confirm_capacity"] == "200.01"  # 600.01 - 400

    _debit(client, user_id, account["id"], "150.00")  # 450.01 - 400 = 50.01 < 100

    assert _confirm(client, user_id, proposal["id"]).status_code == 409


def test_s44_a_later_hold_never_defeats_an_earlier_proposal(client: TestClient, clean_database: None) -> None:
    user_id, account, ((rx, gx), (ry, gy)) = _rs_setup(
        client, [("X", 1, "CONFIRM", "500.00"), ("Y", 2, "CONFIRM", "100.00")],
    )
    evaluate(client, user_id)
    by_rule = {p["rule_id"]: p for p in _proposals(client, user_id)["items"]}
    x, y = by_rule[rx["id"]], by_rule[ry["id"]]
    assert x["hold_sequence"] < y["hold_sequence"] and x["status"] == y["status"] == "awaiting_confirmation"

    _debit(client, user_id, account["id"], "80.00")  # RS 600.01 -> 520.01

    refreshed = {p["rule_id"]: p for p in _proposals(client, user_id)["items"]}
    assert refreshed[rx["id"]]["confirm_capacity"] == "520.01"  # Y's later hold does not count (420.01 would defeat X)
    assert refreshed[ry["id"]]["confirm_capacity"] == "20.01"  # X is a prior hold for Y

    assert _confirm(client, user_id, x["id"]).json()["status"] == "executed"
    assert _confirm(client, user_id, y["id"]).status_code == 409  # RS 20.01 < 100
    assert _proposal(client, user_id, y["id"])["reason_code"] == "stale"


def test_hold_sequence_is_permanent_and_ordered_across_terminal_states(client: TestClient, clean_database: None) -> None:
    user_id, account, ((r1, _), (r2, _), (r3, _)) = _rs_setup(
        client, [("A", 1, "CONFIRM", "10.00"), ("B", 2, "CONFIRM", "10.00"), ("C", 3, "CONFIRM", "10.00")],
    )
    evaluate(client, user_id)
    before = {p["rule_id"]: p for p in _proposals(client, user_id)["items"]}
    sequences = [before[r["id"]]["hold_sequence"] for r in (r1, r2, r3)]
    assert sequences == sorted(sequences) and len(set(sequences)) == 3

    assert _confirm(client, user_id, before[r1["id"]]["id"]).status_code == 200
    assert _reject(client, user_id, before[r2["id"]]["id"]).status_code == 200
    with engine.begin() as connection:
        connection.execute(text("UPDATE rule_executions SET expires_at = now() - interval '1 second' WHERE id = :id"),
                           {"id": before[r3["id"]]["id"]})
    assert _proposals(client, user_id)["total"] == 3

    after = {p["rule_id"]: p for p in _proposals(client, user_id)["items"]}
    assert [after[r["id"]]["status"] for r in (r1, r2, r3)] == ["executed", "rejected", "expired"]
    assert [after[r["id"]]["hold_sequence"] for r in (r1, r2, r3)] == sequences
    assert all(after[r["id"]]["expires_at"] == before[r["id"]]["expires_at"] or r["id"] == r3["id"] for r in (r1, r2, r3))


# ------------------------------------------------------------------
# Reject, expiry (S41), partial
# ------------------------------------------------------------------


def test_reject_is_final_and_ends_the_hold(client: TestClient, clean_database: None) -> None:
    user_id, account, ((r1, g1),) = _rs_setup(client, [("R1", 1, "CONFIRM", "500.00")])
    evaluate(client, user_id)
    proposal_id = _proposals(client, user_id)["items"][0]["id"]
    assert account_view(client, user_id, account["id"])["active_rule_holds"] == "500.00"

    rejected = _reject(client, user_id, proposal_id)

    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert account_view(client, user_id, account["id"])["active_rule_holds"] == "0.00"
    assert _tx_count(user_id) == 0
    assert _reject(client, user_id, proposal_id).json()["status"] == "rejected"
    assert _confirm(client, user_id, proposal_id).json()["status"] == "rejected"  # can never be confirmed
    assert _tx_count(user_id) == 0
    audit = executions(client, user_id)["items"][0]["audit"]
    assert [(a["code"], a["actor"]) for a in audit] == [("proposed", "system"), ("rejected", "user")]


def test_s41_expired_proposal_stops_holding_and_cannot_be_confirmed(client: TestClient, clean_database: None) -> None:
    user_id, account, ((r1, g1),) = _rs_setup(client, [("R1", 1, "CONFIRM", "500.00")])
    evaluate(client, user_id)
    proposal_id = _proposals(client, user_id)["items"][0]["id"]
    with engine.begin() as connection:
        connection.execute(text("UPDATE rule_executions SET expires_at = now() + interval '1 hour'"))
    assert account_view(client, user_id, account["id"])["active_rule_holds"] == "500.00"  # still counting before expiry

    with engine.begin() as connection:
        connection.execute(text("UPDATE rule_executions SET expires_at = now() - interval '1 second'"))

    # The hold stops counting even before the stored state is normalized.
    assert scalar("SELECT status FROM rule_executions") == "awaiting_confirmation"
    assert account_view(client, user_id, account["id"])["active_rule_holds"] == "0.00"

    response = _confirm(client, user_id, proposal_id)
    assert response.status_code == 200 and response.json()["status"] == "expired"
    assert _tx_count(user_id) == 0
    assert _confirm(client, user_id, proposal_id).json()["status"] == "expired"
    assert scalar("SELECT hold_sequence IS NOT NULL AND expires_at IS NOT NULL FROM rule_executions") is True
    assert [a["code"] for a in executions(client, user_id)["items"][0]["audit"]] == ["proposed", "expired"]


def test_expiry_is_also_applied_lazily_at_event_dispatch(client: TestClient, clean_database: None) -> None:
    user_id, account, ((r1, g1),) = _rs_setup(client, [("R1", 1, "CONFIRM", "100.00")])
    evaluate(client, user_id)
    with engine.begin() as connection:
        connection.execute(text("UPDATE rule_executions SET expires_at = now() - interval '1 second'"))
    post_income(client, user_id, "0.01", account["id"])

    evaluate(client, user_id)

    assert scalar("SELECT count(*) FROM rule_executions WHERE status = 'expired'") == 1


def test_partial_proposal_holds_only_what_fits_and_confirms_as_executed_partial(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="300.00")
    g1 = goal_with_target(client, user_id, "G1", 5000)
    g2 = goal_with_target(client, user_id, "G2", 5000)
    enabled_rule(
        client, user_id, account["id"], [g1["id"], g2["id"]], execution_mode="CONFIRM", allow_partial=True,
        targets=[{"goal_id": g1["id"], "amount_or_cap": "200.00"}, {"goal_id": g2["id"], "amount_or_cap": "200.00"}],
    )
    post_income(client, user_id, "10.00", account["id"])
    evaluate(client, user_id)

    proposal = _proposals(client, user_id)["items"][0]
    assert proposal["partial"] is True and proposal["planned_total"] == "310.00"
    assert [(i["goal_id"], i["planned_amount"]) for i in proposal["items"]] == [(g1["id"], "200.00"), (g2["id"], "110.00")]

    assert _confirm(client, user_id, proposal["id"]).json()["status"] == "executed_partial"
    assert [a["code"] for a in executions(client, user_id)["items"][0]["audit"]] == ["proposed", "confirmed", "applied_partial"]


def test_confirm_rule_without_capacity_is_skipped_without_a_hold(client: TestClient, clean_database: None) -> None:
    user_id, account, ((r1, g1),) = _rs_setup(client, [("R1", 1, "CONFIRM", "900.00")])
    evaluate(client, user_id)

    execution = executions(client, user_id)["items"][0]
    assert (execution["status"], execution["reason_code"]) == ("skipped", "insufficient_capacity")
    assert _proposals(client, user_id)["total"] == 0
    assert account_view(client, user_id, account["id"])["active_rule_holds"] == "0.00"


# ------------------------------------------------------------------
# Rule lifecycle and Income corrections
# ------------------------------------------------------------------


def _pending(client: TestClient):
    user_id, account, ((rule, goal),) = _rs_setup(client, [("R1", 1, "CONFIRM", "100.00")])
    evaluate(client, user_id)
    return user_id, account, rule, goal, _proposals(client, user_id)["items"][0]


def test_material_edit_supersedes_open_proposals_but_non_material_does_not(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, rule, goal, proposal = _pending(client)

    assert patch_rule(client, user_id, rule["id"], name="Renamed", execution_order=5).status_code == 200
    assert _proposal(client, user_id, proposal["id"])["status"] == "awaiting_confirmation"
    assert patch_rule(client, user_id, rule["id"], allow_partial=True).json()["version"] == 2

    stored = _proposal(client, user_id, proposal["id"])
    assert (stored["status"], stored["reason_code"]) == ("cancelled", "superseded")
    assert account_view(client, user_id, account["id"])["active_rule_holds"] == "0.00"
    assert _confirm(client, user_id, proposal["id"]).json()["status"] == "cancelled"
    assert _tx_count(user_id) == 0


@pytest.mark.parametrize("name", ["pause", "disable"])
def test_pause_and_disable_cancel_open_proposals_as_rule_inactive(
    client: TestClient, clean_database: None, name: str,
) -> None:
    user_id, account, rule, goal, proposal = _pending(client)

    assert action(client, user_id, rule["id"], name).status_code == 200

    stored = _proposal(client, user_id, proposal["id"])
    assert (stored["status"], stored["reason_code"]) == ("cancelled", "rule_inactive")
    assert _confirm(client, user_id, proposal["id"]).json()["status"] == "cancelled"


def test_pause_keeps_a_completed_allocation_untouched(client: TestClient, clean_database: None) -> None:
    user_id, account, rule, goal, proposal = _pending(client)
    assert _confirm(client, user_id, proposal["id"]).status_code == 200

    assert action(client, user_id, rule["id"], "pause").status_code == 200

    assert _proposal(client, user_id, proposal["id"])["status"] == "executed" and _tx_count(user_id) == 1


def test_every_income_update_cancels_the_proposal_even_a_description_only_edit(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, rule, goal, proposal = _pending(client)
    income_id = scalar("SELECT id FROM income WHERE user_id = :u", u=user_id)
    assert account_view(client, user_id, account["id"])["active_rule_holds"] == "100.00"

    client.patch(f"/api/v1/income/{income_id}", headers=auth_headers(user_id), json={"description": "note"})
    evaluate(client, user_id)

    stored = _proposal(client, user_id, proposal["id"])
    assert (stored["status"], stored["reason_code"]) == ("cancelled", "source_changed")
    assert stored["hold_sequence"] == proposal["hold_sequence"] and stored["expires_at"] == proposal["expires_at"]
    assert account_view(client, user_id, account["id"])["active_rule_holds"] == "0.00"  # hold released
    assert _tx_count(user_id) == 0
    assert _confirm(client, user_id, proposal["id"]).json()["status"] == "cancelled"
    assert executions(client, user_id)["total"] == 1  # no new proposal for the same source
    codes = [a["code"] for a in executions(client, user_id)["items"][0]["audit"]]
    assert codes == ["proposed", "cancelled"]

    for _ in range(2):  # redelivery: no duplicate cancellation or audit
        with engine.begin() as connection:
            connection.execute(text(
                "UPDATE financial_events SET status = 'pending', processed_at = NULL, outcome_summary = NULL "
                "WHERE event_type = 'income.updated'"))
        evaluate(client, user_id)
    assert [a["code"] for a in executions(client, user_id)["items"][0]["audit"]] == codes


def test_an_income_update_leaves_a_completed_execution_unchanged_except_for_its_snapshot_annotation(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, rule, goal, proposal = _pending(client)
    assert _confirm(client, user_id, proposal["id"]).json()["status"] == "executed"
    income_id = scalar("SELECT id FROM income WHERE user_id = :u", u=user_id)

    client.patch(f"/api/v1/income/{income_id}", headers=auth_headers(user_id), json={"description": "note"})
    evaluate(client, user_id)
    assert _proposal(client, user_id, proposal["id"])["status"] == "executed"
    assert [a["code"] for a in executions(client, user_id)["items"][0]["audit"]] == ["proposed", "confirmed", "applied"]

    client.patch(f"/api/v1/income/{income_id}", headers=auth_headers(user_id), json={"amount": "5.00"})
    evaluate(client, user_id)  # snapshot-based annotation, still no re-run
    assert _proposal(client, user_id, proposal["id"])["status"] == "executed"
    assert [a["code"] for a in executions(client, user_id)["items"][0]["audit"]][-1] == "source_changed"
    assert _tx_count(user_id) == 1


def test_a_stored_audit_trail_has_a_stable_order_on_every_read(client: TestClient, clean_database: None) -> None:
    user_id, account, rule, goal, proposal = _pending(client)
    _confirm(client, user_id, proposal["id"])

    reads = {tuple(a["code"] for a in executions(client, user_id)["items"][0]["audit"]) for _ in range(5)}

    assert reads == {("proposed", "confirmed", "applied")}


def test_income_delete_cancels_the_proposal_and_leaves_executed_allocations(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, rule, goal, proposal = _pending(client)
    executed_user = str(uuid4())
    # A second user's executed CONFIRM allocation is untouched by this user's deletion.
    other_account = funded_account(client, executed_user, opening="500.00")
    other_goal = goal_with_target(client, executed_user, "G", 5000)
    enabled_rule(client, executed_user, other_account["id"], [other_goal["id"]], execution_mode="CONFIRM",
                 targets=[{"goal_id": other_goal["id"], "amount_or_cap": "50.00"}])
    other_income = post_income(client, executed_user, "10.00", other_account["id"])
    evaluate(client, executed_user)
    other_proposal = _proposals(client, executed_user)["items"][0]
    assert _confirm(client, executed_user, other_proposal["id"]).status_code == 200

    income_id = scalar("SELECT id FROM income WHERE user_id = :u", u=user_id)
    assert client.delete(f"/api/v1/income/{income_id}", headers=auth_headers(user_id)).status_code == 204
    assert client.delete(f"/api/v1/income/{other_income['id']}", headers=auth_headers(executed_user)).status_code == 204
    evaluate(client, user_id)
    evaluate(client, executed_user)

    stored = _proposal(client, user_id, proposal["id"])
    assert (stored["status"], stored["reason_code"]) == ("cancelled", "source_deleted")
    assert _proposal(client, executed_user, other_proposal["id"])["status"] == "executed"
    assert _tx_count(executed_user) == 1  # preserved, no compensating entry
    assert [a["code"] for a in executions(client, executed_user)["items"][0]["audit"]][-1] == "source_deleted"


def test_enabled_auto_rule_can_become_confirm_and_enable_validates_references(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="500.00")
    goal = goal_with_target(client, user_id, "G", 5000)
    rule = enabled_rule(client, user_id, account["id"], [goal["id"]])

    edited = patch_rule(client, user_id, rule["id"], execution_mode="CONFIRM")
    assert edited.status_code == 200 and edited.json()["version"] == 2 and edited.json()["status"] == "enabled"

    other = create_rule(client, user_id, allocation_payload(account["id"], [goal["id"]], execution_mode="CONFIRM", name="C2"))
    client.patch(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id), json={"status": "archived"})
    assert action(client, user_id, other["id"], "enable").status_code == 409


def test_account_and_goal_with_a_proposal_are_protected(client: TestClient, clean_database: None) -> None:
    user_id, account, rule, goal, proposal = _pending(client)

    assert client.delete(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id)).status_code == 409
    assert client.patch(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user_id), json={"currency": "USD"}).status_code == 409
    assert client.delete(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user_id)).status_code == 409


# ------------------------------------------------------------------
# Isolation, validation, failure
# ------------------------------------------------------------------


def test_proposals_are_isolated_between_users(client: TestClient, clean_database: None) -> None:
    user_id, account, rule, goal, proposal = _pending(client)
    stranger = str(uuid4())

    assert _proposals(client, stranger)["total"] == 0
    assert client.get(f"{PROPOSALS_URL}/{proposal['id']}", headers=auth_headers(stranger)).status_code == 404
    assert _confirm(client, stranger, proposal["id"]).status_code == 404
    assert _reject(client, stranger, proposal["id"]).status_code == 404
    assert _confirm(client, user_id, str(uuid4())).status_code == 404  # indistinguishable from a foreign one
    assert _proposal(client, user_id, proposal["id"])["status"] == "awaiting_confirmation"
    assert _tx_count(user_id) == 0


def test_a_non_proposal_execution_is_not_addressable_as_a_proposal(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="500.00")
    goal = goal_with_target(client, user_id, "G", 5000)
    enabled_rule(client, user_id, account["id"], [goal["id"]])
    post_income(client, user_id, "10.00", account["id"])
    evaluate(client, user_id)
    execution_id = executions(client, user_id)["items"][0]["id"]

    assert _confirm(client, user_id, execution_id).status_code == 404
    assert client.get(f"{PROPOSALS_URL}/{execution_id}", headers=auth_headers(user_id)).status_code == 404


def test_proposal_endpoints_require_authentication_and_bound_the_page(client: TestClient, clean_database: None) -> None:
    assert client.get(PROPOSALS_URL).status_code == 401
    assert client.post(f"{PROPOSALS_URL}/{uuid4()}/confirm").status_code == 401
    user_id = str(uuid4())
    assert client.get(PROPOSALS_URL + "?limit=0", headers=auth_headers(user_id)).status_code == 422
    assert client.get(PROPOSALS_URL + "?limit=101", headers=auth_headers(user_id)).status_code == 422
    assert client.get(PROPOSALS_URL + "?status=bogus", headers=auth_headers(user_id)).status_code == 422


def test_proposal_list_filters_by_status(client: TestClient, clean_database: None) -> None:
    user_id, account, rule, goal, proposal = _pending(client)

    assert _proposals(client, user_id, status="awaiting_confirmation")["total"] == 1
    assert _proposals(client, user_id, status="executed")["total"] == 0
    _confirm(client, user_id, proposal["id"])
    assert _proposals(client, user_id, status="executed")["total"] == 1
    assert _proposals(client, user_id, status="awaiting_confirmation")["total"] == 0


def test_a_failure_during_confirmation_rolls_everything_back(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.financial_rules import rule_proposal_service

    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="600.00")
    goals = [goal_with_target(client, user_id, f"G{i}", 5000) for i in range(3)]
    enabled_rule(client, user_id, account["id"], [g["id"] for g in goals], execution_mode="CONFIRM",
                 targets=[{"goal_id": g["id"], "amount_or_cap": "50.00"} for g in goals])
    post_income(client, user_id, "0.01", account["id"])
    evaluate(client, user_id)
    proposal_id = _proposals(client, user_id)["items"][0]["id"]
    original = rule_proposal_service.write_item_transaction
    calls = {"count": 0}

    def fail_on_second(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("crash mid-confirmation")
        return original(*args, **kwargs)

    monkeypatch.setattr(rule_proposal_service, "write_item_transaction", fail_on_second)
    failing = TestClient(client.app, raise_server_exceptions=False)

    assert _confirm(failing, user_id, proposal_id).status_code == 500
    assert _tx_count(user_id) == 0
    assert scalar("SELECT status FROM rule_executions") == "awaiting_confirmation"
    assert scalar("SELECT count(*) FROM rule_execution_items WHERE goal_transaction_id IS NOT NULL") == 0

    monkeypatch.setattr(rule_proposal_service, "write_item_transaction", original)
    assert _confirm(client, user_id, proposal_id).json()["status"] == "executed"
    assert _tx_count(user_id) == 3


def test_a_failure_while_creating_a_proposal_leaves_no_partial_state(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.financial_rules import rule_execution_repository

    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="600.00")
    goal = goal_with_target(client, user_id, "G", 5000)
    enabled_rule(client, user_id, account["id"], [goal["id"]], execution_mode="CONFIRM",
                 targets=[{"goal_id": goal["id"], "amount_or_cap": "50.00"}])
    post_income(client, user_id, "0.01", account["id"])
    original = rule_execution_repository.add_audit

    def fail(*args, **kwargs):
        raise RuntimeError("crash after the proposal rows")

    monkeypatch.setattr(rule_execution_repository, "add_audit", fail)
    assert evaluate(client, user_id).json()["failed_retryable"] == 1
    assert scalar("SELECT count(*) FROM rule_executions") == 0 and scalar("SELECT count(*) FROM rule_execution_items") == 0
    assert account_view(client, user_id, account["id"])["active_rule_holds"] == "0.00"

    monkeypatch.setattr(rule_execution_repository, "add_audit", original)
    with engine.begin() as connection:
        connection.execute(text("UPDATE financial_events SET next_attempt_at = now() - interval '1 second'"))
    assert evaluate(client, user_id).json()["processed"] == 1
    assert _proposals(client, user_id)["total"] == 1
    assert Decimal(account_view(client, user_id, account["id"])["active_rule_holds"]) == Decimal("50.00")
