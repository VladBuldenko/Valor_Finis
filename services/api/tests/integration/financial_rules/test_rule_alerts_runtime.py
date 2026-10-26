import threading
from datetime import date
from typing import Any, Callable, Optional
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.app_config import settings
from app.db.database_session import SessionLocal, engine
from app.modules.financial_events import financial_event_service
from app.modules.financial_rules import rule_alert_repository, rule_alert_service
from tests.helpers import auth_headers, create_budget
from tests.integration.financial_rules.execution_helpers import (
    account_view,
    enabled_rule,
    evaluate,
    funded_account,
    goal_with_target,
    post_income,
    scalar,
)
from tests.integration.financial_rules.rule_helpers import (
    action,
    create_rule,
    delete_rule,
    floor_payload,
    overcommitment_payload,
)
from tests.integration.financial_rules.test_auto_execution import _reserve
from tests.integration.financial_rules.test_confirm_proposals import _debit
from tests.integration.financial_rules.test_income_corrections_and_lifecycle import _hold

# VF-020E9B alert runtime tests: floor-breach, overcommitment and Budget alerts,
# episode lifecycle, deduplication, acknowledgement, ownership, staged
# availability and concurrency. Real PostgreSQL through the API; the Budget
# scenarios pin "today" so the pace-based risk levels are deterministic.

ALERTS_URL = "/api/v1/rule-alerts"
TODAY = date(2026, 10, 10)  # day 10 of a 31-day month


def _alerts(client: TestClient, user_id: str, **params: Any) -> dict[str, Any]:
    response = client.get(ALERTS_URL, headers=auth_headers(user_id), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _ack(client: TestClient, user_id: str, alert_id: str):
    return client.post(f"{ALERTS_URL}/{alert_id}/acknowledge", headers=auth_headers(user_id))


def _enable(client: TestClient, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    rule = create_rule(client, user_id, payload)
    response = action(client, user_id, rule["id"], "enable")
    assert response.status_code == 200, response.text
    return response.json()


def _evaluate_alerts(user_id: str) -> rule_alert_service.AlertEvaluation:
    with SessionLocal() as session:
        return rule_alert_service.evaluate_user_alerts(session, UUID(user_id))


def _rows(user_id: str) -> list[tuple[Any, ...]]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(
            text("SELECT rule_type, level, period_key, resolved_at IS NOT NULL FROM rule_alerts "
                 "WHERE user_id = :u ORDER BY created_at, period_key, level"), {"u": user_id})]


def _floor_setup(client: TestClient, opening: str = "1500.00", floor: str = "1000.00"):
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening=opening)
    goal = goal_with_target(client, user_id, "G", 5000)
    rule = _enable(client, user_id, floor_payload(account["id"], floor))
    return user_id, account, goal, rule


def _release(client: TestClient, user_id: str, goal_id: str, account_id: str, amount: str) -> None:
    response = client.post(
        f"/api/v1/goals/{goal_id}/transactions", headers=auth_headers(user_id),
        json={"type": "withdrawal", "amount": amount, "account_id": account_id, "client_request_id": str(uuid4())},
    )
    assert response.status_code == 201, response.text


@pytest.fixture
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> date:
    monkeypatch.setattr(financial_event_service, "server_today", lambda: TODAY)
    return TODAY


# ------------------------------------------------------------------
# Floor breach episodes
# ------------------------------------------------------------------


