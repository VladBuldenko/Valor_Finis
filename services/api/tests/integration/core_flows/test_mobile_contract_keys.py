"""Mobile TypeScript response types vs the real API responses (VF-MVP-CORE-001).

The mobile app renders exactly what these types declare, so a field added, renamed or
dropped on one side only is a silent UI bug. This compares the property NAMES declared by
the mobile types with the keys of real responses for the core money flows. Nothing else is
checked (nullability and value shapes stay with the contract docs and the journey test).
The test reads the mobile sources as text; it is skipped when they are not checked out.
"""
import re
from pathlib import Path
from typing import List, Set
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
