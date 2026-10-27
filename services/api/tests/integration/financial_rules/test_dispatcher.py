import json
import os
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db.database_session import SessionLocal, engine
from app.modules.financial_events import financial_event_processor as processor
from app.modules.financial_events import financial_event_queue_repository as queue
from app.modules.financial_events import financial_event_service
from app.modules.financial_rules import dispatcher, rule_alert_repository, rule_alert_service
from app.modules.financial_rules.dispatcher import DispatcherConfig
from tests.helpers import auth_headers, create_budget
from tests.integration.financial_rules.execution_helpers import (
    enabled_rule,
    evaluate,
    executions,
    funded_account,
    goal_with_target,
    post_income,
    scalar,
)
from tests.integration.financial_rules.rule_helpers import action, create_rule, floor_payload
from tests.integration.financial_rules.test_auto_execution import _reserve
from tests.integration.financial_rules.test_event_queue import _ids, _row, _set, _status

# VF-020E10 periodic dispatcher tests against real PostgreSQL. The pass runs
# in-process through run_once (the same code the CLI runs) and the CLI contract
# (exit codes, summary line) through a real subprocess. Every user's effect is
# produced by the REUSED E7/E8/E9B services: these tests prove discovery,
# fairness, isolation, failure handling and idempotency of the new runner.

API_DIR = Path(__file__).resolve().parents[3]
CONFIG = DispatcherConfig()


def _run(config: DispatcherConfig = CONFIG, **kwargs: Any) -> dispatcher.DispatcherSummary:
    return dispatcher.run_once(config, **kwargs)


def _auto_user(client: TestClient, amount: str = "10.00", opening: str = "2000.00"):
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening=opening)
    goal = goal_with_target(client, user_id, "G", 5000)
    rule = enabled_rule(client, user_id, account["id"], [goal["id"]],
                        targets=[{"goal_id": goal["id"], "amount_or_cap": "100.00"}])
    post_income(client, user_id, amount, account["id"])
    return user_id, account, goal, rule


def _tx(user_id: str) -> int:
    return scalar("SELECT count(*) FROM goal_transactions WHERE user_id = :u AND rule_execution_id IS NOT NULL", u=user_id)


def _cli(extra_env: Optional[dict[str, str]] = None) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    environment.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-m", "app.modules.financial_rules.dispatcher"],
        cwd=str(API_DIR), env=environment, capture_output=True, text=True, timeout=120,
    )


def _summary_of(result: subprocess.CompletedProcess) -> dict[str, Any]:
    line = [l for l in result.stdout.splitlines() if "dispatcher_summary" in l][-1]
    return json.loads(line.split("dispatcher_summary ", 1)[1])


# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------


def test_defaults_are_bounded_and_documented() -> None:
    config = dispatcher.load_config({})

    assert (config.enabled, config.max_users, config.max_events_per_user) == (True, 50, 20)
    assert (config.max_alert_users, config.time_budget_seconds) == (200, 240)


@pytest.mark.parametrize(
    "environment",
    [
        {"RULE_DISPATCHER_MAX_USERS": "0"}, {"RULE_DISPATCHER_MAX_USERS": "1001"},
        {"RULE_DISPATCHER_MAX_USERS": "abc"}, {"RULE_DISPATCHER_MAX_EVENTS_PER_USER": "101"},
        {"RULE_DISPATCHER_MAX_ALERT_USERS": "0"}, {"RULE_DISPATCHER_TIME_BUDGET_SECONDS": "4"},
        {"RULE_DISPATCHER_ENABLED": "maybe"},
    ],
)
def test_invalid_configuration_is_rejected_before_any_work(environment: dict[str, str]) -> None:
    with pytest.raises(dispatcher.DispatcherConfigError):
        dispatcher.load_config(environment)


def test_importing_the_module_has_no_side_effects() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import app.modules.financial_rules.dispatcher as d; print(d.__name__)"],
        cwd=str(API_DIR), env=dict(os.environ), capture_output=True, text=True, timeout=60,
    )

    assert result.returncode == 0 and result.stdout.strip() == "app.modules.financial_rules.dispatcher"
    assert "dispatcher_summary" not in result.stdout + result.stderr


# ------------------------------------------------------------------
# Discovery, FIFO, leases, retries
# ------------------------------------------------------------------


