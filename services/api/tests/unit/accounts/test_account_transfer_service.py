from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.database_session import SessionLocal
from app.modules.accounts import (
    account_repository,
    account_service,
    account_transaction_repository,
    account_transfer_repository,
    account_transfer_service,
)
from app.modules.accounts.account_errors import (
    AccountArchivedError,
    AccountNotFoundError,
)
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_schemas import AccountCreate, AccountUpdate
from app.modules.accounts.account_transaction_models import AccountTransactionModel
from app.modules.accounts.account_transfer_errors import (
    AccountTransferCurrencyMismatchError,
    AccountTransferIdempotencyConflictError,
)
from app.modules.accounts.account_transfer_models import AccountTransferModel
from app.modules.accounts.account_transfer_schemas import AccountTransferCreate

AS_OF = date(2026, 9, 28)


def _create_account(db_session, user_id, name, currency="EUR", opening_balance=None) -> AccountModel:
    account = account_repository.create_account(
        db_session=db_session,
        account_data=AccountCreate(name=name, type="checking", currency=currency),
        user_id=user_id,
    )

    if opening_balance is not None:
        account_transaction_repository.create_transaction(
            db_session=db_session,
            account_id=account.id,
            user_id=user_id,
            kind="opening_balance",
            direction="credit",
            amount=Decimal(opening_balance),
            transaction_date=date(2026, 9, 1),
            description=None,
        )

    return account


def _request(source, destination, transfer_date, amount="300.00", key=None, description=None):
    return AccountTransferCreate(
        client_request_id=key or uuid4(),
        source_account_id=source.id,
        destination_account_id=destination.id,
        amount=Decimal(amount),
        transfer_date=transfer_date,
        description=description,
    )


def _balance(db_session, account, user_id) -> Decimal:
    return account_transaction_repository.calculate_ledger_balance(
        db_session=db_session, account_id=account.id, user_id=user_id,
    )


def _transfer_row_counts(user_id) -> tuple:
    verify_session = SessionLocal()
    try:
        transfers = (
            verify_session.query(AccountTransferModel)
            .filter(AccountTransferModel.user_id == user_id)
            .count()
        )
        legs = (
            verify_session.query(AccountTransactionModel)
            .filter(
                AccountTransactionModel.user_id == user_id,
                AccountTransactionModel.kind == "transfer",
            )
            .count()
        )
        return transfers, legs
    finally:
        verify_session.close()


# Replaces the key lookup so its first `misses` calls return None - the
# deterministic stand-in for "a concurrent same-key request had not
# committed yet when this request looked" - and later calls hit the database.
def _patch_lookup_misses(monkeypatch, misses: int) -> None:
    real_lookup = account_transfer_repository.get_account_transfer_by_client_request_id
    state = {"calls": 0}

    def lookup(**kwargs) -> Optional[AccountTransferModel]:
        state["calls"] += 1
        if state["calls"] <= misses:
            return None
        return real_lookup(**kwargs)

    monkeypatch.setattr(
        account_transfer_repository, "get_account_transfer_by_client_request_id", lookup,
    )


