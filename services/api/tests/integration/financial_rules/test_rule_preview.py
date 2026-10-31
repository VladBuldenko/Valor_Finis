import threading
from decimal import Decimal
from typing import Any, Callable, Optional
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.database_session import SessionLocal, engine
from app.main import app
from app.modules.financial_rules import rule_execution_repository, rule_preview_service
from tests.helpers import auth_headers
from tests.integration.financial_rules.execution_helpers import (
    enabled_rule,
    evaluate,
    executions,
    funded_account,
    goal_with_target,
    post_income,
)
from tests.integration.financial_rules.rule_helpers import (
    RULES_URL,
    action,
    allocation_payload,
    create_rule,
    floor_payload,
    overcommitment_payload,
)

# VF-BE-2: POST /financial-rules/{id}/preview against real PostgreSQL. Expected
# values are independent literals; parity tests compare the preview with a REAL
# execution of the same state.


def _preview(
    client: TestClient, user_id: str, rule_id: str, amount: Any = "3000.00", source: Optional[str] = "salary",
):
    sample: dict[str, Any] = {"amount": amount}

    if source is not None:
        sample["source"] = source

    return client.post(
        f"{RULES_URL}/{rule_id}/preview", headers=auth_headers(user_id), json={"sample_income": sample},
    )


def _selected(body: dict[str, Any]) -> dict[str, str]:
    return {
        item["goal_id"]: item["selected_amount"]
        for item in body["items"]
        if Decimal(item["selected_amount"]) > 0
    }


def _floor(client: TestClient, user_id: str, account_id: str, amount: str) -> None:
    rule = create_rule(client, user_id, floor_payload(account_id, amount))
    assert action(client, user_id, rule["id"], "enable").status_code == 200


def _example_a(client: TestClient, user_id: str, floor: str = "1000.00", **overrides: Any):
    """§10.7 setup: account 2,000, 500 already reserved for G1, 20% waterfall, caps 300/200/none."""
    account = funded_account(client, user_id, opening="2000.00")
    g1 = goal_with_target(client, user_id, "G1", 3000)
    g2 = goal_with_target(client, user_id, "G2", 5000)
    g3 = goal_with_target(client, user_id, "G3", 1000)
    reserve = client.post(
        f"/api/v1/goals/{g1['id']}/transactions", headers=auth_headers(user_id),
        json={"type": "contribution", "amount": "500.00", "account_id": account["id"],
              "client_request_id": str(uuid4())},
    )
    assert reserve.status_code == 201, reserve.text
    _floor(client, user_id, account["id"], floor)
    rule = enabled_rule(
        client, user_id, account["id"], [g1["id"], g2["id"], g3["id"]],
        policy="PERCENT_OF_INCOME_WATERFALL", percent="20.00",
        targets=[
            {"goal_id": g1["id"], "amount_or_cap": "300.00"},
            {"goal_id": g2["id"], "amount_or_cap": "200.00"},
            {"goal_id": g3["id"]},
        ],
        **overrides,
    )
    return account, (g1, g2, g3), rule


# ---------------------------------------------------------------- full-state snapshots


def _snapshot() -> dict[str, Any]:
    """Full row content of EVERY application table plus every sequence value."""
    with engine.connect() as connection:
        tables = [
            row[0]
            for row in connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                     "AND tablename <> 'alembic_version' ORDER BY tablename")
            )
        ]
        content = {
            table: connection.execute(
                text(f'SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), \'[]\'::jsonb) '
                     f'FROM "{table}" t')
            ).scalar_one()
            for table in tables
        }
        sequences = {
            row[0]: row[1]
            for row in connection.execute(
                text("SELECT sequencename, last_value FROM pg_sequences WHERE schemaname = 'public' "
                     "ORDER BY sequencename")
            )
        }

    return {"tables": content, "sequences": sequences}


# ---------------------------------------------------------------- contract and errors


