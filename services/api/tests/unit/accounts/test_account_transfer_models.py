from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.database_session import SessionLocal
from app.modules.accounts import account_repository
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_schemas import AccountCreate
from app.modules.accounts.account_transfer_models import AccountTransferModel

# Database-level tests for the account_transfers table (VF-018B). Rows are
# inserted directly through the ORM model - not through any service - so
# each test proves what the database itself accepts or rejects,
# independent of future service-level validation.

POSTED_AT = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)


def _create_account(db_session, user_id, currency="EUR", name="Checking") -> AccountModel:
    return account_repository.create_account(
        db_session=db_session,
        account_data=AccountCreate(name=name, type="checking", currency=currency),
        user_id=user_id,
    )


# Builds an unsaved AccountTransferModel with valid planned-transfer
# defaults; keyword overrides replace individual fields.
def _build_transfer(
    user_id: UUID,
    source_account_id: UUID,
    destination_account_id: UUID,
    **overrides: Any,
) -> AccountTransferModel:
    values = {
        "user_id": user_id,
        "client_request_id": uuid4(),
        "source_account_id": source_account_id,
        "destination_account_id": destination_account_id,
        "amount": Decimal("300.00"),
        "currency": "EUR",
        "status": "planned",
        "planned_date": date(2026, 10, 15),
        "effective_date": None,
        "description": None,
        "posted_at": None,
    }
    values.update(overrides)
    return AccountTransferModel(**values)


# Commits a row that must violate a database constraint and asserts the
# commit raises IntegrityError, leaving the session usable afterward.
def _assert_rejected(db_session, row: Any, reason: str) -> None:
    db_session.add(row)

    try:
        db_session.commit()
        assert False, f"expected IntegrityError for {reason}"
    except IntegrityError:
        db_session.rollback()


# Tests that a planned transfer (planned_date set, effective_date and
# posted_at NULL) persists with every field intact.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the row is persisted with the expected fields.
def test_account_transfer_valid_planned_row_persists(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, name="Checking")
        destination = _create_account(db_session, user_id, name="Savings")

        transfer = _build_transfer(
            user_id, source.id, destination.id, description="Move to savings",
        )
        db_session.add(transfer)
        db_session.commit()
        db_session.refresh(transfer)

        assert transfer.id is not None
        assert transfer.status == "planned"
        assert transfer.planned_date == date(2026, 10, 15)
        assert transfer.effective_date is None
        assert transfer.posted_at is None
        assert transfer.amount == Decimal("300.00")
        assert transfer.currency == "EUR"
        assert transfer.description == "Move to savings"
        assert transfer.created_at is not None
        assert transfer.updated_at is not None
    finally:
        db_session.close()


# Tests that an immediately posted transfer (planned_date NULL,
# effective_date and posted_at set) persists.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the row is persisted.
def test_account_transfer_valid_immediately_posted_row_persists(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, name="Checking")
        destination = _create_account(db_session, user_id, name="Savings")

        transfer = _build_transfer(
            user_id, source.id, destination.id,
            status="posted",
            planned_date=None,
            effective_date=date(2026, 9, 28),
            posted_at=POSTED_AT,
        )
        db_session.add(transfer)
        db_session.commit()
        db_session.refresh(transfer)

        assert transfer.status == "posted"
        assert transfer.planned_date is None
        assert transfer.effective_date == date(2026, 9, 28)
        assert transfer.posted_at == POSTED_AT
    finally:
        db_session.close()


