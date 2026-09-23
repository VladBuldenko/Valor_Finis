from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pytest import MonkeyPatch

from app.db.database_session import SessionLocal
from app.modules.accounts import account_repository, account_service, account_transaction_repository
from app.modules.accounts.account_errors import AccountArchivedError, AccountNotFoundError
from app.modules.accounts.account_models import AccountModel
from app.modules.accounts.account_schemas import AccountCreate, AccountUpdate
from app.modules.income import income_repository, income_service
from app.modules.income.income_errors import IncomeAccountCurrencyMismatchError
from app.modules.income.income_models import IncomeModel
from app.modules.income.income_schemas import IncomeCreate, IncomeUpdate


def _create_account(db_session, user_id, name="Checking", currency="EUR") -> AccountModel:
    return account_repository.create_account(
        db_session=db_session,
        account_data=AccountCreate(name=name, type="checking", currency=currency),
        user_id=user_id,
    )


def _archive(db_session, user_id, account_id) -> None:
    account_service.update_account(
        db_session=db_session, account_id=account_id,
        account_data=AccountUpdate(status="archived"), user_id=user_id,
    )


# ------------------------------------------------------------------
# CREATE
# ------------------------------------------------------------------


# Tests that creating an Income linked to a matching-currency Account
# succeeds, the response reports the linkage, and the Account balance
# reflects the credit.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if response.account_id is set and the Account
#   balance equals the Income amount.
def test_create_income_linked_happy_path(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        result = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("2500.00"), currency="EUR",
                received_at=date(2026, 9, 30), source="salary",
                account_id=account.id,
            ),
            user_id=user_id,
        )

        assert result.account_id == account.id

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("2500.00")
    finally:
        db_session.close()


# Tests that linking to another user's Account behaves as not found.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if AccountNotFoundError is raised.
def test_create_income_linked_wrong_owner_account_not_found(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        other_account = _create_account(db_session, other_user_id)

        with pytest.raises(AccountNotFoundError):
            income_service.create_income(
                db_session=db_session,
                income_data=IncomeCreate(
                    amount=Decimal("100.00"), currency="EUR",
                    received_at=date(2026, 9, 30), source="salary",
                    account_id=other_account.id,
                ),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that linking to an archived Account is rejected.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if AccountArchivedError is raised.
def test_create_income_linked_archived_account_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        _archive(db_session, user_id, account.id)

        with pytest.raises(AccountArchivedError):
            income_service.create_income(
                db_session=db_session,
                income_data=IncomeCreate(
                    amount=Decimal("100.00"), currency="EUR",
                    received_at=date(2026, 9, 30), source="salary",
                    account_id=account.id,
                ),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that linking with a mismatched currency is rejected.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if IncomeAccountCurrencyMismatchError is raised.
def test_create_income_linked_currency_mismatch_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, currency="USD")

        with pytest.raises(IncomeAccountCurrencyMismatchError):
            income_service.create_income(
                db_session=db_session,
                income_data=IncomeCreate(
                    amount=Decimal("100.00"), currency="EUR",
                    received_at=date(2026, 9, 30), source="salary",
                    account_id=account.id,
                ),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that a failure creating the projection AFTER the Income row has
# already been flushed leaves neither row durable.
# This test exists as the atomic-failure regression for linked create:
# it monkeypatches account_transaction_repository.create_income_projection
# to raise, proving the whole operation rolls back together.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to inject the deterministic failure.
# Returns:
# - None. The test passes if no Income row exists afterward, from a
#   completely separate session.
def test_create_income_linked_projection_failure_persists_nothing(
    clean_database: None, monkeypatch: MonkeyPatch,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        def _raise_after_income_flush(*args, **kwargs):
            raise RuntimeError("simulated projection failure")

        monkeypatch.setattr(
            income_service.account_transaction_repository,
            "create_income_projection",
            _raise_after_income_flush,
        )

        with pytest.raises(RuntimeError):
            income_service.create_income(
                db_session=db_session,
                income_data=IncomeCreate(
                    amount=Decimal("100.00"), currency="EUR",
                    received_at=date(2026, 9, 30), source="salary",
                    account_id=account.id,
                ),
                user_id=user_id,
            )
    finally:
        db_session.close()

    verify_session = SessionLocal()
    try:
        surviving = (
            verify_session.query(IncomeModel).filter(IncomeModel.user_id == user_id).all()
        )
        assert surviving == []
    finally:
        verify_session.close()


# ------------------------------------------------------------------
# READ
# ------------------------------------------------------------------


# Tests that get_income correctly derives account_id for a mix of linked
# and unlinked Income records in one bulk-resolved list.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the linked record reports the Account and
#   the unlinked one reports None.
def test_get_income_derives_account_id_for_mixed_list(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account.id,
            ),
            user_id=user_id,
        )
        income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("200.00"), currency="EUR",
                received_at=date(2026, 9, 2), source="gift",
            ),
            user_id=user_id,
        )

        records = income_service.get_income(db_session=db_session, user_id=user_id)
        by_source = {r.source: r for r in records}

        assert by_source["salary"].account_id == account.id
        assert by_source["gift"].account_id is None
    finally:
        db_session.close()


# ------------------------------------------------------------------
# UPDATE - sync
# ------------------------------------------------------------------


# Tests that an amount change on a linked Income synchronizes the
# projection's amount.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the Account balance reflects the new amount.
def test_update_income_amount_sync_when_linked(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 30), source="salary", account_id=account.id,
            ),
            user_id=user_id,
        )

        income_service.update_income(
            db_session=db_session, income_id=created.id,
            income_data=IncomeUpdate(amount=Decimal("150.00")), user_id=user_id,
        )

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("150.00")
    finally:
        db_session.close()