def test_response_contract_full_auto_rule_example_a(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    account, (g1, g2, g3), rule = _example_a(client, user)

    response = _preview(client, user, rule["id"], "3000.00")
    body = response.json()

    assert response.status_code == 200, response.text
    assert body["hypothetical"] is True
    assert body["rule_id"] == rule["id"] and body["rule_version"] == rule["version"]
    assert body["execution_mode"] == "AUTO" and body["policy"] == "PERCENT_OF_INCOME_WATERFALL"
    assert body["sample_income"] == {
        "amount": "3000.00", "currency": "EUR", "source": "salary", "source_selected_by_rule": True,
    }
    assert body["capacity"] == {
        "account_id": account["id"], "currency": "EUR",
        "reservable_amount": "1500.00",           # 2,000 - 500 reserved
        "assumed_sample_income_credit": "3000.00",
        "reservable_with_sample_income": "4500.00",
        "minimum_unallocated_floor": "1000.00",
        "active_rule_holds": "0.00",
        "rule_capacity": "3500.00",               # 4,500 - 1,000 - 0
    }
    assert (body["predicted_outcome"], body["effect"], body["reason_code"]) == ("full", "would_apply", None)
    assert {item["goal_id"]: (item["planned_amount"], item["selected_amount"]) for item in body["items"]} == {
        g1["id"]: ("300.00", "300.00"), g2["id"]: ("200.00", "200.00"), g3["id"]: ("100.00", "100.00"),
    }  # 20% of 3,000 = 600 waterfall: G1 300, G2 200, G3 the remaining 100
    assert body["planned_total"] == "600.00" and body["selected_total"] == "600.00"
    assert body["notices"] == ["hypothetical_snapshot", "income_not_recorded", "eligibility_not_evaluated"]
    assert body["as_of_date"] and body["computed_at"]


def test_owner_isolation_foreign_and_missing_rule_are_the_same_404(client: TestClient, clean_database: None) -> None:
    owner, intruder = str(uuid4()), str(uuid4())
    _, _, rule = _example_a(client, owner)

    foreign = _preview(client, intruder, rule["id"])
    missing = _preview(client, intruder, str(uuid4()))

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": "Financial rule not found.", "code": "financial_rule_not_found"}


def test_non_allocation_rule_is_a_409_with_the_new_code(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    account = funded_account(client, user)
    floor = create_rule(client, user, floor_payload(account["id"], "100.00"))

    response = _preview(client, user, floor["id"])

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Only income allocation rules can be previewed.",
        "code": "financial_rule_preview_not_available",
    }


def test_unauthenticated_preview_is_a_401(client: TestClient, clean_database: None) -> None:
    response = client.post(f"{RULES_URL}/{uuid4()}/preview", json={"sample_income": {"amount": "1.00"}})

    assert response.status_code == 401
    assert response.json()["code"] == "auth_missing_credentials"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"sample_income": {}},
        {"sample_income": {"amount": "0"}},
        {"sample_income": {"amount": "-5.00"}},
        {"sample_income": {"amount": "10.005"}},
        {"sample_income": {"amount": "abc"}},
        {"sample_income": {"amount": "1.00", "source": "lottery"}},
        {"sample_income": {"amount": "1.00", "currency": "USD"}},
        {"sample_income": {"amount": "1.00"}, "user_id": "11111111-1111-1111-1111-111111111111"},
    ],
)
def test_invalid_body_is_a_422_validation_error(client: TestClient, clean_database: None, payload: dict[str, Any]) -> None:
    user = str(uuid4())
    _, _, rule = _example_a(client, user)

    response = client.post(f"{RULES_URL}/{rule['id']}/preview", headers=auth_headers(user), json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# ---------------------------------------------------------------- outcomes


def test_fixed_policy_partial_skipped_and_modes(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    account = funded_account(client, user, opening="100.00")
    ga = goal_with_target(client, user, "A", 1000)
    gb = goal_with_target(client, user, "B", 1000)
    rule = enabled_rule(
        client, user, account["id"], [ga["id"], gb["id"]],
        targets=[{"goal_id": ga["id"], "amount_or_cap": "150.00"}, {"goal_id": gb["id"], "amount_or_cap": "100.00"}],
        allow_partial=True,
    )

    ranked = client.put("/api/v1/goals/priorities", json={"goal_ids": [ga["id"], gb["id"]]}, headers=auth_headers(user))
    assert ranked.status_code == 200, ranked.text

    body = _preview(client, user, rule["id"], "100.00").json()  # capacity 100 + 100 = 200 < 250

    assert (body["predicted_outcome"], body["effect"], body["reason_code"]) == ("partial", "would_apply", None)
    assert body["capacity"]["rule_capacity"] == "200.00"
    assert body["planned_total"] == "250.00" and body["selected_total"] == "200.00"
    assert _selected(body) == {ga["id"]: "150.00", gb["id"]: "50.00"}  # priority order until capacity is spent
    assert [item["priority_rank"] for item in body["items"]] == [1, 2]

    no_partial = enabled_rule(
        client, user, account["id"], [ga["id"], gb["id"]], name="Strict",
        targets=[{"goal_id": ga["id"], "amount_or_cap": "150.00"}, {"goal_id": gb["id"], "amount_or_cap": "100.00"}],
    )
    skipped = _preview(client, user, no_partial["id"], "100.00").json()

    assert (skipped["predicted_outcome"], skipped["effect"], skipped["reason_code"]) == (
        "skipped", "none", "insufficient_capacity",
    )
    assert skipped["selected_total"] == "0.00" and skipped["planned_total"] == "250.00"

    confirm = enabled_rule(
        client, user, account["id"], [ga["id"]], name="Ask", execution_mode="CONFIRM",
        targets=[{"goal_id": ga["id"], "amount_or_cap": "100.00"}],
    )
    held = _preview(client, user, confirm["id"], "100.00").json()

    assert (held["execution_mode"], held["predicted_outcome"], held["effect"]) == ("CONFIRM", "full", "would_hold")


def test_nothing_to_allocate_and_source_notice(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    account = funded_account(client, user)
    goal = goal_with_target(client, user, "G", 1000)
    rule = enabled_rule(
        client, user, account["id"], [goal["id"]], policy="PERCENT_OF_INCOME_WATERFALL", percent="0.01",
    )

    nothing = _preview(client, user, rule["id"], "1.00", source="refund").json()  # 0.01% of 1.00 rounds down to 0.00

    assert (nothing["predicted_outcome"], nothing["reason_code"], nothing["items"]) == ("skipped", "nothing_to_allocate", [])
    assert nothing["sample_income"]["source_selected_by_rule"] is False  # refund is not selected by default
    assert _preview(client, user, rule["id"], "1.00", source=None).json()["sample_income"]["source_selected_by_rule"] is None


def test_blocked_outcomes_for_archived_goal_and_account(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    account = funded_account(client, user)
    goal = goal_with_target(client, user, "G", 1000)
    rule = enabled_rule(client, user, account["id"], [goal["id"]])

    client.patch(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user), json={"status": "archived"})
    goal_blocked = _preview(client, user, rule["id"]).json()

    assert (goal_blocked["predicted_outcome"], goal_blocked["effect"], goal_blocked["reason_code"]) == (
        "blocked", "none", "target_goal_archived",
    )

    client.patch(f"/api/v1/goals/{goal['id']}", headers=auth_headers(user), json={"status": "active"})
    client.patch(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user), json={"status": "archived"})

    assert _preview(client, user, rule["id"]).json()["reason_code"] == "source_account_archived"


def test_cap_at_target_limits_the_plan_to_the_remaining_target(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    account = funded_account(client, user, opening="5000.00")
    goal = goal_with_target(client, user, "Almost", 1000)
    client.post(
        f"/api/v1/goals/{goal['id']}/transactions", headers=auth_headers(user),
        json={"type": "contribution", "amount": "950.00", "account_id": account["id"], "client_request_id": str(uuid4())},
    )
    rule = enabled_rule(
        client, user, account["id"], [goal["id"]], targets=[{"goal_id": goal["id"], "amount_or_cap": "300.00"}],
    )

    body = _preview(client, user, rule["id"], "1000.00").json()

    assert body["items"][0]["planned_amount"] == "50.00"  # target 1,000 - 950 already saved


def test_active_confirm_holds_reduce_the_rule_capacity(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    account = funded_account(client, user, opening="1000.00")
    g_hold = goal_with_target(client, user, "Held", 5000)
    g_other = goal_with_target(client, user, "Other", 5000)
    enabled_rule(
        client, user, account["id"], [g_hold["id"]], name="Confirm", execution_mode="CONFIRM",
        targets=[{"goal_id": g_hold["id"], "amount_or_cap": "400.00"}],
    )
    post_income(client, user, "500.00", account["id"])
    assert evaluate(client, user).json()["outcomes"] == {"awaiting_confirmation": 1}
    preview_rule_id = create_rule(
        client, user, allocation_payload(account["id"], [g_other["id"]], name="Later"),
    )["id"]

    body = _preview(client, user, preview_rule_id, "100.00").json()

    assert body["capacity"]["reservable_amount"] == "1500.00"        # 1,000 + 500 recorded income
    assert body["capacity"]["active_rule_holds"] == "400.00"         # the open proposal
    assert body["capacity"]["reservable_with_sample_income"] == "1600.00"
    assert body["capacity"]["rule_capacity"] == "1200.00"            # 1,600 - 0 floor - 400


# ---------------------------------------------------------------- parity with real execution


PARITY_SCENARIOS = [
    pytest.param({"floor": "1000.00"}, id="percent-waterfall-full-auto"),
    pytest.param({"floor": "4300.00", "allow_partial": True}, id="percent-waterfall-partial-auto"),
    pytest.param({"floor": "4400.00"}, id="percent-waterfall-insufficient-skip"),
    pytest.param({"floor": "1000.00", "execution_mode": "CONFIRM"}, id="percent-waterfall-full-confirm"),
    pytest.param({"floor": "4300.00", "allow_partial": True, "execution_mode": "CONFIRM"}, id="percent-waterfall-partial-confirm"),
]


@pytest.mark.parametrize("scenario", PARITY_SCENARIOS)
def test_preview_equals_real_execution_on_identical_state(
    client: TestClient, clean_database: None, scenario: dict[str, Any],
) -> None:
    user = str(uuid4())
    overrides = {key: value for key, value in scenario.items() if key != "floor"}
    account, _, rule = _example_a(client, user, floor=scenario["floor"], **overrides)

    preview = _preview(client, user, rule["id"], "3000.00").json()

    post_income(client, user, "3000.00", account["id"])
    assert evaluate(client, user).status_code == 200
    execution = executions(client, user)["items"][0]

    assert preview["capacity"]["reservable_with_sample_income"] == execution["capacity_reservable"]
    assert preview["capacity"]["minimum_unallocated_floor"] == execution["capacity_floor"]
    assert preview["capacity"]["active_rule_holds"] == execution["capacity_holds"]
    assert execution["reason_code"] == preview["reason_code"]

    real_amounts = {
        item["goal_id"]: item["planned_amount" if execution["status"] == "awaiting_confirmation" else "applied_amount"]
        for item in execution["items"]
        if item["planned_amount" if execution["status"] == "awaiting_confirmation" else "applied_amount"] is not None
        and Decimal(item["planned_amount" if execution["status"] == "awaiting_confirmation" else "applied_amount"]) > 0
    }

    assert _selected(preview) == real_amounts
    expected_status = {
        "executed": ("full", "would_apply"),
        "executed_partial": ("partial", "would_apply"),
        "skipped": ("skipped", "none"),
        "blocked": ("blocked", "none"),
    }

    if execution["status"] == "awaiting_confirmation":
        proposal_partial = Decimal(sum(Decimal(v) for v in real_amounts.values())) < Decimal(preview["planned_total"])
        assert (preview["predicted_outcome"], preview["effect"]) == (
            "partial" if proposal_partial else "full", "would_hold",
        )
    else:
        assert (preview["predicted_outcome"], preview["effect"]) == expected_status[execution["status"]]


def test_fixed_policy_parity(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    account = funded_account(client, user, opening="100.00")
    ga = goal_with_target(client, user, "A", 1000)
    gb = goal_with_target(client, user, "B", 1000)
    rule = enabled_rule(
        client, user, account["id"], [ga["id"], gb["id"]], allow_partial=True,
        targets=[{"goal_id": ga["id"], "amount_or_cap": "150.00"}, {"goal_id": gb["id"], "amount_or_cap": "100.00"}],
    )

    preview = _preview(client, user, rule["id"], "100.00").json()
    post_income(client, user, "100.00", account["id"])
    evaluate(client, user)
    execution = executions(client, user)["items"][0]

    assert execution["status"] == "executed_partial" and preview["predicted_outcome"] == "partial"
    assert _selected(preview) == {item["goal_id"]: item["applied_amount"] for item in execution["items"]}


# ---------------------------------------------------------------- no writes, database-enforced


def test_successful_and_failed_previews_change_nothing(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    account, _, rule = _example_a(client, user)
    floor_rule = create_rule(client, user, overcommitment_payload(account["id"]))
    crashing = TestClient(app, raise_server_exceptions=False)
    before = _snapshot()

    assert _preview(client, user, rule["id"]).status_code == 200
    assert _preview(client, user, rule["id"], "0.01").status_code == 200
    assert _preview(client, str(uuid4()), rule["id"]).status_code == 404
    assert _preview(client, user, floor_rule["id"]).status_code == 409
    assert _preview(client, user, rule["id"], amount="-1").status_code == 422

    original = rule_execution_repository.get_goals

    def explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("forced internal failure")

    rule_execution_repository.get_goals = explode  # type: ignore[assignment]
    try:
        forced = _preview(crashing, user, rule["id"])
    finally:
        rule_execution_repository.get_goals = original  # type: ignore[assignment]

    assert forced.status_code == 500 and forced.json()["code"] == "internal_server_error"
    assert _snapshot() == before  # every table's full rows and every sequence value


def test_the_preview_transaction_is_read_only_repeatable_read(clean_database: None) -> None:
    with rule_preview_service.read_only_snapshot_session() as session:
        assert session.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
        assert session.execute(text("SHOW transaction_isolation")).scalar_one() == "repeatable read"


def _hold_sequence_name() -> str:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT sequencename FROM pg_sequences WHERE schemaname = 'public' LIMIT 1")
        ).scalar_one()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE accounts SET name = name",
        "UPDATE goals SET name = name",
        "DELETE FROM rule_executions",
        "INSERT INTO rule_alerts (id) VALUES (gen_random_uuid())",
        "SELECT nextval('{sequence}')",
    ],
)
def test_database_rejects_writes_and_nextval_inside_the_preview_transaction(clean_database: None, statement: str) -> None:
    before = _snapshot()

    with pytest.raises(DBAPIError) as raised:
        with rule_preview_service.read_only_snapshot_session() as session:
            session.execute(text(statement.format(sequence=_hold_sequence_name())))

    assert "read-only transaction" in str(raised.value)
    assert _snapshot() == before


def test_an_injected_write_in_the_preview_path_fails_and_persists_nothing(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    _, _, rule = _example_a(client, user)
    crashing = TestClient(app, raise_server_exceptions=False)
    before = _snapshot()
    original = rule_execution_repository.get_goals

    def read_then_write(db_session: Any, *args: Any, **kwargs: Any) -> Any:
        db_session.execute(text("UPDATE goals SET name = 'tampered'"))
        db_session.commit()

        return original(db_session, *args, **kwargs)

    rule_execution_repository.get_goals = read_then_write  # type: ignore[assignment]
    try:
        response = _preview(crashing, user, rule["id"])
    finally:
        rule_execution_repository.get_goals = original  # type: ignore[assignment]

    assert response.status_code == 500
    assert _snapshot() == before


def test_preview_module_contains_no_lock_write_or_execution_calls() -> None:
    source = open(rule_preview_service.__file__, encoding="utf-8").read()
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))

    for forbidden in (
        "for_update", "with_for_update", "advisory", "next_hold_sequence", "expire_due_proposals",
        "_execute_rule", ".commit(", "db_session.add", "db_session.flush", "add_execution", "add_audit",
    ):
        assert forbidden not in code, forbidden


# ---------------------------------------------------------------- concurrency


def _run_in_threads(jobs: list[Callable[[], Any]]) -> list[Any]:
    barrier = threading.Barrier(len(jobs))
    results: list[Any] = [None] * len(jobs)

    def worker(index: int) -> None:
        barrier.wait(timeout=60)
        try:
            results[index] = jobs[index]()
        except Exception as error:  # noqa: BLE001 - asserted below
            results[index] = error

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(jobs))]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive(), "a worker did not finish (possible deadlock)"

    return results