# Tests that a planned transfer can later be updated into the posted
# shape while keeping its original planned_date - the lifecycle CHECK must
# not require planned_date to be NULL for a posted row.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the planned -> posted UPDATE commits with
#   planned_date preserved.
def test_account_transfer_planned_then_posted_shape_persists(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, name="Checking")
        destination = _create_account(db_session, user_id, name="Savings")

        transfer = _build_transfer(user_id, source.id, destination.id)
        db_session.add(transfer)
        db_session.commit()

        transfer.status = "posted"
        transfer.effective_date = date(2026, 10, 18)
        transfer.posted_at = POSTED_AT
        db_session.commit()
        db_session.refresh(transfer)

        assert transfer.status == "posted"
        assert transfer.planned_date == date(2026, 10, 15)
        assert transfer.effective_date == date(2026, 10, 18)
        assert transfer.posted_at == POSTED_AT
    finally:
        db_session.close()


# Tests that a zero or negative amount is rejected by
# ck_account_transfers_amount_positive.
# Parameters:
# - amount: the invalid amount under test.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
@pytest.mark.parametrize("amount", [Decimal("0.00"), Decimal("-1.00")])
def test_account_transfer_non_positive_amount_rejected(
    amount: Decimal, clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, name="Checking")
        destination = _create_account(db_session, user_id, name="Savings")

        _assert_rejected(
            db_session,
            _build_transfer(user_id, source.id, destination.id, amount=amount),
            f"amount {amount}",
        )
    finally:
        db_session.close()


# Tests that a transfer from an Account to itself is rejected by
# ck_account_transfers_distinct_accounts.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transfer_same_source_and_destination_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        _assert_rejected(
            db_session,
            _build_transfer(user_id, account.id, account.id),
            "source == destination",
        )
    finally:
        db_session.close()


# Tests that a status outside planned/posted is rejected by
# ck_account_transfers_status_valid.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transfer_invalid_status_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, name="Checking")
        destination = _create_account(db_session, user_id, name="Savings")

        _assert_rejected(
            db_session,
            _build_transfer(user_id, source.id, destination.id, status="cancelled"),
            "invalid status",
        )
    finally:
        db_session.close()


# Tests that every inconsistent status/date combination is rejected by
# ck_account_transfers_lifecycle_consistent.
# Parameters:
# - overrides: field values producing the inconsistent shape.
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {"status": "planned", "planned_date": None},
            id="planned_without_planned_date",
        ),
        pytest.param(
            {"status": "planned", "effective_date": date(2026, 10, 15)},
            id="planned_with_effective_date",
        ),
        pytest.param(
            {"status": "planned", "posted_at": POSTED_AT},
            id="planned_with_posted_at",
        ),
        pytest.param(
            {"status": "posted", "effective_date": None, "posted_at": POSTED_AT},
            id="posted_without_effective_date",
        ),
        pytest.param(
            {"status": "posted", "effective_date": date(2026, 9, 28), "posted_at": None},
            id="posted_without_posted_at",
        ),
    ],
)
def test_account_transfer_inconsistent_lifecycle_rejected(
    overrides: dict, clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, name="Checking")
        destination = _create_account(db_session, user_id, name="Savings")

        _assert_rejected(
            db_session,
            _build_transfer(user_id, source.id, destination.id, **overrides),
            f"inconsistent lifecycle {overrides}",
        )
    finally:
        db_session.close()


# Tests that the same user cannot create two transfers with the same
# client_request_id (uq_account_transfers_user_id_client_request_id).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the second commit raises IntegrityError.
def test_account_transfer_duplicate_client_request_id_same_user_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    client_request_id = uuid4()

    try:
        source = _create_account(db_session, user_id, name="Checking")
        destination = _create_account(db_session, user_id, name="Savings")

        db_session.add(
            _build_transfer(
                user_id, source.id, destination.id, client_request_id=client_request_id,
            )
        )
        db_session.commit()

        _assert_rejected(
            db_session,
            _build_transfer(
                user_id, source.id, destination.id,
                client_request_id=client_request_id,
                amount=Decimal("10.00"),
            ),
            "duplicate (user_id, client_request_id)",
        )
    finally:
        db_session.close()


