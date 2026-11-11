"""Budgets journey across modules (VF-MVP-CORE-004).

The router tests cover each Budget endpoint on its own. This file covers what only a
sequence can break: the Budget row, its append-only version history, the expenses it is
measured against, the Category rules that protect it and the status the Budgets screen
renders. Every figure is reconciled against PostgreSQL, never against the API under test.

Invariants asserted here:
- a Budget never writes to the money ledger: Accounts, transactions, Transfers and Goals are
  untouched by any Budget create, edit or delete;
- status.spent = sum(expenses) in the Budget currency, the version's category scope and the
  status window up to today; remaining, exceeded and utilization follow from it exactly;
- every edit that changes the limit or category adds exactly one version; a no-op adds none;
- a Budget can never be stored ending before it starts, and one rejected request changes nothing;
- a Category that any Budget version still scopes to cannot be deleted;
- Budgets of another user are invisible: 404 on edit and delete, absent from list and status.

Dates are relative to the server date so the journey is valid on any day.
"""
import re
from datetime import date, timedelta
from pathlib import Path
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database_session import SessionLocal
from tests.helpers import auth_headers

TODAY = date.today()
TODAY_ISO = TODAY.isoformat()
MONTH_START = TODAY.replace(day=1)
LAST_MONTH_END = MONTH_START - timedelta(days=1)
LONG_AGO = TODAY - timedelta(days=120)
NEXT_MONTH = (MONTH_START + timedelta(days=32)).replace(day=1)
FAR_FUTURE = MONTH_START + timedelta(days=95)


def _sql(query: str, **params: Any) -> Any:
    with SessionLocal() as session:
        return session.execute(text(query), params).scalar()


