import json
import re
from pathlib import Path
from typing import Any, Dict, Type

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.core.api_errors import (
    HTTP_ERROR_FALLBACK_CODE,
    HTTP_STATUS_ERROR_CODES,
    INTERNAL_SERVER_ERROR_CODE,
    VALIDATION_ERROR_CODE,
    ApiHTTPException,
)
from app.core.exception_handlers import (
    DOMAIN_ERROR_CODES,
    DOMAIN_ERROR_RESPONSES,
    FINANCIAL_RULE_INVALID_FIELDS_CODE,
    register_exception_handlers,
)
from app.modules.accounts.account_transfer_errors import (
    AccountTransferClientRequestIdTakenError,
)
from app.modules.financial_rules.financial_rule_errors import (
    FinancialRuleInvalidFieldsError,
)
from app.modules.goals.goal_errors import GoalTransactionClientRequestIdTakenError

API_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_PATH = Path(__file__).with_name("error_code_registry_snapshot.json")
SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


def load_snapshot() -> Dict[str, Any]:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def source_codes() -> set:
    codes = set()

    for relative_path in (
        "app/modules/auth/auth_dependencies.py",
        "app/modules/analytics/analytics_router.py",
    ):
        source = (API_ROOT / relative_path).read_text(encoding="utf-8")
        codes.update(re.findall(r'code="([a-z_]+)"', source))

    return codes


@pytest.fixture
def lab_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    return app


# --- registry ---------------------------------------------------------------


def test_every_mapped_domain_error_has_exactly_one_explicit_code() -> None:
    assert set(DOMAIN_ERROR_CODES) == set(DOMAIN_ERROR_RESPONSES)
    assert all(isinstance(code, str) and code for code in DOMAIN_ERROR_CODES.values())


def test_codes_are_lowercase_ascii_snake_case_and_unique() -> None:
    domain_codes = list(DOMAIN_ERROR_CODES.values())
    every_code = (
        domain_codes
        + [FINANCIAL_RULE_INVALID_FIELDS_CODE, VALIDATION_ERROR_CODE, INTERNAL_SERVER_ERROR_CODE]
        + list(HTTP_STATUS_ERROR_CODES.values())
        + [HTTP_ERROR_FALLBACK_CODE]
        + sorted(source_codes())
    )
    # internal_server_error is intentionally the code of both the generic 500 and
    # an HTTPException 500; every other code must have exactly one meaning.
    distinct_meanings = [code for code in every_code if code != INTERNAL_SERVER_ERROR_CODE]

    assert len(set(domain_codes)) == len(domain_codes), "duplicate domain code"
    assert len(set(distinct_meanings)) == len(distinct_meanings), "code reused"
    assert all(SNAKE_CASE.match(code) and code.isascii() for code in every_code)


def test_registry_matches_the_committed_snapshot() -> None:
    snapshot = load_snapshot()
    current_domain = {
        error_type.__name__: {
            "code": DOMAIN_ERROR_CODES[error_type],
            "status": DOMAIN_ERROR_RESPONSES[error_type][0],
        }
        for error_type in DOMAIN_ERROR_RESPONSES
    }

    # A removed or renamed code fails here; a new code must be added to the
    # snapshot in the same change.
    assert current_domain == snapshot["domain"]
    assert snapshot["financial_rule_invalid_fields"]["code"] == FINANCIAL_RULE_INVALID_FIELDS_CODE
    assert sorted(source_codes()) == snapshot["router_and_auth"]
    assert snapshot["generic"] == {
        "validation": VALIDATION_ERROR_CODE,
        "internal": INTERNAL_SERVER_ERROR_CODE,
        "http_fallback": HTTP_ERROR_FALLBACK_CODE,
        "by_status": {str(key): value for key, value in sorted(HTTP_STATUS_ERROR_CODES.items())},
    }


def test_internal_only_signals_have_no_public_code() -> None:
    for internal_error in (
        AccountTransferClientRequestIdTakenError,
        GoalTransactionClientRequestIdTakenError,
    ):
        assert internal_error not in DOMAIN_ERROR_CODES
        assert internal_error not in DOMAIN_ERROR_RESPONSES


# --- handlers through FastAPI -----------------------------------------------


@pytest.mark.parametrize("error_type", sorted(DOMAIN_ERROR_RESPONSES, key=lambda t: t.__name__))
def test_every_domain_error_returns_unchanged_status_and_detail_plus_code(
    lab_app: FastAPI,
    error_type: Type[Exception],
) -> None:
    @lab_app.get("/boom")
    def boom() -> None:
        raise error_type()

    response = TestClient(lab_app).get("/boom")
    expected_status, expected_detail = DOMAIN_ERROR_RESPONSES[error_type]

    assert response.status_code == expected_status
    assert response.json() == {
        "detail": expected_detail,
        "code": DOMAIN_ERROR_CODES[error_type],
    }


