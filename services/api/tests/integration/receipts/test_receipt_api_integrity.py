"""Receipt API integrity (VF-MVP-CORE-005A).

Receipt lifecycle and financial references are server-owned. Before this slice a public
PATCH /receipts/{id} (and POST /receipts with client-supplied file references) let an authenticated
user forge status, expense_id, OCR results and file locations. The worst reproduced sequence: reset a
CONFIRMED receipt to "uploaded", process and confirm it again -> a second Expense and a second Account
debit for the same receipt. These tests pin the public surface and prove every forgery attempt changes nothing.
"""
import io
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from app.db.database_session import SessionLocal
from app.main import app
from app.modules.receipts import receipt_ocr_service, receipt_storage_service
from app.modules.receipts.receipt_schemas import ReceiptCreate, ReceiptUpdate
from tests.helpers import auth_headers, create_receipt, set_receipt_state

TODAY = date.today().isoformat()
RECEIPT_PREFIX = "/api/v1/receipts"


def _sql(query: str, **params: Any) -> Any:
    with SessionLocal() as session:
        return session.execute(text(query), params).all()


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buffer, "PNG")
    return buffer.getvalue()


class Ocr:
    def extract_text(self, file_path: Path) -> str:
        return f"LIDL\n{TODAY}\nSUMME 3,68 EUR"


