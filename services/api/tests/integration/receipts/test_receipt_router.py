from uuid import uuid4
import uuid
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from pathlib import Path

import pytest

from textwrap import dedent
from app.modules.receipts import (
    receipt_ocr_service,
    receipt_storage_service,
)
from app.modules.receipts.receipt_errors import ReceiptOcrProcessingError

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

    # Verifies that an uploaded receipt can be processed through OCR.
# This test exists to confirm the complete HTTP, service, OCR,
# repository, and database processing flow.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - tmp_path: temporary directory used for receipt file storage.
# - monkeypatch: pytest fixture used to replace storage configuration
#   and the external OCR provider.
# Returns:
# - None.
def test_process_receipt_endpoint_saves_ocr_result(
    client: TestClient,
    clean_database: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = str(uuid.uuid4())
    
    extracted_text = dedent(
        """
        LIDL
        31.07.2026
        Milch 1,49
        Brot 2,19
        SUMME 3,68 EUR
        """
    )

    expected_text = (
        "LIDL\n"
        "31.07.2026\n"
        "Milch 1,49\n"
        "Brot 2,19\n"
        "SUMME 3,68 EUR"
    )

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_upload_dir",
        str(tmp_path),
    )

    ocr_provider_mock = MagicMock()
    ocr_provider_mock.extract_text.return_value = extracted_text

    monkeypatch.setattr(
        receipt_ocr_service,
        "receipt_ocr_provider",
        ocr_provider_mock,
    )

    upload_response = client.post(
        "/api/v1/receipts/upload",
        files={
            "file": (
                "receipt.jpg",
                b"receipt-image-content",
                "image/jpeg",
            )
        },
        headers=auth_headers(user_id),
    )

    assert upload_response.status_code == 201, upload_response.text

    uploaded_receipt = upload_response.json()

    process_response = client.post(
        f"/api/v1/receipts/{uploaded_receipt['id']}/process",
        headers=auth_headers(user_id),
    )

    assert process_response.status_code == 200, process_response.text

    processed_receipt = process_response.json()

    assert processed_receipt["id"] == uploaded_receipt["id"]
    assert processed_receipt["user_id"] == user_id
    assert processed_receipt["status"] == "processed"
    assert processed_receipt["ocr_text"] == expected_text
    assert processed_receipt["merchant_detected"] == "LIDL"
    assert processed_receipt["total_amount_detected"] == "3.68"
    assert processed_receipt["currency_detected"] == "EUR"
    assert processed_receipt["purchase_date_detected"] == "2026-07-31"

    stored_response = client.get(
        f"/api/v1/receipts/{uploaded_receipt['id']}",
        headers=auth_headers(user_id),
    )

    assert stored_response.status_code == 200, stored_response.text
    stored_receipt = stored_response.json()

    assert stored_receipt["status"] == "processed"
    assert stored_receipt["ocr_text"] == expected_text
    assert stored_receipt["merchant_detected"] == "LIDL"
    assert stored_receipt["total_amount_detected"] == "3.68"
    assert stored_receipt["currency_detected"] == "EUR"
    assert stored_receipt["purchase_date_detected"] == "2026-07-31"

    ocr_provider_mock.extract_text.assert_called_once_with(
        file_path=Path(uploaded_receipt["storage_path"]),
    )


# Verifies that receipt processing requires authentication.
# This test exists to prevent anonymous users from starting OCR processing.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_process_receipt_endpoint_rejects_missing_authentication(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid.uuid4())

    receipt = create_receipt(
        client=client,
        user_id=user_id,
    )

    response = client.post(
        f"/api/v1/receipts/{receipt['id']}/process",
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Missing authentication credentials.",
    }


