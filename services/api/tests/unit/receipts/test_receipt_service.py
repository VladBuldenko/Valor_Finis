import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock
from typing import Optional

import pytest
from sqlalchemy.orm import Session

from app.modules.expenses.expenses_errors import ExpenseNotFoundError
from app.modules.receipts import receipt_service
from app.modules.receipts.receipt_errors import ReceiptExpenseNotFoundError
from app.modules.receipts.receipt_models import ReceiptModel
from app.modules.receipts.receipt_schemas import (
    ReceiptCreate,
    ReceiptResponse,
    ReceiptUpdate,
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


# Verifies that receipt deletion delegates to the repository.
# This test exists to confirm delete service orchestration.
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

    delete_receipt_mock = MagicMock()

    monkeypatch.setattr(
        receipt_service.receipt_repository,
        "delete_receipt",
        delete_receipt_mock,
    )

    result = receipt_service.delete_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    assert result is None

    delete_receipt_mock.assert_called_once_with(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )