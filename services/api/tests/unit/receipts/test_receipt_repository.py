import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.modules.receipts import receipt_repository
from app.modules.receipts.receipt_errors import ReceiptNotFoundError
from app.modules.receipts.receipt_models import ReceiptModel
from app.modules.receipts.receipt_schemas import ReceiptCreate, ReceiptUpdate


# Creates a mocked SQLAlchemy session for repository unit tests.
# This fixture exists to isolate repository behavior from the real database.
# Parameters:
# - None.
# Returns:
# - Mocked SQLAlchemy Session instance.
@pytest.fixture()
def db_session() -> MagicMock:
    return MagicMock(spec=Session)


# Verifies that a receipt is created and persisted with the uploaded status.
# This test exists to confirm that receipt creation uses authenticated user data
# and performs the expected SQLAlchemy session operations.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# Returns:
# - None.
def test_create_receipt(db_session: MagicMock) -> None:
    user_id = uuid.uuid4()
    receipt_data = ReceiptCreate(
        storage_path=f"receipts/{user_id}/receipt-1.jpg",
    )

    result = receipt_repository.create_receipt(
        db_session=db_session,
        receipt_data=receipt_data,
        user_id=user_id,
    )

    assert isinstance(result, ReceiptModel)
    assert result.user_id == user_id
    assert result.file_url is None
    assert result.storage_path == f"receipts/{user_id}/receipt-1.jpg"
    assert result.status == "uploaded"

    db_session.add.assert_called_once_with(result)
    db_session.commit.assert_called_once_with()
    db_session.refresh.assert_called_once_with(result)


# Verifies that only receipts belonging to the requested user are returned.
# This test exists to confirm user isolation and newest-first ordering.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# Returns:
# - None.
def test_get_receipts_returns_user_receipts(
    db_session: MagicMock,
) -> None:
    user_id = uuid.uuid4()

    first_receipt = ReceiptModel(
        user_id=user_id,
        storage_path="receipts/receipt-1.jpg",
        status="uploaded",
    )
    second_receipt = ReceiptModel(
        user_id=user_id,
        storage_path="receipts/receipt-2.jpg",
        status="processed",
    )

    query_mock = db_session.query.return_value
    filtered_query_mock = query_mock.filter.return_value
    ordered_query_mock = filtered_query_mock.order_by.return_value
    ordered_query_mock.all.return_value = [
        second_receipt,
        first_receipt,
    ]

    result = receipt_repository.get_receipts(
        db_session=db_session,
        user_id=user_id,
    )

    assert result == [
        second_receipt,
        first_receipt,
    ]

    db_session.query.assert_called_once_with(ReceiptModel)
    query_mock.filter.assert_called_once()
    filtered_query_mock.order_by.assert_called_once()
    ordered_query_mock.all.assert_called_once_with()

    filter_expression = query_mock.filter.call_args.args[0]

    assert filter_expression.left.name == "user_id"
    assert filter_expression.right.value == user_id