# Verifies that users cannot process another user's receipt.
# This test exists to preserve user-level data isolation during OCR processing.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - monkeypatch: pytest fixture used to verify that OCR is not called.
# Returns:
# - None.
def test_process_receipt_endpoint_rejects_other_user_receipt(
    client: TestClient,
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    receipt = create_receipt(
        client=client,
        user_id=other_user_id,
    )

    ocr_provider_mock = MagicMock()

    monkeypatch.setattr(
        receipt_ocr_service,
        "receipt_ocr_provider",
        ocr_provider_mock,
    )

    response = client.post(
        f"/api/v1/receipts/{receipt['id']}/process",
        headers=auth_headers(user_id),
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Receipt not found.",
    }

    ocr_provider_mock.extract_text.assert_not_called()


# Verifies that OCR cannot start for receipts in non-processable states.
# This test exists to prevent invalid receipt processing transitions.
# Parameters:
# - receipt_status: current receipt processing status.
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - tmp_path: temporary directory used for receipt file storage.
# - monkeypatch: pytest fixture used to override test dependencies.
# Returns:
# - None.
@pytest.mark.parametrize(
    "receipt_status",
    [
        "processing",
        "processed",
        "confirmed",
    ],
)
def test_process_receipt_endpoint_rejects_unprocessable_status(
    receipt_status: str,
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

    ocr_provider_mock = MagicMock()

    monkeypatch.setattr(
        receipt_ocr_service,
        "receipt_ocr_provider",
        ocr_provider_mock,
    )

    upload_response = client.post(
        "/api/v1/receipts/upload",
        files={
            "file": (
                "receipt.png",
                b"receipt-image-content",
                "image/png",
            )
        },
        headers=auth_headers(user_id),
    )

    assert upload_response.status_code == 201, upload_response.text

    receipt = upload_response.json()

    update_response = client.patch(
        f"/api/v1/receipts/{receipt['id']}",
        json={
            "status": receipt_status,
        },
        headers=auth_headers(user_id),
    )

    assert update_response.status_code == 200, update_response.text

    process_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/process",
        headers=auth_headers(user_id),
    )

    assert process_response.status_code == 409
    assert process_response.json() == {
        "detail": "Receipt cannot be processed in its current status.",
    }

    ocr_provider_mock.extract_text.assert_not_called()


# Verifies that processing fails when the physical receipt file is missing.
# This test exists to confirm that missing stored files produce a failed
# receipt status instead of leaving the receipt in processing.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - tmp_path: temporary directory used to create a missing file path.
# - monkeypatch: pytest fixture used to verify that OCR is not called.
# Returns:
# - None.
def test_process_receipt_endpoint_marks_missing_file_as_failed(
    client: TestClient,
    clean_database: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = str(uuid.uuid4())
    missing_file_path = tmp_path / "missing-receipt.jpg"

    receipt = create_receipt(
        client=client,
        user_id=user_id,
        payload={
            "storage_path": missing_file_path.as_posix(),
        },
    )

    ocr_provider_mock = MagicMock()

    monkeypatch.setattr(
        receipt_ocr_service,
        "receipt_ocr_provider",
        ocr_provider_mock,
    )

    process_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/process",
        headers=auth_headers(user_id),
    )

    assert process_response.status_code == 404
    assert process_response.json() == {
        "detail": "Receipt file not found.",
    }

    stored_response = client.get(
        f"/api/v1/receipts/{receipt['id']}",
        headers=auth_headers(user_id),
    )

    assert stored_response.status_code == 200, stored_response.text
    assert stored_response.json()["status"] == "failed"
    assert stored_response.json()["ocr_text"] is None

    ocr_provider_mock.extract_text.assert_not_called()


# Verifies that OCR provider errors produce a failed receipt status.
# This test exists to confirm that provider failures are mapped
# to an HTTP error and persisted as a failed processing result.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - tmp_path: temporary directory used for receipt file storage.
# - monkeypatch: pytest fixture used to replace the OCR provider.
# Returns:
# - None.
def test_process_receipt_endpoint_marks_ocr_error_as_failed(
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

    ocr_provider_mock = MagicMock()
    ocr_provider_mock.extract_text.side_effect = ReceiptOcrProcessingError()

    monkeypatch.setattr(
        receipt_ocr_service,
        "receipt_ocr_provider",
        ocr_provider_mock,
    )

    upload_response = client.post(
        "/api/v1/receipts/upload",
        files={
            "file": (
                "receipt.jpg",
                b"receipt-image-content",
                "image/jpeg",
            )
        },
        headers=auth_headers(user_id),
    )

    assert upload_response.status_code == 201, upload_response.text

    receipt = upload_response.json()

    process_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/process",
        headers=auth_headers(user_id),
    )

    assert process_response.status_code == 422
    assert process_response.json() == {
        "detail": "Receipt OCR processing failed.",
    }

    stored_response = client.get(
        f"/api/v1/receipts/{receipt['id']}",
        headers=auth_headers(user_id),
    )

    assert stored_response.status_code == 200, stored_response.text
    assert stored_response.json()["status"] == "failed"
    assert stored_response.json()["ocr_text"] is None

    ocr_provider_mock.extract_text.assert_called_once()


# Verifies that a failed receipt can be processed again successfully.
# This test exists to confirm retry support after a temporary OCR failure.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - tmp_path: temporary directory used for receipt file storage.
# - monkeypatch: pytest fixture used to control OCR provider results.
# Returns:
# - None.
def test_process_receipt_endpoint_retries_failed_receipt(
    client: TestClient,
    clean_database: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = str(uuid.uuid4())
    extracted_text = "\nREWE\nTOTAL 18.50 EUR\n"
    expected_text = "REWE\nTOTAL 18.50 EUR"

    monkeypatch.setattr(
        receipt_storage_service.settings,
        "receipt_upload_dir",
        str(tmp_path),
    )

    ocr_provider_mock = MagicMock()
    ocr_provider_mock.extract_text.side_effect = [
        ReceiptOcrProcessingError(),
        extracted_text,
    ]

    monkeypatch.setattr(
        receipt_ocr_service,
        "receipt_ocr_provider",
        ocr_provider_mock,
    )

    upload_response = client.post(
        "/api/v1/receipts/upload",
        files={
            "file": (
                "receipt.jpg",
                b"receipt-image-content",
                "image/jpeg",
            )
        },
        headers=auth_headers(user_id),
    )

    assert upload_response.status_code == 201, upload_response.text

    receipt = upload_response.json()

    first_process_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/process",
        headers=auth_headers(user_id),
    )

    assert first_process_response.status_code == 422

    failed_receipt_response = client.get(
        f"/api/v1/receipts/{receipt['id']}",
        headers=auth_headers(user_id),
    )

    assert failed_receipt_response.status_code == 200
    assert failed_receipt_response.json()["status"] == "failed"

    retry_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/process",
        headers=auth_headers(user_id),
    )

    assert retry_response.status_code == 200, retry_response.text

    retried_receipt = retry_response.json()

    assert retried_receipt["status"] == "processed"
    assert retried_receipt["ocr_text"] == expected_text

    stored_response = client.get(
        f"/api/v1/receipts/{receipt['id']}",
        headers=auth_headers(user_id),
    )

    assert stored_response.status_code == 200
    assert stored_response.json()["status"] == "processed"
    assert stored_response.json()["ocr_text"] == expected_text

    assert ocr_provider_mock.extract_text.call_count == 2

    # Verifies that a processed receipt can be confirmed into an expense.