def test_an_empty_queue_is_a_successful_noop(client: TestClient, clean_database: None) -> None:
    summary = _run()

    assert summary.outcome == "noop" and dispatcher.exit_code_for(summary) == 0
    assert (summary.users_considered, summary.events_processed) == (0, 0)


def test_one_pending_event_is_processed_with_the_auto_rule(client: TestClient, clean_database: None) -> None:
    user_id, account, goal, rule = _auto_user(client)

    summary = _run()

    assert summary.outcome == "success" and summary.events_processed == 1 and summary.users_processed == 1
    assert summary.execution_outcomes == {"executed": 1}
    assert _tx(user_id) == 1  # AUTO allocation correctness: one rule-generated contribution
    assert executions(client, user_id)["items"][0]["status"] == "executed"


def test_several_users_are_processed_independently(client: TestClient, clean_database: None) -> None:
    users = [_auto_user(client)[0] for _ in range(3)]

    summary = _run()

    assert (summary.users_considered, summary.events_processed) == (3, 3)
    assert [_tx(u) for u in users] == [1, 1, 1]


def test_strict_fifo_is_kept_when_the_per_user_cap_is_one(client: TestClient, clean_database: None) -> None:
    user_id, account, goal, rule = _auto_user(client)
    post_income(client, user_id, "20.00", account["id"])
    first, second = _ids(user_id)

    one = _run(DispatcherConfig(max_events_per_user=1))

    assert one.events_processed == 1 and _status(first) == "processed" and _status(second) == "pending"
    assert _run(DispatcherConfig(max_events_per_user=1)).events_processed == 1
    assert _status(second) == "processed"


def test_a_waiting_retry_blocks_the_newer_event_and_the_user_is_not_a_candidate(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, goal, rule = _auto_user(client)
    post_income(client, user_id, "20.00", account["id"])
    first, second = _ids(user_id)
    _set(first, status="'failed_retryable'", attempts="1", next_attempt_at="now() + interval '10 minutes'")

    with SessionLocal() as session:
        assert queue.discover_users_with_progressing_head(session, 10) == []  # head first, then claimability
    summary = _run()

    assert summary.outcome == "noop" and _status(second) == "pending" and _tx(user_id) == 0


def test_a_live_lease_blocks_newer_events(client: TestClient, clean_database: None) -> None:
    user_id, account, goal, rule = _auto_user(client)
    post_income(client, user_id, "20.00", account["id"])
    first, second = _ids(user_id)
    _set(first, status="'processing'", attempts="1", claim_token="gen_random_uuid()",
         lease_expires_at="now() + interval '5 minutes'")

    summary = _run()

    assert summary.users_considered == 0 and _status(second) == "pending"


def test_a_future_not_before_does_not_block_a_due_event(client: TestClient, clean_database: None) -> None:
    user_id, account, goal, rule = _auto_user(client)
    post_income(client, user_id, "20.00", account["id"])
    first, second = _ids(user_id)
    _set(first, not_before="now() + interval '2 days'")

    summary = _run()

    assert summary.events_processed == 1 and _status(first) == "pending" and _status(second) == "processed"


def test_an_expired_lease_is_recovered_and_processed(client: TestClient, clean_database: None) -> None:
    user_id, account, goal, rule = _auto_user(client)
    (event_id,) = _ids(user_id)
    _set(event_id, status="'processing'", attempts="2", claim_token="gen_random_uuid()",
         lease_expires_at="now() - interval '1 second'")

    summary = _run()

    assert summary.events_processed == 1 and _row(event_id)["attempts"] == 3 and _tx(user_id) == 1


def test_an_abandoned_sixth_attempt_lease_becomes_dead_and_the_run_reports_it(
    client: TestClient, clean_database: None,
) -> None:
    user_id, account, goal, rule = _auto_user(client)
    post_income(client, user_id, "20.00", account["id"])
    first, second = _ids(user_id)
    _set(first, status="'processing'", attempts="6", claim_token="gen_random_uuid()",
         lease_expires_at="now() - interval '1 second'")

    summary = _run()

    row = _row(first)
    assert row["status"] == "dead" and row["attempts"] == 6 and row["last_error_code"] == "lease_expired_max_attempts"
    assert _status(second) == "processed"  # dead no longer blocks
    # The recovery to `dead` is counted and surfaces as a failed run for operators.
    assert summary.events_dead == 1 and summary.events_processed == 1
    assert summary.outcome == "completed_with_failures" and dispatcher.exit_code_for(summary) == 3


# ------------------------------------------------------------------
# Idempotency and concurrency
# ------------------------------------------------------------------


def test_a_duplicate_invocation_never_duplicates_money(client: TestClient, clean_database: None) -> None:
    user_id, *_ = _auto_user(client)

    first, second = _run(), _run()

    assert first.events_processed == 1 and second.events_processed == 0 and second.outcome == "noop"
    assert _tx(user_id) == 1 and executions(client, user_id)["total"] == 1


def _threads(jobs: list[Callable[[], Any]]) -> list[Any]:
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


def test_racing_dispatchers_and_a_user_evaluate_produce_one_effect(client: TestClient, clean_database: None) -> None:
    for _ in range(3):
        user_id, account, goal, rule = _auto_user(client)
        post_income(client, user_id, "20.00", account["id"])

        def manual() -> processor.DrainSummary:
            with SessionLocal() as session:
                return processor.drain_user_events(session, UUID(user_id))

        results = _threads([_run, _run, manual, _run])

        assert not [r for r in results if isinstance(r, Exception)], results
        assert _tx(user_id) == 2 and scalar("SELECT count(*) FROM rule_executions WHERE user_id = :u", u=user_id) == 2
        assert scalar("SELECT count(*) FROM financial_events WHERE user_id = :u AND status = 'processed' AND attempts = 1", u=user_id) == 2


def test_a_background_drain_overlapping_the_dispatcher_is_safe(client: TestClient, clean_database: None) -> None:
    user_id, *_ = _auto_user(client)

    results = _threads([_run, lambda: processor.dispatch_user_events_best_effort(UUID(user_id)), _run])

    assert not [r for r in results if isinstance(r, Exception)], results
    assert _tx(user_id) == 1


# ------------------------------------------------------------------
# CONFIRM and expiry
# ------------------------------------------------------------------


def _confirm_user(client: TestClient):
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="600.00")
    goal = goal_with_target(client, user_id, "G", 5000)
    rule = enabled_rule(client, user_id, account["id"], [goal["id"]], execution_mode="CONFIRM",
                        targets=[{"goal_id": goal["id"], "amount_or_cap": "100.00"}])
    post_income(client, user_id, "0.01", account["id"])
    return user_id, account, goal, rule