def _stable(body: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in body.items() if key != "computed_at"}


def test_concurrent_previews_are_identical(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    _, _, rule = _example_a(client, user)

    results = _run_in_threads([lambda: _preview(client, user, rule["id"]).json() for _ in range(8)])

    assert all(isinstance(result, dict) for result in results), results
    assert all(_stable(result) == _stable(results[0]) for result in results)


def test_previews_racing_real_executions_neither_deadlock_nor_change_the_result(
    client: TestClient, clean_database: None,
) -> None:
    raced, control = str(uuid4()), str(uuid4())
    raced_account, _, raced_rule = _example_a(client, raced)
    control_account, _, _ = _example_a(client, control)

    def execute(user: str, account_id: str) -> int:
        post_income(client, user, "3000.00", account_id)
        post_income(client, user, "100.00", account_id)

        return evaluate(client, user).status_code

    jobs: list[Callable[[], Any]] = [lambda: execute(raced, raced_account["id"])]
    jobs += [lambda: _preview(client, raced, raced_rule["id"]).status_code for _ in range(6)]
    results = _run_in_threads(jobs)

    assert results == [200] * 7, results
    assert execute(control, control_account["id"]) == 200

    def outcome(user: str) -> list[tuple[str, tuple[Any, ...]]]:
        return sorted(
            (item["status"], tuple(sorted(
                (i["applied_amount"] for i in item["items"] if i["applied_amount"] is not None)
            )))
            for item in executions(client, user)["items"]
        )

    assert outcome(raced) == outcome(control)
    assert _preview(client, raced, raced_rule["id"]).status_code == 200