# This test exists to confirm the complete upload, OCR, parsing,
# confirmation, expense creation, and database persistence flow.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - tmp_path: temporary directory used for receipt file storage.
# - monkeypatch: pytest fixture used to replace storage configuration
#   and the external OCR provider.
# Returns:
# - None.
def test_confirm_receipt_endpoint_creates_linked_expense(
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

    ocr_provider_mock = MagicMock()
    ocr_provider_mock.extract_text.return_value = (
        "LIDL\n"
        "31.07.2026\n"
        "Milch 1,49\n"
        "Brot 2,19\n"
        "SUMME 3,68 EUR"
    )

    monkeypatch.setattr(
        receipt_ocr_service,
        "receipt_ocr_provider",
        ocr_provider_mock,
    )

    upload_response = client.post(
        "/api/v1/receipts/upload",
        files={
            "file": (
                "receipt.jpg",
                b"receipt-image-content",
                "image/jpeg",
            )
        },
        headers=auth_headers(user_id),
    )

    assert upload_response.status_code == 201, upload_response.text

    receipt_id = upload_response.json()["id"]

    process_response = client.post(
        f"/api/v1/receipts/{receipt_id}/process",
        headers=auth_headers(user_id),
    )

    assert process_response.status_code == 200, process_response.text
    assert process_response.json()["status"] == "processed"

    confirm_response = client.post(
        f"/api/v1/receipts/{receipt_id}/confirm",
        json={},
        headers=auth_headers(user_id),
    )

    assert confirm_response.status_code == 200, confirm_response.text

    response_data = confirm_response.json()
    confirmed_receipt = response_data["receipt"]
    created_expense = response_data["expense"]

    assert confirmed_receipt["id"] == receipt_id
    assert confirmed_receipt["status"] == "confirmed"
    assert confirmed_receipt["expense_id"] == created_expense["id"]

    assert created_expense["user_id"] == user_id
    assert created_expense["category_id"] is None
    assert created_expense["title"] == "LIDL"
    assert created_expense["amount"] == "3.68"
    assert created_expense["currency"] == "EUR"
    assert created_expense["expense_date"] == "2026-07-31"
    assert created_expense["description"] is None
    assert created_expense["source"] == "receipt"

    stored_receipt_response = client.get(
        f"/api/v1/receipts/{receipt_id}",
        headers=auth_headers(user_id),
    )

    assert stored_receipt_response.status_code == 200

    stored_receipt = stored_receipt_response.json()

    assert stored_receipt["status"] == "confirmed"
    assert stored_receipt["expense_id"] == created_expense["id"]

    expenses_response = client.get(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
    )

    assert expenses_response.status_code == 200, expenses_response.text
    assert len(expenses_response.json()) == 1
    assert expenses_response.json()[0]["id"] == created_expense["id"]

# Verifies that confirmation corrections override detected receipt values.
# This test exists because OCR results can be inaccurate
# and must remain editable before expense creation.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_confirm_receipt_endpoint_uses_user_corrections(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid.uuid4())

    receipt = create_receipt(
        client=client,
        user_id=user_id,
    )

    update_response = client.patch(
        f"/api/v1/receipts/{receipt['id']}",
        json={
            "status": "processed",
            "merchant_detected": "L1DL",
            "total_amount_detected": "28.99",
            "currency_detected": "USD",
            "purchase_date_detected": "2026-07-30",
        },
        headers=auth_headers(user_id),
    )

    assert update_response.status_code == 200, update_response.text

    confirm_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={
            "title": "LIDL",
            "amount": "23.99",
            "currency": "eur",
            "expense_date": "2026-07-31",
            "description": "Weekly groceries",
        },
        headers=auth_headers(user_id),
    )

    assert confirm_response.status_code == 200, confirm_response.text

    response_data = confirm_response.json()
    confirmed_receipt = response_data["receipt"]
    created_expense = response_data["expense"]

    assert confirmed_receipt["status"] == "confirmed"
    assert confirmed_receipt["expense_id"] == created_expense["id"]

    assert created_expense["title"] == "LIDL"
    assert created_expense["amount"] == "23.99"
    assert created_expense["currency"] == "EUR"
    assert created_expense["expense_date"] == "2026-07-31"
    assert created_expense["description"] == "Weekly groceries"
    assert created_expense["source"] == "receipt"

