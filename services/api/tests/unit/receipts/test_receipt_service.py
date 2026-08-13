from decimal import Decimal
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock
from typing import Optional
from fastapi import UploadFile

import pytest
from sqlalchemy.orm import Session

from app.modules.expenses.expenses_errors import ExpenseNotFoundError
from app.modules.receipts import receipt_service
from app.modules.expenses.expenses_schemas import ExpenseResponse
from app.modules.receipts.receipt_errors import (
    ReceiptExpenseNotFoundError,
    ReceiptFileStorageError,
    ReceiptFileTooLargeError,
    ReceiptOcrFileNotFoundError,
    ReceiptOcrProcessingError,
    ReceiptProcessingNotAllowedError,
    ReceiptAlreadyConfirmedError,
    ReceiptConfirmationDataMissingError,
    ReceiptConfirmationNotAllowedError,
)
from app.modules.receipts.receipt_models import ReceiptModel
from app.modules.receipts.receipt_schemas import (
    ReceiptCreate,
    ReceiptResponse,
    ReceiptUpdate,
    ReceiptConfirmRequest,
)


# Creates a mocked SQLAlchemy session for receipt service unit tests.
# This fixture exists to isolate service behavior from the real database.
# Parameters:
# - None.
# Returns:
# - Mocked SQLAlchemy Session instance.
@pytest.fixture()
def db_session() -> MagicMock:
    return MagicMock(spec=Session)


# Creates a complete ReceiptModel instance for service unit tests.
# This helper exists to provide valid model data for response mapping.
# Parameters:
# - user_id: optional receipt owner identifier.
# - receipt_id: optional receipt identifier.
# Returns:
# - ReceiptModel instance with populated required fields.
def build_receipt_model(
    user_id: Optional[uuid.UUID] = None,
    receipt_id: Optional[uuid.UUID] = None,
) -> ReceiptModel:
    timestamp = datetime.now(timezone.utc)

    resolved_user_id = (
        user_id
        if user_id is not None
        else uuid.uuid4()
    )
    resolved_receipt_id = (
        receipt_id
        if receipt_id is not None
        else uuid.uuid4()
    )

    return ReceiptModel(
        id=resolved_receipt_id,
        user_id=resolved_user_id,
        expense_id=None,
        file_url=None,
        storage_path="receipts/test-user/receipt-1.jpg",
        status="uploaded",
        ocr_text=None,
        merchant_detected=None,
        total_amount_detected=None,
        currency_detected=None,
        purchase_date_detected=None,
        created_at=timestamp,
        updated_at=timestamp,
    )


# Verifies that a ReceiptModel is converted into ReceiptResponse.
# This test exists to confirm separation between database and API models.
# Parameters:
# - None.
# Returns:
# - None.
def test_map_receipt_to_response() -> None:
    receipt = build_receipt_model()

    result = receipt_service.map_receipt_to_response(receipt)

    assert isinstance(result, ReceiptResponse)
    assert result.id == receipt.id
    assert result.user_id == receipt.user_id
    assert result.expense_id == receipt.expense_id
    assert result.file_url == receipt.file_url
    assert result.storage_path == receipt.storage_path
    assert result.status == receipt.status
    assert result.created_at == receipt.created_at
    assert result.updated_at == receipt.updated_at


# Verifies that receipt creation delegates persistence to the repository.
# This test exists to confirm service orchestration and response mapping.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace dependencies.
# Returns:
# - None.
def test_create_receipt(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_data = ReceiptCreate(
        storage_path=f"receipts/{user_id}/receipt-1.jpg",
    )
    receipt = build_receipt_model(user_id=user_id)
    expected_response = ReceiptResponse.model_validate(receipt)

    create_receipt_mock = MagicMock(return_value=receipt)
    map_receipt_mock = MagicMock(return_value=expected_response)

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "create_receipt",
        create_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "map_receipt_to_response",
        map_receipt_mock,
    )

    result = receipt_service.create_receipt(
        db_session=db_session,
        receipt_data=receipt_data,
        user_id=user_id,
    )

    assert result is expected_response

    create_receipt_mock.assert_called_once_with(
        db_session=db_session,
        receipt_data=receipt_data,
        user_id=user_id,
    )
    map_receipt_mock.assert_called_once_with(receipt)


# Verifies that all repository receipts are converted into responses.
# This test exists to confirm list mapping in the service layer.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace dependencies.
# Returns:
# - None.
def test_get_receipts(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()

    first_receipt = build_receipt_model(user_id=user_id)
    second_receipt = build_receipt_model(user_id=user_id)

    first_response = ReceiptResponse.model_validate(first_receipt)
    second_response = ReceiptResponse.model_validate(second_receipt)

    get_receipts_mock = MagicMock(
        return_value=[
            first_receipt,
            second_receipt,
        ]
    )
    map_receipt_mock = MagicMock(
        side_effect=[
            first_response,
            second_response,
        ]
    )

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "get_receipts",
        get_receipts_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "map_receipt_to_response",
        map_receipt_mock,
    )

    result = receipt_service.get_receipts(
        db_session=db_session,
        user_id=user_id,
    )

    assert result == [
        first_response,
        second_response,
    ]

    get_receipts_mock.assert_called_once_with(
        db_session=db_session,
        user_id=user_id,
    )
    assert map_receipt_mock.call_count == 2
    map_receipt_mock.assert_any_call(first_receipt)
    map_receipt_mock.assert_any_call(second_receipt)


# Verifies that one repository receipt is converted into a response.
# This test exists to confirm get-by-id service orchestration.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace dependencies.
# Returns:
# - None.
def test_get_receipt_by_id(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    expected_response = ReceiptResponse.model_validate(receipt)

    get_receipt_mock = MagicMock(return_value=receipt)
    map_receipt_mock = MagicMock(return_value=expected_response)

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "get_receipt_by_id",
        get_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "map_receipt_to_response",
        map_receipt_mock,
    )

    result = receipt_service.get_receipt_by_id(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    assert result is expected_response

    get_receipt_mock.assert_called_once_with(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )
    map_receipt_mock.assert_called_once_with(receipt)


# Verifies that an existing owned expense passes link validation.
# This test exists to allow linking a receipt to the user's own expense.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace dependencies.
# Returns:
# - None.
def test_validate_receipt_expense_link_accepts_owned_expense(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    expense_id = uuid.uuid4()

    get_expense_mock = MagicMock()

    monkeypatch.setattr(
        receipt_service.expenses_repository,
        "get_expense_by_id",
        get_expense_mock,
    )

    result = receipt_service.validate_receipt_expense_link(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )

    assert result is None

    get_expense_mock.assert_called_once_with(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )


# Verifies that a missing or unowned expense raises a receipt-specific error.
# This test exists to hide expense repository errors from higher layers.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace dependencies.
# Returns:
# - None.
def test_validate_receipt_expense_link_raises_for_missing_expense(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    expense_id = uuid.uuid4()

    expense_error = ExpenseNotFoundError()
    get_expense_mock = MagicMock(side_effect=expense_error)

    monkeypatch.setattr(
        receipt_service.expenses_repository,
        "get_expense_by_id",
        get_expense_mock,
    )

    with pytest.raises(ReceiptExpenseNotFoundError) as error_info:
        receipt_service.validate_receipt_expense_link(
            db_session=db_session,
            expense_id=expense_id,
            user_id=user_id,
        )

    assert error_info.value.__cause__ is expense_error

    get_expense_mock.assert_called_once_with(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )


# Verifies that a non-null expense id is validated before receipt update.
# This test exists to prevent linking a receipt to another user's expense.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace dependencies.
# Returns:
# - None.
def test_update_receipt_validates_expense_link(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    expense_id = uuid.uuid4()

    receipt_data = ReceiptUpdate(
        expense_id=expense_id,
    )
    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    receipt.expense_id = expense_id

    expected_response = ReceiptResponse.model_validate(receipt)

    validate_link_mock = MagicMock()
    update_receipt_mock = MagicMock(return_value=receipt)
    map_receipt_mock = MagicMock(return_value=expected_response)

    monkeypatch.setattr(
        receipt_service,
        "validate_receipt_expense_link",
        validate_link_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "update_receipt",
        update_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "map_receipt_to_response",
        map_receipt_mock,
    )

    result = receipt_service.update_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        receipt_data=receipt_data,
        user_id=user_id,
    )

    assert result is expected_response

    validate_link_mock.assert_called_once_with(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )
    update_receipt_mock.assert_called_once_with(
        db_session=db_session,
        receipt_id=receipt_id,
        receipt_data=receipt_data,
        user_id=user_id,
    )
    map_receipt_mock.assert_called_once_with(receipt)


# Verifies that an omitted expense id does not trigger link validation.
# This test exists to keep unrelated PATCH operations independent.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace dependencies.
# Returns:
# - None.
def test_update_receipt_skips_validation_when_expense_id_is_omitted(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    receipt_data = ReceiptUpdate(
        merchant_detected="Lidl",
    )
    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    receipt.merchant_detected = "Lidl"

    expected_response = ReceiptResponse.model_validate(receipt)

    validate_link_mock = MagicMock()
    update_receipt_mock = MagicMock(return_value=receipt)
    map_receipt_mock = MagicMock(return_value=expected_response)

    monkeypatch.setattr(
        receipt_service,
        "validate_receipt_expense_link",
        validate_link_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "update_receipt",
        update_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "map_receipt_to_response",
        map_receipt_mock,
    )

    result = receipt_service.update_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        receipt_data=receipt_data,
        user_id=user_id,
    )

    assert result is expected_response

    validate_link_mock.assert_not_called()
    update_receipt_mock.assert_called_once_with(
        db_session=db_session,
        receipt_id=receipt_id,
        receipt_data=receipt_data,
        user_id=user_id,
    )


# Verifies that expense_id=null unlinks a receipt without expense validation.
# This test exists to allow explicit removal of an existing expense link.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace dependencies.
# Returns:
# - None.
def test_update_receipt_allows_expense_unlinking(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    receipt_data = ReceiptUpdate(
        expense_id=None,
    )
    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    receipt.expense_id = None

    expected_response = ReceiptResponse.model_validate(receipt)

    validate_link_mock = MagicMock()
    update_receipt_mock = MagicMock(return_value=receipt)
    map_receipt_mock = MagicMock(return_value=expected_response)

    monkeypatch.setattr(
        receipt_service,
        "validate_receipt_expense_link",
        validate_link_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "update_receipt",
        update_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "map_receipt_to_response",
        map_receipt_mock,
    )

    result = receipt_service.update_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        receipt_data=receipt_data,
        user_id=user_id,
    )

    assert result is expected_response

    assert "expense_id" in receipt_data.model_fields_set
    validate_link_mock.assert_not_called()
    update_receipt_mock.assert_called_once_with(
        db_session=db_session,
        receipt_id=receipt_id,
        receipt_data=receipt_data,
        user_id=user_id,
    )


# Verifies that repository update is skipped when expense validation fails.
# This test exists to prevent invalid receipt-to-expense links from being saved.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace dependencies.
# Returns:
# - None.
def test_update_receipt_stops_when_expense_validation_fails(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    expense_id = uuid.uuid4()

    receipt_data = ReceiptUpdate(
        expense_id=expense_id,
    )

    validate_link_mock = MagicMock(
        side_effect=ReceiptExpenseNotFoundError(),
    )
    update_receipt_mock = MagicMock()
    map_receipt_mock = MagicMock()

    monkeypatch.setattr(
        receipt_service,
        "validate_receipt_expense_link",
        validate_link_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "update_receipt",
        update_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "map_receipt_to_response",
        map_receipt_mock,
    )

    with pytest.raises(ReceiptExpenseNotFoundError):
        receipt_service.update_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            receipt_data=receipt_data,
            user_id=user_id,
        )

    validate_link_mock.assert_called_once_with(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )
    update_receipt_mock.assert_not_called()
    map_receipt_mock.assert_not_called()


# Verifies that receipt deletion removes both metadata and stored file.
# This test exists to confirm coordinated database and storage cleanup.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace dependencies.
# Returns:
# - None.
def test_delete_receipt(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )

    storage_path = receipt.storage_path

    get_receipt_mock = MagicMock(
        return_value=receipt,
    )
    delete_receipt_mock = MagicMock()
    delete_receipt_file_mock = MagicMock()

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "get_receipt_by_id",
        get_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "delete_receipt",
        delete_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_storage_service,
        "delete_receipt_file",
        delete_receipt_file_mock,
    )

    result = receipt_service.delete_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    assert result is None

    get_receipt_mock.assert_called_once_with(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    delete_receipt_mock.assert_called_once_with(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
        commit=False,
    )

    delete_receipt_file_mock.assert_called_once_with(
        storage_path=storage_path,
    )

    db_session.commit.assert_called_once_with()
    db_session.rollback.assert_not_called()

# Verifies that database deletion is rolled back
# when receipt file cleanup fails.
# This test exists to prevent receipt metadata from being committed
# when its stored file could not be removed.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace dependencies.
# Returns:
# - None.
def test_delete_receipt_rolls_back_when_storage_cleanup_fails(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )

    storage_error = ReceiptFileStorageError()

    get_receipt_mock = MagicMock(
        return_value=receipt,
    )
    delete_receipt_mock = MagicMock()
    delete_receipt_file_mock = MagicMock(
        side_effect=storage_error,
    )

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "get_receipt_by_id",
        get_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "delete_receipt",
        delete_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_storage_service,
        "delete_receipt_file",
        delete_receipt_file_mock,
    )

    with pytest.raises(
        ReceiptFileStorageError,
    ) as error_info:
        receipt_service.delete_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            user_id=user_id,
        )

    assert error_info.value is storage_error

    delete_receipt_mock.assert_called_once_with(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
        commit=False,
    )

    delete_receipt_file_mock.assert_called_once_with(
        storage_path=receipt.storage_path,
    )

    db_session.commit.assert_not_called()
    db_session.rollback.assert_called_once_with()


# Verifies that an uploaded file is stored before its receipt record is created.
# This test exists to confirm receipt upload orchestration and response forwarding.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace storage and creation dependencies.
# Returns:
# - None.
def test_upload_receipt_saves_file_and_creates_receipt(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    storage_path = (
        f"uploads/receipts/{user_id}/stored-receipt.jpg"
    )

    uploaded_file = MagicMock(spec=UploadFile)
    expected_response = MagicMock(spec=ReceiptResponse)

    save_receipt_file_mock = MagicMock(
        return_value=storage_path,
    )
    create_receipt_mock = MagicMock(
        return_value=expected_response,
    )

    monkeypatch.setattr(
        receipt_service.receipt_storage_service,
        "save_receipt_file",
        save_receipt_file_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "create_receipt",
        create_receipt_mock,
    )

    result = receipt_service.upload_receipt(
        db_session=db_session,
        uploaded_file=uploaded_file,
        user_id=user_id,
    )

    assert result is expected_response

    save_receipt_file_mock.assert_called_once_with(
        uploaded_file=uploaded_file,
        user_id=user_id,
    )

    create_receipt_mock.assert_called_once()

    create_call_arguments = create_receipt_mock.call_args.kwargs
    receipt_data = create_call_arguments["receipt_data"]

    assert create_call_arguments["db_session"] is db_session
    assert create_call_arguments["user_id"] == user_id
    assert isinstance(receipt_data, ReceiptCreate)
    assert receipt_data.storage_path == storage_path
    assert receipt_data.file_url is None


# Verifies that a stored file is removed when receipt persistence fails.
# This test exists to prevent files without matching database records.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace storage and creation dependencies.
# Returns:
# - None.
def test_upload_receipt_removes_file_when_creation_fails(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    storage_path = (
        f"uploads/receipts/{user_id}/stored-receipt.jpg"
    )

    uploaded_file = MagicMock(spec=UploadFile)
    database_error = RuntimeError("Database operation failed.")

    save_receipt_file_mock = MagicMock(
        return_value=storage_path,
    )
    create_receipt_mock = MagicMock(
        side_effect=database_error,
    )
    delete_receipt_file_mock = MagicMock()

    monkeypatch.setattr(
        receipt_service.receipt_storage_service,
        "save_receipt_file",
        save_receipt_file_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "create_receipt",
        create_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_storage_service,
        "delete_receipt_file",
        delete_receipt_file_mock,
    )

    with pytest.raises(RuntimeError) as error_info:
        receipt_service.upload_receipt(
            db_session=db_session,
            uploaded_file=uploaded_file,
            user_id=user_id,
        )

    assert error_info.value is database_error

    delete_receipt_file_mock.assert_called_once_with(
        storage_path=storage_path,
    )


# Verifies that the original database error is preserved when cleanup also fails.
# This test exists to ensure that cleanup failures do not hide the primary error.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace storage and creation dependencies.
# Returns:
# - None.
def test_upload_receipt_preserves_creation_error_when_cleanup_fails(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    storage_path = (
        f"uploads/receipts/{user_id}/stored-receipt.jpg"
    )

    uploaded_file = MagicMock(spec=UploadFile)
    database_error = RuntimeError("Database operation failed.")

    save_receipt_file_mock = MagicMock(
        return_value=storage_path,
    )
    create_receipt_mock = MagicMock(
        side_effect=database_error,
    )
    delete_receipt_file_mock = MagicMock(
        side_effect=ReceiptFileStorageError(),
    )

    monkeypatch.setattr(
        receipt_service.receipt_storage_service,
        "save_receipt_file",
        save_receipt_file_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "create_receipt",
        create_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_storage_service,
        "delete_receipt_file",
        delete_receipt_file_mock,
    )

    with pytest.raises(RuntimeError) as error_info:
        receipt_service.upload_receipt(
            db_session=db_session,
            uploaded_file=uploaded_file,
            user_id=user_id,
        )

    assert error_info.value is database_error

    delete_receipt_file_mock.assert_called_once_with(
        storage_path=storage_path,
    )


# Verifies that database creation is skipped when file storage fails.
# This test exists to prevent receipt records without stored files.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace storage dependencies.
# Returns:
# - None.
def test_upload_receipt_stops_when_file_storage_fails(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    uploaded_file = MagicMock(spec=UploadFile)

    save_receipt_file_mock = MagicMock(
        side_effect=ReceiptFileTooLargeError(),
    )
    create_receipt_mock = MagicMock()
    delete_receipt_file_mock = MagicMock()

    monkeypatch.setattr(
        receipt_service.receipt_storage_service,
        "save_receipt_file",
        save_receipt_file_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "create_receipt",
        create_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_storage_service,
        "delete_receipt_file",
        delete_receipt_file_mock,
    )

    with pytest.raises(ReceiptFileTooLargeError):
        receipt_service.upload_receipt(
            db_session=db_session,
            uploaded_file=uploaded_file,
            user_id=user_id,
        )

    create_receipt_mock.assert_not_called()
    delete_receipt_file_mock.assert_not_called()

    # Verifies that an uploaded or previously failed receipt can be processed.
# This test exists to confirm the complete successful OCR status flow.
# Parameters:
# - initial_status: receipt status before OCR processing starts.
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace service dependencies.
# Returns:
# - None.
@pytest.mark.parametrize(
    "initial_status",
    [
        "uploaded",
        "failed",
    ],
)
def test_process_receipt_saves_processed_ocr_result(
    initial_status: str,
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    storage_path = (
        f"uploads/receipts/{user_id}/receipt.jpg"
    )
    extracted_text = "LIDL\nTOTAL 24.99 EUR"
    
    parsed_data = (
        receipt_service.receipt_parser_service.ParsedReceiptData(
            merchant_detected="LIDL",
            total_amount_detected=Decimal("24.99"),
            currency_detected="EUR",
            purchase_date_detected=date(2026, 7, 31),
        )
    )

    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    receipt.status = initial_status
    receipt.storage_path = storage_path

    processed_receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    processed_receipt.status = "processed"
    processed_receipt.storage_path = storage_path
    processed_receipt.ocr_text = extracted_text

    expected_response = ReceiptResponse.model_validate(
        processed_receipt,
    )

    get_receipt_mock = MagicMock(
        return_value=receipt,
    )
    update_receipt_mock = MagicMock(
        side_effect=[
            receipt,
            processed_receipt,
        ],
    )
    extract_text_mock = MagicMock(
        return_value=extracted_text,
    )
    parse_text_mock = MagicMock(
    return_value=parsed_data,
    )
    map_receipt_mock = MagicMock(
        return_value=expected_response,
    )

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "get_receipt_by_id",
        get_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "update_receipt",
        update_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_ocr_service,
        "extract_receipt_text",
        extract_text_mock,
    )
    monkeypatch.setattr(
    receipt_service.receipt_parser_service,
    "parse_receipt_text",
    parse_text_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "map_receipt_to_response",
        map_receipt_mock,
    )

    result = receipt_service.process_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    assert result is expected_response

    get_receipt_mock.assert_called_once_with(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )
    extract_text_mock.assert_called_once_with(
        storage_path=storage_path,
    )

    parse_text_mock.assert_called_once_with(
    ocr_text=extracted_text,
    )

    assert update_receipt_mock.call_count == 2

    processing_call = update_receipt_mock.call_args_list[0]
    processing_data = processing_call.kwargs["receipt_data"]

    assert processing_call.kwargs["db_session"] is db_session
    assert processing_call.kwargs["receipt_id"] == receipt_id
    assert processing_call.kwargs["user_id"] == user_id
    assert processing_data.model_dump(
        exclude_unset=True,
    ) == {
        "status": "processing",
    }

    processed_call = update_receipt_mock.call_args_list[1]
    processed_data = processed_call.kwargs["receipt_data"]

    assert processed_data.model_dump(
    exclude_unset=True,
    ) == {
        "status": "processed",
        "ocr_text": extracted_text,
        "merchant_detected": "LIDL",
        "total_amount_detected": Decimal("24.99"),
        "currency_detected": "EUR",
        "purchase_date_detected": date(2026, 7, 31),
    }

    map_receipt_mock.assert_called_once_with(
        processed_receipt,
    )


# Verifies that receipts in final or active processing states cannot start OCR.
# This test exists to prevent invalid receipt status transitions.
# Parameters:
# - receipt_status: current receipt status.
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace service dependencies.
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
def test_process_receipt_rejects_unprocessable_status(
    receipt_status: str,
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    receipt.status = receipt_status
    receipt.storage_path = "uploads/receipts/receipt.jpg"

    get_receipt_mock = MagicMock(
        return_value=receipt,
    )
    update_receipt_mock = MagicMock()
    extract_text_mock = MagicMock()
    map_receipt_mock = MagicMock()

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "get_receipt_by_id",
        get_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "update_receipt",
        update_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_ocr_service,
        "extract_receipt_text",
        extract_text_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "map_receipt_to_response",
        map_receipt_mock,
    )

    with pytest.raises(ReceiptProcessingNotAllowedError):
        receipt_service.process_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            user_id=user_id,
        )

    update_receipt_mock.assert_not_called()
    extract_text_mock.assert_not_called()
    map_receipt_mock.assert_not_called()


# Verifies that OCR processing requires a local storage path.
# This test exists to prevent processing when the source receipt file
# is not connected to the database record.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace service dependencies.
# Returns:
# - None.
def test_process_receipt_rejects_missing_storage_path(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    receipt.status = "uploaded"
    receipt.storage_path = None

    get_receipt_mock = MagicMock(
        return_value=receipt,
    )
    update_receipt_mock = MagicMock()
    extract_text_mock = MagicMock()
    map_receipt_mock = MagicMock()

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "get_receipt_by_id",
        get_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "update_receipt",
        update_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_ocr_service,
        "extract_receipt_text",
        extract_text_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "map_receipt_to_response",
        map_receipt_mock,
    )

    with pytest.raises(ReceiptOcrFileNotFoundError):
        receipt_service.process_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            user_id=user_id,
        )

    update_receipt_mock.assert_not_called()
    extract_text_mock.assert_not_called()
    map_receipt_mock.assert_not_called()


# Verifies that OCR failures change the receipt status to failed.
# This test exists to preserve an explicit failed processing state
# when the file is missing or the OCR provider cannot extract text.
# Parameters:
# - ocr_error: OCR domain error raised during processing.
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace service dependencies.
# Returns:
# - None.
@pytest.mark.parametrize(
    "ocr_error",
    [
        ReceiptOcrFileNotFoundError(),
        ReceiptOcrProcessingError(),
    ],
)
def test_process_receipt_marks_receipt_as_failed_when_ocr_fails(
    ocr_error: Exception,
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    storage_path = (
        f"uploads/receipts/{user_id}/receipt.jpg"
    )

    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    receipt.status = "uploaded"
    receipt.storage_path = storage_path

    failed_receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    failed_receipt.status = "failed"
    failed_receipt.storage_path = storage_path

    get_receipt_mock = MagicMock(
        return_value=receipt,
    )
    update_receipt_mock = MagicMock(
        side_effect=[
            receipt,
            failed_receipt,
        ],
    )
    extract_text_mock = MagicMock(
        side_effect=ocr_error,
    )
    map_receipt_mock = MagicMock()

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "get_receipt_by_id",
        get_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "update_receipt",
        update_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_ocr_service,
        "extract_receipt_text",
        extract_text_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "map_receipt_to_response",
        map_receipt_mock,
    )

    with pytest.raises(type(ocr_error)) as error_info:
        receipt_service.process_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            user_id=user_id,
        )

    assert error_info.value is ocr_error
    assert update_receipt_mock.call_count == 2

    processing_data = (
        update_receipt_mock
        .call_args_list[0]
        .kwargs["receipt_data"]
    )
    failed_data = (
        update_receipt_mock
        .call_args_list[1]
        .kwargs["receipt_data"]
    )

    assert processing_data.model_dump(
        exclude_unset=True,
    ) == {
        "status": "processing",
    }
    assert failed_data.model_dump(
        exclude_unset=True,
    ) == {
        "status": "failed",
    }

    map_receipt_mock.assert_not_called()

 # Verifies that a processed receipt creates an expense
# and is atomically changed to confirmed.
# This test exists to confirm transaction coordination
# between expense creation and receipt update.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace service dependencies.
# Returns:
# - None.
def test_confirm_receipt_creates_expense_and_confirms_receipt(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    expense_id = uuid.uuid4()

    detected_date = date(2026, 7, 31)
    created_at = datetime(2026, 8, 1, 10, 0, 0)
    updated_at = datetime(2026, 8, 1, 10, 0, 0)

    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    receipt.status = "processed"
    receipt.expense_id = None
    receipt.merchant_detected = "LIDL"
    receipt.total_amount_detected = Decimal("24.99")
    receipt.currency_detected = "EUR"
    receipt.purchase_date_detected = detected_date

    confirmed_receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    confirmed_receipt.status = "confirmed"
    confirmed_receipt.expense_id = expense_id
    confirmed_receipt.merchant_detected = "LIDL"
    confirmed_receipt.total_amount_detected = Decimal("24.99")
    confirmed_receipt.currency_detected = "EUR"
    confirmed_receipt.purchase_date_detected = detected_date

    created_expense = ExpenseResponse(
        id=expense_id,
        user_id=user_id,
        category_id=None,
        title="LIDL",
        amount=Decimal("24.99"),
        currency="EUR",
        expense_date=detected_date,
        description=None,
        source="receipt",
        created_at=created_at,
        updated_at=updated_at,
    )

    expected_receipt_response = ReceiptResponse.model_validate(
        confirmed_receipt,
    )

    get_receipt_mock = MagicMock(
        return_value=receipt,
    )
    create_expense_mock = MagicMock(
        return_value=created_expense,
    )
    update_receipt_mock = MagicMock(
        return_value=confirmed_receipt,
    )
    map_receipt_mock = MagicMock(
        return_value=expected_receipt_response,
    )

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "get_receipt_by_id",
        get_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service.expenses_service,
        "create_expense",
        create_expense_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "update_receipt",
        update_receipt_mock,
    )
    monkeypatch.setattr(
        receipt_service,
        "map_receipt_to_response",
        map_receipt_mock,
    )

    confirmation_data = ReceiptConfirmRequest()

    result = receipt_service.confirm_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        confirmation_data=confirmation_data,
        user_id=user_id,
    )

    assert result.receipt == expected_receipt_response
    assert result.expense == created_expense

    get_receipt_mock.assert_called_once_with(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    create_expense_mock.assert_called_once()

    create_call = create_expense_mock.call_args
    expense_data = create_call.kwargs["expense_data"]

    assert create_call.kwargs["db_session"] is db_session
    assert create_call.kwargs["user_id"] == user_id
    assert create_call.kwargs["commit"] is False

    assert expense_data.model_dump() == {
        "category_id": None,
        "title": "LIDL",
        "amount": Decimal("24.99"),
        "currency": "EUR",
        "expense_date": detected_date,
        "description": None,
        "source": "receipt",
    }

    update_receipt_mock.assert_called_once()

    update_call = update_receipt_mock.call_args
    receipt_data = update_call.kwargs["receipt_data"]

    assert update_call.kwargs["db_session"] is db_session
    assert update_call.kwargs["receipt_id"] == receipt_id
    assert update_call.kwargs["user_id"] == user_id
    assert update_call.kwargs["commit"] is False

    assert receipt_data.model_dump(
        exclude_unset=True,
    ) == {
        "expense_id": expense_id,
        "status": "confirmed",
    }

    db_session.commit.assert_called_once_with()
    db_session.refresh.assert_called_once_with(
        confirmed_receipt,
    )
    db_session.rollback.assert_not_called()

    map_receipt_mock.assert_called_once_with(
        confirmed_receipt,
    )

# Verifies that user corrections override OCR-detected receipt values.
# This test exists because OCR results can be inaccurate
# and must remain editable before expense creation.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace service dependencies.
# Returns:
# - None.
def test_confirm_receipt_uses_confirmation_corrections(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    expense_id = uuid.uuid4()
    category_id = uuid.uuid4()

    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    receipt.status = "processed"
    receipt.expense_id = None
    receipt.merchant_detected = "L1DL"
    receipt.total_amount_detected = Decimal("28.99")
    receipt.currency_detected = "USD"
    receipt.purchase_date_detected = date(2026, 7, 30)

    confirmed_receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    confirmed_receipt.status = "confirmed"
    confirmed_receipt.expense_id = expense_id

    corrected_date = date(2026, 7, 31)

    created_expense = ExpenseResponse(
        id=expense_id,
        user_id=user_id,
        category_id=category_id,
        title="LIDL",
        amount=Decimal("23.99"),
        currency="EUR",
        expense_date=corrected_date,
        description="Weekly groceries",
        source="receipt",
        created_at=datetime(2026, 8, 1, 10, 0, 0),
        updated_at=datetime(2026, 8, 1, 10, 0, 0),
    )

    confirmation_data = ReceiptConfirmRequest(
        category_id=category_id,
        title="LIDL",
        amount=Decimal("23.99"),
        currency="eur",
        expense_date=corrected_date,
        description="Weekly groceries",
    )

    create_expense_mock = MagicMock(
        return_value=created_expense,
    )

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "get_receipt_by_id",
        MagicMock(return_value=receipt),
    )
    monkeypatch.setattr(
        receipt_service.expenses_service,
        "create_expense",
        create_expense_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "update_receipt",
        MagicMock(return_value=confirmed_receipt),
    )
    monkeypatch.setattr(
        receipt_service,
        "map_receipt_to_response",
        MagicMock(
            return_value=ReceiptResponse.model_validate(
                confirmed_receipt,
            )
        ),
    )

    result = receipt_service.confirm_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        confirmation_data=confirmation_data,
        user_id=user_id,
    )

    expense_data = (
        create_expense_mock
        .call_args
        .kwargs["expense_data"]
    )

    assert expense_data.category_id == category_id
    assert expense_data.title == "LIDL"
    assert expense_data.amount == Decimal("23.99")
    assert expense_data.currency == "EUR"
    assert expense_data.expense_date == corrected_date
    assert expense_data.description == "Weekly groceries"
    assert expense_data.source == "receipt"

    assert result.expense == created_expense
    db_session.commit.assert_called_once_with()
    db_session.rollback.assert_not_called()

# Verifies that a receipt cannot create more than one expense.
# This test exists to prevent duplicate expenses from repeated
# receipt confirmation requests.
# Parameters:
# - receipt_status: receipt status used by the test.
# - has_expense: whether the receipt is already linked to an expense.
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace service dependencies.
# Returns:
# - None.
@pytest.mark.parametrize(
    ("receipt_status", "has_expense"),
    [
        ("confirmed", False),
        ("processed", True),
    ],
)
def test_confirm_receipt_rejects_already_confirmed_receipt(
    receipt_status: str,
    has_expense: bool,
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    receipt.status = receipt_status
    receipt.expense_id = (
        uuid.uuid4()
        if has_expense
        else None
    )

    create_expense_mock = MagicMock()
    update_receipt_mock = MagicMock()

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "get_receipt_by_id",
        MagicMock(return_value=receipt),
    )
    monkeypatch.setattr(
        receipt_service.expenses_service,
        "create_expense",
        create_expense_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "update_receipt",
        update_receipt_mock,
    )

    with pytest.raises(ReceiptAlreadyConfirmedError):
        receipt_service.confirm_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            confirmation_data=ReceiptConfirmRequest(),
            user_id=user_id,
        )

    create_expense_mock.assert_not_called()
    update_receipt_mock.assert_not_called()
    db_session.commit.assert_not_called()
    db_session.rollback.assert_not_called()

    # Verifies that only processed receipts can be confirmed.
