from uuid import uuid4
import uuid
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from pathlib import Path

import pytest

from textwrap import dedent
from app.modules.receipts import (
    receipt_ocr_service,
    receipt_service,
    receipt_storage_service,
)
from app.modules.receipts.receipt_errors import ReceiptOcrProcessingError
from app.modules.fx import fx_ecb_provider

from tests.helpers import (
    auth_headers,
    create_account,
    create_category,
    create_expense,
    create_receipt,
)


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


# Tests (K) that confirming a receipt with a foreign (non-base) currency
# produces an expense with a full ECB-resolved FX snapshot, through the
# same expenses_service.create_expense path every other Expense creation
# uses.
# This test exists to verify VF-014B5C's requirement that receipt
# confirmation automatically inherits FX normalization without any
# duplicated conversion logic in receipt code.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes if the created expense carries a complete,
#   ECB-sourced FX snapshot.
def test_confirm_receipt_endpoint_foreign_currency_gets_fx_snapshot(
    client: TestClient,
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = str(uuid.uuid4())

    response_payload = {
        "dataSets": [{"series": {"0:0:0:0:0": {"observations": {"0": [1.1539, 0, 0, None, None]}}}}],
        "structure": {"dimensions": {"observation": [{"id": "TIME_PERIOD", "values": [{"id": "2026-07-31"}]}]}},
    }
    response_mock = MagicMock()
    response_mock.status_code = 200
    response_mock.json.return_value = response_payload
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", MagicMock(return_value=response_mock))

    receipt = create_receipt(client=client, user_id=user_id)

    update_response = client.patch(
        f"/api/v1/receipts/{receipt['id']}",
        json={
            "status": "processed",
            "merchant_detected": "NYC DELI",
            "total_amount_detected": "20.00",
            "currency_detected": "USD",
            "purchase_date_detected": "2026-07-31",
        },
        headers=auth_headers(user_id),
    )
    assert update_response.status_code == 200, update_response.text

    confirm_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={},
        headers=auth_headers(user_id),
    )
    assert confirm_response.status_code == 200, confirm_response.text

    created_expense = confirm_response.json()["expense"]
    assert created_expense["currency"] == "USD"
    assert created_expense["base_currency"] == "EUR"
    assert created_expense["fx_source"] == "ecb"
    assert created_expense["base_amount"] is not None
    assert created_expense["fx_rate"] is not None