# Verifies that complete manual confirmation data can replace missing OCR data.
# This test exists to allow confirmation when OCR parsing is incomplete
# but the user supplies every required expense value.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_confirm_receipt_endpoint_accepts_complete_manual_data(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid.uuid4())

    receipt = create_receipt(
        client=client,
        user_id=user_id,
    )

    update_response = client.patch(
        f"/api/v1/receipts/{receipt['id']}",
        json={
            "status": "processed",
        },
        headers=auth_headers(user_id),
    )

    assert update_response.status_code == 200, update_response.text

    confirm_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={
            "title": "Local supermarket",
            "amount": "15.50",
            "currency": "eur",
            "expense_date": "2026-07-31",
        },
        headers=auth_headers(user_id),
    )

    assert confirm_response.status_code == 200, confirm_response.text

    response_data = confirm_response.json()

    assert response_data["receipt"]["status"] == "confirmed"
    assert response_data["expense"]["title"] == "Local supermarket"
    assert response_data["expense"]["amount"] == "15.50"
    assert response_data["expense"]["currency"] == "EUR"
    assert response_data["expense"]["expense_date"] == "2026-07-31"

# Verifies that confirmation rejects incomplete expense data.
# This test exists to prevent invalid expenses when required values
# are absent from both OCR output and the confirmation request.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_confirm_receipt_endpoint_rejects_missing_required_data(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid.uuid4())

    receipt = create_receipt(
        client=client,
        user_id=user_id,
    )

    update_response = client.patch(
        f"/api/v1/receipts/{receipt['id']}",
        json={
            "status": "processed",
        },
        headers=auth_headers(user_id),
    )

    assert update_response.status_code == 200, update_response.text

    confirm_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={},
        headers=auth_headers(user_id),
    )

    assert confirm_response.status_code == 422
    assert confirm_response.json() == {
        "detail": "Required receipt confirmation data is missing.",
    }

    stored_receipt_response = client.get(
        f"/api/v1/receipts/{receipt['id']}",
        headers=auth_headers(user_id),
    )

    assert stored_receipt_response.status_code == 200
    assert stored_receipt_response.json()["status"] == "processed"
    assert stored_receipt_response.json()["expense_id"] is None

    expenses_response = client.get(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
    )

    assert expenses_response.status_code == 200
    assert expenses_response.json() == []

