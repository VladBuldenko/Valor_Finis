"""Core money journey across modules (VF-MVP-CORE-001).

Existing router tests cover each endpoint on its own. This file covers what only a
sequence can break: Account -> Income -> Expense -> balance -> history, where every
step must keep the Account balance, the ledger rows, the canonical Income/Expense
records and the Financial Overview in exact agreement. The reconciliation is read
straight from PostgreSQL, never from the API under test.

No network: the ECB HTTP call is replaced by a deterministic stub.
"""
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database_session import SessionLocal
from app.modules.fx import fx_ecb_provider
from tests.helpers import auth_headers

# Server-independent past month: the overview treats it as complete whatever "today" is.
MONTH = (2026, 3)
D1, D2, D3, D4 = "2026-03-02", "2026-03-04", "2026-03-05", "2026-03-06"


# Deterministic ECB stand-in: 1 EUR = 2.00 USD up to 2026-03-03, 1.25 USD afterwards.
# The rate depends on the requested date so a test can prove the snapshot is historical.
def _fake_ecb_get(url: str, params: Dict[str, str] = None, timeout: float = None) -> MagicMock:
    end = date.fromisoformat(params["endPeriod"])
    rate = 2.0 if end <= date(2026, 3, 3) else 1.25
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "dataSets": [{"series": {"0:0:0:0:0": {"observations": {"0": [rate, 0, 0, None, None]}}}}],
        "structure": {"dimensions": {"observation": [{"id": "TIME_PERIOD", "values": [{"id": end.isoformat()}]}]}},
    }
    return response


@pytest.fixture(autouse=True)
def stub_ecb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", _fake_ecb_get)


def _sql(query: str, **params: Any) -> Any:
    with SessionLocal() as session:
        return session.execute(text(query), params).scalar()


def _ledger_sum(account_id: str) -> Decimal:
    return Decimal(
        str(
            _sql(
                "select coalesce(sum(case direction when 'credit' then amount else -amount end), 0) "
                "from account_transactions where account_id = :a",
                a=account_id,
            )
        )
    )


def _balance(client: TestClient, user: str, account_id: str) -> str:
    accounts = client.get("/api/v1/accounts", headers=auth_headers(user)).json()
    return next(a["current_balance"] for a in accounts if a["id"] == account_id)


def _history(client: TestClient, user: str, account_id: str) -> List[Dict[str, Any]]:
    response = client.get(f"/api/v1/accounts/{account_id}/transactions", headers=auth_headers(user))
    assert response.status_code == 200, response.text
    return response.json()


def _assert_reconciled(client: TestClient, user: str, account_id: str, expected: str) -> None:
    """Balance reported by the API == SQL ledger sum == sum of the API history."""
    assert _balance(client, user, account_id) == expected
    assert _ledger_sum(account_id) == Decimal(expected)
    from_history = sum(
        (Decimal(t["amount"]) if t["direction"] == "credit" else -Decimal(t["amount"]))
        for t in _history(client, user, account_id)
    )
    assert from_history == Decimal(expected)