# Tests that a received_at change on a linked Income synchronizes the
# projection's transaction_date.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the projection's transaction_date matches
#   the new received_at.
def test_update_income_received_at_sync_when_linked(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account.id,
            ),
            user_id=user_id,
        )

        income_service.update_income(
            db_session=db_session, income_id=created.id,
            income_data=IncomeUpdate(received_at=date(2026, 9, 15)), user_id=user_id,
        )

        projection = account_transaction_repository.get_income_projection(
            db_session=db_session, income_id=created.id, user_id=user_id,
        )
        assert projection.transaction_date == date(2026, 9, 15)
    finally:
        db_session.close()


# Tests that a source/description-only update on a linked Income does not
# touch the projection at all.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the projection's own updated amount/date
#   stay exactly as they were.
def test_update_income_metadata_only_does_not_touch_projection(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account.id,
            ),
            user_id=user_id,
        )
        before = account_transaction_repository.get_income_projection(
            db_session=db_session, income_id=created.id, user_id=user_id,
        )

        income_service.update_income(
            db_session=db_session, income_id=created.id,
            income_data=IncomeUpdate(description="Updated note"), user_id=user_id,
        )

        after = account_transaction_repository.get_income_projection(
            db_session=db_session, income_id=created.id, user_id=user_id,
        )
        assert after.id == before.id
        assert after.amount == before.amount
        assert after.transaction_date == before.transaction_date
    finally:
        db_session.close()


# ------------------------------------------------------------------
# UPDATE - attach / detach / move
# ------------------------------------------------------------------


# Tests attaching a previously-unlinked Income to an Account.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if a projection is created and the Account
#   balance reflects it.
def test_update_income_attach_creates_projection(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("300.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary",
            ),
            user_id=user_id,
        )

        result = income_service.update_income(
            db_session=db_session, income_id=created.id,
            income_data=IncomeUpdate(account_id=account.id), user_id=user_id,
        )

        assert result.account_id == account.id
        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("300.00")
    finally:
        db_session.close()


# Tests detaching a linked Income.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the projection is gone and the Account
#   balance returns to 0.
def test_update_income_detach_removes_projection(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("300.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account.id,
            ),
            user_id=user_id,
        )

        result = income_service.update_income(
            db_session=db_session, income_id=created.id,
            income_data=IncomeUpdate(account_id=None), user_id=user_id,
        )

        assert result.account_id is None
        assert account_transaction_repository.get_income_projection(
            db_session=db_session, income_id=created.id, user_id=user_id,
        ) is None

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("0.00")
    finally:
        db_session.close()