# Verifies that only processed receipts can be confirmed.
# This test exists to prevent confirmation before successful OCR processing.
# Parameters:
# - receipt_status: current receipt status.
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
@pytest.mark.parametrize(
    "receipt_status",
    [
        "uploaded",
        "processing",
        "failed",
    ],
)
def test_confirm_receipt_endpoint_rejects_unconfirmable_status(
    receipt_status: str,
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid.uuid4())

    receipt = create_receipt(
        client=client,
        user_id=user_id,
    )

    if receipt_status != "uploaded":
        update_response = client.patch(
            f"/api/v1/receipts/{receipt['id']}",
            json={
                "status": receipt_status,
            },
            headers=auth_headers(user_id),
        )

        assert update_response.status_code == 200, update_response.text

    confirm_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={
            "title": "LIDL",
            "amount": "24.99",
            "currency": "EUR",
            "expense_date": "2026-07-31",
        },
        headers=auth_headers(user_id),
    )

    assert confirm_response.status_code == 409
    assert confirm_response.json() == {
        "detail": "Receipt cannot be confirmed in its current status.",
    }

# Verifies that a confirmed receipt cannot create a second expense.
# This test exists to prevent duplicate expenses from repeated requests.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_confirm_receipt_endpoint_rejects_repeated_confirmation(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid.uuid4())

    receipt = create_receipt(
        client=client,
        user_id=user_id,
    )

    update_response = client.patch(
        f"/api/v1/receipts/{receipt['id']}",
        json={
            "status": "processed",
            "merchant_detected": "LIDL",
            "total_amount_detected": "24.99",
            "currency_detected": "EUR",
            "purchase_date_detected": "2026-07-31",
        },
        headers=auth_headers(user_id),
    )

    assert update_response.status_code == 200, update_response.text

    first_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={},
        headers=auth_headers(user_id),
    )

    assert first_response.status_code == 200, first_response.text

    second_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={},
        headers=auth_headers(user_id),
    )

    assert second_response.status_code == 409
    assert second_response.json() == {
        "detail": "Receipt has already been confirmed.",
    }

    expenses_response = client.get(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
    )

    assert expenses_response.status_code == 200
    assert len(expenses_response.json()) == 1

# Verifies that users cannot confirm another user's receipt.
# This test exists to preserve receipt ownership during expense creation.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_confirm_receipt_endpoint_rejects_other_user_receipt(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    receipt = create_receipt(
        client=client,
        user_id=other_user_id,
    )

    update_response = client.patch(
        f"/api/v1/receipts/{receipt['id']}",
        json={
            "status": "processed",
            "merchant_detected": "LIDL",
            "total_amount_detected": "24.99",
            "currency_detected": "EUR",
            "purchase_date_detected": "2026-07-31",
        },
        headers=auth_headers(other_user_id),
    )

    assert update_response.status_code == 200, update_response.text

    confirm_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={},
        headers=auth_headers(user_id),
    )

    assert confirm_response.status_code == 404
    assert confirm_response.json() == {
        "detail": "Receipt not found.",
    }

    expenses_response = client.get(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
    )

    assert expenses_response.status_code == 200
    assert expenses_response.json() == []

# Verifies that receipt confirmation requires authentication.
# This test exists to prevent anonymous expense creation.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_confirm_receipt_endpoint_rejects_missing_authentication(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid.uuid4())

    receipt = create_receipt(
        client=client,
        user_id=user_id,
    )

    confirm_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={},
    )

    assert confirm_response.status_code == 401
    assert confirm_response.json() == {
        "detail": "Missing authentication credentials.",
    }