# Verifies that a receipt is returned when both receipt id and user id match.
# This test exists to confirm repository-level ownership filtering.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# Returns:
# - None.
def test_get_receipt_by_id_returns_owned_receipt(
    db_session: MagicMock,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    expected_receipt = ReceiptModel(
        id=receipt_id,
        user_id=user_id,
        storage_path="receipts/receipt-1.jpg",
        status="uploaded",
    )

    query_mock = db_session.query.return_value
    filtered_query_mock = query_mock.filter.return_value
    filtered_query_mock.first.return_value = expected_receipt

    result = receipt_repository.get_receipt_by_id(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    assert result is expected_receipt

    db_session.query.assert_called_once_with(ReceiptModel)
    query_mock.filter.assert_called_once()
    filtered_query_mock.first.assert_called_once_with()

    filter_expressions = query_mock.filter.call_args.args

    assert len(filter_expressions) == 2

    assert filter_expressions[0].left.name == "id"
    assert filter_expressions[0].right.value == receipt_id

    assert filter_expressions[1].left.name == "user_id"
    assert filter_expressions[1].right.value == user_id


# Verifies that a missing or unowned receipt raises ReceiptNotFoundError.
# This test exists to ensure that the repository does not expose receipts
# that do not belong to the authenticated user.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# Returns:
# - None.
def test_get_receipt_by_id_raises_when_receipt_not_found(
    db_session: MagicMock,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    query_mock = db_session.query.return_value
    filtered_query_mock = query_mock.filter.return_value
    filtered_query_mock.first.return_value = None

    with pytest.raises(ReceiptNotFoundError):
        receipt_repository.get_receipt_by_id(
            db_session=db_session,
            receipt_id=receipt_id,
            user_id=user_id,
        )

    db_session.commit.assert_not_called()


# Verifies that explicitly provided receipt fields are updated.
# This test exists to confirm PATCH behavior and receipt-to-expense unlinking.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to isolate get_receipt_by_id.
# Returns:
# - None.
def test_update_receipt_updates_provided_fields(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    linked_expense_id = uuid.uuid4()

    existing_receipt = ReceiptModel(
        id=receipt_id,
        user_id=user_id,
        storage_path="receipts/receipt-1.jpg",
        status="uploaded",
        expense_id=linked_expense_id,
    )

    receipt_data = MagicMock(spec=ReceiptUpdate)
    receipt_data.model_dump.return_value = {
        "status": "processed",
        "merchant_detected": "Lidl",
        "expense_id": None,
    }

    get_receipt_by_id_mock = MagicMock(
        return_value=existing_receipt,
    )

    monkeypatch.setattr(
        receipt_repository,
        "get_receipt_by_id",
        get_receipt_by_id_mock,
    )

    result = receipt_repository.update_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        receipt_data=receipt_data,
        user_id=user_id,
    )

    assert result is existing_receipt
    assert result.status == "processed"
    assert result.merchant_detected == "Lidl"
    assert result.expense_id is None

    get_receipt_by_id_mock.assert_called_once_with(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )
    receipt_data.model_dump.assert_called_once_with(
        exclude_unset=True,
    )

    db_session.commit.assert_called_once_with()
    db_session.refresh.assert_called_once_with(existing_receipt)


# Verifies that updating a missing receipt propagates ReceiptNotFoundError.
# This test exists to ensure that no database write is performed when
# the requested receipt cannot be found.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to isolate get_receipt_by_id.
# Returns:
# - None.
def test_update_receipt_raises_when_receipt_not_found(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    receipt_data = MagicMock(spec=ReceiptUpdate)

    get_receipt_by_id_mock = MagicMock(
        side_effect=ReceiptNotFoundError(),
    )

    monkeypatch.setattr(
        receipt_repository,
        "get_receipt_by_id",
        get_receipt_by_id_mock,
    )

    with pytest.raises(ReceiptNotFoundError):
        receipt_repository.update_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            receipt_data=receipt_data,
            user_id=user_id,
        )

    receipt_data.model_dump.assert_not_called()
    db_session.commit.assert_not_called()
    db_session.refresh.assert_not_called()


# Verifies that an owned receipt is deleted from the database.
# This test exists to confirm deletion behavior and ownership lookup.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to isolate get_receipt_by_id.
# Returns:
# - None.
def test_delete_receipt_deletes_owned_receipt(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    existing_receipt = ReceiptModel(
        id=receipt_id,
        user_id=user_id,
        storage_path="receipts/receipt-1.jpg",
        status="uploaded",
    )

    get_receipt_by_id_mock = MagicMock(
        return_value=existing_receipt,
    )

    monkeypatch.setattr(
        receipt_repository,
        "get_receipt_by_id",
        get_receipt_by_id_mock,
    )

    result = receipt_repository.delete_receipt(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    assert result is None

    get_receipt_by_id_mock.assert_called_once_with(
        db_session=db_session,
        receipt_id=receipt_id,
        user_id=user_id,
    )

    db_session.delete.assert_called_once_with(existing_receipt)
    db_session.commit.assert_called_once_with()


# Verifies that deleting a missing receipt propagates ReceiptNotFoundError.
# This test exists to ensure that delete and commit are not called when
# the requested receipt cannot be found.
# Parameters:
# - db_session: mocked SQLAlchemy session.
# - monkeypatch: pytest fixture used to isolate get_receipt_by_id.
# Returns:
# - None.
def test_delete_receipt_raises_when_receipt_not_found(
    db_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    get_receipt_by_id_mock = MagicMock(
        side_effect=ReceiptNotFoundError(),
    )

    monkeypatch.setattr(
        receipt_repository,
        "get_receipt_by_id",
        get_receipt_by_id_mock,
    )

    with pytest.raises(ReceiptNotFoundError):
        receipt_repository.delete_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            user_id=user_id,
        )

    db_session.delete.assert_not_called()
    db_session.commit.assert_not_called()

    # Verifies that receipt deletion can be flushed without committing.
    # This test exists to allow the service layer to coordinate
    # database deletion with external storage cleanup in one operation.
    # Parameters:
    # - db_session: mocked SQLAlchemy session.
    # - monkeypatch: pytest fixture used to isolate get_receipt_by_id.
    # Returns:
    # - None.
    def test_delete_receipt_flushes_without_commit_when_commit_disabled(
        db_session: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user_id = uuid.uuid4()
        receipt_id = uuid.uuid4()

        existing_receipt = ReceiptModel(
            id=receipt_id,
            user_id=user_id,
            storage_path="receipts/receipt-1.jpg",
            status="uploaded",
        )

        get_receipt_by_id_mock = MagicMock(
            return_value=existing_receipt,
        )

        monkeypatch.setattr(
            receipt_repository,
            "get_receipt_by_id",
            get_receipt_by_id_mock,
        )

        result = receipt_repository.delete_receipt(
            db_session=db_session,
            receipt_id=receipt_id,
            user_id=user_id,
            commit=False,
        )

        assert result is None

        get_receipt_by_id_mock.assert_called_once_with(
            db_session=db_session,
            receipt_id=receipt_id,
            user_id=user_id,
        )

        db_session.delete.assert_called_once_with(
            existing_receipt,
        )

        db_session.flush.assert_called_once_with()
        db_session.commit.assert_not_called()