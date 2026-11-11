"""Transfers and Goals journey across modules (VF-MVP-CORE-003).

The router tests cover each endpoint on its own. This file covers what only a sequence
can break: Account Transfers and Goal reservations must keep the Account ledger, the
canonical Transfer and Goal rows, the reserved amounts and the analytics in exact
agreement. Every reconciliation is read straight from PostgreSQL, never from the API
under test.

Financial invariants asserted here:
- a transfer moves money: exactly one debit and one equal credit, total money unchanged;
- a planned transfer has no ledger effect until it is posted;
- a Goal reservation / release writes NO account_transactions row and NO transfer, and
  never changes current_balance;
- reserved(A) = sum of linked(G, A) over all Goals; every Goal total = tracked + linked;
- neither feature moves Income, Expenses, Budgets, Financial Overview or forecasts.

Dates are relative to the server date so the journey is valid on any day.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database_session import SessionLocal
from tests.helpers import auth_headers

TODAY = date.today()
PAST = (TODAY - timedelta(days=3)).isoformat()
OPENING = (TODAY - timedelta(days=30)).isoformat()
FUTURE = (TODAY + timedelta(days=5)).isoformat()
TODAY_ISO = TODAY.isoformat()

CAPACITY_CODE = "goal_reservation_capacity_exceeded"


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


def _transfer_rows(transfer_id: str) -> int:
    return int(_sql("select count(*) from account_transactions where transfer_id = :t", t=transfer_id))


def _transfer_count(user: str) -> int:
    return int(_sql("select count(*) from account_transfers where user_id = :u", u=user))


def _account_ledger_stats(account_id: str) -> str:
    return str(
        _sql(
            "select count(*) || ':' || coalesce(sum(amount), 0) from account_transactions where account_id = :a",
            a=account_id,
        )
    )


def _sql_partition(goal_id: str, linked: bool) -> Decimal:
    clause = "account_id is not null" if linked else "account_id is null"
    return Decimal(
        str(
            _sql(
                "select coalesce(sum(case type when 'withdrawal' then -amount else amount end), 0) "
                f"from goal_transactions where goal_id = :g and {clause}",
                g=goal_id,
            )
        )
    )


def _sql_reserved(account_id: str) -> Decimal:
    return Decimal(
        str(
            _sql(
                "select coalesce(sum(case type when 'contribution' then amount else -amount end), 0) "
                "from goal_transactions where account_id = :a",
                a=account_id,
            )
        )
    )


class Api:
    """Thin authenticated wrapper so each journey reads as a sequence of user actions."""

    def __init__(self, client: TestClient, user: str) -> None:
        self.client = client
        self.user = user
        self.headers = auth_headers(user)

    def post(self, path: str, body: Dict[str, Any], expect: Optional[int] = 201) -> Any:
        response = self.client.post(path, headers=self.headers, json=body)
        if expect is not None:
            assert response.status_code == expect, response.text
        return response

    def get(self, path: str) -> Any:
        response = self.client.get(path, headers=self.headers)
        assert response.status_code == 200, response.text
        return response.json()

    def account(self, name: str, opening: Optional[str] = None, currency: str = "EUR") -> Dict[str, Any]:
        body: Dict[str, Any] = {"name": name, "type": "checking", "currency": currency}
        if opening is not None:
            body.update({"opening_balance": opening, "opening_balance_date": OPENING})
        return self.post("/api/v1/accounts", body).json()

    def accounts(self) -> Dict[str, Dict[str, Any]]:
        return {a["id"]: a for a in self.get("/api/v1/accounts")}

    def balance(self, account_id: str) -> Decimal:
        return Decimal(self.accounts()[account_id]["current_balance"])

    def transfer(self, source: str, destination: str, amount: str, on: str = TODAY_ISO, key: Optional[str] = None,
                 expect: Optional[int] = 201, **extra: Any) -> Any:
        body = {
            "client_request_id": key or str(uuid4()),
            "source_account_id": source,
            "destination_account_id": destination,
            "amount": amount,
            "transfer_date": on,
            **extra,
        }
        response = self.post("/api/v1/account-transfers", body, expect=expect)
        return response.json() if expect == 201 else response

    def goal(self, name: str = "Goal", target: str = "1000.00") -> Dict[str, Any]:
        return self.post("/api/v1/goals", {"name": name, "target_amount": target}).json()

    def goals(self) -> Dict[str, Dict[str, Any]]:
        return {g["id"]: g for g in self.get("/api/v1/goals")}

    def goal_tx(self, goal_id: str, type: str, amount: str, account_id: Optional[str] = None,
                key: Optional[str] = None, expect: Optional[int] = 201) -> Any:
        body: Dict[str, Any] = {"type": type, "amount": amount, "client_request_id": key or str(uuid4())}
        if account_id:
            body["account_id"] = account_id
        response = self.post(f"/api/v1/goals/{goal_id}/transactions", body, expect=expect)
        return response.json() if expect in (200, 201) else response


def _analytics_snapshot(api: Api) -> Dict[str, Any]:
    """Everything transfers and reservations must leave untouched."""
    month = f"year={TODAY.year}&month={TODAY.month}"
    return {
        "overview": api.get(f"/api/v1/analytics/financial-overview?{month}"),
        "monthly": api.get(f"/api/v1/analytics/monthly-summary?{month}"),
        "budget_status": api.get("/api/v1/analytics/budget-status"),
        "forecast": api.get("/api/v1/analytics/spending-forecast"),
        "income": api.get("/api/v1/income"),
        "expenses": api.get("/api/v1/expenses"),
        "budgets": api.get("/api/v1/budgets"),
    }


def _assert_ledgers_reconcile(api: Api) -> None:
    for account in api.accounts().values():
        assert _ledger_sum(account["id"]) == Decimal(account["current_balance"]), account["name"]
    # every posted transfer owns exactly one debit and one equal credit; planned ones own none
    assert _sql(
        "select count(*) from account_transfers t where t.user_id = :u and t.status = 'posted' and "
        "((select count(*) from account_transactions x where x.transfer_id = t.id and x.direction = 'debit' and x.amount = t.amount) <> 1 "
        "or (select count(*) from account_transactions x where x.transfer_id = t.id and x.direction = 'credit' and x.amount = t.amount) <> 1)",
        u=api.user,
    ) == 0
    assert _sql(
        "select count(*) from account_transfers t where t.user_id = :u and t.status = 'planned' and "
        "exists (select 1 from account_transactions x where x.transfer_id = t.id)",
        u=api.user,
    ) == 0


def _assert_goals_reconcile(api: Api) -> None:
    accounts = api.accounts()
    for goal in api.goals().values():
        tracked, linked = _sql_partition(goal["id"], False), _sql_partition(goal["id"], True)
        assert Decimal(goal["tracked_amount"]) == tracked, goal["name"]
        assert Decimal(goal["linked_amount"]) == linked, goal["name"]
        assert Decimal(goal["current_amount"]) == tracked + linked, goal["name"]
        assert sum((Decimal(x["amount"]) for x in goal["allocations"]), Decimal("0")) == linked, goal["name"]
        assert all(Decimal(x["amount"]) != 0 for x in goal["allocations"]), "zero partitions are never listed"
        assert tracked >= 0
    for account in accounts.values():
        reserved = _sql_reserved(account["id"])
        assert Decimal(account["reserved_amount"]) == reserved, account["name"]
        assert Decimal(account["unallocated_amount"]) == Decimal(account["balance_as_of_today"]) - reserved
        assert reserved >= 0
    # the database never holds a negative linked partition
    assert _sql(
        "select count(*) from (select goal_id, account_id from goal_transactions where user_id = :u and account_id is not null "
        "group by 1, 2 having sum(case type when 'contribution' then amount else -amount end) < 0) x",
        u=api.user,
    ) == 0


# ---------------------------------------------------------------------------------------------
# Part A: Account Transfers
# ---------------------------------------------------------------------------------------------


def test_transfer_lifecycle_keeps_ledger_balances_and_total_money_exact(
    client: TestClient, clean_database: None,
) -> None:
    api = Api(client, str(uuid4()))
    src = api.account("Src", "1000.00")
    dst = api.account("Dst", "200.00")
    api.post("/api/v1/income", {"amount": "100.00", "currency": "EUR", "received_at": TODAY_ISO, "source": "gift", "account_id": src["id"]})
    api.post("/api/v1/expenses", {"title": "t", "amount": "10.00", "currency": "EUR", "expense_date": TODAY_ISO, "account_id": src["id"]})
    before = _analytics_snapshot(api)
    total_before = api.balance(src["id"]) + api.balance(dst["id"])
    assert total_before == Decimal("1290.00")

    # 1. dated today: posted immediately, exactly two ledger rows, equal debit and credit
    posted = api.transfer(src["id"], dst["id"], "300.00")
    assert posted["status"] == "posted" and posted["effective_date"] == TODAY_ISO and posted["posted_at"]
    assert _transfer_rows(posted["id"]) == 2
    assert _sql("select direction || ':' || amount || ':' || account_id from account_transactions "
                "where transfer_id = :t and direction = 'debit'", t=posted["id"]) == f"debit:300.00:{src['id']}"
    assert _sql("select direction || ':' || amount || ':' || account_id from account_transactions "
                "where transfer_id = :t and direction = 'credit'", t=posted["id"]) == f"credit:300.00:{dst['id']}"
    assert api.balance(src["id"]) == Decimal("790.00") and api.balance(dst["id"]) == Decimal("500.00")

    # 2. dated in the past: posted immediately with that accounting date
    past = api.transfer(src["id"], dst["id"], "10.00", on=PAST)
    assert past["status"] == "posted" and past["effective_date"] == PAST
    assert _sql("select distinct transaction_date from account_transactions where transfer_id = :t", t=past["id"]) == date.fromisoformat(PAST)

    # 3. future-dated: stays planned, no ledger rows, balances and as-of figures untouched
    accounts_before = api.accounts()
    planned = api.transfer(src["id"], dst["id"], "120.00", on=FUTURE)
    assert planned["status"] == "planned" and planned["planned_date"] == FUTURE
    assert planned["effective_date"] is None and planned["posted_at"] is None
    assert _transfer_rows(planned["id"]) == 0
    accounts_mid = api.accounts()
    for account_id in (src["id"], dst["id"]):
        assert accounts_mid[account_id]["current_balance"] == accounts_before[account_id]["current_balance"]
        assert accounts_mid[account_id]["balance_as_of_today"] == accounts_before[account_id]["balance_as_of_today"]
    assert accounts_mid[src["id"]]["planned_transfer_outflows"] == "120.00"
    assert accounts_mid[dst["id"]]["planned_transfer_outflows"] == "0.00"  # planned incoming is ignored
    assert Decimal(accounts_mid[src["id"]]["reservable_amount"]) == Decimal(accounts_before[src["id"]]["reservable_amount"]) - 120

    # 4. manual posting: exactly two rows, balances move by the same amount, planned outflow released
    manual = api.post(f"/api/v1/account-transfers/{planned['id']}/post", {"effective_date": TODAY_ISO}, expect=200).json()
    assert manual["status"] == "posted" and manual["effective_date"] == TODAY_ISO and manual["planned_date"] == FUTURE
    assert _transfer_rows(planned["id"]) == 2
    assert api.balance(src["id"]) == Decimal("790.00") - 10 - 120
    assert api.balance(dst["id"]) == Decimal("500.00") + 10 + 120
    assert api.accounts()[src["id"]]["planned_transfer_outflows"] == "0.00"

    # 5. repeated posting is the documented controlled 409 and writes nothing
    again = api.post(f"/api/v1/account-transfers/{planned['id']}/post", {"effective_date": TODAY_ISO}, expect=None)
    assert again.status_code == 409 and again.json()["code"] == "account_transfer_already_posted"
    assert _transfer_rows(planned["id"]) == 2

    # 6. deleting a posted transfer reverses BOTH ledger effects exactly
    tmp = api.transfer(src["id"], dst["id"], "25.00")
    assert api.balance(src["id"]) == Decimal("660.00") - 25
    assert client.delete(f"/api/v1/account-transfers/{tmp['id']}", headers=api.headers).status_code == 204
    assert api.balance(src["id"]) == Decimal("660.00") and api.balance(dst["id"]) == Decimal("630.00")
    assert _transfer_rows(tmp["id"]) == 0
    assert _sql("select count(*) from account_transfers where id = :t", t=tmp["id"]) == 0

    # 7. deleting a planned transfer has no ledger effect and releases the planned outflow
    plan2 = api.transfer(src["id"], dst["id"], "80.00", on=FUTURE)
    assert api.accounts()[src["id"]]["planned_transfer_outflows"] == "80.00"
    stats = (_account_ledger_stats(src["id"]), _account_ledger_stats(dst["id"]))
    assert client.delete(f"/api/v1/account-transfers/{plan2['id']}", headers=api.headers).status_code == 204
    assert stats == (_account_ledger_stats(src["id"]), _account_ledger_stats(dst["id"]))
    assert api.accounts()[src["id"]]["planned_transfer_outflows"] == "0.00"

    # total money across the two accounts never changed; the ledger reconciles to the cent
    assert api.balance(src["id"]) + api.balance(dst["id"]) == total_before
    _assert_ledgers_reconcile(api)

    # transfers inflated nothing: Income, Expenses, Budgets, Financial Overview, forecast, summaries
    assert _analytics_snapshot(api) == before


def test_transfer_idempotency_conflicts_and_invalid_states_write_nothing(
    client: TestClient, clean_database: None,
) -> None:
    api = Api(client, str(uuid4()))
    src = api.account("Src", "500.00")
    dst = api.account("Dst", "0.00")
    usd = api.account("Usd", "10.00", currency="USD")
    archived = api.account("Old")
    assert client.patch(f"/api/v1/accounts/{archived['id']}", headers=api.headers, json={"status": "archived"}).status_code == 200

    key = str(uuid4())
    first = api.transfer(src["id"], dst["id"], "7.00", key=key)
    count = _transfer_count(api.user)
    stats = _account_ledger_stats(src["id"])

    # same key + same payload: the original transfer comes back (200), nothing new is written
    replay = api.transfer(src["id"], dst["id"], "7.00", key=key, expect=200)
    assert replay.json()["id"] == first["id"]
    assert _transfer_count(api.user) == count and _account_ledger_stats(src["id"]) == stats
    assert _transfer_rows(first["id"]) == 2

    # same key + any changed field: documented 409, still nothing written
    for change in ({"amount": "7.01"}, {"transfer_date": PAST}, {"description": "changed"}, {"destination_account_id": archived["id"]}):
        body = {"client_request_id": key, "source_account_id": src["id"], "destination_account_id": dst["id"],
                "amount": "7.00", "transfer_date": TODAY_ISO, **change}
        response = api.post("/api/v1/account-transfers", body, expect=None)
        assert response.status_code == 409, change
        assert response.json()["code"] == "account_transfer_idempotency_conflict", change
    assert _transfer_count(api.user) == count and _account_ledger_stats(src["id"]) == stats

    # invalid states are rejected before anything is written
    assert api.transfer(src["id"], usd["id"], "1.00", expect=422).status_code == 422          # currency mismatch
    assert api.transfer(src["id"], src["id"], "1.00", expect=422).status_code == 422          # same account
    assert api.transfer(src["id"], archived["id"], "1.00", expect=409).status_code == 409     # archived destination
    assert api.transfer(archived["id"], dst["id"], "1.00", expect=409).status_code == 409     # archived source
    assert api.transfer(src["id"], str(uuid4()), "1.00", expect=404).status_code == 404       # unknown account
    for amount in ("0.00", "-5.00", "1.234"):
        assert api.transfer(src["id"], dst["id"], amount, expect=422).status_code == 422, amount
    assert api.transfer(src["id"], dst["id"], "1.00", expect=422, status="posted").status_code == 422  # server-owned field
    assert _transfer_count(api.user) == count and _account_ledger_stats(src["id"]) == stats


def test_transfers_are_isolated_between_users_and_a_foreign_key_is_not_a_conflict(
    client: TestClient, clean_database: None,
) -> None:
    alice, bob = Api(client, str(uuid4())), Api(client, str(uuid4()))
    a_src, a_dst = alice.account("A1", "100.00"), alice.account("A2", "0.00")
    b_acc, b_acc2 = bob.account("B1", "50.00"), bob.account("B2", "0.00")
    posted = alice.transfer(a_src["id"], a_dst["id"], "20.00")
    planned = alice.transfer(a_src["id"], a_dst["id"], "30.00", on=FUTURE)
    stats = (_account_ledger_stats(a_src["id"]), _account_ledger_stats(a_dst["id"]))

    # Bob cannot use Alice's accounts on either side, and cannot see, post or delete her transfers
    assert bob.transfer(a_src["id"], b_acc["id"], "1.00", expect=404).status_code == 404
    assert bob.transfer(b_acc["id"], a_dst["id"], "1.00", expect=404).status_code == 404
    assert bob.get("/api/v1/account-transfers") == []
    assert bob.post(f"/api/v1/account-transfers/{planned['id']}/post", {"effective_date": TODAY_ISO}, expect=None).status_code == 404
    assert client.delete(f"/api/v1/account-transfers/{posted['id']}", headers=bob.headers).status_code == 404
    assert client.delete(f"/api/v1/account-transfers/{planned['id']}", headers=bob.headers).status_code == 404
    assert client.get(f"/api/v1/accounts/{a_src['id']}/transactions", headers=bob.headers).status_code == 404

    # nothing of Alice's changed
    assert stats == (_account_ledger_stats(a_src["id"]), _account_ledger_stats(a_dst["id"]))
    assert _transfer_rows(posted["id"]) == 2 and _transfer_rows(planned["id"]) == 0
    assert {t["id"] for t in alice.get("/api/v1/account-transfers")} == {posted["id"], planned["id"]}

    # an idempotency key is scoped per user: Bob may reuse Alice's key for his own transfer
    reused = bob.transfer(b_acc["id"], b_acc2["id"], "1.00", key=posted["client_request_id"])
    assert reused["id"] != posted["id"]
    _assert_ledgers_reconcile(alice)
    _assert_ledgers_reconcile(bob)


# ---------------------------------------------------------------------------------------------
# Part B: Goals
# ---------------------------------------------------------------------------------------------


def test_goal_reservations_and_releases_never_touch_the_ledger_or_create_transfers(
    client: TestClient, clean_database: None,
) -> None:
    api = Api(client, str(uuid4()))
    account = api.account("Reserve", "1000.00")
    second = api.account("Reserve2", "500.00")
    holiday, laptop = api.goal("Holiday", "2000.00"), api.goal("Laptop", "1500.00")
    api.post("/api/v1/income", {"amount": "100.00", "currency": "EUR", "received_at": TODAY_ISO, "source": "gift", "account_id": account["id"]})
    before = _analytics_snapshot(api)
    ledger = {x["id"]: _account_ledger_stats(x["id"]) for x in (account, second)}
    transfers = _transfer_count(api.user)

    def untouched() -> None:
        assert {x["id"]: _account_ledger_stats(x["id"]) for x in (account, second)} == ledger
        assert _transfer_count(api.user) == transfers
        assert _sql("select count(*) from account_transactions where account_id in (:a, :b) and kind = 'transfer'",
                    a=account["id"], b=second["id"]) == 0

    # tracked partition only
    api.goal_tx(holiday["id"], "contribution", "100.00")
    api.goal_tx(holiday["id"], "withdrawal", "40.00")
    g = api.goals()[holiday["id"]]
    assert (g["current_amount"], g["tracked_amount"], g["linked_amount"], g["allocations"]) == ("60.00", "60.00", "0.00", [])
    assert api.accounts()[account["id"]]["reserved_amount"] == "0.00"
    over = api.goal_tx(holiday["id"], "withdrawal", "60.01", expect=409)
    assert over.status_code == 409 and over.json()["code"] == "goal_insufficient_funds"  # a tracked shortfall keeps the legacy code
    assert api.post(f"/api/v1/goals/{holiday['id']}/transactions",
                    {"type": "contribution", "amount": "1.00", "client_request_id": str(uuid4()), "effective_date": (TODAY + timedelta(days=1)).isoformat()},
                    expect=422).status_code == 422

    # RESERVE 300: balance unchanged, reserved + linked move, nothing in the ledger, no transfer
    balance_before = api.accounts()[account["id"]]["current_balance"]
    reserved = api.goal_tx(holiday["id"], "contribution", "300.00", account["id"])
    assert reserved["account_id"] == account["id"] and reserved["effective_date"] == TODAY_ISO and reserved["currency"] == "EUR"
    a = api.accounts()[account["id"]]
    assert a["current_balance"] == balance_before and a["reserved_amount"] == "300.00"
    assert a["unallocated_amount"] == "800.00" and a["reservable_amount"] == "800.00" and a["allocation_status"] == "normal"
    g = api.goals()[holiday["id"]]
    assert (g["current_amount"], g["tracked_amount"], g["linked_amount"]) == ("360.00", "60.00", "300.00")
    assert g["allocations"] == [{"account_id": account["id"], "amount": "300.00"}]
    untouched()

    # a second Goal and a second Account: reserved(A) aggregates across Goals
    api.goal_tx(laptop["id"], "contribution", "250.00", account["id"])
    api.goal_tx(laptop["id"], "contribution", "100.00", second["id"])
    assert api.accounts()[account["id"]]["reserved_amount"] == "550.00"
    assert api.accounts()[second["id"]]["reserved_amount"] == "100.00"
    untouched()

    # withdrawals need the right partition; nothing crosses partitions
    cross = api.goal_tx(holiday["id"], "withdrawal", "100.00", expect=409)           # tracked is 60, total is 360
    assert cross.json()["code"] == "goal_insufficient_funds"
    for amount, partition in (("301.00", account["id"]), ("1.00", second["id"])):
        r = api.goal_tx(holiday["id"], "withdrawal", amount, partition, expect=409)
        assert r.json()["code"] == "goal_partition_insufficient_funds", (amount, partition)
    assert api.goals()[holiday["id"]]["current_amount"] == "360.00"
    _assert_goals_reconcile(api)

    # RELEASE 100: capacity restored, STILL no ledger row, no transfer, and it can be reserved again
    reservable_before = Decimal(api.accounts()[account["id"]]["reservable_amount"])
    release = api.goal_tx(laptop["id"], "withdrawal", "100.00", account["id"])
    assert release["type"] == "withdrawal" and release["account_id"] == account["id"]
    assert Decimal(api.accounts()[account["id"]]["reservable_amount"]) == reservable_before + 100
    untouched()
    api.goal_tx(laptop["id"], "contribution", "100.00", account["id"])

    # capacity boundary: one cent over is refused and writes nothing, the exact amount is accepted
    capacity = api.accounts()[account["id"]]["reservable_amount"]
    rows = _sql("select count(*) from goal_transactions where user_id = :u", u=api.user)
    over_cap = api.goal_tx(holiday["id"], "contribution", str(Decimal(capacity) + Decimal("0.01")), account["id"], expect=409)
    assert over_cap.json()["code"] == CAPACITY_CODE
    assert _sql("select count(*) from goal_transactions where user_id = :u", u=api.user) == rows
    api.goal_tx(holiday["id"], "contribution", capacity, account["id"])
    assert api.accounts()[account["id"]]["reservable_amount"] == "0.00"
    assert api.goal_tx(holiday["id"], "contribution", "0.01", account["id"], expect=409).json()["code"] == CAPACITY_CODE
    untouched()

    _assert_goals_reconcile(api)
    _assert_ledgers_reconcile(api)
    # reservations are not income, spending or a balance: analytics are unchanged
    assert _analytics_snapshot(api) == before


def test_goal_transaction_idempotency_returns_the_original_and_writes_one_row(
    client: TestClient, clean_database: None,
) -> None:
    api = Api(client, str(uuid4()))
    account = api.account("Reserve", "1000.00")
    goal_a, goal_b = api.goal("A"), api.goal("B")
    key = str(uuid4())

    first = api.goal_tx(goal_a["id"], "contribution", "12.00", account["id"], key=key)
    rows = _sql("select count(*) from goal_transactions where user_id = :u", u=api.user)
    reserved = api.accounts()[account["id"]]["reserved_amount"]

    replay = api.goal_tx(goal_a["id"], "contribution", "12.00", account["id"], key=key, expect=200)
    assert replay["id"] == first["id"]
    assert _sql("select count(*) from goal_transactions where user_id = :u", u=api.user) == rows
    assert api.accounts()[account["id"]]["reserved_amount"] == reserved

    # the same key with a changed payload (amount, goal, account, type) is a controlled conflict
    for changed in (
        lambda: api.goal_tx(goal_a["id"], "contribution", "13.00", account["id"], key=key, expect=409),
        lambda: api.goal_tx(goal_b["id"], "contribution", "12.00", account["id"], key=key, expect=409),
        lambda: api.goal_tx(goal_a["id"], "contribution", "12.00", None, key=key, expect=409),
        lambda: api.goal_tx(goal_a["id"], "withdrawal", "12.00", account["id"], key=key, expect=409),
    ):
        assert changed().json()["code"] == "goal_transaction_idempotency_conflict"
    assert _sql("select count(*) from goal_transactions where user_id = :u", u=api.user) == rows

    # a linked request without a key is rejected: linked operations are never keyless
    keyless = client.post(f"/api/v1/goals/{goal_a['id']}/transactions", headers=api.headers,
                          json={"type": "contribution", "amount": "1.00", "account_id": account["id"]})
    assert keyless.status_code == 422
    assert _sql("select count(*) from goal_transactions where user_id = :u", u=api.user) == rows


def test_overcommit_planned_transfers_and_archived_accounts_follow_the_reservation_contract(
    client: TestClient, clean_database: None,
) -> None:
    api = Api(client, str(uuid4()))
    reserve = api.account("Reserve", "500.00")
    other = api.account("Other", "0.00")
    goal = api.goal("G")
    api.goal_tx(goal["id"], "contribution", "100.00", reserve["id"])

    # a planned OUTGOING transfer lowers reservable capacity (and only once, even after posting)
    base = Decimal(api.accounts()[reserve["id"]]["reservable_amount"])  # 400.00
    planned = api.transfer(reserve["id"], other["id"], "200.00", on=FUTURE)
    mid = api.accounts()[reserve["id"]]
    assert Decimal(mid["reservable_amount"]) == base - 200 and mid["planned_transfer_outflows"] == "200.00"
    over = api.goal_tx(goal["id"], "contribution", str(Decimal(mid["reservable_amount"]) + Decimal("0.01")), reserve["id"], expect=409)
    assert over.json()["code"] == CAPACITY_CODE
    api.post(f"/api/v1/account-transfers/{planned['id']}/post", {"effective_date": TODAY_ISO}, expect=200)
    after = api.accounts()[reserve["id"]]
    assert after["planned_transfer_outflows"] == "0.00"
    assert Decimal(after["reservable_amount"]) == base - 200  # not double-subtracted

    # spending below the reserved amount is allowed and never rewrites Goal history
    rows = _sql("select count(*) from goal_transactions where user_id = :u", u=api.user)
    api.transfer(reserve["id"], other["id"], "250.00")               # balance 50, reserved 100
    over_committed = api.accounts()[reserve["id"]]
    assert over_committed["reserved_amount"] == "100.00" and over_committed["allocation_status"] == "overcommitted"
    assert over_committed["current_balance"] == "50.00"
    assert _sql("select count(*) from goal_transactions where user_id = :u", u=api.user) == rows
    assert api.goal_tx(goal["id"], "contribution", "0.01", reserve["id"], expect=409).json()["code"] == CAPACITY_CODE
    # a release is always allowed, and ends the overcommitment
    api.goal_tx(goal["id"], "withdrawal", "100.00", reserve["id"])
    assert api.accounts()[reserve["id"]]["allocation_status"] == "normal"

    # archived account: no NEW reservation, but an existing partition can still be released
    api.transfer(other["id"], reserve["id"], "450.00")
    api.goal_tx(goal["id"], "contribution", "40.00", reserve["id"])
    assert client.patch(f"/api/v1/accounts/{reserve['id']}", headers=api.headers, json={"status": "archived"}).status_code == 200
    refused = api.goal_tx(goal["id"], "contribution", "1.00", reserve["id"], expect=409)
    assert refused.json()["code"] == "account_archived"
    api.goal_tx(goal["id"], "withdrawal", "40.00", reserve["id"])
    assert api.accounts()[reserve["id"]]["reserved_amount"] == "0.00"
    # the Account cannot be deleted while it has history (ledger or Goal partitions)
    assert client.delete(f"/api/v1/accounts/{reserve['id']}", headers=api.headers).status_code == 409

    _assert_goals_reconcile(api)
    _assert_ledgers_reconcile(api)


def test_goal_lifecycle_priorities_and_ownership_boundaries(
    client: TestClient, clean_database: None,
) -> None:
    alice, bob = Api(client, str(uuid4())), Api(client, str(uuid4()))
    account = alice.account("Reserve", "100.00")
    g1, g2, g3 = alice.goal("One"), alice.goal("Two"), alice.goal("Three")

    # lifecycle: edit, complete and reactivate, delete without history, delete blocked with history, archive
    edited = client.patch(f"/api/v1/goals/{g1['id']}", headers=alice.headers,
                          json={"name": "Renamed", "target_amount": "2500.00", "target_date": None}).json()
    assert (edited["name"], edited["target_amount"], edited["target_date"]) == ("Renamed", "2500.00", None)
    for status in ("completed", "active"):
        assert client.patch(f"/api/v1/goals/{g1['id']}", headers=alice.headers, json={"status": status}).json()["status"] == status
    assert client.delete(f"/api/v1/goals/{g3['id']}", headers=alice.headers).status_code == 204
    alice.goal_tx(g2["id"], "contribution", "5.00")
    blocked = client.delete(f"/api/v1/goals/{g2['id']}", headers=alice.headers)
    assert blocked.status_code == 409 and blocked.json()["code"] == "goal_deletion_not_allowed"
    archived = client.patch(f"/api/v1/goals/{g2['id']}", headers=alice.headers, json={"status": "archived"}).json()
    assert archived["status"] == "archived" and archived["priority_rank"] is None
    assert alice.goal_tx(g2["id"], "contribution", "1.00", expect=409).json()["code"] == "goal_archived"
    alice.goal_tx(g2["id"], "withdrawal", "5.00")                    # withdrawals stay possible when archived

    # priorities: dense ranks, reorder, stale set refused, archived never ranked
    g4 = alice.goal("Four")
    ranks = {g["id"]: g["priority_rank"] for g in alice.get("/api/v1/goals")}
    assert (ranks[g1["id"]], ranks[g4["id"]], ranks[g2["id"]]) == (1, 2, None)
    reordered = client.put("/api/v1/goals/priorities", headers=alice.headers, json={"goal_ids": [g4["id"], g1["id"]]})
    assert reordered.status_code == 200
    assert [(g["id"], g["priority_rank"]) for g in reordered.json() if g["status"] != "archived"] == [(g4["id"], 1), (g1["id"], 2)]
    stale = client.put("/api/v1/goals/priorities", headers=alice.headers, json={"goal_ids": [g4["id"]]})
    assert stale.status_code == 409 and stale.json()["code"] == "goal_priority_set_stale"
    with_archived = client.put("/api/v1/goals/priorities", headers=alice.headers, json={"goal_ids": [g4["id"], g1["id"], g2["id"]]})
    assert with_archived.status_code == 409

    # ownership: Bob can reserve against neither Alice's account nor goal, and sees none of it
    alice.goal_tx(g1["id"], "contribution", "30.00", account["id"])
    b_goal = bob.goal("Bob")
    snapshot = (alice.goals(), alice.accounts())
    assert bob.goal_tx(b_goal["id"], "contribution", "1.00", account["id"], expect=404).status_code == 404
    assert bob.goal_tx(g1["id"], "contribution", "1.00", expect=404).status_code == 404
    assert bob.goal_tx(g1["id"], "contribution", "1.00", account["id"], expect=404).status_code == 404
    assert client.patch(f"/api/v1/goals/{g1['id']}", headers=bob.headers, json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/v1/goals/{g1['id']}", headers=bob.headers).status_code == 404
    assert client.get(f"/api/v1/goals/{g1['id']}/transactions", headers=bob.headers).status_code == 404
    assert client.put("/api/v1/goals/priorities", headers=bob.headers, json={"goal_ids": [g1["id"]]}).status_code == 404
    assert [g["id"] for g in bob.get("/api/v1/goals")] == [b_goal["id"]]
    assert account["id"] not in bob.accounts()
    assert (alice.goals(), alice.accounts()) == snapshot
    _assert_goals_reconcile(alice)
    _assert_goals_reconcile(bob)


def test_historical_opening_balance_rows_stay_in_the_tracked_partition(
    client: TestClient, clean_database: None,
) -> None:
    api = Api(client, str(uuid4()))
    account = api.account("Reserve", "100.00")
    goal = api.goal("Legacy", "500.00")
    # the system-created historical row: tracked, undated and keyless (what the migration left behind)
    with SessionLocal() as session:
        session.execute(
            text("insert into goal_transactions (id, goal_id, user_id, type, amount, currency, created_at) "
                 "values (:id, :g, :u, 'opening_balance', 150.00, 'EUR', '2025-01-01')"),
            {"id": str(uuid4()), "g": goal["id"], "u": api.user},
        )
        session.commit()

    g = api.goals()[goal["id"]]
    assert (g["current_amount"], g["tracked_amount"], g["linked_amount"]) == ("150.00", "150.00", "0.00")
    history = api.get(f"/api/v1/goals/{goal['id']}/transactions")
    row = next(x for x in history if x["type"] == "opening_balance")
    assert (row["account_id"], row["effective_date"], row["client_request_id"]) == (None, None, None)

    api.goal_tx(goal["id"], "contribution", "50.00", account["id"])
    api.goal_tx(goal["id"], "withdrawal", "150.00")                  # the tracked partition holds exactly the opening balance
    g = api.goals()[goal["id"]]
    assert (g["current_amount"], g["tracked_amount"], g["linked_amount"]) == ("50.00", "0.00", "50.00")
    assert api.goal_tx(goal["id"], "withdrawal", "0.01", expect=409).json()["code"] == "goal_insufficient_funds"

    # opening balances can never be linked or created through the API
    assert api.post(f"/api/v1/goals/{goal['id']}/transactions",
                    {"type": "opening_balance", "amount": "1.00", "client_request_id": str(uuid4())}, expect=422).status_code == 422
    with pytest.raises(Exception):
        with SessionLocal() as session:
            session.execute(
                text("insert into goal_transactions (id, goal_id, user_id, type, amount, currency, account_id, client_request_id, effective_date) "
                     "values (:id, :g, :u, 'opening_balance', 1.00, 'EUR', :a, :k, :d)"),
                {"id": str(uuid4()), "g": goal["id"], "u": api.user, "a": account["id"], "k": str(uuid4()), "d": TODAY_ISO},
            )
            session.commit()
    _assert_goals_reconcile(api)


def test_goal_and_transfer_money_reconcile_after_a_mixed_sequence(
    client: TestClient, clean_database: None,
) -> None:
    """Transfers and reservations interleaved: the two systems never disagree about the money."""
    api = Api(client, str(uuid4()))
    a, b = api.account("A", "1000.00"), api.account("B", "300.00")
    goal = api.goal("Mixed", "5000.00")
    total = api.balance(a["id"]) + api.balance(b["id"])

    api.goal_tx(goal["id"], "contribution", "600.00", a["id"])
    api.transfer(a["id"], b["id"], "350.00")                         # leaves A with 650, reserved 600
    api.goal_tx(goal["id"], "contribution", "300.00", b["id"])
    planned = api.transfer(b["id"], a["id"], "100.00", on=FUTURE)
    api.goal_tx(goal["id"], "withdrawal", "200.00", a["id"])
    api.post(f"/api/v1/account-transfers/{planned['id']}/post", {"effective_date": TODAY_ISO}, expect=200)
    client.delete(f"/api/v1/account-transfers/{planned['id']}", headers=api.headers)

    assert api.balance(a["id"]) + api.balance(b["id"]) == total      # nothing created or destroyed by either system
    accounts = api.accounts()
    # a goal's linked money is always backed by, or flagged against, the Account it lives in
    for account in accounts.values():
        reserved = Decimal(account["reserved_amount"])
        assert Decimal(account["unallocated_amount"]) == Decimal(account["balance_as_of_today"]) - reserved
        assert (account["allocation_status"] == "overcommitted") == (reserved > 0 and Decimal(account["unallocated_amount"]) < 0)
    assert Decimal(api.goals()[goal["id"]]["linked_amount"]) == sum((Decimal(x["reserved_amount"]) for x in accounts.values()), Decimal("0"))
    _assert_ledgers_reconcile(api)
    _assert_goals_reconcile(api)
