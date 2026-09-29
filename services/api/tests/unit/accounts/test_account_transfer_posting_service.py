from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.database_session import SessionLocal
from app.modules.accounts import (
    account_repository,
    account_service,
    account_transaction_repository,
    account_transfer_repository,
    account_transfer_service,
)
from app.modules.accounts.account_errors import AccountArchivedError
from app.modules.accounts.account_schemas import AccountCreate, AccountUpdate
from app.modules.accounts.account_transaction_models import AccountTransactionModel
from app.modules.accounts.account_transfer_errors import (
    AccountTransferAlreadyPostedError,
    AccountTransferCurrencyMismatchError,
    AccountTransferEffectiveDateInFutureError,
    AccountTransferNotFoundError,
)
from app.modules.accounts.account_transfer_models import AccountTransferModel
from app.modules.accounts.account_transfer_schemas import (
    AccountTransferCreate,
    AccountTransferPost,
)

# Service-level tests for manual posting (VF-018D). "today" is pinned with
# as_of so no assertion depends on the wall clock.
CREATED_AS_OF = date(2026, 9, 28)
TODAY = date(2026, 9, 29)
PLANNED_DATE = date(2026, 10, 15)


def _create_account(db_session, user_id, name, opening_balance=None):
    account = account_repository.create_account(
        db_session=db_session,
        account_data=AccountCreate(name=name, type="checking", currency="EUR"),
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


def _create_planned(db_session, user_id, source, destination, planned_date=PLANNED_DATE,
                    amount="300.00", as_of=CREATED_AS_OF):
    return account_transfer_service.create_account_transfer(
        db_session=db_session,
        transfer_data=AccountTransferCreate(
            client_request_id=uuid4(),
            source_account_id=source.id,
            destination_account_id=destination.id,
            amount=Decimal(amount),
            transfer_date=planned_date,
        ),
        user_id=user_id,
        as_of=as_of,
    ).transfer


def _post(db_session, transfer_id, user_id, effective_date=None, as_of=TODAY, body=True):
    return account_transfer_service.post_account_transfer(
        db_session=db_session,
        transfer_id=transfer_id,
        user_id=user_id,
        post_data=AccountTransferPost(effective_date=effective_date) if body else None,
        as_of=as_of,
    )


def _state(transfer_id, user_id):
    verify_session = SessionLocal()
    try:
        transfer = verify_session.get(AccountTransferModel, transfer_id)
        legs = (
            verify_session.query(AccountTransactionModel)
            .filter(
                AccountTransactionModel.user_id == user_id,
                AccountTransactionModel.transfer_id == transfer_id,
            )
            .all()
        )
        return transfer, legs
    finally:
        verify_session.close()


def _archive(db_session, account, user_id, status="archived"):
    account_service.update_account(
        db_session=db_session,
        account_id=account.id,
        account_data=AccountUpdate(status=status),
        user_id=user_id,
    )


# Tests that posting without a body, or with an empty body, uses the server
# date (as_of) as effective_date, keeps planned_date, sets a timezone-aware
# posted_at, and creates exactly one debit and one credit dated
# effective_date.
# Parameters:
# - body: whether an empty AccountTransferPost is passed or no body at all.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the posted state and ledger rows match.
@pytest.mark.parametrize("body", [False, True])
def test_post_defaults_effective_date_to_today(body: bool, clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking", opening_balance="1000.00")
        destination = _create_account(db_session, user_id, "Savings")
        planned = _create_planned(db_session, user_id, source, destination)

        posted = _post(db_session, planned.id, user_id, body=body)

        assert posted.id == planned.id
        assert posted.status == "posted"
        assert posted.planned_date == PLANNED_DATE
        assert posted.effective_date == TODAY
        assert posted.posted_at is not None
        assert posted.posted_at.tzinfo is not None

        stored, legs = _state(planned.id, user_id)
        assert stored.status == "posted"
        assert stored.planned_date == PLANNED_DATE
        assert sorted((leg.direction, leg.account_id) for leg in legs) == sorted([
            ("debit", source.id), ("credit", destination.id),
        ])
        for leg in legs:
            assert leg.kind == "transfer"
            assert leg.amount == Decimal("300.00")
            assert leg.transaction_date == TODAY
            assert leg.description is None

        balances = [
            account_transaction_repository.calculate_ledger_balance(
                db_session=db_session, account_id=account.id, user_id=user_id,
            )
            for account in (source, destination)
        ]
        assert balances == [Decimal("700.00"), Decimal("300.00")]
    finally:
        db_session.close()


# Tests that manual posting has no "not yet due" rule: posting before,
# on, and after planned_date is allowed with any effective_date up to
# today, and planned_date always keeps its original value.
# Parameters:
# - planned_date: the transfer's planned date.
# - effective_date: the explicit posting date.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if every combination posts with planned_date kept.
@pytest.mark.parametrize(
    ("planned_date", "effective_date"),
    [
        pytest.param(date(2026, 10, 15), date(2026, 9, 29), id="early_post_today"),
        pytest.param(date(2026, 10, 15), date(2026, 9, 20), id="early_post_past_date"),
        pytest.param(date(2026, 9, 29), date(2026, 9, 29), id="on_planned_date"),
        pytest.param(date(2026, 9, 20), date(2026, 9, 29), id="late_post_today"),
        pytest.param(date(2026, 9, 20), date(2026, 9, 25), id="late_post_past_date"),
    ],
)
def test_post_before_on_or_after_planned_date(
    planned_date: date, effective_date: date, clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking")
        destination = _create_account(db_session, user_id, "Savings")
        # Created as planned relative to an earlier "today", so a planned
        # date that is overdue by TODAY is still a stored planned transfer.
        planned = _create_planned(
            db_session, user_id, source, destination,
            planned_date=planned_date, as_of=date(2026, 9, 1),
        )
        assert planned.status == "planned"

        posted = _post(db_session, planned.id, user_id, effective_date=effective_date)

        assert posted.status == "posted"
        assert posted.planned_date == planned_date
        assert posted.effective_date == effective_date
        _, legs = _state(planned.id, user_id)
        assert [leg.transaction_date for leg in legs] == [effective_date, effective_date]
    finally:
        db_session.close()


# Tests that a future effective_date is rejected BEFORE the transfer is
# looked up: 422 for an existing, a missing, and another user's transfer
# alike, with nothing written; with a valid date, missing and foreign are
# the same 404.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the precedence holds.
def test_future_effective_date_is_rejected_before_lookup(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking")
        destination = _create_account(db_session, user_id, "Savings")
        own = _create_planned(db_session, user_id, source, destination)
        foreign_source = _create_account(db_session, other_user_id, "Checking")
        foreign_destination = _create_account(db_session, other_user_id, "Savings")
        foreign = _create_planned(db_session, other_user_id, foreign_source, foreign_destination)
        tomorrow = date(2026, 9, 30)

        for transfer_id in (own.id, uuid4(), foreign.id):
            with pytest.raises(AccountTransferEffectiveDateInFutureError):
                _post(db_session, transfer_id, user_id, effective_date=tomorrow)

        for transfer_id in (uuid4(), foreign.id):
            with pytest.raises(AccountTransferNotFoundError):
                _post(db_session, transfer_id, user_id, effective_date=TODAY)

        stored, legs = _state(own.id, user_id)
        assert stored.status == "planned"
        assert legs == []
    finally:
        db_session.close()


# Tests that a transfer can be posted at most once: posting an immediately
# posted transfer, or posting a planned transfer a second time, is
# AccountTransferAlreadyPostedError and never adds projections.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both cases raise and each transfer keeps two rows.
def test_post_already_posted_transfer_is_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking")
        destination = _create_account(db_session, user_id, "Savings")
        immediately_posted = _create_planned(
            db_session, user_id, source, destination, planned_date=date(2026, 9, 20),
        )
        assert immediately_posted.status == "posted"
        manually_posted = _create_planned(db_session, user_id, source, destination)
        first = _post(db_session, manually_posted.id, user_id)

        for transfer_id in (immediately_posted.id, manually_posted.id):
            with pytest.raises(AccountTransferAlreadyPostedError):
                _post(db_session, transfer_id, user_id)
            _, legs = _state(transfer_id, user_id)
            assert len(legs) == 2

        stored, _ = _state(manually_posted.id, user_id)
        assert stored.effective_date == first.effective_date
        assert stored.posted_at == first.posted_at
    finally:
        db_session.close()


# Tests that posting is rejected while either Account is archived - the
# transfer stays planned with no ledger rows - and succeeds once the
# Account is reactivated.
# Parameters:
# - side: which Account is archived.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the post fails, then succeeds after reactivation.
@pytest.mark.parametrize("side", ["source", "destination"])
def test_post_with_archived_account_then_reactivated(side: str, clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking")
        destination = _create_account(db_session, user_id, "Savings")
        planned = _create_planned(db_session, user_id, source, destination)
        archived = source if side == "source" else destination
        _archive(db_session, archived, user_id)

        with pytest.raises(AccountArchivedError):
            _post(db_session, planned.id, user_id)

        stored, legs = _state(planned.id, user_id)
        assert stored.status == "planned"
        assert stored.effective_date is None
        assert stored.posted_at is None
        assert legs == []

        _archive(db_session, archived, user_id, status="active")
        posted = _post(db_session, planned.id, user_id)

        assert posted.status == "posted"
        _, legs = _state(planned.id, user_id)
        assert len(legs) == 2
    finally:
        db_session.close()


# Tests atomicity: a failure injected after the transfer was flushed as
# posted AND both projections were flushed rolls everything back - the
# transfer is planned again with no effective_date/posted_at and no rows.
# Parameters:
# - monkeypatch: pytest fixture used to inject the failure.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the error propagates and the planned state is intact.
def test_post_rolls_back_everything_on_failure(monkeypatch, clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking")
        destination = _create_account(db_session, user_id, "Savings")
        planned = _create_planned(db_session, user_id, source, destination)
        real_create_projections = account_transaction_repository.create_transfer_projections

        def create_projections_then_fail(db_session, transfer):
            assert transfer.status == "posted"
            real_create_projections(db_session=db_session, transfer=transfer)
            raise RuntimeError("injected failure after posting writes were flushed")

        monkeypatch.setattr(
            account_transaction_repository,
            "create_transfer_projections",
            create_projections_then_fail,
        )

        with pytest.raises(RuntimeError):
            _post(db_session, planned.id, user_id)

        stored, legs = _state(planned.id, user_id)
        assert stored.status == "planned"
        assert stored.planned_date == PLANNED_DATE
        assert stored.effective_date is None
        assert stored.posted_at is None
        assert legs == []
    finally:
        db_session.close()


# Tests the defense-in-depth currency re-check: if the locked Accounts ever
# disagreed with the transfer's currency (impossible while the composite
# foreign keys hold, so the lock result is doctored here), posting fails
# with AccountTransferCurrencyMismatchError and writes nothing.
# Parameters:
# - monkeypatch: pytest fixture used to doctor the locked Account.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the post is rejected and nothing changes.
def test_post_rechecks_currency_defensively(monkeypatch, clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking")
        destination = _create_account(db_session, user_id, "Savings")
        planned = _create_planned(db_session, user_id, source, destination)
        real_lock = account_repository.get_accounts_by_ids_for_update

        def lock_with_doctored_currency(**kwargs):
            locked = real_lock(**kwargs)
            locked[destination.id].currency = "USD"
            return locked

        monkeypatch.setattr(account_repository, "get_accounts_by_ids_for_update", lock_with_doctored_currency)

        with pytest.raises(AccountTransferCurrencyMismatchError):
            _post(db_session, planned.id, user_id)

        stored, legs = _state(planned.id, user_id)
        assert stored.status == "planned"
        assert legs == []
    finally:
        db_session.close()


# Tests the repository guard: mark_locked_account_transfer_posted refuses a
# transfer that is already posted (a programming invariant, ValueError).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if ValueError is raised.
def test_mark_posted_primitive_refuses_posted_transfer(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking")
        destination = _create_account(db_session, user_id, "Savings")
        posted = _create_planned(db_session, user_id, source, destination, planned_date=date(2026, 9, 20))
        transfer_model = account_transfer_repository.get_account_transfer_by_id_for_update(
            db_session=db_session, transfer_id=posted.id, user_id=user_id,
        )

        with pytest.raises(ValueError):
            account_transfer_repository.mark_locked_account_transfer_posted(
                db_session=db_session,
                transfer_model=transfer_model,
                effective_date=TODAY,
                posted_at=posted.posted_at,
            )
        db_session.rollback()
    finally:
        db_session.close()


# Tests delete atomicity (VF-018C review follow-up): a failure injected
# after the posted transfer's DELETE was flushed - which already cascaded
# its projections inside the transaction - rolls everything back, leaving
# the transfer and both projections intact.
# Parameters:
# - monkeypatch: pytest fixture used to inject the failure.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the transfer and its two rows survive.
def test_delete_rolls_back_everything_on_failure(monkeypatch, clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, "Checking")
        destination = _create_account(db_session, user_id, "Savings")
        planned = _create_planned(db_session, user_id, source, destination)
        _post(db_session, planned.id, user_id)
        real_delete = account_transfer_repository.delete_locked_account_transfer

        def delete_then_fail(db_session, transfer_model):
            real_delete(db_session=db_session, transfer_model=transfer_model)
            raise RuntimeError("injected failure after the delete was flushed")

        monkeypatch.setattr(account_transfer_repository, "delete_locked_account_transfer", delete_then_fail)

        with pytest.raises(RuntimeError):
            account_transfer_service.delete_account_transfer(
                db_session=db_session, transfer_id=planned.id, user_id=user_id,
            )

        stored, legs = _state(planned.id, user_id)
        assert stored is not None
        assert stored.status == "posted"
        assert len(legs) == 2
    finally:
        db_session.close()