def test_domain_conflict_409_examples_use_the_published_codes(lab_app: FastAPI) -> None:
    from app.modules.goals.goal_errors import GoalPrioritySetStaleError, GoalReservationCapacityError

    @lab_app.get("/stale")
    def stale() -> None:
        raise GoalPrioritySetStaleError()

    @lab_app.get("/capacity")
    def capacity() -> None:
        raise GoalReservationCapacityError()

    client = TestClient(lab_app)

    assert client.get("/stale").status_code == 409
    assert client.get("/stale").json()["code"] == "goal_priority_set_stale"
    assert client.get("/capacity").json()["code"] == "goal_reservation_capacity_exceeded"


def test_rule_field_422_keeps_its_message_and_gains_a_code(lab_app: FastAPI) -> None:
    @lab_app.get("/fields")
    def fields() -> None:
        raise FinancialRuleInvalidFieldsError("percent is required for this rule type.")

    response = TestClient(lab_app).get("/fields")

    assert response.status_code == 422
    assert response.json() == {
        "detail": "percent is required for this rule type.",
        "code": "financial_rule_invalid_fields",
    }


def test_http_exception_keeps_status_detail_and_headers(lab_app: FastAPI) -> None:
    @lab_app.get("/coded")
    def coded() -> None:
        raise ApiHTTPException(
            status_code=401,
            detail="Invalid or expired authentication token.",
            code="auth_invalid_token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @lab_app.get("/plain")
    def plain() -> None:
        raise HTTPException(status_code=403, detail="Nope.", headers={"X-Reason": "policy"})

    client = TestClient(lab_app)
    coded_response = client.get("/coded")
    plain_response = client.get("/plain")

    assert coded_response.status_code == 401
    assert coded_response.json() == {
        "detail": "Invalid or expired authentication token.",
        "code": "auth_invalid_token",
    }
    assert coded_response.headers["www-authenticate"] == "Bearer"
    assert plain_response.json() == {"detail": "Nope.", "code": "forbidden"}
    assert plain_response.headers["x-reason"] == "policy"


def test_unknown_route_404_and_unsupported_method_405(lab_app: FastAPI) -> None:
    @lab_app.get("/only-get")
    def only_get() -> Dict[str, str]:
        return {"ok": "yes"}

    client = TestClient(lab_app)
    missing = client.get("/missing")
    wrong_method = client.post("/only-get")

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Not Found", "code": "not_found"}
    assert wrong_method.status_code == 405
    assert wrong_method.json() == {"detail": "Method Not Allowed", "code": "method_not_allowed"}
    assert "GET" in wrong_method.headers["allow"]


def test_request_validation_keeps_the_structured_detail_list(lab_app: FastAPI) -> None:
    @lab_app.get("/items/{item_id}")
    def item(item_id: int) -> Dict[str, int]:
        return {"id": item_id}

    response = TestClient(lab_app).get("/items/not-a-number")
    body = response.json()

    assert response.status_code == 422
    assert body["code"] == "validation_error"
    assert set(body) == {"detail", "code"}
    assert isinstance(body["detail"], list) and body["detail"]
    assert body["detail"][0]["loc"] == ["path", "item_id"]
    assert {"type", "loc", "msg"} <= set(body["detail"][0])


def test_unexpected_error_500_exposes_nothing_internal(lab_app: FastAPI) -> None:
    secret_text = "SELECT * FROM users WHERE password='hunter2' postgresql://u:pw@db/valor"

    @lab_app.get("/crash")
    def crash() -> None:
        raise RuntimeError(secret_text)

    response = TestClient(lab_app, raise_server_exceptions=False).get("/crash")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error.",
        "code": "internal_server_error",
    }
    assert "hunter2" not in response.text
    assert "SELECT" not in response.text
    assert "Traceback" not in response.text


def test_internal_only_signal_is_a_generic_500_not_a_business_code(lab_app: FastAPI) -> None:
    @lab_app.get("/race")
    def race() -> None:
        raise AccountTransferClientRequestIdTakenError()

    response = TestClient(lab_app, raise_server_exceptions=False).get("/race")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_server_error"


# --- the real application ---------------------------------------------------


def test_real_app_authentication_error_carries_a_code() -> None:
    from app.main import app

    response = TestClient(app).get("/api/v1/goals")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {
        "detail": "Missing authentication credentials.",
        "code": "auth_missing_credentials",
    }


def test_real_app_unknown_route_and_validation_error() -> None:
    from app.main import app

    client = TestClient(app)
    missing = client.get("/api/v1/does-not-exist")
    invalid = client.get(
        "/api/v1/goals/not-a-uuid/transactions",
        headers={"X-User-Id": "11111111-1111-1111-1111-111111111111"},
    )

    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_error"
    assert isinstance(invalid.json()["detail"], list)
