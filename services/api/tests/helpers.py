from typing import Any, Optional, Union
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.goals import goal_repository
from app.modules.goals.goal_models import GoalModel
from app.modules.goals.goal_schemas import GoalCreate


# Builds authentication headers for test requests.
# This helper exists to avoid repeating X-User-Id header creation in every test.
# Parameters:
# - user_id: user identifier as string.
# Returns:
# - Dictionary with authentication headers.
def auth_headers(user_id: str) -> dict[str, str]:
    return {"X-User-Id": user_id}


# Creates an expense through the API for integration tests.
# This helper exists to keep test setup short and readable.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - category_id: optional category identifier.
# - title: expense title.
# - amount: expense amount.
# Returns:
# - Created expense response body.
def create_expense(
    client: TestClient,
    user_id: str,
    category_id: Optional[str] = None,
    title: str = "Groceries",
    amount: Union[int, float] = 50,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
        json={
            "category_id": category_id,
            "title": title,
            "amount": amount,
            "currency": "EUR",
            "expense_date": "2026-05-07",
            "description": title,
            "source": "manual",
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


# Creates an income record through the API for integration tests.
# This helper exists to avoid repeating income setup code. Defaults to
# EUR (the identity FX path), so callers that don't care about FX
# resolution never need to mock the ECB/NBU HTTP boundary.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - amount: amount received.
# - currency: income currency.
# - received_at: date the money was received.
# - source: income source.
# Returns:
# - Created income response body.
def create_income(
    client: TestClient,
    user_id: str,
    amount: Union[int, float] = 2500,
    currency: str = "EUR",
    received_at: str = "2026-05-07",
    source: str = "salary",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/income",
        headers=auth_headers(user_id),
        json={
            "amount": amount,
            "currency": currency,
            "received_at": received_at,
            "source": source,
            "description": None,
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


# Creates a category through the API for integration tests.
# This helper exists to avoid repeating category setup code.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - name: category name.
# Returns:
# - Created category response body.
def create_category(
    client: TestClient,
    user_id: str,
    name: str = "Food",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/categories",
        headers=auth_headers(user_id),
        json={
            "name": name,
            "color": "#FF5733",
            "icon": "utensils",
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


# Creates a budget through the API for integration tests.
# This helper exists to avoid repeating budget setup code.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - category_id: optional category identifier.
# - name: budget name.
# - limit_amount: budget limit amount.
# Returns:
# - Created budget response body.
def create_budget(
    client: TestClient,
    user_id: str,
    category_id: Optional[str] = None,
    name: str = "Food budget",
    limit_amount: int = 400,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/budgets",
        headers=auth_headers(user_id),
        json={
            "category_id": category_id,
            "name": name,
            "limit_amount": limit_amount,
            "currency": "EUR",
            "period": "monthly",
            "start_date": "2026-05-01",
            "end_date": None,
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


# Creates a financial goal through the API for integration tests.
# This helper exists to avoid repeating goal setup code. current_amount is
# not a parameter (VF-016): every new Goal starts at 0 - use
# create_goal_transaction below to fund one.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - name: goal name.
# - target_amount: goal target amount.
# Returns:
# - Created goal response body.
def create_goal(
    client: TestClient,
    user_id: str,
    name: str = "Vacation",
    target_amount: int = 2000,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/goals",
        headers=auth_headers(user_id),
        json={
            "name": name,
            "target_amount": target_amount,
            "currency": "EUR",
            "target_date": "2026-12-31",
            "status": "active",
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


# Creates a goal transaction (contribution or withdrawal) through the API
# for integration tests.
# This helper exists to avoid repeating transaction setup code, e.g. to
# fund a goal before exercising a scenario that depends on a non-zero
# balance.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - goal_id: financial goal identifier to transact against.
# - amount: transaction amount.
# - type: "contribution" or "withdrawal".
# Returns:
# - Created goal transaction response body.
def create_goal_transaction(
    client: TestClient,
    user_id: str,
    goal_id: str,
    amount: int = 500,
    type: str = "contribution",
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/goals/{goal_id}/transactions",
        headers=auth_headers(user_id),
        json={
            "type": type,
            "amount": amount,
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


# Creates an account through the API for integration tests.
# This helper exists to avoid repeating account setup code.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - name: account name.
# - type: account type.
# - currency: account currency.
# - opening_balance: optional signed starting balance.
# Returns:
# - Created account response body.
def create_account(
    client: TestClient,
    user_id: str,
    name: str = "Main Checking",
    type: str = "checking",
    currency: str = "EUR",
    opening_balance: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "type": type,
        "currency": currency,
    }

    if opening_balance is not None:
        payload["opening_balance"] = opening_balance

    response = client.post(
        "/api/v1/accounts",
        headers=auth_headers(user_id),
        json=payload,
    )

    assert response.status_code == 201, response.text

    return response.json()


# Creates a manual adjustment account transaction through the API for
# integration tests.
# This helper exists to avoid repeating adjustment setup code, e.g. to
# fund/drain an account before exercising a scenario that depends on a
# specific balance.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier.
# - account_id: account identifier to adjust.
# - amount: adjustment amount.
# - direction: "credit" or "debit".
# - transaction_date: date the adjustment happened.
# Returns:
# - Created account transaction response body.
def create_account_transaction(
    client: TestClient,
    user_id: str,
    account_id: str,
    amount: str = "100.00",
    direction: str = "credit",
    transaction_date: str = "2026-09-23",
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/accounts/{account_id}/transactions",
        headers=auth_headers(user_id),
        json={
            "direction": direction,
            "amount": amount,
            "transaction_date": transaction_date,
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


# Seeds a receipt row for integration tests (VF-MVP-CORE-005A).
# There is no public route that creates a receipt from metadata or edits its
# server-owned fields any more, so tests that need a receipt in a particular
# state seed it through the repository, exactly as the upload and processing
# services do. Real uploads go through POST /api/v1/receipts/upload.
# Parameters:
# - client: FastAPI test client (kept so call sites stay unchanged).
# - user_id: owner of the receipt, as string.
# - payload: optional ReceiptCreate fields (file_url / storage_path).
# Returns:
# - The created receipt as the API would return it (JSON-compatible dict).
def create_receipt(
    client: TestClient,
    user_id: str,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from uuid import UUID

    from app.db.database_session import SessionLocal
    from app.modules.receipts import receipt_repository
    from app.modules.receipts.receipt_schemas import ReceiptCreate, ReceiptResponse

    receipt_data = ReceiptCreate(
        **(
            payload
            if payload is not None
            else {"storage_path": f"receipts/{user_id}/receipt-1.jpg"}
        )
    )

    with SessionLocal() as session:
        receipt = receipt_repository.create_receipt(
            db_session=session,
            receipt_data=receipt_data,
            user_id=UUID(user_id),
        )

        return ReceiptResponse.model_validate(receipt).model_dump(mode="json")


# A stand-in for the HTTP response of the removed PATCH route, so tests that
# only need to put a receipt into a state keep their assertions unchanged.
class SeededReceiptResponse:
    status_code = 200

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body
        self.text = str(body)

    def json(self) -> dict[str, Any]:
        return self._body


# Moves a seeded receipt into a state, the way OCR processing / confirmation
# do (repository level, never through a public route).
# Parameters:
# - receipt_id / user_id: the receipt and its owner, as strings.
# - fields: ReceiptUpdate fields to write (status, detected values, ...).
# Returns:
# - SeededReceiptResponse carrying the updated receipt.
def set_receipt_state(
    receipt_id: str,
    user_id: str,
    fields: dict[str, Any],
) -> SeededReceiptResponse:
    from uuid import UUID

    from app.db.database_session import SessionLocal
    from app.modules.receipts import receipt_repository
    from app.modules.receipts.receipt_schemas import ReceiptResponse, ReceiptUpdate

    with SessionLocal() as session:
        receipt = receipt_repository.update_receipt(
            db_session=session,
            receipt_id=UUID(receipt_id),
            receipt_data=ReceiptUpdate(**fields),
            user_id=UUID(user_id),
        )

        return SeededReceiptResponse(
            ReceiptResponse.model_validate(receipt).model_dump(mode="json")
        )


# Creates an account transfer through the API (VF-018C).
# This helper exists to avoid repeating the transfer request body in every
# test. A fresh client_request_id is generated unless one is given, so a
# replay test can pass the same key explicitly.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier as string.
# - source_account_id: account the money leaves.
# - destination_account_id: account the money enters.
# - amount: decimal amount as a string.
# - transfer_date: ISO date string.
# - description: optional note.
# - client_request_id: optional idempotency key as string.
# - expected_status: HTTP status the request must return.
# Returns:
# - Parsed JSON response body.
def create_account_transfer(
    client: TestClient,
    user_id: str,
    source_account_id: str,
    destination_account_id: str,
    amount: str = "100.00",
    transfer_date: str = "2026-09-01",
    description: Optional[str] = None,
    client_request_id: Optional[str] = None,
    expected_status: int = 201,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "client_request_id": client_request_id or str(uuid4()),
        "source_account_id": source_account_id,
        "destination_account_id": destination_account_id,
        "amount": amount,
        "transfer_date": transfer_date,
    }

    if description is not None:
        payload["description"] = description

    response = client.post(
        "/api/v1/account-transfers",
        headers=auth_headers(user_id),
        json=payload,
    )

    assert response.status_code == expected_status, response.text

    return response.json()


# Creates a Goal row for TEST SETUP through the repository with an EXPLICIT
# priority_rank that is valid under the D5 schema (VF-020D5).
# This helper exists for tests whose purpose is not rank allocation but which
# need a database-valid Goal fixture: since D5 the database rejects a
# non-archived Goal without a rank, and goal_repository.create_goal itself
# deliberately never invents one (the production service allocates it under
# the user lock). It is plain, explicit setup - not a monkeypatch, not
# autouse, never used by app code, and it never touches goal_service.
# Tests of Goal create / rank allocation must go through goal_service or
# POST /api/v1/goals instead.
# Parameters:
# - db_session: SQLAlchemy session used for the setup.
# - goal_data: validated Goal creation data.
# - user_id: owner of the Goal.
# - priority_rank: explicit rank; when omitted, a non-archived Goal gets the
#   user's current max rank + 1 and an archived Goal gets None.
# - commit: forwarded to the repository.
# Returns:
# - The created GoalModel.
def create_repository_goal(
    db_session: Session,
    goal_data: GoalCreate,
    user_id: Any,
    priority_rank: Optional[int] = None,
    commit: bool = True,
) -> GoalModel:
    if goal_data.status == "archived":
        rank = None
    elif priority_rank is not None:
        rank = priority_rank
    else:
        rank = goal_repository.get_max_priority_rank(db_session, user_id) + 1

    return goal_repository.create_goal(
        db_session=db_session,
        goal_data=goal_data,
        user_id=user_id,
        priority_rank=rank,
        commit=commit,
    )