# Tests moving a linked Income from Account A to Account B - the
# projection row is updated in place (same id, same created_at), not
# deleted and recreated.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the projection id/created_at are preserved
#   and balances shift correctly between the two Accounts.
def test_update_income_move_preserves_projection_id(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account_a = _create_account(db_session, user_id, name="A")
        account_b = _create_account(db_session, user_id, name="B")
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("300.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account_a.id,
            ),
            user_id=user_id,
        )
        before = account_transaction_repository.get_income_projection(
            db_session=db_session, income_id=created.id, user_id=user_id,
        )

        result = income_service.update_income(
            db_session=db_session, income_id=created.id,
            income_data=IncomeUpdate(account_id=account_b.id), user_id=user_id,
        )

        after = account_transaction_repository.get_income_projection(
            db_session=db_session, income_id=created.id, user_id=user_id,
        )

        assert result.account_id == account_b.id
        assert after.id == before.id
        assert after.created_at == before.created_at

        balance_a = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account_a.id, user_id=user_id,
        )
        balance_b = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account_b.id, user_id=user_id,
        )
        assert balance_a == Decimal("0.00")
        assert balance_b == Decimal("300.00")
    finally:
        db_session.close()


# Tests that moving a linked Income INTO an archived Account is rejected.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if AccountArchivedError is raised.
def test_update_income_move_into_archived_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account_a = _create_account(db_session, user_id, name="A")
        account_b = _create_account(db_session, user_id, name="B")
        _archive(db_session, user_id, account_b.id)

        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account_a.id,
            ),
            user_id=user_id,
        )

        with pytest.raises(AccountArchivedError):
            income_service.update_income(
                db_session=db_session, income_id=created.id,
                income_data=IncomeUpdate(account_id=account_b.id), user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that moving a linked Income OUT of an archived Account (into an
# active one) is allowed.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the move succeeds.
def test_update_income_move_out_of_archived_allowed(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account_a = _create_account(db_session, user_id, name="A")
        account_b = _create_account(db_session, user_id, name="B")

        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account_a.id,
            ),
            user_id=user_id,
        )

        _archive(db_session, user_id, account_a.id)

        result = income_service.update_income(
            db_session=db_session, income_id=created.id,
            income_data=IncomeUpdate(account_id=account_b.id), user_id=user_id,
        )
        assert result.account_id == account_b.id
    finally:
        db_session.close()


# ------------------------------------------------------------------
# UPDATE - currency validation
# ------------------------------------------------------------------


# Tests that changing currency while staying linked to the same Account
# succeeds when the new currency still matches.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the update succeeds.
def test_update_income_same_account_currency_change_matching_succeeds(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, currency="EUR")
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account.id,
            ),
            user_id=user_id,
        )

        result = income_service.update_income(
            db_session=db_session, income_id=created.id,
            income_data=IncomeUpdate(currency="eur"), user_id=user_id,
        )
        assert result.currency == "EUR"
        assert result.account_id == account.id
    finally:
        db_session.close()


# Tests that changing currency while staying linked to the same Account
# is rejected when the new currency no longer matches.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if IncomeAccountCurrencyMismatchError is
#   raised, with no silent auto-detach.
def test_update_income_same_account_currency_change_mismatched_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, currency="EUR")
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account.id,
            ),
            user_id=user_id,
        )

        with pytest.raises(IncomeAccountCurrencyMismatchError):
            income_service.update_income(
                db_session=db_session, income_id=created.id,
                income_data=IncomeUpdate(currency="USD"), user_id=user_id,
            )

        # No silent auto-detach: the projection must still exist.
        assert account_transaction_repository.get_income_projection(
            db_session=db_session, income_id=created.id, user_id=user_id,
        ) is not None
    finally:
        db_session.close()


# Tests that changing currency AND account_id together in the same PATCH
# is validated against the FINAL combination, not intermediate states -
# EUR Income on EUR Account A moving to USD Account B while also changing
# to USD succeeds because the final currency matches the final Account.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the combined update succeeds.
def test_update_income_currency_and_account_id_together_final_state_valid(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account_a = _create_account(db_session, user_id, name="A", currency="EUR")
        account_b = _create_account(db_session, user_id, name="B", currency="USD")

        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account_a.id,
            ),
            user_id=user_id,
        )

        result = income_service.update_income(
            db_session=db_session, income_id=created.id,
            income_data=IncomeUpdate(currency="USD", account_id=account_b.id),
            user_id=user_id,
        )

        assert result.currency == "USD"
        assert result.account_id == account_b.id
    finally:
        db_session.close()


# Tests that changing currency AND detaching in the same PATCH succeeds,
# since the final Income is unlinked and has no Account currency to
# match at all.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the combined update succeeds.
def test_update_income_currency_and_detach_together_succeeds(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, currency="EUR")
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account.id,
            ),
            user_id=user_id,
        )

        result = income_service.update_income(
            db_session=db_session, income_id=created.id,
            income_data=IncomeUpdate(currency="USD", account_id=None), user_id=user_id,
        )

        assert result.currency == "USD"
        assert result.account_id is None
    finally:
        db_session.close()


