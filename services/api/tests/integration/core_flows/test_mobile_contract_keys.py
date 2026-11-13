"""Mobile TypeScript response types vs the real API responses (VF-MVP-CORE-001).

The mobile app renders exactly what these types declare, so a field added, renamed or
dropped on one side only is a silent UI bug. This compares the property NAMES declared by
the mobile types with the keys of real responses for the core money flows. Nothing else is
checked (nullability and value shapes stay with the contract docs and the journey test).
The test reads the mobile sources as text; it is skipped when they are not checked out.
"""
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Set
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.helpers import auth_headers

FEATURES = Path(__file__).resolve().parents[5] / "apps" / "mobile" / "src" / "features"

pytestmark = pytest.mark.skipif(not FEATURES.is_dir(), reason="apps/mobile is not checked out")


# Property names of `export type <name> = { ... }` (also `A & { ... }`; the keys of a
# referenced type in the same file are included). Only top-level properties are read.
def ts_type_keys(relative_file: str, name: str) -> Set[str]:
    source = (FEATURES / relative_file).read_text()
    match = re.search(rf"export type {name} =\s*", source)
    assert match, f"type {name} not found in {relative_file}"

    depth = 0
    top_level_text: List[str] = []
    property_text: List[str] = []
    for char in source[match.end():]:
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            continue
        if char == ";" and depth == 0:
            break
        (top_level_text if depth == 0 else property_text if depth == 1 else []).append(char)

    keys = set(re.findall(r"^\s*(\w+)\??:", "".join(property_text), re.MULTILINE))
    for reference in re.findall(r"[A-Z]\w+", "".join(top_level_text)):
        if re.search(rf"export type {reference} =", source):
            keys |= ts_type_keys(relative_file, reference)
    return keys


def assert_same_keys(response_object: dict, relative_file: str, type_name: str) -> None:
    declared = ts_type_keys(relative_file, type_name)
    actual = set(response_object.keys())
    assert actual == declared, (
        f"{type_name}: response-only={sorted(actual - declared)} type-only={sorted(declared - actual)}"
    )


