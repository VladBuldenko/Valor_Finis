"""Receipts journey across modules (VF-MVP-CORE-005).

test_receipt_router.py covers each Receipt endpoint on its own. This file covers what only a
sequence can break: upload -> OCR processing -> review/correction -> confirm, reconciled
against PostgreSQL and the local file system, never against the API under test.

Invariants asserted here:
- an upload creates exactly one Receipt row and one file with the uploaded bytes; a refused or
  failed upload leaves neither a row nor a file;
- a Receipt can only ever make the server read or delete files inside its OWN user's storage
  area, whatever `storage_path` the client wrote;
- processing moves uploaded|failed -> processing -> processed|failed and never creates money;
  no failure leaves a Receipt in "processing" (it would have no way forward);
- confirming writes exactly one Expense (source "receipt") from the USER's values, one Account
  debit when linked, and nothing at all when it is refused; Income is never touched;
- confirmation is serialized: two confirmations produce one Expense, and a lost response is
  reconciled by rereading the Receipt and its Expense;
- Receipts of another user are invisible and untouchable.

OCR is a controlled stand-in everywhere except test_real_tesseract_reads_a_rendered_receipt,
which runs the installed Tesseract engine and is skipped when it is not available.
"""
import io
import logging
import re
import shutil
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import text

from app.db.database_session import SessionLocal
from app.modules.fx import fx_ecb_provider
from app.modules.receipts import (
    receipt_ocr_service,
    receipt_parser_service,
    receipt_service,
    receipt_storage_service,
)
from tests.helpers import auth_headers

TODAY = date.today()
TODAY_ISO = TODAY.isoformat()
TODAY_DE = TODAY.strftime("%d.%m.%Y")
RECEIPT_TEXT = f"LIDL\n{TODAY_DE}\nMilch 1,49\nBrot 2,19\nSUMME 3,68 EUR"


def _sql(query: str, **params: Any) -> Any:
    with SessionLocal() as session:
        return session.execute(text(query), params).scalar()


def _png(lines: Optional[List[str]] = None) -> bytes:
    size = 34
    font = ImageFont.load_default(size=size)
    lines = lines or ["receipt"]
    image = Image.new("RGB", (900, 120 + len(lines) * (size + 18)), "white")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text((30, 40 + index * (size + 18)), line, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (60, 60), "white").save(buffer, "JPEG")
    return buffer.getvalue()


PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF"


def _files_under(root: Path) -> List[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file()) if root.exists() else []


def _ledger(user: str) -> str:
    """Every row a Receipt confirmation could write, as one comparable value."""
    return str(
        _sql(
            "select (select count(*) from expenses where user_id = :u) || ':' "
            "|| (select coalesce(sum(amount), 0) from expenses where user_id = :u) || ':' "
            "|| (select count(*) from account_transactions where user_id = :u) || ':' "
            "|| (select coalesce(sum(amount), 0) from account_transactions where user_id = :u) || ':' "
            "|| (select count(*) from income where user_id = :u)",
            u=user,
        )
    )


def _receipt_row(receipt_id: str) -> Dict[str, Any]:
    with SessionLocal() as session:
        row = session.execute(
            text("select status, expense_id, merchant_detected, total_amount_detected, storage_path from receipts where id = :r"),
            {"r": receipt_id},
        ).one()
    return {"status": row[0], "expense_id": row[1], "merchant": row[2], "amount": row[3], "storage_path": row[4]}


class Ocr:
    """Controlled OCR provider: returns configured text or raises; records the paths it was asked to read."""

    def __init__(self) -> None:
        self.text: str = RECEIPT_TEXT
        self.error: Optional[Exception] = None
        self.paths: List[Path] = []

    def extract_text(self, file_path: Path) -> str:
        self.paths.append(file_path)
        if self.error is not None:
            raise self.error
        return self.text


@pytest.fixture(autouse=True)
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "uploads"
    monkeypatch.setattr(receipt_storage_service.settings, "receipt_upload_dir", str(root))
    return root


@pytest.fixture
def ocr(monkeypatch: pytest.MonkeyPatch) -> Ocr:
    provider = Ocr()
    monkeypatch.setattr(receipt_ocr_service, "receipt_ocr_provider", provider)
    return provider


def _fake_ecb_get(url: str, params: Dict[str, str] = None, timeout: float = None) -> Any:
    from unittest.mock import MagicMock

    end = date.fromisoformat(params["endPeriod"])
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "dataSets": [{"series": {"0:0:0:0:0": {"observations": {"0": [1.25, 0, 0, None, None]}}}}],
        "structure": {"dimensions": {"observation": [{"id": "TIME_PERIOD", "values": [{"id": end.isoformat()}]}]}},
    }
    return response