# ------------------------------------------------------------------
# UPDATE - virtual field safety
# ------------------------------------------------------------------


# Tests that account_id is never persisted as a stray ORM attribute on
# IncomeModel.
# This test exists as the direct regression for the remote-review
# requirement: Income has no account_id database column, so
# income_repository.update_income's generic update_data loop must
# structurally exclude it, not merely happen to skip it in this one
# review pass. Calls the repository function directly (bypassing the
# service) with an IncomeUpdate that sets account_id, then re-queries a
# completely fresh IncomeModel instance and confirms it has no
# account_id-driven side effect.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the persisted row round-trips with no
#   account_id attribute error and the real columns are correct.
def test_update_income_virtual_account_id_never_persisted_on_income_model(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary",
            ),
            user_id=user_id,
        )

        income_model = income_repository.get_income_by_id_for_update(
            db_session=db_session, income_id=created.id, user_id=user_id,
        )

        income_repository.update_income(
            db_session=db_session,
            income_model=income_model,
            income_data=IncomeUpdate(account_id=account.id, description="test"),
            base_amount=income_model.base_amount,
            base_currency=income_model.base_currency,
            fx_rate=income_model.fx_rate,
            fx_rate_date=income_model.fx_rate_date,
            fx_source=income_model.fx_source,
        )
    finally:
        db_session.close()

    verify_session = SessionLocal()
    try:
        fresh = (
            verify_session.query(IncomeModel).filter(IncomeModel.id == created.id).first()
        )
        assert fresh is not None
        assert fresh.description == "test"
        assert not hasattr(fresh, "account_id")
        assert "account_id" not in IncomeModel.__table__.columns
    finally:
        verify_session.close()


# ------------------------------------------------------------------
# UPDATE - archived semantics
# ------------------------------------------------------------------


# Tests that amount/date corrections to an Income already linked to an
# Account archived AFTERWARD are allowed - this is maintenance of
# existing history, not new activity.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the amount correction succeeds and the
#   Account balance reflects it.
def test_update_income_amount_correction_on_later_archived_account_allowed(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account.id,
            ),
            user_id=user_id,
        )

        _archive(db_session, user_id, account.id)

        result = income_service.update_income(
            db_session=db_session, income_id=created.id,
            income_data=IncomeUpdate(amount=Decimal("150.00")), user_id=user_id,
        )
        assert result.amount == Decimal("150.00")

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("150.00")
    finally:
        db_session.close()


# Tests that detaching a linked Income from an archived Account is
# allowed.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the detach succeeds.
def test_update_income_detach_from_archived_account_allowed(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account.id,
            ),
            user_id=user_id,
        )

        _archive(db_session, user_id, account.id)

        result = income_service.update_income(
            db_session=db_session, income_id=created.id,
            income_data=IncomeUpdate(account_id=None), user_id=user_id,
        )
        assert result.account_id is None
    finally:
        db_session.close()


# ------------------------------------------------------------------
# DELETE
# ------------------------------------------------------------------


# Tests that deleting a linked Income removes its projection via CASCADE
# and leaves the Account balance correct, with no orphan row.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the Income is gone, the projection is gone,
#   and the Account balance returns to 0.
def test_delete_income_linked_cascades_projection_balance_correct(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("500.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account.id,
            ),
            user_id=user_id,
        )

        income_service.delete_income(
            db_session=db_session, income_id=created.id, user_id=user_id,
        )

        remaining_income = (
            db_session.query(IncomeModel).filter(IncomeModel.id == created.id).first()
        )
        assert remaining_income is None

        assert account_transaction_repository.get_income_projection(
            db_session=db_session, income_id=created.id, user_id=user_id,
        ) is None

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("0.00")
    finally:
        db_session.close()


# Tests that deleting a linked Income from an archived Account is
# allowed.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the delete succeeds.
def test_delete_income_linked_to_archived_account_allowed(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 9, 1), source="salary", account_id=account.id,
            ),
            user_id=user_id,
        )

        _archive(db_session, user_id, account.id)

        income_service.delete_income(
            db_session=db_session, income_id=created.id, user_id=user_id,
        )

        remaining = (
            db_session.query(IncomeModel).filter(IncomeModel.id == created.id).first()
        )
        assert remaining is None
    finally:
        db_session.close()