def test_core_money_responses_match_the_mobile_types(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    headers = auth_headers(user)

    def post(path: str, body: dict) -> dict:
        response = client.post(path, headers=headers, json=body)
        assert response.status_code in (200, 201), response.text
        return response.json()

    source = post("/api/v1/accounts", {"name": "A", "type": "checking", "currency": "EUR", "opening_balance": "100.00", "opening_balance_date": "2026-03-02"})
    destination = post("/api/v1/accounts", {"name": "B", "type": "cash", "currency": "EUR"})
    income = post("/api/v1/income", {"amount": "10.00", "currency": "EUR", "received_at": "2026-03-04", "source": "gift", "account_id": source["id"]})
    expense = post("/api/v1/expenses", {"title": "t", "amount": "3.00", "currency": "EUR", "expense_date": "2026-03-04", "account_id": source["id"]})
    transfer = post(
        "/api/v1/account-transfers",
        {"client_request_id": str(uuid4()), "source_account_id": source["id"], "destination_account_id": destination["id"], "amount": "5.00", "transfer_date": "2026-03-05"},
    )
    transactions = client.get(f"/api/v1/accounts/{source['id']}/transactions", headers=headers).json()
    assert {t["kind"] for t in transactions} == {"opening_balance", "income", "expense", "transfer"}
    overview = client.get("/api/v1/analytics/financial-overview?year=2026&month=3", headers=headers).json()
    trend = client.get("/api/v1/analytics/income-expense-trend?count=2", headers=headers).json()
    monthly = client.get("/api/v1/analytics/monthly-summary?year=2026&month=3", headers=headers).json()

    assert_same_keys(source, "accounts/account.types.ts", "Account")
    assert_same_keys(client.get("/api/v1/accounts", headers=headers).json()[0], "accounts/account.types.ts", "Account")
    for row in transactions:
        assert_same_keys(row, "accounts/account.types.ts", "AccountTransaction")
    assert_same_keys(income, "income/income.types.ts", "Income")
    assert_same_keys(expense, "expenses/expense.types.ts", "Expense")
    assert_same_keys(transfer, "transfers/transfer.types.ts", "AccountTransfer")
    assert_same_keys(overview, "analytics/analytics.types.ts", "FinancialOverviewResponse")
    assert_same_keys(trend, "analytics/analytics.types.ts", "IncomeExpenseTrendResponse")
    assert_same_keys(trend["buckets"][0], "analytics/analytics.types.ts", "IncomeExpenseTrendBucket")
    assert_same_keys(monthly, "analytics/analytics.types.ts", "MonthlySummary")


# The string constants `export const NAME = "..."` of a mobile source file (a value may wrap
# onto the next line). Only plain double-quoted literals are read.
def ts_string_constants(relative_file: str) -> Dict[str, str]:
    source = (FEATURES / relative_file).read_text()
    pairs = re.findall(r'export const (\w+) =\s*"((?:[^"\\]|\\.)*)";', source)
    return {name: value.replace('\\"', '"') for name, value in pairs}


# VF-MVP-CORE-003: the Goal / Transfer shapes the mobile screens render.
def test_goal_and_transfer_responses_match_the_mobile_types(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    headers = auth_headers(user)

    def post(path: str, body: dict, expected: int = 201) -> dict:
        response = client.post(path, headers=headers, json=body)
        assert response.status_code == expected, response.text
        return response.json()

    account = post("/api/v1/accounts", {"name": "A", "type": "checking", "currency": "EUR", "opening_balance": "500.00", "opening_balance_date": "2026-03-02"})
    other = post("/api/v1/accounts", {"name": "B", "type": "cash", "currency": "EUR"})
    goal = post("/api/v1/goals", {"name": "G", "target_amount": "300.00"})
    tracked = post(f"/api/v1/goals/{goal['id']}/transactions", {"type": "contribution", "amount": "10.00"})
    linked = post(f"/api/v1/goals/{goal['id']}/transactions", {"type": "contribution", "amount": "20.00", "account_id": account["id"], "client_request_id": str(uuid4())})
    transfer = post("/api/v1/account-transfers", {"client_request_id": str(uuid4()), "source_account_id": account["id"], "destination_account_id": other["id"], "amount": "5.00", "transfer_date": "2026-03-05"})
    planned = post("/api/v1/account-transfers", {"client_request_id": str(uuid4()), "source_account_id": account["id"], "destination_account_id": other["id"], "amount": "5.00", "transfer_date": "2999-01-01"})
    posted = client.post(f"/api/v1/account-transfers/{planned['id']}/post", headers=headers, json={"effective_date": date.today().isoformat()})
    assert posted.status_code == 200, posted.text

    assert_same_keys(goal, "goals/goal.types.ts", "Goal")
    listed = client.get("/api/v1/goals", headers=headers).json()
    assert listed and all(ts_type_keys("goals/goal.types.ts", "Goal") == set(g.keys()) for g in listed)
    # the POST response is GoalTransaction + the optional warnings list; a history row has no warnings
    for created in (tracked, linked):
        assert set(created.keys()) == ts_type_keys("goals/goal.types.ts", "GoalTransactionCreated")
    history = client.get(f"/api/v1/goals/{goal['id']}/transactions", headers=headers).json()
    assert len(history) == 2
    for row in history:
        assert_same_keys(row, "goals/goal.types.ts", "GoalTransaction")
    progress = client.get("/api/v1/analytics/goal-progress", headers=headers).json()
    assert progress
    for item in progress:
        assert_same_keys(item, "analytics/analytics.types.ts", "GoalProgressItem")
    for record in (transfer, planned, posted.json()):
        assert_same_keys(record, "transfers/transfer.types.ts", "AccountTransfer")
    assert_same_keys(client.get("/api/v1/account-transfers", headers=headers).json()[0], "transfers/transfer.types.ts", "AccountTransfer")
    # the Account carries the reservation read model the Goal screens display
    assert_same_keys(client.get("/api/v1/accounts", headers=headers).json()[0], "accounts/account.types.ts", "Account")


# The mobile Goal-transaction error copy is keyed on EXACT backend detail strings. If the backend
# wording drifts, the screen silently falls back to generic text and stops refreshing stale data.
def test_goal_transaction_error_copy_is_keyed_on_the_real_backend_details(client: TestClient, clean_database: None) -> None:
    constants = ts_string_constants("goals/goal-transaction-errors.ts")
    user = str(uuid4())
    headers = auth_headers(user)

    def post(path: str, body: dict) -> dict:
        response = client.post(path, headers=headers, json=body)
        assert response.status_code == 201, response.text
        return response.json()

    def attempt(goal_id: str, body: dict, status_code: int) -> str:
        response = client.post(
            f"/api/v1/goals/{goal_id}/transactions", headers=headers, json={"client_request_id": str(uuid4()), **body}
        )
        assert response.status_code == status_code, response.text
        return response.json()["detail"]

    account = post("/api/v1/accounts", {"name": "A", "type": "checking", "currency": "EUR", "opening_balance": "100.00", "opening_balance_date": "2026-03-02"})
    archived_account = post("/api/v1/accounts", {"name": "Z", "type": "cash", "currency": "EUR"})
    assert client.patch(f"/api/v1/accounts/{archived_account['id']}", headers=headers, json={"status": "archived"}).status_code == 200
    goal = post("/api/v1/goals", {"name": "G", "target_amount": "50.00"})
    archived_goal = post("/api/v1/goals", {"name": "Old", "target_amount": "50.00"})
    assert client.patch(f"/api/v1/goals/{archived_goal['id']}", headers=headers, json={"status": "archived"}).status_code == 200
    key = str(uuid4())
    post(f"/api/v1/goals/{goal['id']}/transactions", {"type": "contribution", "amount": "5.00", "client_request_id": key})

    assert attempt(str(uuid4()), {"type": "contribution", "amount": "1.00"}, 404) == constants["GOAL_NOT_FOUND_DETAIL"]
    assert attempt(goal["id"], {"type": "contribution", "amount": "1.00", "account_id": str(uuid4())}, 404) == constants["ACCOUNT_NOT_FOUND_DETAIL"]
    assert attempt(archived_goal["id"], {"type": "contribution", "amount": "1.00"}, 409) == constants["GOAL_ARCHIVED_DETAIL"]
    assert attempt(goal["id"], {"type": "contribution", "amount": "1.00", "account_id": archived_account["id"]}, 409) == constants["ACCOUNT_ARCHIVED_DETAIL"]
    assert attempt(goal["id"], {"type": "contribution", "amount": "100.01", "account_id": account["id"]}, 409) == constants["CAPACITY_DETAIL"]
    assert attempt(goal["id"], {"type": "withdrawal", "amount": "5.01"}, 409) == constants["TRACKED_SHORTFALL_DETAIL"]
    conflict = client.post(f"/api/v1/goals/{goal['id']}/transactions", headers=headers,
                           json={"client_request_id": key, "type": "contribution", "amount": "6.00"})
    assert conflict.status_code == 409 and conflict.json()["detail"] == constants["IDEMPOTENCY_CONFLICT_DETAIL"]


# VF-MVP-CORE-004: the Budget and Budget status shapes the mobile screens render.
def test_budget_and_budget_status_responses_match_the_mobile_types(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    headers = auth_headers(user)
    today = date.today()

    def post(path: str, body: dict) -> dict:
        response = client.post(path, headers=headers, json=body)
        assert response.status_code == 201, response.text
        return response.json()

    category = post("/api/v1/categories", {"name": "Food", "color": "#FF5733", "icon": "x"})
    # one budget per lifecycle state: active, not started, ended (the status shape is the same)
    active = post("/api/v1/budgets", {"name": "Active", "limit_amount": "100.00", "start_date": today.replace(day=1).isoformat(), "category_id": category["id"]})
    future = post("/api/v1/budgets", {"name": "Future", "limit_amount": "100.00", "start_date": (today.replace(day=1) + timedelta(days=95)).isoformat()})
    post("/api/v1/budgets", {"name": "Ended", "limit_amount": "100.00", "start_date": (today - timedelta(days=90)).isoformat(), "end_date": (today - timedelta(days=60)).isoformat()})
    post("/api/v1/expenses", {"title": "t", "amount": "10.00", "currency": "EUR", "expense_date": today.isoformat(), "category_id": category["id"]})

    updated = client.patch(f"/api/v1/budgets/{future['id']}", headers=headers, json={"limit_amount": "120.00"})
    assert updated.status_code == 200, updated.text

    listed = client.get("/api/v1/budgets", headers=headers).json()
    assert len(listed) == 3
    for record in (active, future, updated.json(), *listed):
        assert_same_keys(record, "budgets/budget.types.ts", "Budget")

    status = client.get("/api/v1/analytics/budget-status", headers=headers).json()
    assert {item["period_state"] for item in status} == {"active", "not_started", "ended"}
    for item in status:
        assert_same_keys(item, "analytics/analytics.types.ts", "BudgetStatusItem")


# VF-MVP-CORE-005: the Receipt flow (upload -> process -> review -> confirm) is typed by hand in the
# mobile app. Every key it reads must exist in the real responses, and the confirm payload the
# review screen sends must be accepted exactly as typed.
def test_receipt_responses_and_confirm_input_match_the_mobile_types(
    client: TestClient, clean_database: None, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.receipts import receipt_ocr_service, receipt_storage_service

    user = str(uuid4())
    headers = auth_headers(user)
    monkeypatch.setattr(receipt_storage_service.settings, "receipt_upload_dir", str(tmp_path))

    class Ocr:
        def extract_text(self, file_path):
            return "LIDL\n11.11.2026\nSUMME 3,68 EUR"

    monkeypatch.setattr(receipt_ocr_service, "receipt_ocr_provider", Ocr())

    uploaded = client.post("/api/v1/receipts/upload", headers=headers, files={"file": ("r.png", b"\x89PNG....", "image/png")}).json()
    processed = client.post(f"/api/v1/receipts/{uploaded['id']}/process", headers=headers).json()
    fetched = client.get(f"/api/v1/receipts/{uploaded['id']}", headers=headers).json()
    account = client.post("/api/v1/accounts", headers=headers, json={"name": "a", "type": "checking", "currency": "EUR"}).json()

    # Every key the review screen sends, in the shape the mobile type declares (account_id omitted when unlinked).
    confirm_input = {"category_id": None, "title": "Lidl", "amount": "3.68", "currency": "EUR", "expense_date": "2026-11-11", "description": None, "account_id": account["id"]}
    confirmed = client.post(f"/api/v1/receipts/{uploaded['id']}/confirm", headers=headers, json=confirm_input)
    assert confirmed.status_code == 200, confirmed.text

    receipt_keys = ts_type_keys("receipts/receipt.types.ts", "Receipt")
    for body in (uploaded, processed, fetched, confirmed.json()["receipt"]):
        assert set(body.keys()) == receipt_keys
    assert set(confirmed.json().keys()) == ts_type_keys("receipts/receipt.types.ts", "ReceiptConfirmResult")
    assert set(confirm_input.keys()) == ts_type_keys("receipts/receipt.types.ts", "ReceiptConfirmInput")
    assert set(confirmed.json()["expense"].keys()) == ts_type_keys("expenses/expense.types.ts", "Expense")


# VF-MVP-CORE-006: every Analytics response the Dashboard and Analytics screens read, key for key, including
# nested items and the nullable blocks (period_over_period, incomplete forecast).
def test_every_analytics_response_matches_the_mobile_types(client: TestClient, clean_database: None) -> None:
    user = str(uuid4())
    headers = auth_headers(user)
    category = client.post("/api/v1/categories", headers=headers, json={"name": "Contract", "color": "#FF5733", "icon": "x"}).json()
    this_month = date.today().replace(day=1)
    previous_month = (this_month - timedelta(days=1)).replace(day=1)
    for day, category_id in ((previous_month + timedelta(days=2), category["id"]), (this_month, None)):
        body = {"title": "t", "amount": "4.00", "currency": "EUR", "expense_date": day.isoformat(), "client_request_id": str(uuid4())}
        if category_id:
            body["category_id"] = category_id
        assert client.post("/api/v1/expenses", headers=headers, json=body).status_code == 201
    assert client.post("/api/v1/budgets", headers=headers, json={"name": "B", "limit_amount": "10.00", "period": "monthly", "start_date": this_month.isoformat()}).status_code == 201
    assert client.post("/api/v1/goals", headers=headers, json={"name": "G", "target_amount": "10.00"}).status_code == 201

    def read(path: str) -> Any:
        response = client.get(f"/api/v1/analytics/{path}", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    summary = read(f"category-summary?year={this_month.year}&month={this_month.month}")
    spending = read("spending-trend?period=month&count=3")
    by_category = read("category-trend?period=month&count=3")
    forecast = read("spending-forecast")

    assert summary
    for item in summary:
        assert_same_keys(item, "analytics/analytics.types.ts", "CategorySummaryItem")
    assert_same_keys(spending, "analytics/analytics.types.ts", "SpendingTrendResponse")
    for bucket in spending["buckets"]:
        assert_same_keys(bucket, "analytics/analytics.types.ts", "SpendingTrendBucket")
    assert spending["period_over_period"] is not None, "two complete months exist for a user with older data"
    assert_same_keys(spending["period_over_period"], "analytics/analytics.types.ts", "PeriodOverPeriodComparison")
    assert_same_keys(by_category, "analytics/analytics.types.ts", "CategoryTrendResponse")
    for item in by_category["categories"]:
        assert_same_keys(item, "analytics/analytics.types.ts", "CategoryTrendItem")
        for bucket in item["buckets"]:
            assert_same_keys(bucket, "analytics/analytics.types.ts", "SpendingTrendBucket")
    assert_same_keys(forecast, "analytics/analytics.types.ts", "SpendingForecastResponse")
    for item in read("budget-status"):
        assert_same_keys(item, "analytics/analytics.types.ts", "BudgetStatusItem")
    for item in read("goal-progress"):
        assert_same_keys(item, "analytics/analytics.types.ts", "GoalProgressItem")