def _versions(budget_id: str) -> List[Dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.execute(
            text(
                "select effective_from, limit_amount, category_id, change_reason from budget_versions "
                "where budget_id = :b order by created_at, id"
            ),
            {"b": budget_id},
        ).all()
    return [
        {"from": r[0], "limit": Decimal(r[1]), "category": str(r[2]) if r[2] else None, "reason": r[3]}
        for r in rows
    ]


def _sql_spent(user: str, start: date, end: date, category: Optional[str], currency: str = "EUR") -> Decimal:
    return Decimal(
        str(
            _sql(
                "select coalesce(sum(amount), 0) from expenses where user_id = :u and currency = :c "
                "and expense_date between :s and :e and (cast(:cat as uuid) is null or category_id = cast(:cat as uuid))",
                u=user, c=currency, s=start, e=end, cat=category,
            )
        )
    )


def _money_state(user: str) -> str:
    """Everything a Budget must never touch."""
    return str(
        _sql(
            "select (select count(*) from accounts where user_id = :u) || ':' "
            "|| (select count(*) from account_transactions where user_id = :u) || ':' "
            "|| (select coalesce(sum(amount), 0) from account_transactions where user_id = :u) || ':' "
            "|| (select count(*) from account_transfers where user_id = :u) || ':' "
            "|| (select count(*) from goals where user_id = :u) || ':' "
            "|| (select count(*) from goal_transactions where user_id = :u) || ':' "
            "|| (select count(*) from expenses where user_id = :u) || ':' "
            "|| (select coalesce(sum(amount), 0) from expenses where user_id = :u)",
            u=user,
        )
    )


class Api:
    def __init__(self, client: TestClient, user: str) -> None:
        self.client = client
        self.user = user
        self.headers = auth_headers(user)

    def call(self, method: str, path: str, expect: Optional[int], body: Optional[dict] = None) -> Any:
        response = self.client.request(method, path, headers=self.headers, json=body)
        if expect is not None:
            assert response.status_code == expect, f"{method} {path} -> {response.status_code} {response.text}"
        return response

    def category(self, name: str) -> Dict[str, Any]:
        return self.call("POST", "/api/v1/categories", 201, {"name": name, "color": "#FF5733", "icon": "x"}).json()

    def budget(self, name: str, limit: str = "100.00", start: date = MONTH_START, expect: Optional[int] = 201, **extra: Any) -> Any:
        body = {"name": name, "limit_amount": limit, "period": "monthly", "start_date": start.isoformat(), **extra}
        response = self.call("POST", "/api/v1/budgets", expect, body)
        return response.json() if expect == 201 else response

    def patch(self, budget_id: str, body: dict, expect: Optional[int] = 200) -> Any:
        response = self.call("PATCH", f"/api/v1/budgets/{budget_id}", expect, body)
        return response.json() if expect == 200 else response

    def budgets(self) -> List[Dict[str, Any]]:
        return self.call("GET", "/api/v1/budgets", 200).json()

    def status(self, budget_id: Optional[str] = None) -> Any:
        items = self.call("GET", "/api/v1/analytics/budget-status", 200).json()
        if budget_id is None:
            return items
        return next(item for item in items if item["budget_id"] == budget_id)

    def expense(self, amount: str, on: date = TODAY, category: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
        body = {"title": "e", "amount": amount, "currency": "EUR", "expense_date": on.isoformat(), **extra}
        if category:
            body["category_id"] = category
        return self.call("POST", "/api/v1/expenses", 201, body).json()


# ---------------------------------------------------------------------------------------------
# Status reconciliation
# ---------------------------------------------------------------------------------------------


def test_budget_status_equals_the_expenses_in_the_database_for_every_scope(
    client: TestClient, clean_database: None,
) -> None:
    api = Api(client, str(uuid4()))
    food, fun = api.category("Food"), api.category("Fun")
    general = api.budget("General", "1000.00")
    food_budget = api.budget("Food only", "300.00", category_id=food["id"])
    usd_budget = api.budget("Dollars", "50.00", currency="USD")

    # in scope today
    api.expense("40.00", category=food["id"])
    api.expense("25.50", category=fun["id"])
    api.expense("10.00")
    # out of scope: a previous month's period, and a day that has not happened yet
    api.expense("99.00", on=LAST_MONTH_END, category=food["id"])
    api.expense("7.00", on=TODAY + timedelta(days=1), category=food["id"])

    status = api.status()
    assert [s["budget_id"] for s in status] == [b["id"] for b in api.budgets()], "status follows the list order"

    for budget_id, category in ((general["id"], None), (food_budget["id"], food["id"])):
        item = api.status(budget_id)
        spent = _sql_spent(api.user, MONTH_START, TODAY, category)
        limit = Decimal(item["limit_amount"])
        assert Decimal(item["spent"]) == spent
        assert Decimal(item["remaining"]) == max(limit - spent, Decimal("0"))
        assert Decimal(item["exceeded_amount"]) == max(spent - limit, Decimal("0"))
        assert Decimal(item["utilization_percent"]) == (spent / limit * 100).quantize(Decimal("0.01"))
        assert item["is_exceeded"] is (spent > limit)
        assert item["period_state"] == "active"
        assert item["period_start"] == MONTH_START.isoformat()
    assert Decimal(api.status(general["id"])["spent"]) == Decimal("75.50")
    assert Decimal(api.status(food_budget["id"])["spent"]) == Decimal("40.00")

    # a budget in another currency never counts EUR expenses (no FX conversion is invented)
    usd = api.status(usd_budget["id"])
    assert Decimal(usd["spent"]) == Decimal("0") and usd["risk_status"] == "healthy"

    # editing and deleting an expense moves the status by exactly that amount
    expenses = api.call("GET", "/api/v1/expenses", 200).json()
    forty = next(e for e in expenses if e["amount"] == "40.00")
    api.call("PATCH", f"/api/v1/expenses/{forty['id']}", 200, {"amount": "60.00"})
    assert Decimal(api.status(food_budget["id"])["spent"]) == Decimal("60.00")
    assert Decimal(api.status(general["id"])["spent"]) == Decimal("95.50")
    api.call("DELETE", f"/api/v1/expenses/{forty['id']}", 204)
    assert Decimal(api.status(food_budget["id"])["spent"]) == Decimal("0.00")
    assert Decimal(api.status(general["id"])["spent"]) == _sql_spent(api.user, MONTH_START, TODAY, None)


def test_exceeding_a_budget_is_reported_exactly_and_is_exceeded_for_the_risk_status(
    client: TestClient, clean_database: None,
) -> None:
    api = Api(client, str(uuid4()))
    budget = api.budget("Tight", "50.00")
    api.expense("50.00")
    exact = api.status(budget["id"])
    assert Decimal(exact["remaining"]) == 0 and exact["is_exceeded"] is False, "spending exactly the limit is not exceeded"

    api.expense("0.01")
    over = api.status(budget["id"])
    assert over["is_exceeded"] is True and Decimal(over["exceeded_amount"]) == Decimal("0.01")
    assert Decimal(over["remaining"]) == 0 and over["risk_status"] == "exceeded"
    assert Decimal(over["utilization_percent"]) == Decimal("100.02")


def test_weekly_budget_measures_the_calendar_week(client: TestClient, clean_database: None) -> None:
    api = Api(client, str(uuid4()))
    week_start = TODAY - timedelta(days=TODAY.weekday())
    budget = api.budget("Weekly", "70.00", start=week_start - timedelta(days=14), period="weekly")
    api.expense("20.00")
    api.expense("5.00", on=week_start - timedelta(days=1))

    item = api.status(budget["id"])
    assert item["period_start"] == week_start.isoformat()
    assert item["period_end"] == (week_start + timedelta(days=6)).isoformat()
    assert Decimal(item["spent"]) == _sql_spent(api.user, week_start, TODAY, None) == Decimal("20.00")


# ---------------------------------------------------------------------------------------------
# Lifecycle and version history
# ---------------------------------------------------------------------------------------------


def test_every_limit_or_category_change_adds_exactly_one_version_and_no_op_adds_none(
    client: TestClient, clean_database: None,
) -> None:
    api = Api(client, str(uuid4()))
    food = api.category("Food")
    budget = api.budget("Plan", "100.00")
    assert _versions(budget["id"]) == [{"from": MONTH_START, "limit": Decimal("100.00"), "category": None, "reason": "initial"}]

    api.patch(budget["id"], {"name": "Renamed", "end_date": None})
    api.patch(budget["id"], {"limit_amount": "100"})  # the same value, written differently
    assert len(_versions(budget["id"])) == 1, "a rename and an unchanged limit are not period changes"

    api.patch(budget["id"], {"limit_amount": "150.00"})
    api.patch(budget["id"], {"category_id": food["id"]})
    versions = _versions(budget["id"])
    assert [v["reason"] for v in versions] == ["initial", "user_edit", "category_change"]
    assert [v["limit"] for v in versions] == [Decimal("100.00"), Decimal("150.00"), Decimal("150.00")]
    assert versions[-1]["category"] == food["id"]

    stored = api.budgets()[0]
    assert Decimal(stored["limit_amount"]) == Decimal("150.00") and stored["category_id"] == food["id"]
    item = api.status(budget["id"])
    assert Decimal(item["limit_amount"]) == Decimal("150.00") and item["category_id"] == food["id"]
    assert item["category_name"] == "Food"

    # the category can be cleared again: an all-expenses budget
    api.patch(budget["id"], {"category_id": None})
    assert api.status(budget["id"])["category_id"] is None
    assert len(_versions(budget["id"])) == 4


def test_a_budget_that_has_not_started_shows_its_edited_limit_and_category(
    client: TestClient, clean_database: None,
) -> None:
    api = Api(client, str(uuid4()))
    food = api.category("Food")
    budget = api.budget("Next quarter", "100.00", start=FAR_FUTURE)

    before = api.status(budget["id"])
    assert before["period_state"] == "not_started" and Decimal(before["limit_amount"]) == Decimal("100.00")

    api.patch(budget["id"], {"limit_amount": "250.00"})
    api.patch(budget["id"], {"category_id": food["id"]})
    after = api.status(budget["id"])
    assert Decimal(after["limit_amount"]) == Decimal("250.00"), "the edited limit, not the first one"
    assert after["category_id"] == food["id"]
    assert Decimal(after["limit_amount"]) == Decimal(api.budgets()[0]["limit_amount"])
    assert Decimal(after["spent"]) == 0


def test_delete_removes_the_budget_its_versions_and_its_status_and_touches_no_money(
    client: TestClient, clean_database: None,
) -> None:
    api = Api(client, str(uuid4()))
    account = api.call("POST", "/api/v1/accounts", 201, {"name": "A", "type": "checking", "currency": "EUR", "opening_balance": "500.00", "opening_balance_date": LONG_AGO.isoformat()}).json()
    api.expense("12.34", account_id=account["id"])
    goal = api.call("POST", "/api/v1/goals", 201, {"name": "G", "target_amount": "100.00"}).json()
    api.call("POST", f"/api/v1/goals/{goal['id']}/transactions", 201, {"type": "contribution", "amount": "10.00"})
    money = _money_state(api.user)

    keep = api.budget("Keep", "100.00")
    gone = api.budget("Gone", "100.00")
    api.patch(gone["id"], {"limit_amount": "120.00"})
    assert len(_versions(gone["id"])) == 2
    assert _money_state(api.user) == money, "creating and editing budgets writes no money"

    api.call("DELETE", f"/api/v1/budgets/{gone['id']}", 204)
    assert _versions(gone["id"]) == []
    assert [b["id"] for b in api.budgets()] == [keep["id"]]
    assert [s["budget_id"] for s in api.status()] == [keep["id"]]
    assert len(_versions(keep["id"])) == 1
    assert api.call("DELETE", f"/api/v1/budgets/{gone['id']}", 404).json()["code"] == "budget_not_found"
    assert _money_state(api.user) == money, "deleting a budget writes no money"


def test_a_budget_referenced_by_a_rule_cannot_be_deleted_and_stays_intact(
    client: TestClient, clean_database: None,
) -> None:
    api = Api(client, str(uuid4()))
    budget = api.budget("Watched", "100.00")
    api.call("POST", "/api/v1/financial-rules", 201, {"rule_type": "BUDGET_ALERT", "name": "Watch", "budget_id": budget["id"]})

    response = api.call("DELETE", f"/api/v1/budgets/{budget['id']}", 409)
    assert response.json()["code"] == "budget_referenced_by_rule"
    assert response.json()["detail"] == "Budget is referenced by a financial rule and cannot be deleted."
    assert [b["id"] for b in api.budgets()] == [budget["id"]]
    assert len(_versions(budget["id"])) == 1


def test_budget_list_keeps_its_order_after_an_edit(client: TestClient, clean_database: None) -> None:
    api = Api(client, str(uuid4()))
    names = ["alpha", "bravo", "charlie", "delta"]
    ids = [api.budget(name, "10.00")["id"] for name in names]
    older = api.budget("older", "10.00", start=MONTH_START - timedelta(days=62))

    expected = names + ["older"]
    assert [b["name"] for b in api.budgets()] == expected

    api.patch(ids[0], {"limit_amount": "11.00"})
    api.patch(ids[1], {"name": "bravo"})
    api.patch(older["id"], {"limit_amount": "12.00"})
    assert [b["name"] for b in api.budgets()] == expected, "an edited budget must not jump in the list"
    assert [s["budget_name"] for s in api.status()] == expected


# ---------------------------------------------------------------------------------------------
# Duplicates, ownership, immutability
# ---------------------------------------------------------------------------------------------


def test_duplicates_are_refused_and_a_refused_edit_changes_nothing(client: TestClient, clean_database: None) -> None:
    api = Api(client, str(uuid4()))
    first = api.budget("Food", "100.00")
    second = api.budget("Other", "100.00")

    duplicate = api.budget("Food", "999.00", expect=409)
    assert duplicate.json()["code"] == "budget_already_exists"
    assert int(_sql("select count(*) from budgets where user_id = :u", u=api.user)) == 2

    # the same name in another period or on another start date is a different budget
    api.budget("Food", "100.00", period="weekly")
    api.budget("Food", "100.00", start=MONTH_START - timedelta(days=40))

    # renaming onto an existing name is refused and neither the row nor its history moves
    snapshot = (api.budgets(), _versions(second["id"]))
    refused = api.patch(second["id"], {"name": "Food", "limit_amount": "555.00"}, expect=409)
    assert refused.json()["code"] == "budget_already_exists"
    assert (api.budgets(), _versions(second["id"])) == snapshot
    assert _versions(first["id"])[0]["limit"] == Decimal("100.00")


def test_budgets_are_private_to_their_owner(client: TestClient, clean_database: None) -> None:
    owner, other = Api(client, str(uuid4())), Api(client, str(uuid4()))
    category = owner.category("Mine")
    budget = owner.budget("Private", "100.00")
    other.budget("Theirs", "100.00")

    assert [b["name"] for b in other.budgets()] == ["Theirs"]
    assert [s["budget_name"] for s in other.status()] == ["Theirs"]
    assert other.call("PATCH", f"/api/v1/budgets/{budget['id']}", 404, {"limit_amount": "1.00"}).json()["code"] == "budget_not_found"
    assert other.call("DELETE", f"/api/v1/budgets/{budget['id']}", 404).json()["code"] == "budget_not_found"
    # someone else's category is a 404, never a cross-user link
    assert other.budget("Stolen", "10.00", category_id=category["id"], expect=404).json()["code"] == "category_not_found"
    assert other.patch(other.budgets()[0]["id"], {"category_id": category["id"]}, expect=404).json()["code"] == "category_not_found"
    assert owner.budgets()[0]["limit_amount"] == "100.00" and len(_versions(budget["id"])) == 1
    assert other.call("POST", "/api/v1/budgets", 422, {"user_id": owner.user, "name": "x", "limit_amount": "1.00", "start_date": TODAY_ISO}).status_code == 422


def test_currency_and_period_definition_rules(client: TestClient, clean_database: None) -> None:
    api = Api(client, str(uuid4()))
    old = api.budget("Old", "100.00", start=LONG_AGO)

    # currency can never change, not even to the same value
    assert api.patch(old["id"], {"currency": "USD"}, expect=409).json()["code"] == "budget_immutable_field"
    assert api.patch(old["id"], {"currency": "EUR"}, expect=409).json()["code"] == "budget_immutable_field"
    # once its first period has completed, period and start date are fixed...
    assert api.patch(old["id"], {"period": "weekly"}, expect=409).json()["code"] == "budget_immutable_field"
    assert api.patch(old["id"], {"start_date": TODAY_ISO}, expect=409).json()["code"] == "budget_immutable_field"
    # ...but sending the stored value again is not a change and must not be refused
    api.patch(old["id"], {"period": "monthly", "name": "Old 2"})
    api.patch(old["id"], {"start_date": LONG_AGO.isoformat(), "name": "Old 3"})
    stored = api.budgets()[0]
    assert stored["name"] == "Old 3" and stored["period"] == "monthly" and stored["start_date"] == LONG_AGO.isoformat()
    assert len(_versions(old["id"])) == 1

    # within its first period the definition may be corrected, and the history is rebuilt from it
    fresh = api.budget("Fresh", "100.00", start=TODAY)
    api.patch(fresh["id"], {"limit_amount": "130.00"})
    assert len(_versions(fresh["id"])) == 2
    api.patch(fresh["id"], {"period": "weekly"})
    rebuilt = _versions(fresh["id"])
    assert len(rebuilt) == 1 and rebuilt[0]["reason"] == "initial" and rebuilt[0]["limit"] == Decimal("130.00")
    assert api.status(fresh["id"])["period"] == "weekly"
    assert _versions(fresh["id"])[0]["from"] == TODAY - timedelta(days=TODAY.weekday())


# ---------------------------------------------------------------------------------------------
# Dates: a budget can never end before it starts
# ---------------------------------------------------------------------------------------------


def test_a_budget_can_never_be_saved_ending_before_it_starts(client: TestClient, clean_database: None) -> None:
    api = Api(client, str(uuid4()))
    healthy = api.budget("Healthy", "100.00")
    future = api.budget("Future", "100.00", start=FAR_FUTURE)
    ending = api.budget("Ending", "100.00", start=TODAY - timedelta(days=2), end_date=(FAR_FUTURE + timedelta(days=60)).isoformat())

    # creation: rejected by the schema
    api.budget("Inverted", "10.00", start=TODAY, end_date=(TODAY - timedelta(days=1)).isoformat(), expect=422)

    # a partial update is checked against the stored value of the other date
    before = (api.budgets(), _versions(future["id"]), _versions(ending["id"]))
    too_early = api.patch(future["id"], {"end_date": (FAR_FUTURE - timedelta(days=3)).isoformat()}, expect=422)
    assert too_early.json()["code"] == "budget_date_range_invalid"
    too_late = api.patch(ending["id"], {"start_date": (FAR_FUTURE + timedelta(days=400)).isoformat()}, expect=422)
    assert too_late.json()["code"] == "budget_date_range_invalid"
    assert (api.budgets(), _versions(future["id"]), _versions(ending["id"])) == before, "a refused request changes nothing"
    assert int(_sql("select count(*) from budgets where end_date < start_date")) == 0

    # the whole list and the status still load
    assert len(api.budgets()) == 3 and len(api.status()) == 3

    # moving the start past the stored end of a not-yet-started budget is refused as well
    api.patch(future["id"], {"end_date": (FAR_FUTURE + timedelta(days=20)).isoformat()})
    refused = api.patch(future["id"], {"start_date": (FAR_FUTURE + timedelta(days=30)).isoformat()}, expect=422)
    assert refused.json()["code"] == "budget_date_range_invalid"
    assert int(_sql("select count(*) from budgets where end_date < start_date")) == 0
    assert api.patch(healthy["id"], {"end_date": TODAY_ISO})["end_date"] == TODAY_ISO


def test_end_dates_cannot_be_set_in_the_past_but_can_be_today_or_cleared(client: TestClient, clean_database: None) -> None:
    api = Api(client, str(uuid4()))
    budget = api.budget("Ends", "100.00")

    refused = api.patch(budget["id"], {"end_date": (TODAY - timedelta(days=1)).isoformat()}, expect=409)
    assert refused.json()["code"] == "budget_retroactive_deactivation"
    assert refused.json()["detail"] == "Budget end date cannot be set to a date before today."
    assert api.budgets()[0]["end_date"] is None

    ended_today = api.patch(budget["id"], {"end_date": TODAY_ISO})
    assert ended_today["end_date"] == TODAY_ISO and api.status(budget["id"])["period_state"] == "active"
    assert api.patch(budget["id"], {"end_date": None})["end_date"] is None
    assert api.budgets()[0]["end_date"] is None


# ---------------------------------------------------------------------------------------------
# Categories protect budgets
# ---------------------------------------------------------------------------------------------


def test_a_category_that_any_budget_version_scopes_to_cannot_be_deleted(client: TestClient, clean_database: None) -> None:
    api = Api(client, str(uuid4()))
    old, new = api.category("Old"), api.category("New")
    budget = api.budget("Scoped", "100.00", category_id=old["id"])

    in_use = api.call("DELETE", f"/api/v1/categories/{old['id']}", 409)
    assert in_use.json()["code"] == "category_in_use_by_budget"

    # moving the budget to another category leaves the old one in the version history
    api.patch(budget["id"], {"category_id": new["id"]})
    still = api.call("DELETE", f"/api/v1/categories/{old['id']}", 409)
    assert still.json()["code"] == "category_in_use_by_budget", "a 409 with a clear cause, never a database error"
    assert api.status(budget["id"])["category_id"] == new["id"]

    # hiding is the supported alternative and keeps every figure
    api.call("PATCH", f"/api/v1/categories/{old['id']}", 200, {"is_visible": False})
    assert Decimal(api.status(budget["id"])["limit_amount"]) == Decimal("100.00")

    # once no budget refers to it any more, it can go
    api.call("DELETE", f"/api/v1/budgets/{budget['id']}", 204)
    api.call("DELETE", f"/api/v1/categories/{old['id']}", 204)
    api.call("DELETE", f"/api/v1/categories/{new['id']}", 204)


# ---------------------------------------------------------------------------------------------
# Validation boundaries
# ---------------------------------------------------------------------------------------------


def test_request_validation_rejects_bad_input_and_stores_good_input_exactly(client: TestClient, clean_database: None) -> None:
    api = Api(client, str(uuid4()))
    good = {"name": "x", "start_date": TODAY_ISO}

    for limit in ("0", "0.00", "-1", "1.234", "abc", "", None, "10000000000.00"):
        assert api.call("POST", "/api/v1/budgets", 422, {**good, "limit_amount": limit}).status_code == 422, limit
    for name in ("", "   ", None):
        assert api.call("POST", "/api/v1/budgets", 422, {**good, "limit_amount": "1.00", "name": name}).status_code == 422, repr(name)
    for currency in ("EU", "EURO", "E1R", "12 ", "€€€"):
        assert api.call("POST", "/api/v1/budgets", 422, {**good, "limit_amount": "1.00", "currency": currency}).status_code == 422, currency
    for bad in ({"period": "daily"}, {"start_date": "2026-02-30"}, {"start_date": "05/01/2026"}, {"category_id": "nope"}, {"unknown": 1}):
        assert api.call("POST", "/api/v1/budgets", 422, {**good, "limit_amount": "1.00", **bad}).status_code == 422, bad
    assert int(_sql("select count(*) from budgets where user_id = :u", u=api.user)) == 0

    # exact storage: no rounding, trimmed name, normalized currency, the largest allowed limit
    stored = api.call("POST", "/api/v1/budgets", 201, {"name": "  Padded  ", "limit_amount": "9999999999.99", "currency": "eur", "start_date": TODAY_ISO}).json()
    assert stored["name"] == "Padded" and stored["currency"] == "EUR" and stored["limit_amount"] == "9999999999.99"
    assert _sql("select limit_amount::text from budgets where id = :b", b=stored["id"]) == "9999999999.99"
    tiny = api.call("POST", "/api/v1/budgets", 201, {"name": "tiny", "limit_amount": "0.01", "start_date": TODAY_ISO}).json()
    assert tiny["limit_amount"] == "0.01" and tiny["period"] == "monthly" and tiny["currency"] == "EUR"

    # updates: empty, null for a required field, blank name, forbidden field
    assert api.patch(tiny["id"], {}, expect=422).status_code == 422
    for body in ({"name": None}, {"limit_amount": None}, {"period": None}, {"start_date": None}, {"name": "  "}, {"limit_amount": "0"}, {"user_id": api.user}, {"currency": "E1R"}):
        assert api.patch(tiny["id"], body, expect=422).status_code == 422, body
    assert api.patch(tiny["id"], {"name": "  trimmed "})["name"] == "trimmed"


MOBILE_COPY_TEST = (
    Path(__file__).resolve().parents[5] / "apps" / "mobile" / "src" / "features" / "budgets" / "budget-lifecycle.test.ts"
)


def test_the_messages_the_mobile_tests_expect_are_the_real_backend_details(client: TestClient, clean_database: None) -> None:
    """Mobile shows the backend `detail` as the user's message, so the strings its tests pin must be the live ones."""
    if not MOBILE_COPY_TEST.is_file():
        import pytest

        pytest.skip("apps/mobile is not checked out")

    expected = {
        code: (int(status), detail)
        for status, code, detail in re.findall(r'\[(\d{3}), "(\w+)", "((?:[^"\\]|\\.)*)"\]', MOBILE_COPY_TEST.read_text())
    }
    assert set(expected) == {
        "budget_already_exists", "budget_immutable_field", "budget_retroactive_deactivation",
        "budget_referenced_by_rule", "budget_date_range_invalid", "budget_not_found", "category_in_use_by_budget",
    }

    api = Api(client, str(uuid4()))
    category = api.category("Food")
    budget = api.budget("A", "10.00", category_id=category["id"])
    watched = api.budget("W", "10.00")
    api.call("POST", "/api/v1/financial-rules", 201, {"rule_type": "BUDGET_ALERT", "name": "w", "budget_id": watched["id"]})
    future = api.budget("F", "10.00", start=FAR_FUTURE)

    actual = {
        "budget_already_exists": api.budget("A", "10.00", category_id=category["id"], expect=409),
        "budget_immutable_field": api.patch(budget["id"], {"currency": "USD"}, expect=409),
        "budget_retroactive_deactivation": api.patch(budget["id"], {"end_date": (TODAY - timedelta(days=1)).isoformat()}, expect=409),
        "budget_referenced_by_rule": api.call("DELETE", f"/api/v1/budgets/{watched['id']}", 409),
        "budget_date_range_invalid": api.patch(future["id"], {"end_date": (FAR_FUTURE - timedelta(days=1)).isoformat()}, expect=422),
        "budget_not_found": api.call("DELETE", f"/api/v1/budgets/{uuid4()}", 404),
        "category_in_use_by_budget": api.call("DELETE", f"/api/v1/categories/{category['id']}", 409),
    }
    for code, response in actual.items():
        body = response.json()
        assert (response.status_code, body["detail"]) == expected[code], code
        assert body["code"] == code