# VF-014B5C financial-integrity correction (transaction boundary): proves
# that confirm_receipt is a single atomic transaction end to end, even
# though it composes three internally-transactional pieces - the lazy
# financial-settings bootstrap, expenses_service.create_expense, and the
# receipt's own status update. Before the fix,
# financial_settings_repository.get_or_create_financial_settings committed
# unconditionally, so a settings row (and, depending on ordering, other
# pending session state) could survive a rollback triggered by a later
# provider failure in the same confirm_receipt call - a real caller-owned
# atomicity violation.
# Part 1 exercises the dangerous case: a brand-new user (no
# user_financial_settings row yet) confirms a foreign-currency receipt
# while the ECB provider fails. Part 2 then confirms that a normal,
# successful confirmation for a brand-new user still commits the
# settings bootstrap, the receipt update, and the Expense/FX snapshot
# together.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - monkeypatch: pytest fixture used to mock the ECB HTTP boundary.
# Returns:
# - None. The test passes only if the failed confirmation leaves no
#   Expense, no committed settings row, and the receipt un-confirmed,
#   while the subsequent successful confirmation commits everything.
def test_confirm_receipt_endpoint_atomic_across_settings_bootstrap_and_fx_failure(
    client: TestClient,
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.database_session import SessionLocal
    from app.modules.financial_settings.financial_settings_models import (
        UserFinancialSettingsModel,
    )

    user_id_uuid = uuid.uuid4()
    user_id = str(user_id_uuid)

    def _settings_row_count() -> int:
        session = SessionLocal()
        try:
            return (
                session.query(UserFinancialSettingsModel)
                .filter(UserFinancialSettingsModel.user_id == user_id_uuid)
                .count()
            )
        finally:
            session.close()

    # Sanity: this user genuinely has no settings row yet.
    assert _settings_row_count() == 0

    # --- Part 1: dangerous case - provider fails after the settings
    # bootstrap would have run inside the same transaction. ---
    response_mock = MagicMock()
    response_mock.status_code = 404
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", MagicMock(return_value=response_mock))

    receipt = create_receipt(client=client, user_id=user_id)
    update_response = client.patch(
        f"/api/v1/receipts/{receipt['id']}",
        json={
            "status": "processed",
            "merchant_detected": "NYC DELI",
            "total_amount_detected": "20.00",
            "currency_detected": "USD",
            "purchase_date_detected": "2026-07-31",
        },
        headers=auth_headers(user_id),
    )
    assert update_response.status_code == 200, update_response.text

    failed_confirm_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={},
        headers=auth_headers(user_id),
    )

    # The provider failure must surface as an error, not a partial success.
    assert failed_confirm_response.status_code == 422, failed_confirm_response.text

    # No Expense was created.
    expenses_after_failure = client.get("/api/v1/expenses", headers=auth_headers(user_id))
    assert expenses_after_failure.json() == []

    # The receipt itself was never mutated into "confirmed" - the whole
    # attempt rolled back together, not just the Expense insert.
    receipts_after_failure = client.get("/api/v1/receipts", headers=auth_headers(user_id))
    receipt_after_failure = next(
        r for r in receipts_after_failure.json() if r["id"] == receipt["id"]
    )
    assert receipt_after_failure["status"] == "processed"
    assert receipt_after_failure["expense_id"] is None

    # The lazy settings bootstrap did not survive as a premature,
    # independently-committed write - it rolled back with everything else.
    assert _settings_row_count() == 0

    # --- Part 2: the same brand-new user's next confirmation attempt,
    # this time with a working provider, must commit the settings
    # bootstrap, the receipt update, and the Expense/FX snapshot as one
    # atomic unit. ---
    ecb_payload = {
        "dataSets": [{"series": {"0:0:0:0:0": {"observations": {"0": [1.1539, 0, 0, None, None]}}}}],
        "structure": {"dimensions": {"observation": [{"id": "TIME_PERIOD", "values": [{"id": "2026-07-31"}]}]}},
    }
    ecb_response_mock = MagicMock()
    ecb_response_mock.status_code = 200
    ecb_response_mock.json.return_value = ecb_payload
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", MagicMock(return_value=ecb_response_mock))

    success_confirm_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={},
        headers=auth_headers(user_id),
    )
    assert success_confirm_response.status_code == 200, success_confirm_response.text

    body = success_confirm_response.json()
    assert body["receipt"]["status"] == "confirmed"
    assert body["expense"]["base_currency"] == "EUR"
    assert body["expense"]["fx_source"] == "ecb"
    assert body["expense"]["base_amount"] is not None

    # The settings row now exists, committed together with the rest.
    assert _settings_row_count() == 1

    expenses_after_success = client.get("/api/v1/expenses", headers=auth_headers(user_id))
    assert len(expenses_after_success.json()) == 1


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

    # Verifies that receipt confirmation can assign
# a category owned by the authenticated user.
# This test exists to confirm valid category ownership
# during receipt-to-expense conversion.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_confirm_receipt_endpoint_allows_own_category(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid.uuid4())

    category = create_category(
        client=client,
        user_id=user_id,
        name="Food",
    )

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

    # Act
    confirm_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={
            "category_id": category["id"],
        },
        headers=auth_headers(user_id),
    )

    # Assert
    assert confirm_response.status_code == 200, confirm_response.text

    response_data = confirm_response.json()
    confirmed_receipt = response_data["receipt"]
    created_expense = response_data["expense"]

    assert confirmed_receipt["status"] == "confirmed"
    assert confirmed_receipt["expense_id"] == created_expense["id"]

    assert created_expense["user_id"] == user_id
    assert created_expense["category_id"] == category["id"]
    assert created_expense["title"] == "LIDL"
    assert created_expense["amount"] == "24.99"
    assert created_expense["source"] == "receipt"

    expenses_response = client.get(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
    )

    assert expenses_response.status_code == 200
    assert len(expenses_response.json()) == 1
    assert expenses_response.json()[0]["category_id"] == category["id"]

    # Verifies that receipt confirmation cannot use