def test_a_confirm_rule_creates_a_proposal_and_moves_no_money(client: TestClient, clean_database: None) -> None:
    user_id, account, goal, rule = _confirm_user(client)
    ledger = scalar("SELECT count(*) FROM account_transactions")

    summary = _run()

    assert summary.execution_outcomes == {"awaiting_confirmation": 1}
    assert _tx(user_id) == 0 and scalar("SELECT count(*) FROM account_transactions") == ledger
    assert scalar("SELECT status FROM rule_executions WHERE user_id = :u", u=user_id) == "awaiting_confirmation"


def test_an_expired_proposal_is_normalized_at_dispatch_and_stops_holding(client: TestClient, clean_database: None) -> None:
    user_id, account, goal, rule = _confirm_user(client)
    _run()
    with engine.begin() as connection:
        connection.execute(text("UPDATE rule_executions SET expires_at = now() - interval '1 second'"))
    held = client.get("/api/v1/accounts", headers=auth_headers(user_id)).json()[0]["active_rule_holds"]
    assert held == "0.00"  # the hold stopped counting even before normalization

    post_income(client, user_id, "0.01", account["id"])
    _run()

    row = scalar("SELECT status FROM rule_executions WHERE user_id = :u ORDER BY created_at LIMIT 1", u=user_id)
    assert row == "expired"
    assert scalar("SELECT hold_sequence IS NOT NULL AND expires_at IS NOT NULL FROM rule_executions "
                  "WHERE status = 'expired'") is True
    assert _tx(user_id) == 0  # expiry performs no financial operation


# ------------------------------------------------------------------
# Alerts without Income
# ------------------------------------------------------------------


def _floor_user(client: TestClient):
    user_id = str(uuid4())
    account = funded_account(client, user_id, opening="1500.00")
    goal = goal_with_target(client, user_id, "G", 5000)
    rule = create_rule(client, user_id, floor_payload(account["id"], "1000.00"))
    assert action(client, user_id, rule["id"], "enable").status_code == 200
    _reserve(client, user_id, goal["id"], account["id"], "800.00")
    return user_id, account, goal


