from uuid import uuid4
import uuid

from fastapi.testclient import TestClient
from pathlib import Path

import pytest

from app.modules.receipts import receipt_storage_service

from tests.helpers import auth_headers, create_expense, create_receipt


# Tests that an authenticated user can create a receipt.
# This test exists to verify receipt creation through the HTTP API.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns the created receipt.
def test_create_receipt_endpoint_creates_receipt(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    payload = {
        "storage_path": f"receipts/{user_id}/receipt-1.jpg",
    }

    # Act
    response = client.post(
        "/api/v1/receipts",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 201, response.text

    response_data = response.json()

    assert response_data["user_id"] == user_id
    assert response_data["storage_path"] == payload["storage_path"]
    assert response_data["file_url"] is None
    assert response_data["status"] == "uploaded"
    assert response_data["expense_id"] is None


# Tests that receipt creation rejects missing authentication.
# This test exists to verify that receipt data is protected by auth.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns unauthorized status code.
def test_create_receipt_endpoint_rejects_missing_authentication(
    client: TestClient,
    clean_database: None,
) -> None:
    # Act
    response = client.post(
        "/api/v1/receipts",
        json={"storage_path": "receipts/receipt-1.jpg"},
    )

    # Assert
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing authentication credentials."


# Tests that receipt creation rejects empty payloads.
# This test exists to verify that a receipt must contain a file reference.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_create_receipt_endpoint_rejects_missing_file_reference(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    # Act
    response = client.post(
        "/api/v1/receipts",
        json={},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 422


# Tests that users can list only their own receipts.
# This test exists to verify user-level data isolation for receipt listing.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if only current user's receipts are returned.
def test_get_receipts_endpoint_returns_only_current_user_receipts(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    own_receipt = create_receipt(
        client=client,
        user_id=user_id,
        payload={"storage_path": f"receipts/{user_id}/receipt-1.jpg"},
    )
    create_receipt(
        client=client,
        user_id=other_user_id,
        payload={"storage_path": f"receipts/{other_user_id}/receipt-1.jpg"},
    )

    # Act
    response = client.get(
        "/api/v1/receipts",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text

    response_data = response.json()

    assert len(response_data) == 1
    assert response_data[0]["id"] == own_receipt["id"]
    assert response_data[0]["user_id"] == user_id


# Tests that a user can get their own receipt by id.
# This test exists to verify single receipt retrieval through the API.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the requested receipt is returned.
def test_get_receipt_by_id_endpoint_returns_own_receipt(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    receipt = create_receipt(client=client, user_id=user_id)

    # Act
    response = client.get(
        f"/api/v1/receipts/{receipt['id']}",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["id"] == receipt["id"]


# Tests that users cannot get another user's receipt.
# This test exists to verify ownership checks for single receipt retrieval.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns not found.
def test_get_receipt_by_id_endpoint_rejects_other_user_receipt(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    receipt = create_receipt(client=client, user_id=other_user_id)

    # Act
    response = client.get(
        f"/api/v1/receipts/{receipt['id']}",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Receipt not found."


# Tests that a user can update their own receipt.
# This test exists to verify OCR metadata updates through the API.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the receipt is updated.
def test_update_receipt_endpoint_updates_own_receipt(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    receipt = create_receipt(client=client, user_id=user_id)

    payload = {
        "status": "processed",
        "ocr_text": "Lidl total 24.99 EUR",
        "merchant_detected": "Lidl",
        "total_amount_detected": "24.99",
        "currency_detected": "eur",
        "purchase_date_detected": "2026-07-25",
    }

    # Act
    response = client.patch(
        f"/api/v1/receipts/{receipt['id']}",
        json=payload,
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text

    response_data = response.json()

    assert response_data["id"] == receipt["id"]
    assert response_data["status"] == "processed"
    assert response_data["ocr_text"] == "Lidl total 24.99 EUR"
    assert response_data["merchant_detected"] == "Lidl"
    assert response_data["total_amount_detected"] == "24.99"
    assert response_data["currency_detected"] == "EUR"
    assert response_data["purchase_date_detected"] == "2026-07-25"


# Tests that receipt update rejects empty payloads.
# This test exists to prevent PATCH requests that do not change anything.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns validation error status code.
def test_update_receipt_endpoint_rejects_empty_payload(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    receipt = create_receipt(client=client, user_id=user_id)

    # Act
    response = client.patch(
        f"/api/v1/receipts/{receipt['id']}",
        json={},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 422


# Tests that a receipt can be linked to an expense owned by the same user.
# This test exists to verify valid receipt-to-expense linking.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the receipt is linked to the expense.
def test_update_receipt_endpoint_links_to_own_expense(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())

    receipt = create_receipt(client=client, user_id=user_id)
    expense = create_expense(client=client, user_id=user_id)

    # Act
    response = client.patch(
        f"/api/v1/receipts/{receipt['id']}",
        json={"expense_id": expense["id"]},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["expense_id"] == expense["id"]


# Tests that a receipt cannot be linked to another user's expense.
# This test exists to prevent cross-user receipt-to-expense linking.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns not found.
def test_update_receipt_endpoint_rejects_other_user_expense_link(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    receipt = create_receipt(client=client, user_id=user_id)
    other_expense = create_expense(client=client, user_id=other_user_id)

    # Act
    response = client.patch(
        f"/api/v1/receipts/{receipt['id']}",
        json={"expense_id": other_expense["id"]},
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Linked expense not found."


# Tests that a user can delete their own receipt.
# This test exists to verify receipt deletion through the API.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the receipt is deleted.
def test_delete_receipt_endpoint_deletes_own_receipt(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    receipt = create_receipt(client=client, user_id=user_id)

    # Act
    delete_response = client.delete(
        f"/api/v1/receipts/{receipt['id']}",
        headers=auth_headers(user_id),
    )

    list_response = client.get(
        "/api/v1/receipts",
        headers=auth_headers(user_id),
    )

    # Assert
    assert delete_response.status_code == 204
    assert list_response.status_code == 200, list_response.text
    assert list_response.json() == []


# Tests that users cannot delete another user's receipt.
# This test exists to verify ownership checks for receipt deletion.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that clears database tables before and after the test.
# Returns:
# - None. The test passes if the API returns not found.
def test_delete_receipt_endpoint_rejects_other_user_receipt(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid4())
    other_user_id = str(uuid4())

    receipt = create_receipt(client=client, user_id=other_user_id)

    # Act
    response = client.delete(
        f"/api/v1/receipts/{receipt['id']}",
        headers=auth_headers(user_id),
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Receipt not found."

    # Verifies that an authenticated user can upload a valid PDF receipt.
# This test exists to confirm PDF support in the receipt upload endpoint.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - tmp_path: temporary directory used for receipt file storage.
# - monkeypatch: pytest fixture used to override storage configuration.
# Returns:
# - None.
def test_upload_pdf_receipt(
    client: TestClient,
    clean_database: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = str(uuid.uuid4())
    file_content = b"%PDF-1.4 test receipt content"

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_upload_dir",
        str(tmp_path),
    )

    response = client.post(
        "/api/v1/receipts/upload",
        files={
            "file": (
                "receipt.pdf",
                file_content,
                "application/pdf",
            )
        },
        headers=auth_headers(user_id),
    )

    assert response.status_code == 201, response.text

    response_data = response.json()
    stored_file_path = Path(response_data["storage_path"])

    assert response_data["status"] == "uploaded"
    assert stored_file_path.exists()
    assert stored_file_path.suffix == ".pdf"
    assert stored_file_path.read_bytes() == file_content

# Verifies that an uploaded receipt is available through the receipt list endpoint.
# This test exists to confirm that file upload also creates persistent metadata.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - tmp_path: temporary directory used for receipt file storage.
# - monkeypatch: pytest fixture used to override storage configuration.
# Returns:
# - None.
def test_uploaded_receipt_is_available_in_user_receipts(
    client: TestClient,
    clean_database: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = str(uuid.uuid4())

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_upload_dir",
        str(tmp_path),
    )

    upload_response = client.post(
        "/api/v1/receipts/upload",
        files={
            "file": (
                "receipt.png",
                b"valid-png-content",
                "image/png",
            )
        },
        headers=auth_headers(user_id),
    )

    assert upload_response.status_code == 201, upload_response.text

    uploaded_receipt = upload_response.json()

    list_response = client.get(
        "/api/v1/receipts",
        headers=auth_headers(user_id),
    )

    assert list_response.status_code == 200, list_response.text
    assert list_response.json() == [uploaded_receipt]

    # Verifies that receipt upload requires authentication.
# This test exists to prevent anonymous users from storing receipt files.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_upload_receipt_rejects_missing_authentication(
    client: TestClient,
    clean_database: None,
) -> None:
    response = client.post(
        "/api/v1/receipts/upload",
        files={
            "file": (
                "receipt.jpg",
                b"receipt-content",
                "image/jpeg",
            )
        },
    )

    assert response.status_code == 401

# Verifies that the MIME type must match the uploaded file extension.
# This test exists to reject files disguised as supported receipt formats.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - tmp_path: temporary directory used for receipt file storage.
# - monkeypatch: pytest fixture used to override storage configuration.
# Returns:
# - None.
def test_upload_receipt_rejects_mismatched_file_type(
    client: TestClient,
    clean_database: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = str(uuid.uuid4())

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_upload_dir",
        str(tmp_path),
    )

    response = client.post(
        "/api/v1/receipts/upload",
        files={
            "file": (
                "receipt.png",
                b"invalid-content",
                "image/jpeg",
            )
        },
        headers=auth_headers(user_id),
    )

    assert response.status_code == 415
    assert response.json() == {
        "detail": "Receipt file type is not supported.",
    }

# Verifies that a zero-byte receipt file is rejected.
# This test exists to prevent empty files from being stored or persisted.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - tmp_path: temporary directory used for receipt file storage.
# - monkeypatch: pytest fixture used to override storage configuration.
# Returns:
# - None.
def test_upload_receipt_rejects_empty_file(
    client: TestClient,
    clean_database: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = str(uuid.uuid4())

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_upload_dir",
        str(tmp_path),
    )

    response = client.post(
        "/api/v1/receipts/upload",
        files={
            "file": (
                "receipt.jpg",
                b"",
                "image/jpeg",
            )
        },
        headers=auth_headers(user_id),
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Receipt file is empty.",
    }

    user_directory = tmp_path / user_id

    assert user_directory.exists()
    assert list(user_directory.iterdir()) == []

# Verifies that receipt files exceeding the configured limit are rejected.
# This test exists to enforce upload size restrictions without writing
# large test files.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - tmp_path: temporary directory used for receipt file storage.
# - monkeypatch: pytest fixture used to override storage configuration.
# Returns:
# - None.
def test_upload_receipt_rejects_oversized_file(
    client: TestClient,
    clean_database: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = str(uuid.uuid4())

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_upload_dir",
        str(tmp_path),
    )
    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_max_file_size_mb",
        0,
    )

    response = client.post(
        "/api/v1/receipts/upload",
        files={
            "file": (
                "receipt.jpg",
                b"file-content",
                "image/jpeg",
            )
        },
        headers=auth_headers(user_id),
    )

    assert response.status_code == 413
    assert response.json() == {
        "detail": "Receipt file is too large.",
    }

    user_directory = tmp_path / user_id

    assert user_directory.exists()
    assert list(user_directory.iterdir()) == []