# a category owned by another user.
# This test exists to prevent cross-user category assignment
# and confirm that the operation remains atomic after failure.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_confirm_receipt_endpoint_rejects_other_user_category(
    client: TestClient,
    clean_database: None,
) -> None:
    # Arrange
    user_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    other_user_category = create_category(
        client=client,
        user_id=other_user_id,
        name="Food",
    )

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

    # Act
    confirm_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={
            "category_id": other_user_category["id"],
        },
        headers=auth_headers(user_id),
    )

    # Assert
    assert confirm_response.status_code == 404
    assert confirm_response.json() == {
        "detail": "Category not found.",
    }

    stored_receipt_response = client.get(
        f"/api/v1/receipts/{receipt['id']}",
        headers=auth_headers(user_id),
    )

    assert stored_receipt_response.status_code == 200

    stored_receipt = stored_receipt_response.json()

    assert stored_receipt["status"] == "processed"
    assert stored_receipt["expense_id"] is None

    expenses_response = client.get(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
    )

    assert expenses_response.status_code == 200
    assert expenses_response.json() == []


# --- VF-017I: receipt confirmation -> Account linking ---


# Creates a receipt and moves it to "processed" with detected values.
# This helper exists so Account-linking confirmation tests start from a
# confirmable receipt without repeating the OCR upload/process setup.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier as string.
# - currency: detected receipt currency.
# - amount: detected receipt total.
# Returns:
# - The processed receipt response body.
def _create_processed_receipt(
    client: TestClient,
    user_id: str,
    currency: str = "EUR",
    amount: str = "24.99",
) -> dict:
    receipt = create_receipt(client=client, user_id=user_id)

    response = client.patch(
        f"/api/v1/receipts/{receipt['id']}",
        json={
            "status": "processed",
            "merchant_detected": "LIDL",
            "total_amount_detected": amount,
            "currency_detected": currency,
            "purchase_date_detected": "2026-07-31",
        },
        headers=auth_headers(user_id),
    )

    assert response.status_code == 200, response.text

    return response.json()


# Returns one Account (with its ledger-derived current_balance) from the
# Account list endpoint.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier as string.
# - account_id: Account identifier to find.
# Returns:
# - The Account response body.
def _get_account(client: TestClient, user_id: str, account_id: str) -> dict:
    response = client.get("/api/v1/accounts", headers=auth_headers(user_id))

    assert response.status_code == 200, response.text

    accounts = {account["id"]: account for account in response.json()}

    return accounts[account_id]


# Returns an Account's kind="expense" ledger rows.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier as string.
# - account_id: Account identifier.
# Returns:
# - List of AccountTransaction response bodies with kind "expense".
def _get_expense_transactions(
    client: TestClient,
    user_id: str,
    account_id: str,
) -> list:
    response = client.get(
        f"/api/v1/accounts/{account_id}/transactions",
        headers=auth_headers(user_id),
    )

    assert response.status_code == 200, response.text

    return [
        transaction
        for transaction in response.json()
        if transaction["kind"] == "expense"
    ]


# Asserts that a failed confirmation left no partial writes behind: the
# receipt is still processed and unlinked, no Expense exists, and the
# Account has no expense debit and an unchanged balance.
# Parameters:
# - client: FastAPI test client.
# - user_id: authenticated user identifier as string.
# - receipt_id: receipt identifier.
# - account_id: Account identifier.
# - expected_balance: the Account balance before the attempt.
# Returns:
# - None.
def _assert_confirmation_left_no_partial_writes(
    client: TestClient,
    user_id: str,
    receipt_id: str,
    account_id: str,
    expected_balance: str,
) -> None:
    receipt_response = client.get(
        f"/api/v1/receipts/{receipt_id}",
        headers=auth_headers(user_id),
    )

    assert receipt_response.status_code == 200, receipt_response.text
    assert receipt_response.json()["status"] == "processed"
    assert receipt_response.json()["expense_id"] is None

    expenses_response = client.get(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
    )

    assert expenses_response.status_code == 200, expenses_response.text
    assert expenses_response.json() == []

    assert _get_expense_transactions(client, user_id, account_id) == []
    assert _get_account(client, user_id, account_id)["current_balance"] == expected_balance