# Tests that two different users may each use the same client_request_id -
# the idempotency key is unique per user, not globally.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both rows persist.
def test_account_transfer_same_client_request_id_different_users_allowed(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()
    client_request_id = uuid4()

    try:
        source = _create_account(db_session, user_id, name="Checking")
        destination = _create_account(db_session, user_id, name="Savings")
        other_source = _create_account(db_session, other_user_id, name="Checking")
        other_destination = _create_account(db_session, other_user_id, name="Savings")

        db_session.add_all([
            _build_transfer(
                user_id, source.id, destination.id, client_request_id=client_request_id,
            ),
            _build_transfer(
                other_user_id, other_source.id, other_destination.id,
                client_request_id=client_request_id,
            ),
        ])
        db_session.commit()

        count = db_session.execute(
            text("SELECT COUNT(*) FROM account_transfers WHERE client_request_id = :key"),
            {"key": client_request_id},
        ).scalar()
        assert count == 2
    finally:
        db_session.close()


# Tests that a source Account owned by another user is rejected by
# fk_account_transfers_source_account.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transfer_source_account_wrong_owner_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        other_users_source = _create_account(db_session, other_user_id, name="Checking")
        destination = _create_account(db_session, user_id, name="Savings")

        _assert_rejected(
            db_session,
            _build_transfer(user_id, other_users_source.id, destination.id),
            "cross-user source Account",
        )
    finally:
        db_session.close()


# Tests that a destination Account owned by another user is rejected by
# fk_account_transfers_destination_account.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transfer_destination_account_wrong_owner_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, name="Checking")
        other_users_destination = _create_account(db_session, other_user_id, name="Savings")

        _assert_rejected(
            db_session,
            _build_transfer(user_id, source.id, other_users_destination.id),
            "cross-user destination Account",
        )
    finally:
        db_session.close()


# Tests that a source Account whose currency differs from the transfer's
# currency is rejected by fk_account_transfers_source_account.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transfer_source_currency_mismatch_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        usd_source = _create_account(db_session, user_id, currency="USD", name="USD Checking")
        eur_destination = _create_account(db_session, user_id, currency="EUR", name="Savings")

        _assert_rejected(
            db_session,
            _build_transfer(user_id, usd_source.id, eur_destination.id, currency="EUR"),
            "source currency mismatch",
        )
    finally:
        db_session.close()


# Tests that a destination Account whose currency differs from the
# transfer's currency is rejected by fk_account_transfers_destination_account.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_account_transfer_destination_currency_mismatch_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        eur_source = _create_account(db_session, user_id, currency="EUR", name="Checking")
        usd_destination = _create_account(
            db_session, user_id, currency="USD", name="USD Savings",
        )

        _assert_rejected(
            db_session,
            _build_transfer(user_id, eur_source.id, usd_destination.id, currency="EUR"),
            "destination currency mismatch",
        )
    finally:
        db_session.close()


# Tests that an Account referenced by a (planned) transfer cannot be
# deleted at the database level (ON DELETE RESTRICT) - the last line of
# defense behind the future service-level 409.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if deleting the referenced Account raises
#   IntegrityError.
def test_account_referenced_by_transfer_cannot_be_deleted(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, name="Checking")
        destination = _create_account(db_session, user_id, name="Savings")
        db_session.add(_build_transfer(user_id, source.id, destination.id))
        db_session.commit()

        db_session.delete(source)

        try:
            db_session.commit()
            assert False, "expected IntegrityError deleting a referenced Account"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that the currency of an Account referenced by a (planned) transfer
# cannot change at the database level - the composite FK includes currency.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if updating the referenced Account's currency
#   raises IntegrityError.
def test_account_referenced_by_transfer_currency_cannot_change(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        source = _create_account(db_session, user_id, name="Checking")
        destination = _create_account(db_session, user_id, name="Savings")
        db_session.add(_build_transfer(user_id, source.id, destination.id))
        db_session.commit()

        source.currency = "USD"

        try:
            db_session.commit()
            assert False, "expected IntegrityError changing a referenced Account's currency"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()
