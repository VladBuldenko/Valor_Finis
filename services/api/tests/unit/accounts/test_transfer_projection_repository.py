from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.database_session import SessionLocal
from app.modules.accounts import (
    account_repository,
    account_transaction_repository,
    account_transfer_repository,
)
from app.modules.accounts.account_schemas import AccountCreate
from app.modules.accounts.account_transaction_models import AccountTransactionModel

POSTED_AT = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)


def _create_account(db_session, user_id, name):
    return account_repository.create_account(
        db_session=db_session,
        account_data=AccountCreate(name=name, type="checking", currency="EUR"),
        user_id=user_id,
    )


# Creates (flushes, does not commit) a transfer between two fresh EUR
# Accounts and returns (transfer, source, destination). status controls
# the lifecycle shape: "posted" is an immediately posted transfer,
# "planned" a planned one.
def _create_transfer(db_session, user_id, status):
    source = _create_account(db_session, user_id, "Checking")
    destination = _create_account(db_session, user_id, "Savings")

    is_posted = status == "posted"
    transfer = account_transfer_repository.create_account_transfer(
        db_session=db_session,
        user_id=user_id,
        client_request_id=uuid4(),
        source_account_id=source.id,
        destination_account_id=destination.id,
        amount=Decimal("300.00"),
        currency="EUR",
        status=status,
        planned_date=None if is_posted else date(2026, 10, 15),
        effective_date=date(2026, 9, 28) if is_posted else None,
        description="Move to savings",
        posted_at=POSTED_AT if is_posted else None,
    )
    return transfer, source, destination


# Tests that create_transfer_projections creates exactly two rows for a
# posted transfer: a debit on the source Account and a credit on the
# destination Account, with kind="transfer", the transfer's amount and id,
# transaction_date = effective_date, and description NULL.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the two committed rows match exactly.
def test_create_transfer_projections_creates_debit_and_credit(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        transfer, source, destination = _create_transfer(db_session, user_id, "posted")

        source_debit, destination_credit = (
            account_transaction_repository.create_transfer_projections(
                db_session=db_session, transfer=transfer,
            )
        )
        db_session.commit()

        rows = (
            db_session.query(AccountTransactionModel)
            .filter(AccountTransactionModel.transfer_id == transfer.id)
            .all()
        )
        assert len(rows) == 2
        assert {row.id for row in rows} == {source_debit.id, destination_credit.id}

        assert source_debit.account_id == source.id
        assert source_debit.direction == "debit"
        assert destination_credit.account_id == destination.id
        assert destination_credit.direction == "credit"

        for row in (source_debit, destination_credit):
            assert row.kind == "transfer"
            assert row.user_id == user_id
            assert row.transfer_id == transfer.id
            assert row.amount == Decimal("300.00")
            assert row.transaction_date == date(2026, 9, 28)
            assert row.description is None
            assert row.income_id is None
            assert row.expense_id is None
    finally:
        db_session.close()


# Tests that the projections move balances exactly as a transfer should:
# the source Account is debited and the destination Account credited by
# the same amount, so the sum of both balances is unchanged.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the ledger balances are -300.00 and +300.00.
def test_create_transfer_projections_moves_ledger_balances(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        transfer, source, destination = _create_transfer(db_session, user_id, "posted")
        account_transaction_repository.create_transfer_projections(
            db_session=db_session, transfer=transfer,
        )
        db_session.commit()

        source_balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=source.id, user_id=user_id,
        )
        destination_balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=destination.id, user_id=user_id,
        )
        assert source_balance == Decimal("-300.00")
        assert destination_balance == Decimal("300.00")
        assert source_balance + destination_balance == Decimal("0.00")
    finally:
        db_session.close()


# Tests that a planned transfer is refused by the status guard before any
# row is added - a planned transfer must never receive ledger projections.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if ValueError is raised and no transfer row
#   exists in the session or the database.
def test_create_transfer_projections_rejects_planned_transfer(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        transfer, _, _ = _create_transfer(db_session, user_id, "planned")

        with pytest.raises(ValueError):
            account_transaction_repository.create_transfer_projections(
                db_session=db_session, transfer=transfer,
            )

        db_session.commit()

        count = (
            db_session.query(AccountTransactionModel)
            .filter(AccountTransactionModel.transfer_id == transfer.id)
            .count()
        )
        assert count == 0
    finally:
        db_session.close()


# Tests that create_transfer_projections only flushes and never commits:
# rolling back the caller's transaction must remove the canonical
# transfer and both projections together.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if nothing persists after rollback.
def test_create_transfer_projections_does_not_commit(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        transfer, _, _ = _create_transfer(db_session, user_id, "posted")
        transfer_id = transfer.id
        account_transaction_repository.create_transfer_projections(
            db_session=db_session, transfer=transfer,
        )

        db_session.rollback()

        verify_session = SessionLocal()
        try:
            count = (
                verify_session.query(AccountTransactionModel)
                .filter(AccountTransactionModel.transfer_id == transfer_id)
                .count()
            )
            assert count == 0
        finally:
            verify_session.close()
    finally:
        db_session.close()


# Tests that calling create_transfer_projections twice for the same
# transfer fails on flush (UNIQUE(transfer_id, direction)) rather than
# silently creating a second pair.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the second call raises IntegrityError.
def test_create_transfer_projections_twice_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        transfer, _, _ = _create_transfer(db_session, user_id, "posted")
        account_transaction_repository.create_transfer_projections(
            db_session=db_session, transfer=transfer,
        )

        with pytest.raises(IntegrityError):
            account_transaction_repository.create_transfer_projections(
                db_session=db_session, transfer=transfer,
            )

        db_session.rollback()
    finally:
        db_session.close()