# Verifies that an unlinked confirmation (no account_id) keeps its
# pre-VF-017I behavior and reports account_id as null.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_confirm_receipt_endpoint_without_account_creates_unlinked_expense(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid.uuid4())
    receipt = _create_processed_receipt(client, user_id)
    account = create_account(client, user_id, opening_balance="100.00")

    response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["receipt"]["status"] == "confirmed"
    assert body["receipt"]["expense_id"] == body["expense"]["id"]
    assert body["expense"]["account_id"] is None

    assert _get_expense_transactions(client, user_id, account["id"]) == []
    assert _get_account(client, user_id, account["id"])["current_balance"] == "100.00"


# Verifies that confirming with an owned, active, same-currency Account
# creates the Expense and exactly one debit projection in one step.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_confirm_receipt_endpoint_with_account_links_expense(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid.uuid4())
    receipt = _create_processed_receipt(client, user_id)
    account = create_account(client, user_id, opening_balance="100.00")

    response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={"account_id": account["id"]},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 200, response.text

    body = response.json()
    expense = body["expense"]

    assert expense["account_id"] == account["id"]
    assert expense["amount"] == "24.99"
    assert expense["source"] == "receipt"
    assert body["receipt"]["status"] == "confirmed"
    assert body["receipt"]["expense_id"] == expense["id"]

    expenses_response = client.get(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
    )

    assert expenses_response.status_code == 200, expenses_response.text
    assert [item["id"] for item in expenses_response.json()] == [expense["id"]]
    assert expenses_response.json()[0]["account_id"] == account["id"]

    transactions = _get_expense_transactions(client, user_id, account["id"])

    assert len(transactions) == 1
    assert transactions[0]["direction"] == "debit"
    assert transactions[0]["amount"] == "24.99"
    assert transactions[0]["expense_id"] == expense["id"]
    assert transactions[0]["transaction_date"] == "2026-07-31"

    assert _get_account(client, user_id, account["id"])["current_balance"] == "75.01"


# Verifies that a currency mismatch between the receipt's final currency
# and the Account rejects the whole confirmation atomically.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_confirm_receipt_endpoint_account_currency_mismatch_is_atomic(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid.uuid4())
    receipt = _create_processed_receipt(client, user_id, currency="EUR")
    account = create_account(
        client,
        user_id,
        currency="USD",
        opening_balance="100.00",
    )

    response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={"account_id": account["id"]},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "Expense currency must match the account's currency to link them.",
    }

    _assert_confirmation_left_no_partial_writes(
        client, user_id, receipt["id"], account["id"], "100.00",
    )


# Verifies that an archived Account cannot receive the receipt's Expense
# and that the rejection leaves no partial writes.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_confirm_receipt_endpoint_archived_account_is_atomic(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid.uuid4())
    receipt = _create_processed_receipt(client, user_id)
    account = create_account(client, user_id, opening_balance="100.00")

    archive_response = client.patch(
        f"/api/v1/accounts/{account['id']}",
        json={"status": "archived"},
        headers=auth_headers(user_id),
    )

    assert archive_response.status_code == 200, archive_response.text

    response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={"account_id": account["id"]},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 409, response.text
    assert response.json() == {
        "detail": "Archived account cannot receive new transactions.",
    }

    _assert_confirmation_left_no_partial_writes(
        client, user_id, receipt["id"], account["id"], "100.00",
    )


