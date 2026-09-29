from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.database_session import SessionLocal
from app.modules.accounts import (
    account_repository,
    account_transaction_repository,
    account_transfer_repository,
)
from app.modules.accounts.account_schemas import AccountCreate
from app.modules.accounts.account_transaction_models import AccountTransactionModel
from app.modules.accounts.account_transfer_errors import AccountTransferNotFoundError
from app.modules.accounts.account_transfer_models import AccountTransferModel

POSTED_AT = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)


def _create_accounts(db_session, user_id):
    source = account_repository.create_account(
        db_session=db_session,
        account_data=AccountCreate(name="Checking", type="checking", currency="EUR"),
        user_id=user_id,
    )
    destination = account_repository.create_account(
        db_session=db_session,
        account_data=AccountCreate(name="Savings", type="savings", currency="EUR"),
        user_id=user_id,
    )
    return source, destination


def _create_planned_transfer(db_session, user_id, source, destination, client_request_id=None):
    return account_transfer_repository.create_account_transfer(
        db_session=db_session,
        user_id=user_id,
        client_request_id=client_request_id or uuid4(),
        source_account_id=source.id,
        destination_account_id=destination.id,
        amount=Decimal("300.00"),
        currency="EUR",
        status="planned",
        planned_date=date(2026, 10, 15),
        effective_date=None,
        description=None,
        posted_at=None,
    )


# Tests that create_account_transfer persists exactly the given values
# once the caller commits.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the committed row matches the arguments.
def test_create_account_transfer_persists_given_values(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    client_request_id = uuid4()

    try:
        source, destination = _create_accounts(db_session, user_id)

        transfer = account_transfer_repository.create_account_transfer(
            db_session=db_session,
            user_id=user_id,
            client_request_id=client_request_id,
            source_account_id=source.id,
            destination_account_id=destination.id,
            amount=Decimal("300.00"),
            currency="EUR",
            status="posted",
            planned_date=None,
            effective_date=date(2026, 9, 28),
            description="Move to savings",
            posted_at=POSTED_AT,
        )
        db_session.commit()
        db_session.refresh(transfer)

        assert transfer.id is not None
        assert transfer.user_id == user_id
        assert transfer.client_request_id == client_request_id
        assert transfer.source_account_id == source.id
        assert transfer.destination_account_id == destination.id
        assert transfer.amount == Decimal("300.00")
        assert transfer.currency == "EUR"
        assert transfer.status == "posted"
        assert transfer.planned_date is None
        assert transfer.effective_date == date(2026, 9, 28)
        assert transfer.description == "Move to savings"
        assert transfer.posted_at == POSTED_AT
    finally:
        db_session.close()


# Tests that create_account_transfer only flushes: rolling back the
# caller's transaction leaves no row behind.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if no transfer exists after rollback.
def test_create_account_transfer_does_not_commit(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source, destination = _create_accounts(db_session, user_id)
        db_session.commit()

        transfer = _create_planned_transfer(db_session, user_id, source, destination)
        assert transfer.id is not None

        db_session.rollback()

        assert db_session.query(AccountTransferModel).count() == 0
    finally:
        db_session.close()


# Tests that get_account_transfer_by_client_request_id finds the user's
# transfer by key and never returns another user's transfer with the same
# key.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the lookup is correct and user-scoped.
def test_get_account_transfer_by_client_request_id_is_user_scoped(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()
    client_request_id = uuid4()

    try:
        source, destination = _create_accounts(db_session, user_id)
        other_source, other_destination = _create_accounts(db_session, other_user_id)
        own = _create_planned_transfer(
            db_session, user_id, source, destination, client_request_id,
        )
        others = _create_planned_transfer(
            db_session, other_user_id, other_source, other_destination, client_request_id,
        )
        db_session.commit()

        found = account_transfer_repository.get_account_transfer_by_client_request_id(
            db_session=db_session, user_id=user_id, client_request_id=client_request_id,
        )
        assert found is not None
        assert found.id == own.id
        assert found.id != others.id

        missing = account_transfer_repository.get_account_transfer_by_client_request_id(
            db_session=db_session, user_id=user_id, client_request_id=uuid4(),
        )
        assert missing is None
    finally:
        db_session.close()


# Tests that get_account_transfer_by_id_for_update returns the owned
# transfer and raises AccountTransferNotFoundError for a missing id or
# another user's transfer.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if ownership is enforced at the query level.
def test_get_account_transfer_by_id_for_update_enforces_ownership(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        source, destination = _create_accounts(db_session, user_id)
        transfer = _create_planned_transfer(db_session, user_id, source, destination)
        db_session.commit()

        locked = account_transfer_repository.get_account_transfer_by_id_for_update(
            db_session=db_session, transfer_id=transfer.id, user_id=user_id,
        )
        assert locked.id == transfer.id
        db_session.rollback()

        with pytest.raises(AccountTransferNotFoundError):
            account_transfer_repository.get_account_transfer_by_id_for_update(
                db_session=db_session, transfer_id=transfer.id, user_id=other_user_id,
            )

        with pytest.raises(AccountTransferNotFoundError):
            account_transfer_repository.get_account_transfer_by_id_for_update(
                db_session=db_session, transfer_id=uuid4(), user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that delete_locked_account_transfer removes a planned transfer
# without touching the ledger (a planned transfer has no projections).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the transfer is gone and the ledger is empty.
def test_delete_locked_account_transfer_planned(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source, destination = _create_accounts(db_session, user_id)
        transfer = _create_planned_transfer(db_session, user_id, source, destination)
        db_session.commit()

        locked = account_transfer_repository.get_account_transfer_by_id_for_update(
            db_session=db_session, transfer_id=transfer.id, user_id=user_id,
        )
        account_transfer_repository.delete_locked_account_transfer(
            db_session=db_session, transfer_model=locked,
        )
        db_session.commit()

        assert db_session.query(AccountTransferModel).count() == 0
        assert db_session.query(AccountTransactionModel).count() == 0
    finally:
        db_session.close()


# Tests that delete_locked_account_transfer on a posted transfer removes
# both ledger projections via ON DELETE CASCADE, restoring both balances.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the transfer and its projections are gone
#   and both balances are back to 0.00.
def test_delete_locked_account_transfer_posted_cascades_projections(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source, destination = _create_accounts(db_session, user_id)
        transfer = account_transfer_repository.create_account_transfer(
            db_session=db_session,
            user_id=user_id,
            client_request_id=uuid4(),
            source_account_id=source.id,
            destination_account_id=destination.id,
            amount=Decimal("300.00"),
            currency="EUR",
            status="posted",
            planned_date=None,
            effective_date=date(2026, 9, 28),
            description=None,
            posted_at=POSTED_AT,
        )
        account_transaction_repository.create_transfer_projections(
            db_session=db_session, transfer=transfer,
        )
        db_session.commit()
        assert db_session.query(AccountTransactionModel).count() == 2

        locked = account_transfer_repository.get_account_transfer_by_id_for_update(
            db_session=db_session, transfer_id=transfer.id, user_id=user_id,
        )
        account_transfer_repository.delete_locked_account_transfer(
            db_session=db_session, transfer_model=locked,
        )
        db_session.commit()
        db_session.expire_all()

        assert db_session.query(AccountTransferModel).count() == 0
        assert db_session.query(AccountTransactionModel).count() == 0
        for account in (source, destination):
            balance = account_transaction_repository.calculate_ledger_balance(
                db_session=db_session, account_id=account.id, user_id=user_id,
            )
            assert balance == Decimal("0.00")
    finally:
        db_session.close()