# This test exists to prevent expense creation from incomplete
# or failed receipt processing results.
# Parameters:
# - receipt_status: receipt status before confirmation.
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace service dependencies.
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
def test_confirm_receipt_rejects_unconfirmable_status(
    receipt_status: str,
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    receipt.status = receipt_status
    receipt.expense_id = None

    create_expense_mock = MagicMock()
    update_receipt_mock = MagicMock()

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "get_receipt_by_id",
        MagicMock(return_value=receipt),
    )
    monkeypatch.setattr(
        receipt_service.expenses_service,
        "create_expense",
        create_expense_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "update_receipt",
        update_receipt_mock,
    )

    with pytest.raises(ReceiptConfirmationNotAllowedError):
        receipt_service.confirm_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            confirmation_data=ReceiptConfirmRequest(),
            user_id=user_id,
        )

    create_expense_mock.assert_not_called()
    update_receipt_mock.assert_not_called()
    db_session.commit.assert_not_called()
    db_session.rollback.assert_not_called()

# Verifies that confirmation requires all mandatory expense values.
# This test exists to prevent invalid expenses from being created
# when OCR results and user corrections are incomplete.
# Parameters:
# - missing_field: required detected receipt field removed by the test.
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace service dependencies.
# Returns:
# - None.
@pytest.mark.parametrize(
    "missing_field",
    [
        "merchant_detected",
        "total_amount_detected",
        "currency_detected",
        "purchase_date_detected",
    ],
)
def test_confirm_receipt_rejects_missing_required_data(
    missing_field: str,
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    receipt.status = "processed"
    receipt.expense_id = None
    receipt.merchant_detected = "LIDL"
    receipt.total_amount_detected = Decimal("24.99")
    receipt.currency_detected = "EUR"
    receipt.purchase_date_detected = date(2026, 7, 31)

    setattr(
        receipt,
        missing_field,
        None,
    )

    create_expense_mock = MagicMock()
    update_receipt_mock = MagicMock()

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "get_receipt_by_id",
        MagicMock(return_value=receipt),
    )
    monkeypatch.setattr(
        receipt_service.expenses_service,
        "create_expense",
        create_expense_mock,
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "update_receipt",
        update_receipt_mock,
    )

    with pytest.raises(ReceiptConfirmationDataMissingError):
        receipt_service.confirm_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            confirmation_data=ReceiptConfirmRequest(),
            user_id=user_id,
        )

    create_expense_mock.assert_not_called()
    update_receipt_mock.assert_not_called()
    db_session.commit.assert_not_called()
    db_session.rollback.assert_not_called()