# Verifies that another user's Account is indistinguishable from a
# missing one and that the rejection leaves no partial writes.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_confirm_receipt_endpoint_other_user_account_not_found(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())
    receipt = _create_processed_receipt(client, user_id)
    other_account = create_account(client, other_user_id, opening_balance="100.00")

    response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={"account_id": other_account["id"]},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Account not found."}

    receipt_response = client.get(
        f"/api/v1/receipts/{receipt['id']}",
        headers=auth_headers(user_id),
    )

    assert receipt_response.json()["status"] == "processed"
    assert receipt_response.json()["expense_id"] is None

    expenses_response = client.get(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
    )

    assert expenses_response.json() == []

    # The other user's Account is untouched.
    assert _get_expense_transactions(client, other_user_id, other_account["id"]) == []
    assert (
        _get_account(client, other_user_id, other_account["id"])["current_balance"]
        == "100.00"
    )


# Verifies that a repeated (sequential) confirmation of a linked receipt
# is rejected and never produces a second Expense or a second debit.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# Returns:
# - None.
def test_confirm_receipt_endpoint_repeated_linked_confirmation_single_debit(
    client: TestClient,
    clean_database: None,
) -> None:
    user_id = str(uuid.uuid4())
    receipt = _create_processed_receipt(client, user_id)
    account = create_account(client, user_id, opening_balance="100.00")

    first_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={"account_id": account["id"]},
        headers=auth_headers(user_id),
    )

    assert first_response.status_code == 200, first_response.text

    second_response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={"account_id": account["id"]},
        headers=auth_headers(user_id),
    )

    assert second_response.status_code == 409, second_response.text
    assert second_response.json() == {
        "detail": "Receipt has already been confirmed.",
    }

    expenses_response = client.get(
        "/api/v1/expenses",
        headers=auth_headers(user_id),
    )

    assert len(expenses_response.json()) == 1
    assert len(_get_expense_transactions(client, user_id, account["id"])) == 1
    assert _get_account(client, user_id, account["id"])["current_balance"] == "75.01"


# Verifies that an FX failure on a linked foreign-currency confirmation
# (USD receipt -> USD Account, EUR base currency) rolls everything back.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - monkeypatch: pytest fixture used to make the ECB provider fail.
# Returns:
# - None.
def test_confirm_receipt_endpoint_linked_fx_failure_is_atomic(
    client: TestClient,
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = str(uuid.uuid4())
    receipt = _create_processed_receipt(
        client, user_id, currency="USD", amount="20.00",
    )
    account = create_account(
        client,
        user_id,
        currency="USD",
        opening_balance="100.00",
    )

    response_mock = MagicMock()
    response_mock.status_code = 404
    monkeypatch.setattr(
        fx_ecb_provider.httpx, "get", MagicMock(return_value=response_mock),
    )

    response = client.post(
        f"/api/v1/receipts/{receipt['id']}/confirm",
        json={"account_id": account["id"]},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "This currency cannot be converted for the given date.",
    }

    _assert_confirmation_left_no_partial_writes(
        client, user_id, receipt["id"], account["id"], "100.00",
    )


# Verifies that a failure AFTER the Expense and its debit projection were
# flushed (the receipt update itself fails) rolls back both writes and
# leaves the receipt unconfirmed - the linked-path counterpart of the
# unit-level rollback test, proven against the real database.
# Parameters:
# - client: FastAPI test client.
# - clean_database: fixture that isolates database state.
# - monkeypatch: pytest fixture used to make the receipt update fail.
# Returns:
# - None.
def test_confirm_receipt_endpoint_linked_rolls_back_when_receipt_update_fails(
    client: TestClient,
    clean_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = str(uuid.uuid4())
    receipt = _create_processed_receipt(client, user_id)
    account = create_account(client, user_id, opening_balance="100.00")

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "update_receipt",
        MagicMock(side_effect=RuntimeError("Receipt update failed.")),
    )

    with pytest.raises(RuntimeError, match="Receipt update failed."):
        client.post(
            f"/api/v1/receipts/{receipt['id']}/confirm",
            json={"account_id": account["id"]},
            headers=auth_headers(user_id),
        )

    _assert_confirmation_left_no_partial_writes(
        client, user_id, receipt["id"], account["id"], "100.00",
    )