@pytest.fixture(autouse=True)
def stub_ecb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", _fake_ecb_get)


class Api:
    def __init__(self, client: TestClient, user: Optional[str] = None) -> None:
        self.client = client
        self.user = user or str(uuid4())
        self.headers = auth_headers(self.user)

    def call(self, method: str, path: str, expect: Optional[int], **kwargs: Any) -> Any:
        response = self.client.request(method, path, headers=self.headers, **kwargs)
        if expect is not None:
            assert response.status_code == expect, f"{method} {path} -> {response.status_code} {response.text}"
        return response

    def upload(self, name: str = "receipt.png", data: Optional[bytes] = None, ctype: str = "image/png", expect: Optional[int] = 201) -> Any:
        payload = data if data is not None else _png()
        response = self.call("POST", "/api/v1/receipts/upload", expect, files={"file": (name, payload, ctype)})
        return response.json() if expect == 201 else response

    def process(self, receipt_id: str, expect: Optional[int] = 200) -> Any:
        response = self.call("POST", f"/api/v1/receipts/{receipt_id}/process", expect)
        return response.json() if expect == 200 else response

    def processed(self) -> Dict[str, Any]:
        receipt = self.upload()
        return self.process(receipt["id"])

    def confirm(self, receipt_id: str, body: Optional[dict] = None, expect: Optional[int] = 200) -> Any:
        response = self.call("POST", f"/api/v1/receipts/{receipt_id}/confirm", expect, json=body or {})
        return response.json() if expect == 200 else response

    def get(self, receipt_id: str, expect: Optional[int] = 200) -> Any:
        response = self.call("GET", f"/api/v1/receipts/{receipt_id}", expect)
        return response.json() if expect == 200 else response

    def account(self, opening: str = "100.00", currency: str = "EUR") -> Dict[str, Any]:
        return self.call(
            "POST", "/api/v1/accounts", 201,
            json={"name": f"acc-{uuid4().hex[:6]}", "type": "checking", "currency": currency, "opening_balance": opening},
        ).json()

    def balance(self, account_id: str) -> str:
        accounts = self.call("GET", "/api/v1/accounts", 200).json()
        return next(a["current_balance"] for a in accounts if a["id"] == account_id)

    def category(self, name: str) -> Dict[str, Any]:
        return self.call("POST", "/api/v1/categories", 201, json={"name": name, "color": "#FF5733", "icon": "x"}).json()

    def overview(self) -> Dict[str, Any]:
        return self.call("GET", f"/api/v1/analytics/financial-overview?year={TODAY.year}&month={TODAY.month}", 200).json()


# ---------------------------------------------------------------------------------------------
# Part A - upload
# ---------------------------------------------------------------------------------------------


def test_valid_uploads_store_the_exact_bytes_once_and_only_in_the_users_area(
    client: TestClient, clean_database: None, storage: Path,
) -> None:
    api = Api(client)
    uploads = [("a.jpg", _jpeg(), "image/jpeg"), ("b.jpeg", _jpeg(), "image/jpeg"), ("c.png", _png(), "image/png"), ("d.pdf", PDF, "application/pdf")]

    created = [api.upload(name, data, ctype) for name, data, ctype in uploads]

    assert _sql("select count(*) from receipts where user_id = :u", u=api.user) == len(uploads)
    for (name, data, _), receipt in zip(uploads, created):
        path = Path(receipt["storage_path"])
        assert receipt["status"] == "uploaded" and receipt["expense_id"] is None
        assert path.read_bytes() == data
        assert path.suffix == Path(name).suffix.lower()
        assert path.parent == storage / api.user, "stored inside the uploader's own directory"
        assert receipt["storage_path"] == _receipt_row(receipt["id"])["storage_path"]
    assert len(_files_under(storage)) == len(uploads)
    assert _ledger(api.user) == "0:0:0:0:0", "an upload writes no money"


def test_a_hostile_filename_never_decides_where_the_file_lands(client: TestClient, clean_database: None, storage: Path) -> None:
    api = Api(client)

    receipt = api.upload("../../../evil name.JPG", _jpeg(), "image/jpeg")

    stored = Path(receipt["storage_path"])
    assert stored.parent == storage / api.user and stored.suffix == ".jpg"
    assert "evil" not in stored.name
    assert [p for p in _files_under(storage)] == [stored]
    assert not (storage.parent / "evil name.JPG").exists()