def test_floor_breach_opens_one_episode_and_recovery_then_rebreach_opens_the_next(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, goal, rule = _floor_setup(client)
    assert _evaluate_alerts(user_id).created == 0  # reservable 1500 >= floor 1000

    _reserve(client, user_id, goal["id"], account["id"], "800.00")  # reservable 700 < 1000 (manual warning case)
    first = _evaluate_alerts(user_id)
    again = _evaluate_alerts(user_id)  # idempotent

    assert (first.created, again.created, again.resolved) == (1, 0, 0)
    assert _rows(user_id) == [("MINIMUM_UNALLOCATED_FLOOR", "breached", "E1", False)]

    _release(client, user_id, goal["id"], account["id"], "800.00")  # recovery
    recovered = _evaluate_alerts(user_id)
    assert (recovered.created, recovered.resolved) == (0, 1)
    assert _rows(user_id) == [("MINIMUM_UNALLOCATED_FLOOR", "breached", "E1", True)]

    _reserve(client, user_id, goal["id"], account["id"], "800.00")  # a later breach
    assert _evaluate_alerts(user_id).created == 1
    assert _rows(user_id) == [
        ("MINIMUM_UNALLOCATED_FLOOR", "breached", "E1", True),
        ("MINIMUM_UNALLOCATED_FLOOR", "breached", "E2", False),
    ]


def test_a_floor_of_zero_a_disabled_floor_and_equality_do_not_alert(client: TestClient, clean_database: None) -> None:
    user_id, account, goal, rule = _floor_setup(client, opening="1500.00", floor="700.00")
    _reserve(client, user_id, goal["id"], account["id"], "800.00")  # reservable 700 == floor 700 (equality)
    assert _evaluate_alerts(user_id).created == 0

    _reserve(client, user_id, goal["id"], account["id"], "100.00")  # 600 < 700
    assert action(client, user_id, rule["id"], "disable").status_code == 200  # a disabled floor is not evaluated
    assert _evaluate_alerts(user_id).created == 0


def test_soft_holds_alone_never_create_a_floor_alert(client: TestClient, clean_database: None) -> None:
    user_id, account, goal, rule = _floor_setup(client, opening="1500.00", floor="1000.00")
    confirm_rule = create_rule(client, user_id, {
        "rule_type": "INCOME_ALLOCATION", "name": "C", "source_account_id": account["id"], "execution_mode": "CONFIRM",
        "policy": "FIXED_PER_GOAL", "targets": [{"goal_id": goal["id"], "amount_or_cap": "100.00"}],
    })
    _hold(user_id, account["id"], confirm_rule["id"], goal["id"], "400.00", "7 days")

    assert account_view(client, user_id, account["id"])["rule_capacity"] == "100.00"  # holds reduce capacity ...
    assert _evaluate_alerts(user_id).created == 0  # ... but reservable (1500) is still above the floor


def test_s21_deleting_the_income_after_an_allocation_raises_a_floor_alert_not_an_overcommitment(
    client: TestClient, clean_database: None,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="2000.00")
    goal = goal_with_target(client, user_id, "G", 5000)
    _enable(client, user_id, floor_payload(account["id"], "1600.00"))
    _enable(client, user_id, overcommitment_payload(account["id"]))
    enabled_rule(client, user_id, account["id"], [goal["id"]], targets=[{"goal_id": goal["id"], "amount_or_cap": "500.00"}])
    income = post_income(client, user_id, "3000.00", account["id"])
    evaluate(client, user_id)  # AUTO reserves 500; reservable 4500 >= floor 1600
    assert _rows(user_id) == []

    assert client.delete(f"/api/v1/income/{income['id']}", headers=auth_headers(user_id)).status_code == 204
    summary = evaluate(client, user_id).json()  # drains the delete event, then evaluates alerts

    # Balance back to 2000 with 500 preserved (P47): reservable 1500 < floor 1600.
    assert summary["alerts_available"] is True and summary["alerts_created"] == 1
    assert _rows(user_id) == [("MINIMUM_UNALLOCATED_FLOOR", "breached", "E1", False)]  # floor only
    assert account_view(client, user_id, account["id"])["allocation_status"] == "normal"


# ------------------------------------------------------------------
# Overcommitment
# ------------------------------------------------------------------


def test_overcommitment_is_a_separate_alert_from_the_floor_breach(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="1000.00")
    goal = goal_with_target(client, user_id, "G", 5000)
    _enable(client, user_id, overcommitment_payload(account["id"]))
    _enable(client, user_id, floor_payload(account["id"], "500.00"))
    _reserve(client, user_id, goal["id"], account["id"], "800.00")  # reservable 200 < floor 500, not overcommitted

    assert _evaluate_alerts(user_id).created == 1
    assert _rows(user_id) == [("MINIMUM_UNALLOCATED_FLOOR", "breached", "E1", False)]

    _debit(client, user_id, account["id"], "500.00")  # unallocated 1000-500-800 = -300 -> overcommitted (P05)
    assert _evaluate_alerts(user_id).created == 1
    assert sorted(_rows(user_id)) == [
        ("MINIMUM_UNALLOCATED_FLOOR", "breached", "E1", False),
        ("OVERCOMMITMENT_ALERT", "breached", "E1", False),
    ]

    _release(client, user_id, goal["id"], account["id"], "800.00")  # no longer overcommitted
    result = _evaluate_alerts(user_id)
    assert result.resolved == 2  # reservable 500 == floor 500, balance 500: both episodes end
    assert all(row[3] is True for row in _rows(user_id))


def test_an_overcommitment_rule_ignores_a_pure_floor_state(client: TestClient, clean_database: None) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="1000.00")
    _enable(client, user_id, overcommitment_payload(account["id"]))

    assert _evaluate_alerts(user_id).created == 0


