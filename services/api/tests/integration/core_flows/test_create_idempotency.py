"""Income and Expense create idempotency (VF-MVP-CORE-002), through the real API and PostgreSQL.

Every scenario runs for BOTH domains (parametrized), because the two implementations must
behave identically. The reconciliation is read straight from PostgreSQL, never from the API
under test. No network: the ECB HTTP call is replaced by a counting, deterministic stub.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import create_idempotency
from app.db.database_session import SessionLocal
from app.main import app
from app.modules.financial_events import financial_event_processor
from app.modules.fx import fx_ecb_provider
from tests.helpers import auth_headers

D = "2026-03-04"  # after the stub's rate change: 1 EUR = 1.25 USD
D_EARLY = "2026-03-02"  # 1 EUR = 2.00 USD


class FxStub:
    """Deterministic ECB stand-in that counts its calls and whose rate can be changed."""

    def __init__(self) -> None:
        self.calls = 0
        self.late_rate = 1.25

    def __call__(self, url: str, params: Dict[str, str] = None, timeout: float = None) -> MagicMock:
        self.calls += 1
        end = date.fromisoformat(params["endPeriod"])
        rate = 2.0 if end <= date(2026, 3, 3) else self.late_rate
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "dataSets": [{"series": {"0:0:0:0:0": {"observations": {"0": [rate, 0, 0, None, None]}}}}],
            "structure": {"dimensions": {"observation": [{"id": "TIME_PERIOD", "values": [{"id": end.isoformat()}]}]}},
        }
        return response


@pytest.fixture(autouse=True)
def fx(monkeypatch: pytest.MonkeyPatch) -> FxStub:
    stub = FxStub()
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", stub)
    return stub


@pytest.fixture
def dispatches(monkeypatch: pytest.MonkeyPatch) -> List[Any]:
    """Records every background event dispatch the Income router schedules."""
    calls: List[Any] = []
    monkeypatch.setattr(financial_event_processor, "dispatch_user_events_best_effort", lambda user_id: calls.append(user_id))
    return calls


DOMAINS = ("income", "expense")


def _path(domain: str) -> str:
    return "/api/v1/income" if domain == "income" else "/api/v1/expenses"


def _table(domain: str) -> str:
    return "income" if domain == "income" else "expenses"


def _body(domain: str, key: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    if domain == "income":
        body: Dict[str, Any] = {"amount": "100.00", "currency": "EUR", "received_at": D, "source": "salary"}
    else:
        body = {"title": "Groceries", "amount": "100.00", "currency": "EUR", "expense_date": D}
    body.update(overrides)
    if key is not None:
        body["client_request_id"] = key
    return body


def _sql(query: str, **params: Any) -> Any:
    with SessionLocal() as session:
        return session.execute(text(query), params).scalar()


def _rows(domain: str, user: str) -> int:
    return _sql(f"select count(*) from {_table(domain)} where user_id = :u", u=user)


def _ledger_rows(account_id: str) -> int:
    return _sql("select count(*) from account_transactions where account_id = :a", a=account_id)


def _ledger_sum(account_id: str) -> Decimal:
    return Decimal(str(_sql(
        "select coalesce(sum(case direction when 'credit' then amount else -amount end), 0) "
        "from account_transactions where account_id = :a", a=account_id)))


def _account(client: TestClient, user: str, currency: str = "EUR", opening: str = "1000.00") -> Dict[str, Any]:
    response = client.post(
        "/api/v1/accounts", headers=auth_headers(user),
        json={"name": "A", "type": "checking", "currency": currency, "opening_balance": opening, "opening_balance_date": D_EARLY},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _balance(client: TestClient, user: str, account_id: str) -> str:
    return next(a["current_balance"] for a in client.get("/api/v1/accounts", headers=auth_headers(user)).json() if a["id"] == account_id)


def _expected_delta(domain: str, amount: str) -> Decimal:
    return Decimal(amount) if domain == "income" else -Decimal(amount)


def _events(user: str) -> int:
    return _sql("select count(*) from financial_events where user_id = :u", u=user)


@pytest.mark.parametrize("domain", DOMAINS)
def test_first_create_with_a_key_is_201_and_returns_the_key(client: TestClient, clean_database: None, domain: str) -> None:
    user, key = str(uuid4()), str(uuid4())

    response = client.post(_path(domain), headers=auth_headers(user), json=_body(domain, key))

    assert response.status_code == 201, response.text
    assert response.json()["client_request_id"] == key
    assert _rows(domain, user) == 1
    assert _sql(f"select client_request_fingerprint from {_table(domain)} where user_id = :u", u=user) is not None


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize("linked", [False, True])
def test_same_request_replay_returns_the_original_and_creates_nothing(
    client: TestClient, clean_database: None, dispatches: List[Any], domain: str, linked: bool,
) -> None:
    user, key = str(uuid4()), str(uuid4())
    account = _account(client, user) if linked else None
    body = _body(domain, key, **({"account_id": account["id"]} if account else {}))

    first = client.post(_path(domain), headers=auth_headers(user), json=body)
    events_after_first = _events(user)
    replay = client.post(_path(domain), headers=auth_headers(user), json=body)

    assert (first.status_code, replay.status_code) == (201, 200), replay.text
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json() == first.json()
    assert _rows(domain, user) == 1
    assert _events(user) == events_after_first  # no new outbox event
    if domain == "income":
        assert len(dispatches) == 1  # the replay scheduled no event dispatch
    if account:
        assert _ledger_rows(account["id"]) == 2  # opening balance + exactly one projection
        expected = Decimal("1000.00") + _expected_delta(domain, "100.00")
        assert _balance(client, user, account["id"]) == str(expected)
        assert _ledger_sum(account["id"]) == expected


@pytest.mark.parametrize("domain", DOMAINS)
def test_equivalent_spellings_of_the_same_request_are_a_replay(client: TestClient, clean_database: None, domain: str) -> None:
    user, key = str(uuid4()), str(uuid4())

    first = client.post(_path(domain), headers=auth_headers(user), json=_body(domain, key, amount="100"))
    replay = client.post(_path(domain), headers=auth_headers(user), json=_body(domain, key, amount="100.00", currency="eur"))

    assert (first.status_code, replay.status_code) == (201, 200), replay.text
    assert _rows(domain, user) == 1


@pytest.mark.parametrize("domain", DOMAINS)
def test_replay_does_not_resolve_fx_again_and_keeps_the_historical_snapshot(
    client: TestClient, clean_database: None, fx: FxStub, domain: str,
) -> None:
    user, key = str(uuid4()), str(uuid4())
    body = _body(domain, key, currency="USD")

    first = client.post(_path(domain), headers=auth_headers(user), json=body)
    assert first.status_code == 201, first.text
    assert (first.json()["fx_rate"], first.json()["base_amount"]) == ("0.80000000", "80.00")
    assert fx.calls == 1

    fx.late_rate = 5.0  # a re-resolution today would now produce a different snapshot
    replay = client.post(_path(domain), headers=auth_headers(user), json=body)

    assert replay.status_code == 200
    assert fx.calls == 1  # no FX call on replay
    assert (replay.json()["fx_rate"], replay.json()["base_amount"], replay.json()["fx_rate_date"]) == (
        first.json()["fx_rate"], first.json()["base_amount"], first.json()["fx_rate_date"])
    assert _sql(f"select base_amount from {_table(domain)} where user_id = :u", u=user) == Decimal("80.00")


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize(
    "change",
    [{"amount": "100.01"}, {"currency": "USD"}, {"description": "x"}, {"description": ""}],
    ids=["amount", "currency", "description", "empty-description"],
)
def test_same_key_with_a_different_request_is_a_safe_409_and_changes_nothing(
    client: TestClient, clean_database: None, domain: str, change: Dict[str, Any],
) -> None:
    user, key = str(uuid4()), str(uuid4())
    original = client.post(_path(domain), headers=auth_headers(user), json=_body(domain, key))
    assert original.status_code == 201

    conflict = client.post(_path(domain), headers=auth_headers(user), json=_body(domain, key, **change))

    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == f"{domain}_idempotency_conflict"
    # The message never echoes either request.
    assert "100" not in conflict.json()["detail"] and key not in conflict.json()["detail"]
    assert _rows(domain, user) == 1
    assert _sql(f"select amount from {_table(domain)} where user_id = :u", u=user) == Decimal("100.00")


@pytest.mark.parametrize("domain", DOMAINS)
def test_same_key_with_a_different_date_or_account_or_source_is_a_conflict(
    client: TestClient, clean_database: None, domain: str,
) -> None:
    user, key = str(uuid4()), str(uuid4())
    account = _account(client, user)
    assert client.post(_path(domain), headers=auth_headers(user), json=_body(domain, key)).status_code == 201

    date_field = "received_at" if domain == "income" else "expense_date"
    variants = [{date_field: "2026-03-05"}, {"account_id": account["id"]}]
    variants.append({"source": "gift"} if domain == "income" else {"title": "Other"})
    for change in variants:
        response = client.post(_path(domain), headers=auth_headers(user), json=_body(domain, key, **change))
        assert response.status_code == 409, (change, response.text)

    assert _rows(domain, user) == 1
    assert _ledger_rows(account["id"]) == 1  # the conflicting linked request wrote nothing


@pytest.mark.parametrize("domain", DOMAINS)
def test_different_keys_with_identical_fields_are_two_intentional_operations(
    client: TestClient, clean_database: None, domain: str,
) -> None:
    user = str(uuid4())
    account = _account(client, user)
    body = {"account_id": account["id"]}

    first = client.post(_path(domain), headers=auth_headers(user), json=_body(domain, str(uuid4()), **body))
    second = client.post(_path(domain), headers=auth_headers(user), json=_body(domain, str(uuid4()), **body))

    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["id"] != second.json()["id"]
    assert _rows(domain, user) == 2
    assert _ledger_sum(account["id"]) == Decimal("1000.00") + 2 * _expected_delta(domain, "100.00")


@pytest.mark.parametrize("domain", DOMAINS)
def test_the_same_key_for_different_users_never_interferes(client: TestClient, clean_database: None, domain: str) -> None:
    alice, bob, key = str(uuid4()), str(uuid4()), str(uuid4())

    a = client.post(_path(domain), headers=auth_headers(alice), json=_body(domain, key, amount="10.00"))
    b = client.post(_path(domain), headers=auth_headers(bob), json=_body(domain, key, amount="20.00"))

    assert (a.status_code, b.status_code) == (201, 201)  # not a replay, not a conflict
    assert a.json()["id"] != b.json()["id"]
    assert (a.json()["amount"], b.json()["amount"]) == ("10.00", "20.00")
    assert _rows(domain, alice) == 1 and _rows(domain, bob) == 1
    # Each user's replay answers only for their own record.
    assert client.post(_path(domain), headers=auth_headers(bob), json=_body(domain, key, amount="20.00")).json()["id"] == b.json()["id"]


def test_the_same_key_may_be_used_for_an_income_and_an_expense(client: TestClient, clean_database: None) -> None:
    user, key = str(uuid4()), str(uuid4())

    assert client.post(_path("income"), headers=auth_headers(user), json=_body("income", key)).status_code == 201
    assert client.post(_path("expense"), headers=auth_headers(user), json=_body("expense", key)).status_code == 201


@pytest.mark.parametrize("domain", DOMAINS)
def test_lost_response_then_user_retry_after_an_edit_replays_the_current_state_without_new_effects(
    client: TestClient, clean_database: None, dispatches: List[Any], domain: str,
) -> None:
    user, key = str(uuid4()), str(uuid4())
    account = _account(client, user)
    body = _body(domain, key, account_id=account["id"])
    created = client.post(_path(domain), headers=auth_headers(user), json=body)  # the client never saw this response
    assert created.status_code == 201

    # The user edits the record, then the unknown-outcome submission is retried.
    edited = client.patch(f"{_path(domain)}/{created.json()['id']}", headers=auth_headers(user), json={"amount": "150.00"})
    assert edited.status_code == 200
    events_before = _events(user)

    retry = client.post(_path(domain), headers=auth_headers(user), json=body)

    assert retry.status_code == 200, retry.text  # an edit never turns a retry into a false conflict
    assert retry.json()["amount"] == "150.00"  # the record's CURRENT state
    assert _rows(domain, user) == 1
    assert _events(user) == events_before
    assert _ledger_sum(account["id"]) == Decimal("1000.00") + _expected_delta(domain, "150.00")


@pytest.mark.parametrize("domain", DOMAINS)
def test_replay_is_not_new_account_activity_even_if_the_account_was_archived_since(
    client: TestClient, clean_database: None, domain: str,
) -> None:
    user, key = str(uuid4()), str(uuid4())
    account = _account(client, user)
    body = _body(domain, key, account_id=account["id"])
    assert client.post(_path(domain), headers=auth_headers(user), json=body).status_code == 201
    assert client.patch(f"/api/v1/accounts/{account['id']}", headers=auth_headers(user), json={"status": "archived"}).status_code == 200

    replay = client.post(_path(domain), headers=auth_headers(user), json=body)
    fresh = client.post(_path(domain), headers=auth_headers(user), json=_body(domain, str(uuid4()), account_id=account["id"]))

    assert replay.status_code == 200
    assert fresh.status_code == 409  # a genuinely new create is still refused
    assert _rows(domain, user) == 1


def test_expense_replay_survives_the_category_being_deleted(client: TestClient, clean_database: None) -> None:
    user, key = str(uuid4()), str(uuid4())
    category = client.post("/api/v1/categories", headers=auth_headers(user), json={"name": "Food"}).json()
    body = _body("expense", key, category_id=category["id"])
    assert client.post(_path("expense"), headers=auth_headers(user), json=body).status_code == 201
    assert client.delete(f"/api/v1/categories/{category['id']}", headers=auth_headers(user)).status_code == 204

    replay = client.post(_path("expense"), headers=auth_headers(user), json=body)

    assert replay.status_code == 200  # the category is not validated again on a replay
    assert replay.json()["category_id"] is None
    assert _rows("expense", user) == 1


@pytest.mark.parametrize("domain", DOMAINS)
def test_a_deleted_record_releases_its_key(client: TestClient, clean_database: None, domain: str) -> None:
    """Characterization: the key lives and dies with its record (there is no tombstone)."""
    user, key = str(uuid4()), str(uuid4())
    first = client.post(_path(domain), headers=auth_headers(user), json=_body(domain, key))
    assert client.delete(f"{_path(domain)}/{first.json()['id']}", headers=auth_headers(user)).status_code == 204

    again = client.post(_path(domain), headers=auth_headers(user), json=_body(domain, key))

    assert again.status_code == 201
    assert again.json()["id"] != first.json()["id"]


@pytest.mark.parametrize("domain", DOMAINS)
def test_requests_without_a_key_keep_the_legacy_behavior_and_mix_with_keyed_ones(
    client: TestClient, clean_database: None, domain: str,
) -> None:
    user = str(uuid4())

    legacy_a = client.post(_path(domain), headers=auth_headers(user), json=_body(domain))
    legacy_b = client.post(_path(domain), headers=auth_headers(user), json=_body(domain))  # identical, no key
    explicit_null = client.post(_path(domain), headers=auth_headers(user), json=_body(domain, None) | {"client_request_id": None})
    keyed = client.post(_path(domain), headers=auth_headers(user), json=_body(domain, str(uuid4())))

    assert [r.status_code for r in (legacy_a, legacy_b, explicit_null, keyed)] == [201, 201, 201, 201]
    assert legacy_a.json()["client_request_id"] is None and explicit_null.json()["client_request_id"] is None
    assert keyed.json()["client_request_id"] is not None
    assert len({r.json()["id"] for r in (legacy_a, legacy_b, explicit_null, keyed)}) == 4
    assert _rows(domain, user) == 4
    assert _sql(f"select count(*) from {_table(domain)} where user_id = :u and client_request_id is null and client_request_fingerprint is null", u=user) == 3


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize("bad_key", ["not-a-uuid", 123, ""])
def test_a_malformed_key_is_rejected_before_anything_is_written(
    client: TestClient, clean_database: None, domain: str, bad_key: Any,
) -> None:
    user = str(uuid4())

    response = client.post(_path(domain), headers=auth_headers(user), json=_body(domain) | {"client_request_id": bad_key})

    assert response.status_code == 422
    assert _rows(domain, user) == 0


@pytest.mark.parametrize("domain", DOMAINS)
def test_a_rejected_create_with_a_key_does_not_consume_the_key(client: TestClient, clean_database: None, domain: str) -> None:
    user, key = str(uuid4()), str(uuid4())
    account = _account(client, user)  # an EUR account: a USD create linked to it is refused (422)

    refused = client.post(_path(domain), headers=auth_headers(user), json=_body(domain, key, currency="USD", account_id=account["id"]))
    corrected = client.post(_path(domain), headers=auth_headers(user), json=_body(domain, key))

    assert refused.status_code == 422
    assert corrected.status_code == 201  # the key was never bound to the refused request
    assert _rows(domain, user) == 1


@pytest.mark.parametrize("domain", DOMAINS)
def test_financial_overview_counts_a_replayed_create_once(client: TestClient, clean_database: None, domain: str) -> None:
    user, key = str(uuid4()), str(uuid4())
    body = _body(domain, key)
    for _ in range(3):
        assert client.post(_path(domain), headers=auth_headers(user), json=body).status_code in (200, 201)

    overview = client.get("/api/v1/analytics/financial-overview?year=2026&month=3", headers=auth_headers(user)).json()
    field = "income" if domain == "income" else "expense"

    assert overview[f"{field}_count"] == 1
    assert overview[f"{field}_total"] == "100.00"


def _concurrent_posts(domain: str, user: str, body: Dict[str, Any], count: int) -> List[Any]:
    barrier = threading.Barrier(count)

    def post() -> Any:
        with TestClient(app) as thread_client:
            barrier.wait(timeout=15)
            return thread_client.post(_path(domain), headers=auth_headers(user), json=body)

    with ThreadPoolExecutor(max_workers=count) as pool:
        return [future.result(timeout=60) for future in [pool.submit(post) for _ in range(count)]]


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize("linked", [False, True])
def test_concurrent_requests_with_one_key_create_exactly_one_record_and_one_ledger_effect(
    client: TestClient, clean_database: None, fx: FxStub, dispatches: List[Any], domain: str, linked: bool,
) -> None:
    user, key = str(uuid4()), str(uuid4())
    account = _account(client, user, currency="USD", opening="1000.00") if linked else None
    body = _body(domain, key, currency="USD", **({"account_id": account["id"]} if account else {}))
    fx.calls = 0

    responses = _concurrent_posts(domain, user, body, count=8)

    assert sorted(r.status_code for r in responses) == [200] * 7 + [201], [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    assert _rows(domain, user) == 1
    assert fx.calls == 1  # the key lock stopped the 7 replays before any FX resolution
    assert _events(user) == (1 if domain == "income" else 0)
    if domain == "income":
        assert len(dispatches) == 1
    if account:
        assert _ledger_rows(account["id"]) == 2
        assert _ledger_sum(account["id"]) == Decimal("1000.00") + _expected_delta(domain, "100.00")


@pytest.mark.parametrize("domain", DOMAINS)
def test_the_unique_constraint_alone_also_prevents_duplicates_when_the_key_lock_is_bypassed(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch, domain: str,
) -> None:
    """Backstop: without the advisory lock the losers hit the unique constraint, and are still
    resolved as replays (200) - never a 500 and never a second record."""
    monkeypatch.setattr(create_idempotency, "acquire_create_key_lock", lambda *args, **kwargs: None)
    user, key = str(uuid4()), str(uuid4())
    account = _account(client, user)
    body = _body(domain, key, account_id=account["id"])

    responses = _concurrent_posts(domain, user, body, count=8)

    assert sorted(r.status_code for r in responses) == [200] * 7 + [201], [r.text for r in responses]
    assert _rows(domain, user) == 1
    assert _ledger_rows(account["id"]) == 2


@pytest.mark.parametrize("domain", DOMAINS)
def test_concurrent_requests_with_one_key_but_different_payloads_create_one_and_conflict_the_rest(
    client: TestClient, clean_database: None, domain: str,
) -> None:
    user, key = str(uuid4()), str(uuid4())
    barrier = threading.Barrier(4)

    def post(amount: str) -> Any:
        with TestClient(app) as thread_client:
            barrier.wait(timeout=15)
            return thread_client.post(_path(domain), headers=auth_headers(user), json=_body(domain, key, amount=amount))

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = [f.result(timeout=60) for f in [pool.submit(post, a) for a in ("1.00", "2.00", "3.00", "4.00")]]

    assert sorted(r.status_code for r in responses) == [201, 409, 409, 409], [r.text for r in responses]
    assert _rows(domain, user) == 1


@pytest.mark.parametrize("domain", DOMAINS)
def test_independent_keys_run_in_parallel_and_all_succeed(client: TestClient, clean_database: None, domain: str) -> None:
    user = str(uuid4())
    account = _account(client, user)
    barrier = threading.Barrier(6)

    def post() -> Any:
        with TestClient(app) as thread_client:
            barrier.wait(timeout=15)
            return thread_client.post(_path(domain), headers=auth_headers(user), json=_body(domain, str(uuid4()), account_id=account["id"]))

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = [f.result(timeout=60) for f in [pool.submit(post) for _ in range(6)]]

    assert [r.status_code for r in responses] == [201] * 6
    assert _rows(domain, user) == 6
    assert _ledger_sum(account["id"]) == Decimal("1000.00") + 6 * _expected_delta(domain, "100.00")