@pytest.mark.parametrize(
    "name,data,ctype,expected",
    [
        ("r.gif", b"GIF89a....", "image/gif", 415),
        ("r.txt", b"hello", "text/plain", 415),
        ("r.jpg", _jpeg(), "image/png", 415),  # MIME / extension mismatch
        ("r.png", _png(), "image/jpeg", 415),
        ("r.pdf", PDF, "image/jpeg", 415),
        ("receipt", _jpeg(), "image/jpeg", 415),  # no extension
        ("r.jpg.exe", _jpeg(), "image/jpeg", 415),
        ("r.jpg", b"", "image/jpeg", 422),  # empty
    ],
)
def test_refused_uploads_leave_no_row_and_no_file(
    client: TestClient, clean_database: None, storage: Path, name: str, data: bytes, ctype: str, expected: int,
) -> None:
    api = Api(client)

    response = api.upload(name, data, ctype, expect=None)

    assert response.status_code == expected, response.text
    assert _sql("select count(*) from receipts") == 0
    assert _files_under(storage) == []


def test_an_oversized_upload_is_refused_and_its_partial_file_removed(
    client: TestClient, clean_database: None, storage: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(receipt_storage_service.settings, "receipt_max_file_size_mb", 1)
    api = Api(client)

    at_limit = api.upload("ok.pdf", PDF + b"0" * (1024 * 1024 - len(PDF)), "application/pdf", expect=201)
    over = api.upload("big.pdf", PDF + b"0" * (1024 * 1024), "application/pdf", expect=None)

    assert over.status_code == 413 and over.json()["code"] == "receipt_file_too_large"
    assert _sql("select count(*) from receipts") == 1
    assert _files_under(storage) == [Path(at_limit["storage_path"])]


def test_a_database_failure_after_the_file_was_written_removes_the_file(
    client: TestClient, clean_database: None, storage: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(**_: Any) -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(receipt_service, "create_receipt", broken)
    api = Api(TestClient(client.app, raise_server_exceptions=False))

    response = api.upload(expect=None)

    assert response.status_code == 500
    assert _sql("select count(*) from receipts") == 0
    assert _files_under(storage) == []


def test_delete_removes_the_row_and_only_that_users_file(client: TestClient, clean_database: None, storage: Path) -> None:
    owner, other = Api(client), Api(client)
    mine = owner.upload()
    theirs = other.upload()

    owner.call("DELETE", f"/api/v1/receipts/{mine['id']}", 204)

    assert _sql("select count(*) from receipts where id = :r", r=mine["id"]) == 0
    assert not Path(mine["storage_path"]).exists()
    assert Path(theirs["storage_path"]).exists() and _receipt_row(theirs["id"])["status"] == "uploaded"
    # Deleting a receipt whose file is already gone still deletes the row.
    Path(theirs["storage_path"]).unlink()
    other.call("DELETE", f"/api/v1/receipts/{theirs['id']}", 204)
    assert _sql("select count(*) from receipts") == 0


def test_storage_path_can_never_make_the_server_read_or_delete_files_outside_the_users_area(
    client: TestClient, clean_database: None, storage: Path, ocr: Ocr, tmp_path: Path,
) -> None:
    attacker, victim = Api(client), Api(client)
    victims_receipt = victim.upload()
    victims_file = Path(victims_receipt["storage_path"])
    server_file = tmp_path / "server-secret.png"
    server_file.write_bytes(_png(["SECRET"]))
    (storage / attacker.user).mkdir(parents=True, exist_ok=True)
    link = storage / attacker.user / "link.png"
    link.symlink_to(server_file)

    hostile_paths = [
        str(server_file),
        str(victims_file),
        str(storage / attacker.user / ".." / victim.user / victims_file.name),
        str(link),
        str(storage / attacker.user),
        "supabase://receipts/" + victim.user + "/x.png",
        "supabase://other-bucket/" + attacker.user + "/x.png",
    ]

    for hostile in hostile_paths:
        # Both client-writable entry points: create with the path, and PATCH an own upload to it.
        created = attacker.call("POST", "/api/v1/receipts", 201, json={"storage_path": hostile}).json()
        own = attacker.upload()
        attacker.call("PATCH", f"/api/v1/receipts/{own['id']}", 200, json={"storage_path": hostile})

        for receipt_id in (created["id"], own["id"]):
            refused = attacker.process(receipt_id, expect=404)
            assert refused.json()["code"] == "receipt_ocr_file_not_found"
            assert _receipt_row(receipt_id)["status"] == "failed", hostile
            attacker.call("DELETE", f"/api/v1/receipts/{receipt_id}", 204)

        assert victims_file.exists() and server_file.exists() and link.is_symlink(), hostile

    assert ocr.paths == [], "OCR was never asked to read any of them"
    assert victim.get(victims_receipt["id"])["status"] == "uploaded"


# ---------------------------------------------------------------------------------------------
# Part B - OCR processing
# ---------------------------------------------------------------------------------------------


def test_processing_moves_uploaded_to_processed_through_processing_and_creates_no_money(
    client: TestClient, clean_database: None, ocr: Ocr, monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = Api(client)
    receipt = api.upload()
    seen: List[str] = []
    original = ocr.extract_text

    def spying(file_path: Path) -> str:
        seen.append(_receipt_row(receipt["id"])["status"])
        return original(file_path)

    monkeypatch.setattr(ocr, "extract_text", spying)
    before = _ledger(api.user)

    processed = api.process(receipt["id"])

    assert seen == ["processing"], "committed as processing before OCR starts"
    assert processed["status"] == "processed"
    assert (processed["merchant_detected"], processed["total_amount_detected"], processed["currency_detected"], processed["purchase_date_detected"]) == (
        "LIDL", "3.68", "EUR", TODAY_ISO,
    )
    assert processed["ocr_text"] == RECEIPT_TEXT
    assert _ledger(api.user) == before, "OCR detection writes no Expense, ledger row or Income"
    assert api.process(receipt["id"], expect=409).json()["code"] == "receipt_processing_not_allowed"
    assert len(ocr.paths) == 1, "processing a processed receipt again does not run OCR again"


def test_missing_and_ambiguous_fields_stay_empty_for_the_user_to_supply(client: TestClient, clean_database: None, ocr: Ocr) -> None:
    api = Api(client)
    ocr.text = "Thank you for shopping\nhave a nice day"

    processed = api.process(api.upload()["id"])

    assert processed["status"] == "processed"
    assert processed["total_amount_detected"] is None and processed["currency_detected"] is None
    assert processed["purchase_date_detected"] is None
    assert _sql("select count(*) from expenses") == 0


def test_a_failed_processing_attempt_creates_nothing_and_can_be_retried(client: TestClient, clean_database: None, ocr: Ocr) -> None:
    api = Api(client)
    receipt = api.upload()
    ocr.error = receipt_ocr_service.ReceiptOcrProcessingError()
    before = _ledger(api.user)

    failure = api.process(receipt["id"], expect=422)

    assert failure.json()["code"] == "receipt_ocr_processing_failed"
    assert _receipt_row(receipt["id"])["status"] == "failed"
    assert _ledger(api.user) == before
    api.confirm(receipt["id"], {"title": "x", "amount": "1.00", "currency": "EUR", "expense_date": TODAY_ISO}, expect=409)

    ocr.error = None
    assert api.process(receipt["id"])["status"] == "processed"
    assert _ledger(api.user) == before
    assert _sql("select count(*) from receipts where user_id = :u", u=api.user) == 1


def test_files_the_ocr_engine_cannot_read_fail_safely(client: TestClient, clean_database: None, storage: Path) -> None:
    """Real provider, no stub: a PDF and a non-image named .jpg are accepted at upload and fail OCR cleanly."""
    api = Api(TestClient(client.app, raise_server_exceptions=False))
    unreadable = [api.upload("r.pdf", PDF, "application/pdf"), api.upload("r.jpg", b"not an image", "image/jpeg")]

    for receipt in unreadable:
        assert api.process(receipt["id"], expect=422).json()["code"] == "receipt_ocr_processing_failed"
        assert _receipt_row(receipt["id"])["status"] == "failed"

    assert _sql("select count(*) from expenses") == 0


def test_an_implausible_ocr_amount_is_left_undetected_instead_of_breaking_processing(
    client: TestClient, clean_database: None, ocr: Ocr,
) -> None:
    api = Api(TestClient(client.app, raise_server_exceptions=False))
    ocr.text = f"SHOP\n{TODAY_DE}\nSUMME 1.234.567.890.123,45 EUR"

    response = api.process(api.upload()["id"], expect=None)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "processed"
    assert response.json()["total_amount_detected"] is None
    assert response.json()["currency_detected"] == "EUR"


@pytest.mark.parametrize("failure", ["parser", "nul_byte"])
def test_no_failure_leaves_a_receipt_stuck_in_processing(
    client: TestClient, clean_database: None, ocr: Ocr, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    api = Api(TestClient(client.app, raise_server_exceptions=False))
    receipt = api.upload()
    real_parser = receipt_parser_service.parse_receipt_text
    if failure == "parser":
        def broken(ocr_text: str) -> None:
            raise RuntimeError("parser bug")

        monkeypatch.setattr(receipt_parser_service, "parse_receipt_text", broken)
    else:
        ocr.text = "SHOP\x00\nSUMME 3,00 EUR"

    response = api.process(receipt["id"], expect=None)

    status = _receipt_row(receipt["id"])["status"]
    assert status in ("failed", "processed"), f"{failure}: stuck in {status} after HTTP {response.status_code}"
    if failure == "nul_byte":
        # NUL is stripped from the OCR text, so this receipt processes normally instead of failing.
        assert status == "processed" and response.status_code == 200, response.text
        assert "\x00" not in response.json()["ocr_text"]
        assert response.json()["total_amount_detected"] == "3.00"
    if status == "failed":
        monkeypatch.setattr(receipt_parser_service, "parse_receipt_text", real_parser)
        ocr.text = RECEIPT_TEXT
        assert api.process(receipt["id"])["status"] == "processed", "a failed receipt can always be retried"


def test_two_simultaneous_process_requests_run_ocr_once(
    client: TestClient, clean_database: None, ocr: Ocr, monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = Api(client)
    receipt = api.upload()
    # Hold the first request right after it moved the receipt to "processing" so the second one
    # arrives while the status check of both could still see "uploaded".
    gate = threading.Barrier(2, timeout=1.5)
    original = receipt_service.receipt_repository.update_receipt

    def gated(**kwargs: Any) -> Any:
        data = kwargs["receipt_data"]
        if data.model_fields_set == {"status"} and data.status == "processing":
            try:
                gate.wait()
            except threading.BrokenBarrierError:
                pass
        return original(**kwargs)

    monkeypatch.setattr(receipt_service.receipt_repository, "update_receipt", gated)
    codes: List[int] = []

    def run() -> None:
        codes.append(TestClient(client.app, raise_server_exceptions=False).post(f"/api/v1/receipts/{receipt['id']}/process", headers=api.headers).status_code)

    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert sorted(codes) == [200, 409]
    assert len(ocr.paths) == 1
    assert _receipt_row(receipt["id"])["status"] == "processed"


def test_receipt_content_never_reaches_the_logs(
    client: TestClient, clean_database: None, ocr: Ocr, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    api = Api(client)
    ocr.text = f"CONFIDENTIAL MERCHANT\n{TODAY_DE}\nSUMME 7777,77 EUR"

    receipt = api.upload("private-name.png")
    api.process(receipt["id"])
    api.confirm(receipt["id"], {"description": "secret note"})

    logged = "\n".join(record.getMessage() for record in caplog.records)
    for secret in ("CONFIDENTIAL", "7777", "secret note", "private-name", receipt["storage_path"]):
        assert secret not in logged


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")
def test_real_tesseract_reads_a_rendered_receipt(
    client: TestClient, clean_database: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REAL OCR (not a stub) on a clean synthetic render. This proves the wiring, not accuracy on camera photos."""
    monkeypatch.setattr(receipt_ocr_service, "TESSERACT_OCR_LANGUAGES", "eng")
    api = Api(client)
    receipt = api.upload("r.png", _png(["LIDL", TODAY_DE, "Milch 1,49", "Brot 2,19", "SUMME 3,68 EUR"]), "image/png")

    processed = api.process(receipt["id"])

    assert processed["status"] == "processed"
    assert (processed["merchant_detected"], processed["total_amount_detected"], processed["currency_detected"], processed["purchase_date_detected"]) == (
        "LIDL", "3.68", "EUR", TODAY_ISO,
    )


# ---------------------------------------------------------------------------------------------
# Parts C and D - review, correction and confirmation
# ---------------------------------------------------------------------------------------------


def test_user_corrections_replace_wrong_ocr_values_and_the_money_reconciles(
    client: TestClient, clean_database: None, ocr: Ocr,
) -> None:
    api = Api(client)
    account = api.account("100.00")
    category = api.category("Receipt scope")
    api.call("POST", "/api/v1/income", 201, json={"amount": "500.00", "currency": "EUR", "received_at": TODAY_ISO, "source": "salary"})
    budget = api.call(
        "POST", "/api/v1/budgets", 201,
        json={"name": "Food", "limit_amount": "50.00", "period": "monthly", "start_date": TODAY.replace(day=1).isoformat(), "category_id": category["id"]},
    ).json()
    receipt = api.processed()  # OCR read LIDL / 3.68 EUR
    income_before = api.overview()["income_total"]
    expenses_before = Decimal(api.overview()["expense_total"])

    result = api.confirm(
        receipt["id"],
        {"title": "Lidl (corrected)", "amount": "12.34", "currency": "EUR", "expense_date": TODAY_ISO,
         "category_id": category["id"], "description": "weekly shop", "account_id": account["id"]},
    )

    expense = result["expense"]
    row = _sql("select title || '|' || amount || '|' || currency || '|' || expense_date || '|' || source || '|' || category_id || '|' || description from expenses where id = :e", e=expense["id"])
    assert row == f"Lidl (corrected)|12.34|EUR|{TODAY_ISO}|receipt|{category['id']}|weekly shop", "the user's values, not OCR's"
    assert _sql("select count(*) from expenses where user_id = :u", u=api.user) == 1
    stored = _receipt_row(receipt["id"])
    assert stored["status"] == "confirmed" and str(stored["expense_id"]) == expense["id"]
    assert result["receipt"]["status"] == "confirmed" and result["receipt"]["expense_id"] == expense["id"]
    assert result["receipt"]["total_amount_detected"] == "3.68", "the detected value is kept as history, not rewritten"
    assert _sql("select count(*) from account_transactions where account_id = :a and direction = 'debit'", a=account["id"]) == 1
    assert _sql("select amount from account_transactions where account_id = :a and direction = 'debit'", a=account["id"]) == Decimal("12.34")
    assert api.balance(account["id"]) == "87.66", "100.00 - 12.34 exactly"
    overview = api.overview()
    assert overview["income_total"] == income_before, "Income is untouched"
    assert Decimal(overview["expense_total"]) == expenses_before + Decimal("12.34"), "counted exactly once"
    status = next(item for item in api.call("GET", "/api/v1/analytics/budget-status", 200).json() if item["budget_id"] == budget["id"])
    assert Decimal(status["spent"]) == Decimal("12.34")


def test_unlinked_confirmation_writes_one_expense_and_no_ledger_row(client: TestClient, clean_database: None, ocr: Ocr) -> None:
    api = Api(client)
    account = api.account("100.00")
    receipt = api.processed()
    ledger_rows = _sql("select count(*) from account_transactions where user_id = :u", u=api.user)

    result = api.confirm(receipt["id"])

    assert result["expense"]["account_id"] is None and result["expense"]["source"] == "receipt"
    assert (result["expense"]["title"], result["expense"]["amount"], result["expense"]["expense_date"]) == ("LIDL", "3.68", TODAY_ISO)
    assert _sql("select count(*) from expenses where user_id = :u", u=api.user) == 1
    assert _sql("select count(*) from account_transactions where user_id = :u", u=api.user) == ledger_rows
    assert api.balance(account["id"]) == "100.00"


def test_missing_ocr_values_can_be_supplied_manually_and_confirming_without_them_creates_nothing(
    client: TestClient, clean_database: None, ocr: Ocr,
) -> None:
    api = Api(client)
    ocr.text = "illegible scribble"
    receipt = api.processed()
    before = _ledger(api.user)

    for partial in ({}, {"title": "Shop"}, {"title": "Shop", "amount": "5.00", "currency": "EUR"}):
        refused = api.confirm(receipt["id"], partial, expect=422)
        assert refused.json()["code"] == "receipt_confirmation_data_missing"
        assert _ledger(api.user) == before
        assert _receipt_row(receipt["id"])["status"] == "processed"

    api.confirm(receipt["id"], {"title": "Shop", "amount": "5.00", "currency": "EUR", "expense_date": TODAY_ISO})
    assert _ledger(api.user).startswith("1:5.00:")


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"amount": "0"}, 422),
        ({"amount": "-1.00"}, 422),
        ({"amount": "1.234"}, 422),
        ({"amount": "abc"}, 422),
        ({"amount": "10000000000.00"}, 422),
        ({"currency": "E1R"}, 422),
        ({"currency": "EU"}, 422),
        ({"currency": "ZZZ"}, 422),
        ({"expense_date": "2026-13-45"}, 422),
        ({"title": "x" * 121}, 422),
        ({"description": "x" * 501}, 422),
        ({"unknown_field": "x"}, 422),
    ],
)
def test_invalid_corrections_are_refused_and_create_nothing(
    client: TestClient, clean_database: None, ocr: Ocr, body: dict, expected: int,
) -> None:
    api = Api(client)
    receipt = api.processed()
    before = _ledger(api.user)

    response = api.confirm(receipt["id"], body, expect=None)

    assert response.status_code == expected, response.text
    assert _ledger(api.user) == before
    assert _receipt_row(receipt["id"])["status"] == "processed"


def test_foreign_archived_and_mismatched_links_are_refused_atomically(client: TestClient, clean_database: None, ocr: Ocr) -> None:
    api, stranger = Api(client), Api(client)
    receipt = api.processed()
    foreign_category = stranger.category("Theirs")
    foreign_account = stranger.account("50.00")
    usd_account = api.account("50.00", currency="USD")
    archived = api.account("50.00")
    api.call("PATCH", f"/api/v1/accounts/{archived['id']}", 200, json={"status": "archived"})
    before = _ledger(api.user)

    cases = [
        ({"category_id": foreign_category["id"]}, 404),
        ({"account_id": foreign_account["id"]}, 404),
        ({"account_id": str(uuid4())}, 404),
        ({"account_id": archived["id"]}, 409),
        ({"account_id": usd_account["id"]}, 422),
    ]
    for body, expected in cases:
        response = api.confirm(receipt["id"], body, expect=None)
        assert response.status_code == expected, f"{body}: {response.status_code} {response.text}"
        assert _ledger(api.user) == before, body
        assert _receipt_row(receipt["id"])["status"] == "processed", body
    assert _ledger(stranger.user).split(":")[0:1] == ["0"]

    api.confirm(receipt["id"])  # the receipt is still confirmable after every refusal
    assert _sql("select count(*) from expenses where user_id = :u", u=api.user) == 1


def test_a_stored_detected_currency_the_expense_rules_refuse_asks_for_a_correction_instead_of_failing(
    client: TestClient, clean_database: None, ocr: Ocr,
) -> None:
    """PATCH is client-writable: a malformed detected value must not turn confirmation into a 500."""
    api = Api(TestClient(client.app, raise_server_exceptions=False))
    receipt = api.processed()
    with SessionLocal() as session:
        session.execute(text("update receipts set currency_detected = 'E1R' where id = :r"), {"r": receipt["id"]})
        session.commit()
    before = _ledger(api.user)

    refused = api.confirm(receipt["id"], {}, expect=422)

    assert refused.json()["code"] == "receipt_confirmation_data_missing"
    assert _ledger(api.user) == before and _receipt_row(receipt["id"])["status"] == "processed"
    assert api.call("PATCH", f"/api/v1/receipts/{receipt['id']}", 422, json={"currency_detected": "E1R"}).status_code == 422
    api.confirm(receipt["id"], {"currency": "EUR"})
    assert _sql("select count(*) from expenses where user_id = :u", u=api.user) == 1


def test_foreign_currency_confirmation_gets_the_same_fx_snapshot_as_an_ordinary_expense(
    client: TestClient, clean_database: None, ocr: Ocr,
) -> None:
    api = Api(client)
    ocr.text = f"NYC DELI\n{TODAY_DE}\nTOTAL 20,00 USD"
    receipt = api.processed()

    from_receipt = api.confirm(receipt["id"])["expense"]
    ordinary = api.call(
        "POST", "/api/v1/expenses", 201,
        json={"title": "NYC DELI", "amount": "20.00", "currency": "USD", "expense_date": TODAY_ISO, "client_request_id": str(uuid4())},
    ).json()

    for field in ("currency", "base_currency", "base_amount", "fx_rate", "fx_source", "fx_rate_date"):
        assert from_receipt[field] == ordinary[field], field
    assert from_receipt["base_currency"] == "EUR" and from_receipt["base_amount"] is not None


def test_a_repeated_confirmation_is_refused_and_changes_nothing(client: TestClient, clean_database: None, ocr: Ocr) -> None:
    api = Api(client)
    account = api.account("100.00")
    receipt = api.processed()
    api.confirm(receipt["id"], {"account_id": account["id"]})
    settled = _ledger(api.user)

    again = api.confirm(receipt["id"], {"account_id": account["id"], "amount": "99.00"}, expect=409)

    assert again.json()["code"] == "receipt_already_confirmed"
    assert _ledger(api.user) == settled
    assert api.balance(account["id"]) == "96.32"


def test_two_simultaneous_confirmations_create_one_expense_and_one_debit(client: TestClient, clean_database: None, ocr: Ocr) -> None:
    api = Api(client)
    account = api.account("100.00")
    receipt = api.processed()
    go = threading.Barrier(2)
    codes: List[int] = []

    def run() -> None:
        go.wait()
        response = TestClient(client.app, raise_server_exceptions=False).post(
            f"/api/v1/receipts/{receipt['id']}/confirm", json={"account_id": account["id"]}, headers=api.headers,
        )
        codes.append(response.status_code)

    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert sorted(codes) == [200, 409]
    assert _sql("select count(*) from expenses where user_id = :u", u=api.user) == 1
    assert _sql("select count(*) from account_transactions where account_id = :a and direction = 'debit'", a=account["id"]) == 1
    assert api.balance(account["id"]) == "96.32"


def test_a_lost_confirmation_response_is_reconciled_by_rereading_the_receipt_and_expense(
    client: TestClient, clean_database: None, ocr: Ocr,
) -> None:
    api = Api(client)
    account = api.account("100.00")
    receipt = api.processed()

    api.call("POST", f"/api/v1/receipts/{receipt['id']}/confirm", 200, json={"account_id": account["id"]})  # response "lost": never read

    reread = api.get(receipt["id"])
    expenses = api.call("GET", "/api/v1/expenses", 200).json()
    expense = next(e for e in expenses if e["id"] == reread["expense_id"])
    assert reread["status"] == "confirmed" and expense["source"] == "receipt" and expense["account_id"] == account["id"]
    assert (expense["title"], expense["amount"]) == ("LIDL", "3.68")
    assert [e["id"] for e in expenses] == [expense["id"]], "exactly one Expense exists"
    # The client's blind retry is refused (409) and cannot double-spend.
    assert api.confirm(receipt["id"], {"account_id": account["id"]}, expect=409).json()["code"] == "receipt_already_confirmed"
    assert api.balance(account["id"]) == "96.32"
    assert _sql("select count(*) from expenses where user_id = :u", u=api.user) == 1


def test_receipts_of_another_user_are_invisible_and_untouchable(client: TestClient, clean_database: None, ocr: Ocr) -> None:
    owner, intruder = Api(client), Api(client)
    receipt = owner.processed()
    before = (_ledger(owner.user), _receipt_row(receipt["id"]))

    attempts = [
        intruder.call("GET", f"/api/v1/receipts/{receipt['id']}", None),
        intruder.call("POST", f"/api/v1/receipts/{receipt['id']}/process", None),
        intruder.call("POST", f"/api/v1/receipts/{receipt['id']}/confirm", None, json={}),
        intruder.call("PATCH", f"/api/v1/receipts/{receipt['id']}", None, json={"status": "failed"}),
        intruder.call("DELETE", f"/api/v1/receipts/{receipt['id']}", None),
    ]

    assert [a.status_code for a in attempts] == [404] * 5
    assert intruder.call("GET", "/api/v1/receipts", 200).json() == []
    assert (_ledger(owner.user), _receipt_row(receipt["id"])) == before
    assert _ledger(intruder.user).startswith("0:")
    assert Path(receipt["storage_path"]).exists()
    assert [r["id"] for r in owner.call("GET", "/api/v1/receipts", 200).json()] == [receipt["id"]]


def test_the_refusal_messages_the_mobile_tests_pin_are_the_backends_exact_details(
    client: TestClient, clean_database: None, ocr: Ocr, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mobile receipt-lifecycle.test.ts lists (status, detail) pairs; each must be what the API really sends."""
    mobile = Path(__file__).resolve().parents[5] / "apps" / "mobile" / "src" / "features" / "receipts" / "receipt-lifecycle.test.ts"
    if not mobile.exists():
        pytest.skip("apps/mobile is not checked out")
    pinned = {(int(status), detail) for status, detail in re.findall(r'\[(\d{3}), "([^"]+)"\]', mobile.read_text())}
    api = Api(client)
    real = set()

    def seen(response: Any) -> None:
        real.add((response.status_code, response.json()["detail"]))

    seen(api.upload("r.gif", b"GIF89a", "image/gif", expect=None))  # 415
    seen(api.upload("r.png", b"", "image/png", expect=None))  # 422 empty
    limit = receipt_storage_service.settings.receipt_max_file_size_mb
    monkeypatch.setattr(receipt_storage_service.settings, "receipt_max_file_size_mb", 1)
    seen(api.upload("big.pdf", PDF + b"0" * (1024 * 1024), "application/pdf", expect=None))  # 413
    monkeypatch.setattr(receipt_storage_service.settings, "receipt_max_file_size_mb", limit)

    uploaded = api.upload()
    seen(api.confirm(uploaded["id"], {}, expect=None))  # uploaded, not processed -> not confirmable (409)
    ocr.error = receipt_ocr_service.ReceiptOcrProcessingError()
    seen(api.process(uploaded["id"], expect=None))  # 422 OCR failed
    ocr.error = None
    done = api.process(uploaded["id"])
    seen(api.process(done["id"], expect=None))  # processed -> not processable (409)
    seen(api.get(str(uuid4()), expect=None))  # 404 not found
    no_file = api.call("POST", "/api/v1/receipts", 201, json={"file_url": "https://example.com/r.jpg"}).json()
    seen(api.process(no_file["id"], expect=None))  # 404 file not found
    ocr.text = "nothing readable"
    seen(api.confirm(api.processed()["id"], {}, expect=None))  # 422 data missing
    confirmed = api.processed()
    api.confirm(confirmed["id"], {"title": "x", "amount": "1.00", "currency": "EUR", "expense_date": TODAY_ISO})
    seen(api.confirm(confirmed["id"], {}, expect=None))  # 409 already confirmed

    assert pinned and pinned <= real, f"mobile pins messages the API does not send: {sorted(pinned - real)}"