# Tests the server-date classification boundary: a transfer dated before
# or on as_of is created posted with effective_date, planned_date NULL, a
# timezone-aware posted_at, and both projections; a transfer dated after
# as_of is created planned with no ledger rows.
# Parameters:
# - transfer_date: the request date under test.
# - expected_status: planned or posted.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if status, dates, and ledger rows match.
@pytest.mark.parametrize(
    ("transfer_date", "expected_status"),
    [
        (date(2026, 9, 27), "posted"),
        (date(2026, 9, 28), "posted"),
        (date(2026, 9, 29), "planned"),
    ],
)
def test_create_classifies_transfer_date_against_as_of(
    transfer_date: date, expected_status: str, clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking", opening_balance="1000.00")
        destination = _create_account(db_session, user_id, "Savings")

        result = account_transfer_service.create_account_transfer(
            db_session=db_session,
            transfer_data=_request(source, destination, transfer_date),
            user_id=user_id,
            as_of=AS_OF,
        )

        assert result.created is True
        transfer = result.transfer
        assert transfer.status == expected_status
        assert transfer.currency == "EUR"

        if expected_status == "posted":
            assert transfer.planned_date is None
            assert transfer.effective_date == transfer_date
            assert transfer.posted_at is not None
            assert transfer.posted_at.tzinfo is not None
            assert _transfer_row_counts(user_id) == (1, 2)
            assert _balance(db_session, source, user_id) == Decimal("700.00")
            assert _balance(db_session, destination, user_id) == Decimal("300.00")
        else:
            assert transfer.planned_date == transfer_date
            assert transfer.effective_date is None
            assert transfer.posted_at is None
            assert _transfer_row_counts(user_id) == (1, 0)
            assert _balance(db_session, source, user_id) == Decimal("1000.00")
            assert _balance(db_session, destination, user_id) == Decimal("0.00")
    finally:
        db_session.close()


# Tests that a posted transfer may make the source balance negative - there
# is no insufficient-funds rule.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the transfer is created and the balance is -300.00.
def test_create_posted_transfer_allows_negative_source_balance(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking")
        destination = _create_account(db_session, user_id, "Savings")

        account_transfer_service.create_account_transfer(
            db_session=db_session,
            transfer_data=_request(source, destination, AS_OF),
            user_id=user_id,
            as_of=AS_OF,
        )

        assert _balance(db_session, source, user_id) == Decimal("-300.00")
        assert _balance(db_session, destination, user_id) == Decimal("300.00")
    finally:
        db_session.close()


# Tests atomicity: a failure after the canonical transfer is flushed but
# before commit (injected into create_transfer_projections) leaves no
# transfer and no projection behind.
# Parameters:
# - monkeypatch: pytest fixture used to inject the failure.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the error propagates and nothing persists.
def test_create_posted_transfer_rolls_back_everything_on_failure(
    monkeypatch, clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking", opening_balance="1000.00")
        destination = _create_account(db_session, user_id, "Savings")
        real_create_projections = account_transaction_repository.create_transfer_projections

        def create_one_side_then_fail(db_session, transfer):
            real_create_projections(db_session=db_session, transfer=transfer)
            raise RuntimeError("injected failure after projections were flushed")

        monkeypatch.setattr(
            account_transaction_repository,
            "create_transfer_projections",
            create_one_side_then_fail,
        )

        with pytest.raises(RuntimeError):
            account_transfer_service.create_account_transfer(
                db_session=db_session,
                transfer_data=_request(source, destination, AS_OF),
                user_id=user_id,
                as_of=AS_OF,
            )

        assert _transfer_row_counts(user_id) == (0, 0)
        assert _balance(db_session, source, user_id) == Decimal("1000.00")
    finally:
        db_session.close()


# Tests that an IntegrityError other than the create-idempotency unique
# violation is never swallowed as a replay: it propagates and nothing
# persists.
# Parameters:
# - monkeypatch: pytest fixture used to inject the failure.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if IntegrityError propagates and nothing persists.
def test_create_does_not_treat_other_integrity_errors_as_replay(
    monkeypatch, clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking")
        destination = _create_account(db_session, user_id, "Savings")

        def raise_other_integrity_error(db_session, transfer):
            raise IntegrityError("INSERT ...", {}, Exception("some other constraint"))

        monkeypatch.setattr(
            account_transaction_repository,
            "create_transfer_projections",
            raise_other_integrity_error,
        )

        with pytest.raises(IntegrityError):
            account_transfer_service.create_account_transfer(
                db_session=db_session,
                transfer_data=_request(source, destination, AS_OF),
                user_id=user_id,
                as_of=AS_OF,
            )

        assert _transfer_row_counts(user_id) == (0, 0)
    finally:
        db_session.close()


# Tests step 8 of the idempotency algorithm deterministically: both lookups
# miss (as if a concurrent same-key request had not committed yet), so the
# INSERT hits uq_account_transfers_user_id_client_request_id; the service
# rolls back, reloads the winner, and resolves an identical payload as a
# replay without creating anything.
# Parameters:
# - monkeypatch: pytest fixture used to hide the committed transfer from both lookups.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the replay returns the existing transfer.
def test_unique_race_recovery_resolves_identical_payload_as_replay(
    monkeypatch, clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    key = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking")
        destination = _create_account(db_session, user_id, "Savings")
        request = _request(source, destination, AS_OF, key=key)
        first = account_transfer_service.create_account_transfer(
            db_session=db_session, transfer_data=request, user_id=user_id, as_of=AS_OF,
        )

        _patch_lookup_misses(monkeypatch, misses=2)

        replay = account_transfer_service.create_account_transfer(
            db_session=db_session, transfer_data=request, user_id=user_id, as_of=AS_OF,
        )

        assert replay.created is False
        assert replay.transfer.id == first.transfer.id
        assert _transfer_row_counts(user_id) == (1, 2)
    finally:
        db_session.close()


# Tests step 8 with a different payload on non-overlapping Accounts - the
# case Account locks cannot serialize: the unique violation is resolved as
# an idempotency conflict, never a second transfer or a 500.
# Parameters:
# - monkeypatch: pytest fixture used to hide the committed transfer from both lookups.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the conflict is raised and one transfer exists.
def test_unique_race_recovery_resolves_different_payload_as_conflict(
    monkeypatch, clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    key = uuid4()

    try:
        first_source = _create_account(db_session, user_id, "A")
        first_destination = _create_account(db_session, user_id, "B")
        other_source = _create_account(db_session, user_id, "C")
        other_destination = _create_account(db_session, user_id, "D")
        account_transfer_service.create_account_transfer(
            db_session=db_session,
            transfer_data=_request(first_source, first_destination, AS_OF, key=key),
            user_id=user_id,
            as_of=AS_OF,
        )

        _patch_lookup_misses(monkeypatch, misses=2)

        with pytest.raises(AccountTransferIdempotencyConflictError):
            account_transfer_service.create_account_transfer(
                db_session=db_session,
                transfer_data=_request(other_source, other_destination, AS_OF, key=key),
                user_id=user_id,
                as_of=AS_OF,
            )

        assert _transfer_row_counts(user_id) == (1, 2)
    finally:
        db_session.close()


# Tests step 4: when the fast lookup misses but the second lookup (under
# the Account locks) finds the committed transfer, an identical payload is
# a replay even though one Account was archived since - Account validation
# is never rerun for an existing logical transfer.
# Parameters:
# - monkeypatch: pytest fixture used to hide the transfer from the fast lookup.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the replay succeeds instead of AccountArchivedError.
def test_second_lookup_replay_takes_precedence_over_archived_account(
    monkeypatch, clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    key = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking")
        destination = _create_account(db_session, user_id, "Savings")
        request = _request(source, destination, date(2026, 10, 15), key=key)
        first = account_transfer_service.create_account_transfer(
            db_session=db_session, transfer_data=request, user_id=user_id, as_of=AS_OF,
        )
        account_service.update_account(
            db_session=db_session,
            account_id=source.id,
            account_data=AccountUpdate(status="archived"),
            user_id=user_id,
        )

        _patch_lookup_misses(monkeypatch, misses=1)

        replay = account_transfer_service.create_account_transfer(
            db_session=db_session, transfer_data=request, user_id=user_id, as_of=AS_OF,
        )

        assert replay.created is False
        assert replay.transfer.id == first.transfer.id
        assert replay.transfer.status == "planned"
    finally:
        db_session.close()


# Tests new-create validation after both lookups miss: a missing or
# foreign Account is AccountNotFoundError, an archived one
# AccountArchivedError, and different currencies
# AccountTransferCurrencyMismatchError - and nothing is written in any case.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if each case raises its domain error.
def test_create_validates_accounts_for_new_transfer(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking")
        destination = _create_account(db_session, user_id, "Savings")
        foreign = _create_account(db_session, uuid4(), "Other user's")
        usd = _create_account(db_session, user_id, "USD", currency="USD")
        archived = _create_account(db_session, user_id, "Old")
        account_service.update_account(
            db_session=db_session,
            account_id=archived.id,
            account_data=AccountUpdate(status="archived"),
            user_id=user_id,
        )

        cases = [
            (_request(source, foreign, AS_OF), AccountNotFoundError),
            (_request(foreign, destination, AS_OF), AccountNotFoundError),
            (_request(archived, destination, AS_OF), AccountArchivedError),
            (_request(source, archived, AS_OF), AccountArchivedError),
            (_request(source, usd, AS_OF), AccountTransferCurrencyMismatchError),
        ]

        for request, expected_error in cases:
            with pytest.raises(expected_error):
                account_transfer_service.create_account_transfer(
                    db_session=db_session, transfer_data=request, user_id=user_id, as_of=AS_OF,
                )

        assert _transfer_row_counts(user_id) == (0, 0)
    finally:
        db_session.close()