# Verifies that receipt update failures roll back expense creation.
# This test exists to prevent orphan expenses when confirmation
# cannot complete atomically.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to replace service dependencies.
# Returns:
# - None.
def test_confirm_receipt_rolls_back_when_receipt_update_fails(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    expense_id = uuid.uuid4()

    receipt = build_receipt_model(
        user_id=user_id,
        receipt_id=receipt_id,
    )
    receipt.status = "processed"
    receipt.expense_id = None
    receipt.merchant_detected = "LIDL"
    receipt.total_amount_detected = Decimal("24.99")
    receipt.currency_detected = "EUR"
    receipt.purchase_date_detected = date(2026, 7, 31)

    created_expense = ExpenseResponse(
        id=expense_id,
        user_id=user_id,
        category_id=None,
        title="LIDL",
        amount=Decimal("24.99"),
        currency="EUR",
        expense_date=date(2026, 7, 31),
        description=None,
        source="receipt",
        created_at=datetime(2026, 8, 1, 10, 0, 0),
        updated_at=datetime(2026, 8, 1, 10, 0, 0),
    )

    update_error = RuntimeError(
        "Receipt update failed.",
    )

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "get_receipt_by_id",
        MagicMock(return_value=receipt),
    )
    monkeypatch.setattr(
        receipt_service.expenses_service,
        "create_expense",
        MagicMock(return_value=created_expense),
    )
    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "update_receipt",
        MagicMock(side_effect=update_error),
    )

    with pytest.raises(RuntimeError) as error_info:
        receipt_service.confirm_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            confirmation_data=ReceiptConfirmRequest(),
            user_id=user_id,
        )

    assert error_info.value is update_error

    db_session.rollback.assert_called_once_with()
    db_session.commit.assert_not_called()
    db_session.refresh.assert_not_called()