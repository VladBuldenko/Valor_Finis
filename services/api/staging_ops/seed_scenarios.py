"""
Deterministic synthetic scenarios for the staging seed.

What:
    Pure data: for each QA actor an ordered list of steps (accounts, goals,
    budgets, rules, income, expenses, a reservation, event drain, alert
    evaluation) with stable scenario identifiers. It performs no I/O.

Why:
    The seed must be repeatable and reviewable without a database. All dates
    derive from one `as_of` date, every amount is a decimal string, and every
    currency other than the base currency is funded only through opening
    balances, so the seed never needs a foreign-exchange lookup (no network).
    Entities are created through the backend domain services (seed.py), never
    by writing ledger rows directly. Scenario catalog and acceptance mapping:
    docs/operations/staging/staging-architecture-and-runbook.md.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List

BASE_CURRENCY = "EUR"
ACTORS = ("QA-A", "QA-B")
MARKER_PREFIX = "QA-SEED-"

# Fixed namespace so client_request_ids are stable across runs and machines.
REQUEST_ID_NAMESPACE = uuid.UUID("5b0a7f3e-6c1d-4f7e-9a52-0c3d1e7b8a41")

SCENARIOS = {
    "QA1-S01": "Accounts in several currencies (three EUR accounts, one USD account)",
    "QA1-S02": "Category and monthly budget",
    "QA1-S03": "Income and expenses linked to accounts",
    "QA1-S04": "Goals in two currencies",
    "QA1-S05": "Linked goal reservation (idempotent request id)",
    "QA1-S06": "AUTO allocation rule executed on income (execution history)",
    "QA1-S07": "CONFIRM allocation rule leaving a pending proposal",
    "QA1-S08": "Floor alert on an account",
    "QA1-S09": "Budget alert after the limit is exceeded",
    "QA1-S10": "Cross-user isolation: QA-B owns separate data with overlapping names",
}


# Minimum rows each actor must hold after its steps ran, proving the domain
# services produced the intended effects (checked before the marker is written).
MINIMUM_ROWS = {
    "QA-A": {"accounts": 4, "goals": 3, "budgets": 1, "income": 2, "expenses": 2, "financial_rules": 4, "goal_transactions": 2, "rule_executions": 2, "rule_alerts": 2},
    "QA-B": {"accounts": 1, "goals": 1, "budgets": 1, "income": 1, "expenses": 1, "financial_rules": 1, "goal_transactions": 1, "rule_executions": 1, "rule_alerts": 0},
}


@dataclass(frozen=True)
class Step:
    scenario: str
    kind: str
    key: str
    payload: Dict[str, object] = field(default_factory=dict)


# Resolves a payload placeholder: "$ref:<key>" refers to an entity created by an earlier step.
def ref(key: str) -> str:
    return f"$ref:{key}"


def request_id(actor: str, key: str) -> str:
    return str(uuid.uuid5(REQUEST_ID_NAMESPACE, f"{actor}/{key}"))


def _first_of_month(day: date) -> date:
    return day.replace(day=1)


def _iso(day: date) -> str:
    return day.isoformat()


def _qa_a(as_of: date) -> List[Step]:
    opening = _iso(as_of - timedelta(days=30))
    return [
        Step("QA1-S02", "category", "cat", {"name": "QA Groceries", "color": "#2E7D32", "icon": "cart"}),
        Step("QA1-S01", "account", "acct-eur", {"name": "QA-A EUR Checking", "type": "checking", "currency": "EUR", "opening_balance": "5000.00", "opening_balance_date": opening}),
        Step("QA1-S01", "account", "acct-eur2", {"name": "QA-A EUR Savings", "type": "savings", "currency": "EUR", "opening_balance": "1500.00", "opening_balance_date": opening}),
        # A floor above the balance must not share an account with the AUTO rule: the floor would leave it no capacity.
        Step("QA1-S01", "account", "acct-eur3", {"name": "QA-A EUR Buffer", "type": "savings", "currency": "EUR", "opening_balance": "600.00", "opening_balance_date": opening}),
        Step("QA1-S01", "account", "acct-usd", {"name": "QA-A USD Cash", "type": "cash", "currency": "USD", "opening_balance": "800.00", "opening_balance_date": opening}),
        Step("QA1-S04", "goal", "goal-auto", {"name": "QA-A Emergency Fund", "target_amount": "6000.00", "currency": "EUR", "target_date": _iso(as_of + timedelta(days=365)), "status": "active"}),
        Step("QA1-S04", "goal", "goal-confirm", {"name": "QA-A Holiday", "target_amount": "2000.00", "currency": "EUR", "target_date": _iso(as_of + timedelta(days=300)), "status": "active"}),
        Step("QA1-S04", "goal", "goal-usd", {"name": "QA-A USD Reserve", "target_amount": "1200.00", "currency": "USD", "target_date": _iso(as_of + timedelta(days=200)), "status": "active"}),
        Step("QA1-S02", "budget", "budget", {"category_id": ref("cat"), "name": "QA-A Groceries Budget", "limit_amount": "400.00", "currency": "EUR", "period": "monthly", "start_date": _iso(_first_of_month(as_of)), "end_date": None}),
        Step("QA1-S06", "rule", "rule-auto", {"rule_type": "INCOME_ALLOCATION", "name": "QA-A Save from salary (AUTO)", "source_account_id": ref("acct-eur"), "execution_mode": "AUTO", "policy": "FIXED_PER_GOAL", "targets": [{"goal_id": ref("goal-auto"), "amount_or_cap": "100.00"}]}),
        Step("QA1-S07", "rule", "rule-confirm", {"rule_type": "INCOME_ALLOCATION", "name": "QA-A Holiday saving (CONFIRM)", "source_account_id": ref("acct-eur2"), "execution_mode": "CONFIRM", "policy": "FIXED_PER_GOAL", "targets": [{"goal_id": ref("goal-confirm"), "amount_or_cap": "50.00"}]}),
        Step("QA1-S08", "rule", "rule-floor", {"rule_type": "MINIMUM_UNALLOCATED_FLOOR", "name": "QA-A Floor", "source_account_id": ref("acct-eur3"), "floor_amount": "1000.00"}),
        Step("QA1-S09", "rule", "rule-budget", {"rule_type": "BUDGET_ALERT", "name": "QA-A Budget watch", "budget_id": ref("budget")}),
        # Rules are enabled before the income so the income is a live event for them.
        Step("QA1-S03", "income", "income-salary", {"amount": "3000.00", "currency": "EUR", "received_at": _iso(as_of), "source": "salary", "description": None, "account_id": ref("acct-eur")}),
        Step("QA1-S07", "income", "income-side", {"amount": "800.00", "currency": "EUR", "received_at": _iso(as_of), "source": "salary", "description": None, "account_id": ref("acct-eur2")}),
        Step("QA1-S03", "expense", "expense-1", {"category_id": ref("cat"), "title": "QA-A Groceries", "amount": "250.00", "currency": "EUR", "expense_date": _iso(as_of), "description": None, "source": "manual", "account_id": ref("acct-eur")}),
        Step("QA1-S09", "expense", "expense-2", {"category_id": ref("cat"), "title": "QA-A Supermarket", "amount": "180.00", "currency": "EUR", "expense_date": _iso(as_of), "description": None, "source": "manual", "account_id": ref("acct-eur")}),
        Step("QA1-S05", "reservation", "reserve-usd", {"goal": "goal-usd", "type": "contribution", "amount": "100.00", "account_id": ref("acct-usd"), "client_request_id": request_id("QA-A", "reserve-usd")}),
        Step("QA1-S06", "drain", "drain", {}),
        Step("QA1-S08", "alerts", "alerts", {}),
    ]


def _qa_b(as_of: date) -> List[Step]:
    opening = _iso(as_of - timedelta(days=30))
    return [
        # Overlapping names with QA-A on purpose: isolation must hold by owner, not by name.
        Step("QA1-S10", "category", "cat", {"name": "QA Groceries", "color": "#1565C0", "icon": "cart"}),
        Step("QA1-S10", "account", "acct-eur", {"name": "QA-B EUR Checking", "type": "checking", "currency": "EUR", "opening_balance": "2500.00", "opening_balance_date": opening}),
        Step("QA1-S10", "goal", "goal-auto", {"name": "QA-B Laptop", "target_amount": "1500.00", "currency": "EUR", "target_date": _iso(as_of + timedelta(days=200)), "status": "active"}),
        Step("QA1-S10", "budget", "budget", {"category_id": ref("cat"), "name": "QA-B Groceries Budget", "limit_amount": "300.00", "currency": "EUR", "period": "monthly", "start_date": _iso(_first_of_month(as_of)), "end_date": None}),
        Step("QA1-S10", "rule", "rule-auto", {"rule_type": "INCOME_ALLOCATION", "name": "QA-B Save from salary (AUTO)", "source_account_id": ref("acct-eur"), "execution_mode": "AUTO", "policy": "FIXED_PER_GOAL", "targets": [{"goal_id": ref("goal-auto"), "amount_or_cap": "75.00"}]}),
        Step("QA1-S10", "income", "income-salary", {"amount": "2000.00", "currency": "EUR", "received_at": _iso(as_of), "source": "salary", "description": None, "account_id": ref("acct-eur")}),
        Step("QA1-S10", "expense", "expense-1", {"category_id": ref("cat"), "title": "QA-B Groceries", "amount": "120.00", "currency": "EUR", "expense_date": _iso(as_of), "description": None, "source": "manual", "account_id": ref("acct-eur")}),
        Step("QA1-S10", "drain", "drain", {}),
        Step("QA1-S10", "alerts", "alerts", {}),
    ]


# Returns the ordered steps for every actor.
# Parameters:
# - as_of: the business date every other date derives from.
# Returns:
# - {"QA-A": [...], "QA-B": [...]}; identical output for identical input.
def build_scenarios(as_of: date) -> Dict[str, List[Step]]:
    return {"QA-A": _qa_a(as_of), "QA-B": _qa_b(as_of)}


def marker_name(staging_id: str) -> str:
    return f"{MARKER_PREFIX}{staging_id}"