@pytest.fixture(autouse=True)
def isolated_storage_and_ocr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(receipt_storage_service.settings, "receipt_upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(receipt_ocr_service, "receipt_ocr_provider", Ocr())


class User:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.id = str(uuid4())
        self.headers = auth_headers(self.id)

    def call(self, method: str, path: str, **kwargs: Any) -> Any:
        return self.client.request(method, f"{RECEIPT_PREFIX}{path}", headers=self.headers, **kwargs)

    def upload(self) -> Dict[str, Any]:
        response = self.call("POST", "/upload", files={"file": ("r.png", _png(), "image/png")})
        assert response.status_code == 201, response.text
        return response.json()

    def confirmed(self, account_id: str) -> Dict[str, Any]:
        receipt = self.upload()
        assert self.call("POST", f"/{receipt['id']}/process").status_code == 200
        assert self.call("POST", f"/{receipt['id']}/confirm", json={"account_id": account_id}).status_code == 200
        return receipt

    def account(self) -> str:
        response = self.client.post(
            "/api/v1/accounts", headers=self.headers,
            json={"name": "a", "type": "checking", "currency": "EUR", "opening_balance": "100.00"},
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def expense(self) -> str:
        response = self.client.post(
            "/api/v1/expenses", headers=self.headers,
            json={"title": "own", "amount": "50.00", "currency": "EUR", "expense_date": TODAY, "client_request_id": str(uuid4())},
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]


def _state(user: str, receipt_id: str, account_id: str) -> Tuple[Any, ...]:
    """Everything a forged request could change: the receipt row, Expenses, ledger and balance."""
    receipt = _sql(
        "select status, expense_id, ocr_text, merchant_detected, total_amount_detected, currency_detected, "
        "purchase_date_detected, storage_path, file_url from receipts where id = :r", r=receipt_id,
    )[0]
    counts = _sql(
        "select (select count(*) from expenses where user_id = :u), "
        "(select count(*) from account_transactions where user_id = :u and kind = 'expense'), "
        "(select coalesce(sum(case direction when 'credit' then amount else -amount end), 0) "
        "from account_transactions where account_id = :a)", u=user, a=account_id,
    )[0]
    return tuple(receipt) + tuple(counts)


# ---------------------------------------------------------------------------------------------
# The public surface
# ---------------------------------------------------------------------------------------------


def test_the_public_receipt_routes_are_exactly_the_server_owned_flow() -> None:
    routes = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(RECEIPT_PREFIX)
        for method in route.methods
    }

    assert routes == {
        ("POST", f"{RECEIPT_PREFIX}/upload"),
        ("POST", f"{RECEIPT_PREFIX}/{{receipt_id}}/process"),
        ("POST", f"{RECEIPT_PREFIX}/{{receipt_id}}/confirm"),
        ("GET", RECEIPT_PREFIX),
        ("GET", f"{RECEIPT_PREFIX}/{{receipt_id}}"),
        ("DELETE", f"{RECEIPT_PREFIX}/{{receipt_id}}"),
    }


def test_no_public_receipt_route_accepts_the_internal_persistence_schemas() -> None:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith(RECEIPT_PREFIX):
            for param in route.dependant.body_params:
                annotation = param.field_info.annotation
                assert annotation not in (ReceiptCreate, ReceiptUpdate), f"{route.path} exposes {annotation.__name__}"


# ---------------------------------------------------------------------------------------------
# Every forgery attempt is refused and changes nothing
# ---------------------------------------------------------------------------------------------

FORGERIES: List[Tuple[str, str, Dict[str, Any]]] = [
    ("processed without OCR", "PATCH", {"status": "processed", "merchant_detected": "FORGED", "total_amount_detected": "9.99",
                                       "currency_detected": "EUR", "purchase_date_detected": TODAY, "ocr_text": "forged"}),
    ("confirmed without an Expense", "PATCH", {"status": "confirmed"}),
    ("reset to uploaded", "PATCH", {"status": "uploaded", "expense_id": None}),
    ("reset to processed", "PATCH", {"status": "processed"}),
    ("link an unrelated Expense", "PATCH", {"expense_id": "{expense}"}),
    ("rewrite OCR evidence", "PATCH", {"merchant_detected": "REWRITTEN", "total_amount_detected": "1.00", "ocr_text": "x"}),
    ("point at a server file", "PATCH", {"storage_path": "/etc/hosts"}),
    ("point at another user's object", "PATCH", {"storage_path": "{foreign_path}", "file_url": "https://evil.example/x"}),
    ("empty body", "PATCH", {}),
]


@pytest.mark.parametrize("label,method,body", FORGERIES, ids=[f[0] for f in FORGERIES])
def test_forging_a_receipt_through_the_api_is_refused_and_changes_nothing(
    client: TestClient, clean_database: None, label: str, method: str, body: Dict[str, Any],
) -> None:
    owner, other = User(client), User(client)
    account = owner.account()
    foreign_path = other.upload()["storage_path"]
    values = {"expense": owner.expense(), "foreign_path": foreign_path}
    body = {key: values.get(value.strip("{}"), value) if isinstance(value, str) and value.startswith("{") else value for key, value in body.items()}
    uploaded = owner.upload()
    confirmed = owner.confirmed(account)

    for receipt in (uploaded, confirmed):
        before = _state(owner.id, receipt["id"], account)

        response = owner.call(method, f"/{receipt['id']}", json=body)

        assert response.status_code == 405 and response.json()["code"] == "method_not_allowed", label
        assert _state(owner.id, receipt["id"], account) == before, label


@pytest.mark.parametrize("path", ["", "/"])
def test_creating_a_receipt_from_client_supplied_references_is_not_possible(
    client: TestClient, clean_database: None, path: str,
) -> None:
    user, other = User(client), User(client)
    foreign_path = other.upload()["storage_path"]
    receipts_before = _sql("select count(*) from receipts")[0][0]

    for body in (
        {"storage_path": foreign_path},
        {"storage_path": "/etc/hosts"},
        {"file_url": "javascript:alert(1)"},
        {"storage_path": foreign_path, "file_url": "https://evil.example/x"},
    ):
        response = user.call("POST", path, json=body)

        assert response.status_code in (404, 405), f"{path!r} {body}: {response.status_code}"

    assert _sql("select count(*) from receipts")[0][0] == receipts_before


def test_other_users_receipts_and_expenses_cannot_be_manipulated_through_any_verb(client: TestClient, clean_database: None) -> None:
    owner, intruder = User(client), User(client)
    account = owner.account()
    confirmed = owner.confirmed(account)
    own_expense = owner.expense()
    before = _state(owner.id, confirmed["id"], account)

    for body in ({"status": "failed"}, {"expense_id": own_expense}):
        assert intruder.call("PATCH", f"/{confirmed['id']}", json=body).status_code == 405
    for method, path in (("GET", f"/{confirmed['id']}"), ("POST", f"/{confirmed['id']}/process"), ("DELETE", f"/{confirmed['id']}")):
        assert intruder.call(method, path).status_code == 404
    assert intruder.call("POST", f"/{confirmed['id']}/confirm", json={}).status_code == 404

    assert _state(owner.id, confirmed["id"], account) == before


# ---------------------------------------------------------------------------------------------
# The reproduced exploit: reset + reconfirm = a second Expense and a second debit
# ---------------------------------------------------------------------------------------------


def test_a_confirmed_receipt_can_never_produce_a_second_expense_or_debit(client: TestClient, clean_database: None) -> None:
    user = User(client)
    account = user.account()
    receipt = user.confirmed(account)
    settled = _state(user.id, receipt["id"], account)
    assert settled[-3] == 1 and settled[-2] == 1, "one Expense and one debit from the legitimate confirmation"

    # The old attack: reset the status through PATCH, reprocess, confirm again.
    assert user.call("PATCH", f"/{receipt['id']}", json={"status": "uploaded", "expense_id": None}).status_code == 405
    assert user.call("POST", f"/{receipt['id']}/process").status_code == 409
    assert user.call("POST", f"/{receipt['id']}/confirm", json={"account_id": account}).status_code == 409
    assert user.call("POST", f"/{receipt['id']}/confirm", json={"account_id": account, "amount": "99.00"}).json()["code"] == "receipt_already_confirmed"

    assert _state(user.id, receipt["id"], account) == settled
    assert _sql("select count(*) from expenses where user_id = :u", u=user.id)[0][0] == 1


def test_an_unprocessed_receipt_cannot_be_confirmed_so_nothing_can_be_forged_around_ocr(client: TestClient, clean_database: None) -> None:
    user = User(client)
    account = user.account()
    receipt = user.upload()
    before = _state(user.id, receipt["id"], account)

    response = user.call("POST", f"/{receipt['id']}/confirm", json={
        "title": "Forged", "amount": "9.99", "currency": "EUR", "expense_date": TODAY, "account_id": account,
    })

    assert response.status_code == 409 and response.json()["code"] == "receipt_confirmation_not_allowed"
    assert _state(user.id, receipt["id"], account) == before


# ---------------------------------------------------------------------------------------------
# What stays working
# ---------------------------------------------------------------------------------------------


def test_the_legitimate_flow_and_deletion_still_work_and_deleting_keeps_the_expense(client: TestClient, clean_database: None) -> None:
    user = User(client)
    account = user.account()
    receipt = user.confirmed(account)

    assert user.call("GET", f"/{receipt['id']}").json()["status"] == "confirmed"
    assert [r["id"] for r in user.call("GET", "").json()] == [receipt["id"]]
    assert user.call("DELETE", f"/{receipt['id']}").status_code == 204

    assert user.call("GET", "").json() == []
    assert _sql("select count(*) from expenses where user_id = :u", u=user.id)[0][0] == 1, "deleting a receipt never deletes the Expense"
    assert _sql("select count(*) from account_transactions where user_id = :u and kind = 'expense'", u=user.id)[0][0] == 1


def test_internal_state_changes_still_work_at_the_repository_level(client: TestClient, clean_database: None) -> None:
    """OCR processing and confirmation write server-owned fields through ReceiptUpdate; that path is unchanged."""
    user = User(client)
    receipt = create_receipt(client, user.id)

    moved = set_receipt_state(receipt["id"], user.id, {"status": "processed", "merchant_detected": "LIDL"}).json()

    assert moved["status"] == "processed" and moved["merchant_detected"] == "LIDL"