def _alert_count(user_id: str) -> int:
    return scalar("SELECT count(*) FROM rule_alerts WHERE user_id = :u", u=user_id)


def test_a_floor_alert_is_detected_without_any_income_event(client: TestClient, clean_database: None) -> None:
    user_id, account, goal = _floor_user(client)
    assert scalar("SELECT count(*) FROM financial_events") == 0

    summary = _run()

    assert summary.alerts_created == 1 and summary.alert_users_evaluated == 1 and summary.users_considered == 0
    assert _alert_count(user_id) == 1


def test_repeated_runs_never_duplicate_an_alert(client: TestClient, clean_database: None) -> None:
    user_id, *_ = _floor_user(client)

    totals = [_run().alerts_created for _ in range(4)]

    assert totals == [1, 0, 0, 0] and _alert_count(user_id) == 1


def test_a_budget_threshold_is_detected_without_income(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(financial_event_service, "server_today", lambda: date(2026, 10, 10))
    user_id = str(uuid4())
    budget = create_budget(client, user_id, limit_amount=300)
    rule = create_rule(client, user_id, {"rule_type": "BUDGET_ALERT", "name": "B", "budget_id": budget["id"]})
    assert action(client, user_id, rule["id"], "enable").status_code == 200
    expense = client.post("/api/v1/expenses", headers=auth_headers(user_id), json={
        "category_id": None, "title": "x", "amount": "400.00", "currency": "EUR",
        "expense_date": "2026-10-10", "description": "x", "source": "manual"})
    assert expense.status_code == 201

    summary = _run()

    assert summary.alerts_created == 1
    assert scalar("SELECT level FROM rule_alerts WHERE user_id = :u", u=user_id) == "exceeded"
    assert _run().alerts_created == 0


def test_only_users_with_an_enabled_alert_rule_are_discovered(client: TestClient, clean_database: None) -> None:
    alert_user, *_ = _floor_user(client)
    plain = str(uuid4())
    funded_account(client, plain, opening="100.00")
    paused_user = str(uuid4())
    paused_account = funded_account(client, paused_user, opening="100.00")
    paused = create_rule(client, paused_user, floor_payload(paused_account["id"], "10.00"))  # draft: not enabled

    summary = _run()

    assert summary.alert_users_considered == 1 and paused["status"] == "draft"
    assert _alert_count(alert_user) == 1 and _alert_count(plain) == 0


def test_a_missing_alert_table_is_not_a_failure_and_does_not_stop_events(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, *_ = _auto_user(client)
    monkeypatch.setattr(rule_alert_repository, "table_exists", lambda _session: False)

    summary = _run()

    assert summary.alerts_unavailable is True and summary.alert_failures == 0
    assert summary.events_processed == 1 and summary.outcome == "success" and dispatcher.exit_code_for(summary) == 0
    assert _tx(user_id) == 1


def test_a_real_alert_failure_is_reported_as_a_failure_not_as_unavailable(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, *_ = _floor_user(client)

    def explode(*_args, **_kwargs):
        raise RuntimeError("alert storage failure")

    monkeypatch.setattr(rule_alert_service, "evaluate_user_alerts", explode)
    summary = _run()

    assert summary.alert_failures == 1 and summary.alerts_unavailable is False
    assert summary.outcome == "completed_with_failures" and dispatcher.exit_code_for(summary) == 3
    assert _alert_count(user_id) == 0


# ------------------------------------------------------------------
# Failure isolation, fairness, budgets
# ------------------------------------------------------------------


def test_one_failing_user_does_not_starve_or_abort_the_others(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad, *_ = _auto_user(client)
    good = [_auto_user(client)[0] for _ in range(2)]
    original = processor.drain_user_events

    def selective(session, user_id, limit=20):
        if str(user_id) == bad:
            raise RuntimeError("injected user failure")
        return original(session, user_id, limit)

    monkeypatch.setattr(processor, "drain_user_events", selective)
    summary = _run()

    assert summary.user_failures == 1 and summary.users_processed == 2 and summary.events_processed == 2
    assert [_tx(u) for u in good] == [1, 1] and _tx(bad) == 0
    assert summary.outcome == "completed_with_failures" and dispatcher.exit_code_for(summary) == 3

    monkeypatch.setattr(processor, "drain_user_events", original)
    assert _run().events_processed == 1 and _tx(bad) == 1  # the failed user recovers next run


def test_a_technical_event_failure_is_reported_and_retried_later(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.financial_rules import rule_execution_service

    user_id, *_ = _auto_user(client)
    original = rule_execution_service.process_event

    def fail(*_args, **_kwargs):
        raise RuntimeError("injected technical failure")

    monkeypatch.setattr(rule_execution_service, "process_event", fail)
    summary = _run()
    assert summary.events_failed_retryable == 1 and summary.outcome == "completed_with_failures"
    assert _tx(user_id) == 0

    monkeypatch.setattr(rule_execution_service, "process_event", original)
    (event_id,) = _ids(user_id)
    _set(event_id, next_attempt_at="now() - interval '1 second'")
    assert _run().events_processed == 1 and _tx(user_id) == 1


def test_the_batch_is_bounded_and_backlog_users_are_served_oldest_head_first(
    client: TestClient, clean_database: None,
) -> None:
    users = [_auto_user(client)[0] for _ in range(5)]  # created oldest -> newest
    config = DispatcherConfig(max_users=2)

    first = _run(config)
    assert first.users_considered == 2 and [_tx(u) for u in users] == [1, 1, 0, 0, 0]
    second = _run(config)
    assert second.users_considered == 2 and [_tx(u) for u in users] == [1, 1, 1, 1, 0]
    assert _run(config).users_considered == 1 and [_tx(u) for u in users] == [1, 1, 1, 1, 1]
    assert _run(config).outcome == "noop"  # nobody starved beyond the first page


def test_the_time_budget_stops_the_pass_without_failing(client: TestClient, clean_database: None) -> None:
    for _ in range(3):
        _auto_user(client)
    ticks = iter([0, 0, 1000, 1000, 1000, 1000, 1000, 1000])  # the budget is spent after the first user

    summary = _run(DispatcherConfig(time_budget_seconds=5), monotonic=lambda: next(ticks))

    assert summary.budget_exhausted is True and summary.users_processed == 1
    assert summary.outcome == "success" and dispatcher.exit_code_for(summary) == 0
    assert _run().events_processed == 2  # the rest is picked up by the next run


def test_cross_user_isolation_a_user_without_events_is_never_touched(client: TestClient, clean_database: None) -> None:
    worker, *_ = _auto_user(client)
    bystander = str(uuid4())
    account = funded_account(client, bystander, opening="2000.00")
    goal = goal_with_target(client, bystander, "G", 5000)
    enabled_rule(client, bystander, account["id"], [goal["id"]])  # an enabled rule but NO income event
    before = scalar("SELECT count(*) FROM goal_transactions WHERE user_id = :u", u=bystander)

    _run()

    assert _tx(worker) == 1 and scalar("SELECT count(*) FROM goal_transactions WHERE user_id = :u", u=bystander) == before
    assert scalar("SELECT count(*) FROM rule_executions WHERE user_id = :u", u=bystander) == 0


# ------------------------------------------------------------------
# Database failure and recovery
# ------------------------------------------------------------------


def test_a_discovery_connection_failure_is_fatal_and_the_next_run_recovers(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, *_ = _auto_user(client)
    original = queue.discover_users_with_progressing_head

    def down(*_args, **_kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(queue, "discover_users_with_progressing_head", down)
    summary = _run()
    assert summary.outcome == "fatal" and dispatcher.exit_code_for(summary) == 1 and _tx(user_id) == 0

    monkeypatch.setattr(queue, "discover_users_with_progressing_head", original)
    recovered = _run()
    assert recovered.events_processed == 1 and _tx(user_id) == 1


def test_repeated_connection_errors_while_draining_abort_the_pass(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for _ in range(5):
        _auto_user(client)
    calls = {"count": 0}

    def down(*_args, **_kwargs):
        calls["count"] += 1
        raise OperationalError("SELECT 1", {}, Exception("connection lost"))

    monkeypatch.setattr(processor, "drain_user_events", down)
    summary = _run()

    assert summary.outcome == "fatal" and calls["count"] == dispatcher.MAX_CONSECUTIVE_CONNECTION_ERRORS


# ------------------------------------------------------------------
# CLI process contract
# ------------------------------------------------------------------


def test_the_cli_processes_work_and_exits_zero_with_a_summary_line(client: TestClient, clean_database: None) -> None:
    user_id, *_ = _auto_user(client)

    result = _cli()

    assert result.returncode == 0, result.stdout + result.stderr
    summary = _summary_of(result)
    assert summary["outcome"] == "success" and summary["events_processed"] == 1
    assert _tx(user_id) == 1
    assert "postgresql://" not in result.stdout + result.stderr and "password" not in (result.stdout + result.stderr).lower()


def test_the_cli_exits_zero_for_an_empty_queue(client: TestClient, clean_database: None) -> None:
    result = _cli()

    assert result.returncode == 0 and _summary_of(result)["outcome"] == "noop"


def test_the_cli_can_be_disabled_without_touching_the_database(client: TestClient, clean_database: None) -> None:
    user_id, *_ = _auto_user(client)

    result = _cli({"RULE_DISPATCHER_ENABLED": "false"})

    assert result.returncode == 0 and _summary_of(result)["outcome"] == "disabled" and _tx(user_id) == 0


def test_the_cli_exits_two_on_invalid_configuration_before_any_work(client: TestClient, clean_database: None) -> None:
    user_id, *_ = _auto_user(client)

    result = _cli({"RULE_DISPATCHER_MAX_USERS": "0"})

    assert result.returncode == 2 and "dispatcher_summary" not in result.stdout and _tx(user_id) == 0


def test_the_cli_exits_one_when_the_database_is_unreachable(client: TestClient, clean_database: None) -> None:
    url = engine.url.set(database="valor_dispatcher_missing_test").render_as_string(hide_password=False)

    result = _cli({"DATABASE_URL": url})

    assert result.returncode == 1, result.stdout + result.stderr
    assert _summary_of(result)["outcome"] == "fatal"
    assert "postgresql://" not in result.stdout + result.stderr  # the URL is never printed
    assert "postgres:postgres" not in result.stdout + result.stderr


def test_the_cli_exits_three_when_the_run_completed_with_a_dead_event(client: TestClient, clean_database: None) -> None:
    user_id, account, goal, rule = _auto_user(client)
    (event_id,) = _ids(user_id)
    _set(event_id, status="'failed_retryable'", attempts="5", next_attempt_at="now() - interval '1 second'")
    from app.modules.financial_rules import rule_execution_service  # noqa: F401

    # A real sixth failure needs a failing processor; emulate it in a subprocess-free way:
    original = rule_execution_service.process_event

    def fail(*_args, **_kwargs):
        raise RuntimeError("injected")

    rule_execution_service.process_event = fail
    try:
        summary = _run()
    finally:
        rule_execution_service.process_event = original

    assert summary.events_dead == 1 and summary.outcome == "completed_with_failures"
    assert dispatcher.exit_code_for(summary) == 3 and _row(event_id)["status"] == "dead"


# ------------------------------------------------------------------
# Review follow-ups: failures must never look like success
# ------------------------------------------------------------------


def test_a_failure_that_cannot_be_recorded_is_still_reported(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.financial_rules import rule_execution_service

    user_id, *_ = _auto_user(client)

    def fail(*_args, **_kwargs):
        raise RuntimeError("processing failed")

    def cannot_record(*_args, **_kwargs):
        raise OperationalError("UPDATE", {}, Exception("connection lost"))

    monkeypatch.setattr(rule_execution_service, "process_event", fail)
    monkeypatch.setattr(queue, "record_technical_failure", cannot_record)
    summary = _run()

    assert summary.events_unrecorded_failures == 1 and summary.events_processed == 0
    assert summary.outcome == "completed_with_failures" and dispatcher.exit_code_for(summary) == 3
    assert _tx(user_id) == 0  # nothing partial; the lease simply expires


def test_repeated_unrecorded_failures_are_a_fatal_database_outage(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.financial_rules import rule_execution_service

    for _ in range(4):
        _auto_user(client)

    def fail(*_args, **_kwargs):
        raise RuntimeError("processing failed")

    def cannot_record(*_args, **_kwargs):
        raise OperationalError("UPDATE", {}, Exception("connection lost"))

    monkeypatch.setattr(rule_execution_service, "process_event", fail)
    monkeypatch.setattr(queue, "record_technical_failure", cannot_record)
    summary = _run()

    assert summary.outcome == "fatal" and dispatcher.exit_code_for(summary) == 1


def test_consecutive_alert_failures_are_systemic_and_fatal(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for _ in range(4):
        _floor_user(client)

    def explode(*_args, **_kwargs):
        raise RuntimeError("alert storage failure")

    monkeypatch.setattr(rule_alert_service, "evaluate_user_alerts", explode)
    summary = _run()

    assert summary.outcome == "fatal" and summary.alert_failures == dispatcher.MAX_CONSECUTIVE_FAILURES


def test_alert_evaluation_keeps_a_reserved_share_of_the_time_budget(client: TestClient, clean_database: None) -> None:
    _floor_user(client)
    for _ in range(3):
        _auto_user(client)
    # Budget 100 s -> events stop at 80 s, alerts may run until 100 s.
    clock = iter([0, 0, 85, 90, 90, 90, 90, 90, 90, 90, 90, 90])

    summary = _run(DispatcherConfig(time_budget_seconds=100), monotonic=lambda: next(clock))

    assert summary.budget_exhausted is True
    assert summary.alert_users_evaluated == 1 and summary.alerts_created == 1



# ------------------------------------------------------------------
# VF-020E10 corrective review: alert-user liveness (HIGH / MEDIUM / LOW)
#
# The previous design picked a page by floor(time / interval) % pages in user_id
# order. Reproduced on the merged code with 6 users: when every run was cut after
# two users, only the first two were EVER evaluated (2 of 6 after 10 runs), and
# when the real cadence was 3x the configured interval, the same single page was
# visited forever (2 of 6). Stateless paging cannot give liveness under partial
# runs or missed ticks. The replacement shuffles with a fresh per-run seed
# (no clock, no cursor): an interrupted run evaluated a random prefix, and a
# skipped tick changes nothing. The guarantee is therefore: a full pass over a
# population within the cap covers everyone EVERY run; beyond that, coverage is
# almost-sure, with per-user miss probability (1 - n/M)^k after k runs. A
# deterministic bound needs persisted progress (a migration, documented as a gate).
# ------------------------------------------------------------------


def _alert_users(client: TestClient, count: int) -> list[str]:
    return [_floor_user(client)[0] for _ in range(count)]


def _covered_users(users: list[str]) -> set[str]:
    return {u for u in users if _alert_count(u) > 0}


def _cut_after(users_allowed: int):
    """A clock that lets exactly `users_allowed` alert users start, then runs out of budget."""
    calls = {"count": 0}

    def clock() -> float:
        calls["count"] += 1
        return 0.0 if calls["count"] <= 1 + users_allowed else 10_000.0

    return clock


def test_every_run_cut_midway_through_the_sample_still_covers_all_users_eventually(
    client: TestClient, clean_database: None,
) -> None:
    users = _alert_users(client, 6)
    config = DispatcherConfig(max_alert_users=6, time_budget_seconds=100)

    first = _run(config, monotonic=_cut_after(2), seed="run-0")
    assert first.alert_users_evaluated == 2 and first.budget_exhausted is True
    assert len(_covered_users(users)) == 2

    for index in range(1, 20):  # every single run is interrupted after two users
        _run(config, monotonic=_cut_after(2), seed=f"run-{index}")

    assert _covered_users(users) == set(users)  # the old design stayed at 2 of 6 forever


def test_the_first_evaluated_user_differs_between_runs_unlike_the_old_fixed_order(
    client: TestClient, clean_database: None,
) -> None:
    users = _alert_users(client, 6)

    with SessionLocal() as session:
        firsts = [
            rule_alert_repository.get_users_with_enabled_alert_rules_sample(session, 1, f"seed-{i}")[0]
            for i in range(12)
        ]
        same_seed = [
            rule_alert_repository.get_users_with_enabled_alert_rules_sample(session, 6, "fixed") for _ in range(2)
        ]

    assert len(set(firsts)) >= 3 and {str(u) for u in firsts} <= set(users)  # a moving prefix, never one fixed head
    assert same_seed[0] == same_seed[1] and sorted(map(str, same_seed[0])) == sorted(users)  # deterministic per seed


def test_delayed_or_skipped_ticks_do_not_change_coverage(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    users = _alert_users(client, 6)
    config = DispatcherConfig(max_alert_users=2)
    # The wall clock only ever jumps by whole multiples of any plausible cadence
    # (what used to make floor(time / interval) land on one page forever).
    ticks = iter(range(1_000_000, 10_000_000, 1800))
    monkeypatch.setattr(time, "time", lambda: float(next(ticks)))

    for _ in range(60):  # unseeded: a fresh random seed per run, as in production
        _run(config)

    assert _covered_users(users) == set(users)


def test_a_population_within_the_cap_is_covered_completely_by_every_run(client: TestClient, clean_database: None) -> None:
    users = _alert_users(client, 5)

    summary = _run(DispatcherConfig(max_alert_users=5), seed="any")

    assert summary.alert_users_total == 5 and summary.alert_users_evaluated == 5
    assert summary.alert_users_truncated is False and _covered_users(users) == set(users)


def test_truncation_is_visible_when_the_population_exceeds_the_cap(client: TestClient, clean_database: None) -> None:
    _alert_users(client, 5)

    summary = _run(DispatcherConfig(max_alert_users=2), seed="x")

    assert (summary.alert_users_total, summary.alert_users_considered) == (5, 2)
    assert summary.alert_users_truncated is True and summary.outcome == "success"


def test_users_added_and_removed_between_runs_are_handled(client: TestClient, clean_database: None) -> None:
    original = _alert_users(client, 4)
    config = DispatcherConfig(max_alert_users=2)
    _run(config, seed="a")

    newcomers = _alert_users(client, 2)  # joined while the group was being walked
    rules = scalar("SELECT id FROM financial_rules WHERE user_id = :u", u=original[0])
    with engine.begin() as connection:  # one user leaves (their rule is disabled)
        connection.execute(text("UPDATE financial_rules SET status = 'disabled' WHERE id = :i"), {"i": rules})

    for index in range(40):
        _run(config, seed=f"churn-{index}")

    stayers = original[1:] + newcomers
    assert _covered_users(stayers) == set(stayers)  # everyone still enabled, old or new, is reached
    leaver_alerts = _alert_count(original[0])
    assert leaver_alerts <= 1  # at most the alert from before they left; never evaluated again after disabling


class _FailingAlertSessions:
    """A session factory whose sessions work for discovery and fail for every evaluation."""

    def __init__(self, healthy_calls: int) -> None:
        self.calls = 0
        self.healthy_calls = healthy_calls

    def __call__(self):
        self.calls += 1

        if self.calls > self.healthy_calls:
            raise OperationalError("SELECT 1", {}, Exception("could not open a session"))

        return SessionLocal()


def test_three_consecutive_alert_session_failures_are_fatal(client: TestClient, clean_database: None) -> None:
    _alert_users(client, 5)
    # call 1 = event discovery, call 2 = alert discovery; every evaluation session fails.
    factory = _FailingAlertSessions(healthy_calls=2)

    summary = _run(DispatcherConfig(max_alert_users=5), session_factory=factory, seed="s")

    assert summary.outcome == "fatal" and dispatcher.exit_code_for(summary) == 1
    assert summary.alert_failures == dispatcher.MAX_CONSECUTIVE_FAILURES
    # 2 discovery sessions + one evaluation session per failed user; the session never opened, so no user lock
    # was held, no attempt identity exists and no progress write is attempted. The breaker stops any further user.
    assert factory.calls == 2 + dispatcher.MAX_CONSECUTIVE_FAILURES
    assert summary.progress_unordered_failures == dispatcher.MAX_CONSECUTIVE_FAILURES


def test_a_single_alert_session_failure_is_a_counted_failure_not_fatal(client: TestClient, clean_database: None) -> None:
    users = _alert_users(client, 3)
    seen = {"calls": 0}

    def flaky():
        seen["calls"] += 1
        if seen["calls"] == 3:  # exactly one evaluation session fails
            raise RuntimeError("transient session failure")
        return SessionLocal()

    summary = _run(DispatcherConfig(max_alert_users=3), session_factory=flaky, seed="s")

    assert summary.alert_failures == 1 and summary.alert_users_evaluated == 2
    assert summary.outcome == "completed_with_failures" and dispatcher.exit_code_for(summary) == 3
    assert len(_covered_users(users)) == 2