def _post(client: TestClient, user: str, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    response = client.post(path, headers=auth_headers(user), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _account(client: TestClient, user: str, currency: str = "EUR", opening: str = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"name": f"acct-{currency}", "type": "checking", "currency": currency}
    if opening is not None:
        body["opening_balance"] = opening
        body["opening_balance_date"] = D1
    return _post(client, user, "/api/v1/accounts", body)


def _income(client: TestClient, user: str, amount: str, on: str, account_id: str = None, currency: str = "EUR") -> Dict[str, Any]:
    body: Dict[str, Any] = {"amount": amount, "currency": currency, "received_at": on, "source": "salary"}
    if account_id:
        body["account_id"] = account_id
    return _post(client, user, "/api/v1/income", body)


def _expense(client: TestClient, user: str, amount: str, on: str, account_id: str = None, currency: str = "EUR") -> Dict[str, Any]:
    body: Dict[str, Any] = {"title": "e", "amount": amount, "currency": currency, "expense_date": on}
    if account_id:
        body["account_id"] = account_id
    return _post(client, user, "/api/v1/expenses", body)


def test_account_income_expense_edit_move_delete_keep_balance_ledger_and_history_exact(
    client: TestClient, clean_database: None,
) -> None:
    user = str(uuid4())
    main = _account(client, user, opening="1000.00")
    other = _account(client, user, opening="50.00")
    _assert_reconciled(client, user, main["id"], "1000.00")

    income = _income(client, user, "2500.00", D2, main["id"])
    expense = _expense(client, user, "35.50", D3, main["id"])
    _assert_reconciled(client, user, main["id"], "3464.50")
    assert [t["kind"] for t in _history(client, user, main["id"])] == ["expense", "income", "opening_balance"]

    # Edits change the single projection row in place; no duplicate row ever appears.
    assert client.patch(f"/api/v1/income/{income['id']}", headers=auth_headers(user), json={"amount": "2600.00", "received_at": D1}).status_code == 200
    assert client.patch(f"/api/v1/expenses/{expense['id']}", headers=auth_headers(user), json={"amount": "40.00"}).status_code == 200
    _assert_reconciled(client, user, main["id"], "3560.00")
    assert _sql("select count(*) from account_transactions where income_id = :i", i=income["id"]) == 1
    assert _sql("select count(*) from account_transactions where expense_id = :e", e=expense["id"]) == 1

    # Detach, re-attach elsewhere, and move: each reverses and re-applies exactly.
    assert client.patch(f"/api/v1/expenses/{expense['id']}", headers=auth_headers(user), json={"account_id": None}).status_code == 200
    _assert_reconciled(client, user, main["id"], "3600.00")
    assert client.patch(f"/api/v1/expenses/{expense['id']}", headers=auth_headers(user), json={"account_id": other["id"]}).status_code == 200
    assert client.patch(f"/api/v1/income/{income['id']}", headers=auth_headers(user), json={"account_id": other["id"]}).status_code == 200
    _assert_reconciled(client, user, main["id"], "1000.00")
    _assert_reconciled(client, user, other["id"], "2610.00")

    # Deleting the canonical records removes their effect and their ledger rows.
    assert client.delete(f"/api/v1/expenses/{expense['id']}", headers=auth_headers(user)).status_code == 204
    assert client.delete(f"/api/v1/income/{income['id']}", headers=auth_headers(user)).status_code == 204
    _assert_reconciled(client, user, other["id"], "50.00")
    assert _sql("select count(*) from account_transactions where income_id is not null or expense_id is not null") == 0


def test_unlinked_income_and_expense_never_change_any_account_but_still_count_in_overview(
    client: TestClient, clean_database: None,
) -> None:
    user = str(uuid4())
    account = _account(client, user, opening="100.00")
    income = _income(client, user, "40.00", D2)
    expense = _expense(client, user, "15.00", D2)

    assert income["account_id"] is None and expense["account_id"] is None
    _assert_reconciled(client, user, account["id"], "100.00")
    assert _sql("select count(*) from account_transactions where account_id = :a", a=account["id"]) == 1

    overview = client.get(
        f"/api/v1/analytics/financial-overview?year={MONTH[0]}&month={MONTH[1]}", headers=auth_headers(user)
    ).json()
    assert (overview["income_total"], overview["expense_total"], overview["net_flow"]) == ("40.00", "15.00", "25.00")


def test_financial_overview_equals_canonical_snapshots_and_never_counts_ledger_rows(
    client: TestClient, clean_database: None,
) -> None:
    user = str(uuid4())
    eur = _account(client, user, opening="1000.00")
    usd = _account(client, user, currency="USD", opening="100.00")
    _income(client, user, "500.00", D2, eur["id"])
    _income(client, user, "200.00", D1, usd["id"], currency="USD")  # 1 EUR = 2.00 USD -> 100.00 EUR
    _expense(client, user, "30.00", D3, eur["id"])
    _expense(client, user, "50.00", D3, usd["id"], currency="USD")  # 1 EUR = 1.25 USD -> 40.00 EUR
    _expense(client, user, "10.00", D4)

    overview = client.get(
        f"/api/v1/analytics/financial-overview?year={MONTH[0]}&month={MONTH[1]}", headers=auth_headers(user)
    ).json()
    sql_income = Decimal(str(_sql("select sum(base_amount) from income where user_id = :u", u=user)))
    sql_expense = Decimal(str(_sql("select sum(base_amount) from expenses where user_id = :u", u=user)))

    assert Decimal(overview["income_total"]) == sql_income == Decimal("600.00")
    assert Decimal(overview["expense_total"]) == sql_expense == Decimal("80.00")
    assert overview["net_flow"] == "520.00"
    assert (overview["income_count"], overview["expense_count"]) == (2, 3)
    assert overview["data_status"] == "complete_data"
    # Opening balances / ledger rows are not income: 1000 + 100 must not appear.
    assert Decimal(overview["income_total"]) < Decimal("1100.00")

    # A USD Account keeps its own currency: it is never revalued through FX.
    _assert_reconciled(client, user, usd["id"], "250.00")

    summary = client.get(
        f"/api/v1/analytics/monthly-summary?year={MONTH[0]}&month={MONTH[1]}", headers=auth_headers(user)
    ).json()
    assert summary["total_spent"] == overview["expense_total"]


def test_foreign_edit_resnapshots_only_that_record(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    usd = _account(client, user, currency="USD", opening="0.00")
    early = _income(client, user, "200.00", D1, usd["id"], currency="USD")
    late = _expense(client, user, "50.00", D3, usd["id"], currency="USD")
    assert (early["fx_rate"], early["base_amount"]) == ("0.50000000", "100.00")
    assert (late["fx_rate"], late["base_amount"]) == ("0.80000000", "40.00")

    edited = client.patch(f"/api/v1/expenses/{late['id']}", headers=auth_headers(user), json={"amount": "60.00"}).json()
    assert (edited["fx_rate"], edited["base_amount"]) == ("0.80000000", "48.00")
    still = next(i for i in client.get("/api/v1/income", headers=auth_headers(user)).json() if i["id"] == early["id"])
    assert (still["fx_rate"], still["fx_rate_date"], still["base_amount"]) == (early["fx_rate"], early["fx_rate_date"], early["base_amount"])
    _assert_reconciled(client, user, usd["id"], "140.00")


def test_a_second_user_cannot_see_link_edit_or_read_anything_of_the_first(
    client: TestClient, clean_database: None,
) -> None:
    owner, intruder = str(uuid4()), str(uuid4())
    account = _account(client, owner, opening="100.00")
    income = _income(client, owner, "10.00", D2, account["id"])

    for path in ("/api/v1/accounts", "/api/v1/income", "/api/v1/expenses"):
        assert client.get(path, headers=auth_headers(intruder)).json() == []
    assert client.get(f"/api/v1/accounts/{account['id']}/transactions", headers=auth_headers(intruder)).status_code == 404
    assert client.patch(f"/api/v1/accounts/{account['id']}", headers=auth_headers(intruder), json={"name": "x"}).status_code == 404
    assert client.patch(f"/api/v1/income/{income['id']}", headers=auth_headers(intruder), json={"amount": "1.00"}).status_code == 404
    assert client.delete(f"/api/v1/income/{income['id']}", headers=auth_headers(intruder)).status_code == 404
    link = client.post(
        "/api/v1/income",
        headers=auth_headers(intruder),
        json={"amount": "1.00", "currency": "EUR", "received_at": D2, "source": "gift", "account_id": account["id"]},
    )
    assert link.status_code == 404
    _assert_reconciled(client, owner, account["id"], "110.00")
    assert _sql("select count(*) from account_transactions where user_id = :u", u=intruder) == 0


def test_posted_transfer_replay_after_a_lost_response_has_one_ledger_effect_and_conserves_money(
    client: TestClient, clean_database: None,
) -> None:
    user = str(uuid4())
    source = _account(client, user, opening="1000.00")
    destination = _account(client, user, opening="50.00")
    body = {
        "client_request_id": str(uuid4()),
        "source_account_id": source["id"],
        "destination_account_id": destination["id"],
        "amount": "100.00",
        "transfer_date": D2,  # <= today: posted immediately
    }

    first = client.post("/api/v1/account-transfers", headers=auth_headers(user), json=body)
    replay = client.post("/api/v1/account-transfers", headers=auth_headers(user), json=body)  # the client never saw `first`
    assert (first.status_code, replay.status_code) == (201, 200)
    assert replay.json()["id"] == first.json()["id"]
    assert _sql("select count(*) from account_transfers where user_id = :u", u=user) == 1

    _assert_reconciled(client, user, source["id"], "900.00")
    _assert_reconciled(client, user, destination["id"], "150.00")
    assert Decimal(_balance(client, user, source["id"])) + Decimal(_balance(client, user, destination["id"])) == Decimal("1050.00")

    changed = client.post("/api/v1/account-transfers", headers=auth_headers(user), json={**body, "amount": "101.00"})
    assert changed.status_code == 409

    assert client.delete(f"/api/v1/account-transfers/{first.json()['id']}", headers=auth_headers(user)).status_code == 204
    _assert_reconciled(client, user, source["id"], "1000.00")
    _assert_reconciled(client, user, destination["id"], "50.00")


def test_create_without_a_key_keeps_the_legacy_non_idempotent_behavior(
    client: TestClient, clean_database: None,
) -> None:
    """Characterizes the LEGACY contract that remains for clients that send no client_request_id
    (docs/api-contract.md, VF-MVP-CORE-002): every such request creates a new record. A client
    that wants duplicate protection must send a key; see test_create_idempotency.py."""
    user = str(uuid4())
    account = _account(client, user, opening="100.00")

    first = _expense(client, user, "7.00", D2, account["id"])
    second = _expense(client, user, "7.00", D2, account["id"])

    assert first["id"] != second["id"]
    assert first["client_request_id"] is None and second["client_request_id"] is None
    assert _sql("select count(*) from expenses where user_id = :u", u=user) == 2
    _assert_reconciled(client, user, account["id"], "86.00")


def test_create_with_a_key_is_idempotent_so_the_same_resend_is_one_record(
    client: TestClient, clean_database: None,
) -> None:
    """The counterpart of the legacy test above: the same resend WITH a key creates one record."""
    user = str(uuid4())
    account = _account(client, user, opening="100.00")
    body = {"title": "e", "amount": "7.00", "currency": "EUR", "expense_date": D2,
            "account_id": account["id"], "client_request_id": str(uuid4())}

    first = client.post("/api/v1/expenses", headers=auth_headers(user), json=body)
    second = client.post("/api/v1/expenses", headers=auth_headers(user), json=body)

    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert _sql("select count(*) from expenses where user_id = :u", u=user) == 1
    _assert_reconciled(client, user, account["id"], "93.00")


@pytest.mark.parametrize(
    "amount, expected_status",
    [("0", 422), ("0.00", 422), ("-1.00", 422), ("1.005", 422), ("10000000000.00", 422), ("9999999999.99", 201)],
)
def test_amount_boundaries_are_rejected_or_stored_exactly_never_rounded(
    client: TestClient, clean_database: None, amount: str, expected_status: int,
) -> None:
    user = str(uuid4())
    response = client.post(
        "/api/v1/income",
        headers=auth_headers(user),
        json={"amount": amount, "currency": "EUR", "received_at": D2, "source": "gift"},
    )
    assert response.status_code == expected_status, response.text
    if expected_status == 201:
        assert response.json()["amount"] == amount
        assert response.json()["base_amount"] == amount
    else:
        assert _sql("select count(*) from income where user_id = :u", u=user) == 0


def test_every_account_balance_in_the_database_equals_its_ledger_and_links_are_unique(
    client: TestClient, clean_database: None,
) -> None:
    """Invariants a user-visible number depends on, checked over a mixed history."""
    user = str(uuid4())
    a = _account(client, user, opening="10.00")
    b = _account(client, user, opening="-5.00")  # a negative opening balance is a debit row
    _income(client, user, "1.10", D1, a["id"])
    _income(client, user, "2.20", D2, b["id"])
    _expense(client, user, "0.30", D3, a["id"])
    _expense(client, user, "0.01", D4, b["id"])

    _assert_reconciled(client, user, a["id"], "10.80")
    _assert_reconciled(client, user, b["id"], "-2.81")
    assert _sql(
        "select count(*) from (select income_id from account_transactions where income_id is not null "
        "group by income_id having count(*) > 1) d"
    ) == 0
    assert _sql(
        "select count(*) from (select expense_id from account_transactions where expense_id is not null "
        "group by expense_id having count(*) > 1) d"
    ) == 0
    assert _sql(
        "select count(*) from account_transactions t where t.income_id is not null and not exists "
        "(select 1 from income i where i.id = t.income_id and i.user_id = t.user_id)"
    ) == 0