# ------------------------------------------------------------------
# Budget alerts (levels once per period, upward only)
# ------------------------------------------------------------------


def _expense(client: TestClient, user_id: str, amount: str, day: date = TODAY) -> str:
    response = client.post(
        "/api/v1/expenses", headers=auth_headers(user_id),
        json={"category_id": None, "title": "x", "amount": amount, "currency": "EUR",
              "expense_date": day.isoformat(), "description": "x", "source": "manual"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _budget_setup(client: TestClient):
    user_id = str(uuid4())
    budget = create_budget(client, user_id, limit_amount=300)
    rule = _enable(client, user_id, {"rule_type": "BUDGET_ALERT", "name": "B", "budget_id": budget["id"]})
    return user_id, budget, rule


def test_budget_levels_alert_once_per_period_and_only_on_escalation(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id, budget, rule = _budget_setup(client)
    assert _evaluate_alerts(user_id).created == 0  # healthy

    watch_expense = _expense(client, user_id, "90.00")  # projected 279 of 300 -> watch
    assert _evaluate_alerts(user_id).created == 1
    assert _evaluate_alerts(user_id).created == 0  # same level again: nothing
    _expense(client, user_id, "10.00")  # 100 -> projected 310 -> at_risk
    assert _evaluate_alerts(user_id).created == 1
    _expense(client, user_id, "250.00")  # 350 > 300 -> exceeded
    assert _evaluate_alerts(user_id).created == 1

    assert [(r[1], r[2]) for r in _rows(user_id)] == [
        ("watch", "2026-10-01"), ("at_risk", "2026-10-01"), ("exceeded", "2026-10-01"),
    ]

    # De-escalation never alerts, and the same level again inside the period never re-alerts.
    response = client.delete(f"/api/v1/expenses/{watch_expense}", headers=auth_headers(user_id))
    assert response.status_code == 204
    assert _evaluate_alerts(user_id).created == 0
    assert len(_rows(user_id)) == 3


def test_a_direct_jump_to_exceeded_alerts_only_the_exceeded_level(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id, budget, rule = _budget_setup(client)
    _expense(client, user_id, "400.00")

    assert _evaluate_alerts(user_id).created == 1
    assert [(r[1]) for r in _rows(user_id)] == ["exceeded"]


def test_a_new_budget_period_starts_clean(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, budget, rule = _budget_setup(client)
    monkeypatch.setattr(financial_event_service, "server_today", lambda: TODAY)
    _expense(client, user_id, "400.00")
    assert _evaluate_alerts(user_id).created == 1

    november = date(2026, 11, 10)
    monkeypatch.setattr(financial_event_service, "server_today", lambda: november)
    assert _evaluate_alerts(user_id).created == 0  # nothing spent in November yet
    _expense(client, user_id, "400.00", november)
    assert _evaluate_alerts(user_id).created == 1

    assert [r[2] for r in _rows(user_id)] == ["2026-10-01", "2026-11-01"]


def test_a_disabled_or_inactive_budget_rule_does_not_alert(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id, budget, rule = _budget_setup(client)
    _expense(client, user_id, "400.00")
    assert action(client, user_id, rule["id"], "pause").status_code == 200

    assert _evaluate_alerts(user_id).created == 0
    assert action(client, user_id, rule["id"], "enable").status_code == 200
    assert _evaluate_alerts(user_id).created == 1


def test_budget_status_for_selected_budgets_matches_the_full_status(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    from app.modules.analytics import analytics_service

    user_id, budget, rule = _budget_setup(client)
    other = create_budget(client, user_id, name="Other", limit_amount=50)
    _expense(client, user_id, "90.00")
    _expense(client, user_id, "60.00", date(2026, 9, 20))  # outside the October window

    with SessionLocal() as session:
        full = {i.budget_id: i for i in analytics_service.get_budget_status(session, UUID(user_id), TODAY)}
        selected = analytics_service.get_budget_status_for_budgets(session, UUID(user_id), [UUID(budget["id"])], TODAY)

    assert len(selected) == 1 and selected[0] == full[UUID(budget["id"])]
    assert str(other["id"]) in {str(k) for k in full}


# ------------------------------------------------------------------
# API: list, acknowledge, ownership, history
# ------------------------------------------------------------------


def _one_alert(client: TestClient):
    user_id, account, goal, rule = _floor_setup(client)
    _reserve(client, user_id, goal["id"], account["id"], "800.00")
    _evaluate_alerts(user_id)
    return user_id, account, goal, rule, _alerts(client, user_id)["items"][0]


def test_list_and_acknowledge_are_user_scoped_and_idempotent(client: TestClient, clean_database: None) -> None:
    user_id, account, goal, rule, alert = _one_alert(client)
    stranger = str(uuid4())

    assert alert["subject_name"] == "Main Checking" and alert["rule_id"] == rule["id"]
    assert alert["level"] == "breached" and alert["period_key"] == "E1" and alert["acknowledged_at"] is None
    assert _alerts(client, stranger)["total"] == 0
    assert _ack(client, stranger, alert["id"]).status_code == 404
    assert _ack(client, user_id, str(uuid4())).status_code == 404  # indistinguishable

    first = _ack(client, user_id, alert["id"])
    assert first.status_code == 200 and first.json()["acknowledged_at"]
    second = _ack(client, user_id, alert["id"])
    assert second.json()["acknowledged_at"] == first.json()["acknowledged_at"]  # the first time is kept

    assert _alerts(client, user_id, acknowledged=False)["total"] == 0
    assert _alerts(client, user_id, acknowledged=True)["total"] == 1
    # Acknowledging does not end the episode, so no duplicate alert appears.
    assert _evaluate_alerts(user_id).created == 0 and _alerts(client, user_id)["total"] == 1


def test_endpoints_require_authentication_and_bound_the_page(client: TestClient, clean_database: None) -> None:
    assert client.get(ALERTS_URL).status_code == 401
    assert client.post(f"{ALERTS_URL}/{uuid4()}/acknowledge").status_code == 401
    user_id = str(uuid4())
    assert client.get(ALERTS_URL + "?limit=0", headers=auth_headers(user_id)).status_code == 422
    assert client.get(ALERTS_URL + "?limit=101", headers=auth_headers(user_id)).status_code == 422
    assert client.post(f"{ALERTS_URL}/not-a-uuid/acknowledge", headers=auth_headers(user_id)).status_code == 422


def test_alert_history_survives_the_deletion_of_its_rule(client: TestClient, clean_database: None) -> None:
    user_id, account, goal, rule, alert = _one_alert(client)
    assert action(client, user_id, rule["id"], "disable").status_code == 200

    assert delete_rule(client, user_id, rule["id"]).status_code == 204  # no execution history: still deletable

    kept = _alerts(client, user_id)["items"][0]
    assert kept["id"] == alert["id"] and kept["rule_id"] is None and kept["rule_type"] == "MINIMUM_UNALLOCATED_FLOOR"
    assert _ack(client, user_id, alert["id"]).status_code == 200


def test_the_subject_name_is_null_after_the_budget_is_deleted(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id, budget, rule = _budget_setup(client)
    _expense(client, user_id, "400.00")
    _evaluate_alerts(user_id)
    assert _alerts(client, user_id)["items"][0]["subject_name"] == "Food budget"
    assert action(client, user_id, rule["id"], "disable").status_code == 200
    assert delete_rule(client, user_id, rule["id"]).status_code == 204
    assert client.delete(f"/api/v1/budgets/{budget['id']}", headers=auth_headers(user_id)).status_code == 204

    alert = _alerts(client, user_id)["items"][0]
    assert alert["subject_name"] is None and alert["level"] == "exceeded"


def test_evaluate_reports_alert_counters_and_never_changes_money(client: TestClient, clean_database: None) -> None:
    user_id, account, goal, rule = _floor_setup(client)
    _reserve(client, user_id, goal["id"], account["id"], "800.00")
    before = account_view(client, user_id, account["id"])
    tx_before = scalar("SELECT count(*) FROM goal_transactions")
    ledger_before = scalar("SELECT count(*) FROM account_transactions")

    body = evaluate(client, user_id).json()

    assert (body["alerts_available"], body["alerts_created"], body["alerts_resolved"]) == (True, 1, 0)
    assert evaluate(client, user_id).json()["alerts_created"] == 0
    after = account_view(client, user_id, account["id"])
    assert {k: after[k] for k in after if k != "updated_at"} == {k: before[k] for k in before if k != "updated_at"}
    assert scalar("SELECT count(*) FROM goal_transactions") == tx_before
    assert scalar("SELECT count(*) FROM account_transactions") == ledger_before


def test_the_best_effort_drain_also_detects_alerts(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, account, goal, rule = _floor_setup(client, opening="1500.00", floor="1000.00")
    _reserve(client, user_id, goal["id"], account["id"], "800.00")
    monkeypatch.setattr(settings, "rule_event_background_dispatch", True)

    post_income(client, user_id, "1.00", account["id"])  # response sent, then drain + alert evaluation

    assert _alerts(client, user_id)["total"] == 1


# ------------------------------------------------------------------
# Staged availability and failure isolation
# ------------------------------------------------------------------


def test_without_the_alert_schema_everything_degrades_gracefully(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, account, goal, rule = _floor_setup(client)
    _reserve(client, user_id, goal["id"], account["id"], "800.00")
    statements: list[str] = []

    from sqlalchemy import event

    @event.listens_for(engine, "before_cursor_execute")
    def capture(_c, _cur, statement, *_args):  # noqa: ANN001
        statements.append(statement)

    try:
        monkeypatch.setattr(rule_alert_repository, "table_exists", lambda _session: False)
        body = evaluate(client, user_id).json()
        listing = _alerts(client, user_id)
        ack = _ack(client, user_id, str(uuid4()))
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert body["alerts_available"] is False and body["alerts_created"] == 0
    assert listing == {"items": [], "total": 0, "limit": 20, "offset": 0, "available": False}
    assert ack.status_code == 404
    assert not [s for s in statements if "FROM rule_alerts" in s or "INTO rule_alerts" in s or "UPDATE rule_alerts" in s]


def test_an_alert_failure_never_hides_the_drain_result(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="1000.00")
    post_income(client, user_id, "1.00", account["id"])

    def explode(*_args, **_kwargs):
        raise RuntimeError("alert storage failure")

    monkeypatch.setattr(rule_alert_service, "evaluate_user_alerts", explode)
    body = evaluate(client, user_id).json()

    assert body["processed"] == 1 and body["alerts_available"] is False


def test_a_failed_evaluation_rolls_back_every_alert_write(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="1000.00")
    goal = goal_with_target(client, user_id, "G", 5000)
    _enable(client, user_id, floor_payload(account["id"], "900.00"))
    _enable(client, user_id, overcommitment_payload(account["id"]))
    _reserve(client, user_id, goal["id"], account["id"], "500.00")
    _debit(client, user_id, account["id"], "700.00")  # both breached
    original = rule_alert_repository.insert_alert_if_absent
    calls = {"count": 0}

    def fail_second(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("crash between the two alerts")
        return original(*args, **kwargs)

    monkeypatch.setattr(rule_alert_repository, "insert_alert_if_absent", fail_second)
    with pytest.raises(RuntimeError):
        _evaluate_alerts(user_id)
    assert scalar("SELECT count(*) FROM rule_alerts") == 0  # the first insert was rolled back too

    monkeypatch.setattr(rule_alert_repository, "insert_alert_if_absent", original)
    assert _evaluate_alerts(user_id).created == 2


# ------------------------------------------------------------------
# Concurrency
# ------------------------------------------------------------------


def _run(jobs: list[Callable[[], Any]]) -> list[Any]:
    barrier = threading.Barrier(len(jobs))
    results: list[Any] = [None] * len(jobs)

    def worker(index: int) -> None:
        barrier.wait(timeout=60)
        try:
            results[index] = jobs[index]()
        except Exception as error:  # noqa: BLE001
            results[index] = error

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(jobs))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive(), "possible deadlock"
    return results


def test_parallel_evaluations_create_exactly_one_alert_per_key(client: TestClient, clean_database: None) -> None:
    for _ in range(3):
        user_id, account, goal, rule = _floor_setup(client)
        _reserve(client, user_id, goal["id"], account["id"], "800.00")

        results = _run([lambda uid=user_id: _evaluate_alerts(uid) for _ in range(6)])

        assert not [r for r in results if isinstance(r, Exception)], results
        assert sum(r.created for r in results) == 1
        assert len(_rows(user_id)) == 1


def test_parallel_budget_evaluations_alert_each_level_once(
    client: TestClient, clean_database: None, fixed_today: date,
) -> None:
    user_id, budget, rule = _budget_setup(client)
    _expense(client, user_id, "400.00")

    results = _run([lambda: _evaluate_alerts(user_id) for _ in range(6)])

    assert not [r for r in results if isinstance(r, Exception)], results
    assert sum(r.created for r in results) == 1 and len(_rows(user_id)) == 1


def test_two_users_evaluate_independently(client: TestClient, clean_database: None) -> None:
    first = _floor_setup(client)
    second = _floor_setup(client)
    for user_id, account, goal, _ in (first, second):
        _reserve(client, user_id, goal["id"], account["id"], "800.00")

    results = _run([lambda: _evaluate_alerts(first[0]), lambda: _evaluate_alerts(second[0])])

    assert [r.created for r in results] == [1, 1]
    assert _alerts(client, first[0])["total"] == 1 and _alerts(client, second[0])["total"] == 1
