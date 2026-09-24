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
from app.modules.expenses import expenses_repository, expenses_service
from app.modules.expenses.expenses_errors import ExpenseAccountCurrencyMismatchError
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.expenses.expenses_schemas import ExpenseCreate, ExpenseUpdate
from app.modules.receipts import receipt_repository
from app.modules.receipts.receipt_models import ReceiptModel


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


def _create_legacy_unresolved_expense(
    db_session, user_id, currency="USD", amount=Decimal("100.00"),
    expense_date=date(2026, 1, 15),
) -> ExpenseModel:
    expense = ExpenseModel(
        user_id=user_id,
        category_id=None,
        title="Legacy NYC taxi",
        amount=amount,
        currency=currency,
        expense_date=expense_date,
        description=None,
        source="manual",
        base_amount=None,
        base_currency=None,
        fx_rate=None,
        fx_rate_date=None,
        fx_source=None,
    )
    db_session.add(expense)
    db_session.commit()
    db_session.refresh(expense)
    return expense


def _fail_if_fx_called(*args, **kwargs):
    raise AssertionError("fx_service.resolve_fx_rate must not be called for this operation")


# ------------------------------------------------------------------
# CREATE
# ------------------------------------------------------------------


# Tests that creating an Expense linked to a matching-currency Account
# succeeds, the response reports the linkage, and the Account balance
# reflects the debit.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if response.account_id is set and the Account
#   balance equals -Expense.amount.
def test_create_expense_linked_happy_path(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        result = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("50.00"), currency="EUR",
                expense_date=date(2026, 9, 30), source="manual",
                account_id=account.id,
            ),
            user_id=user_id,
        )

        assert result.account_id == account.id

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("-50.00")
    finally:
        db_session.close()


# Tests that linking to another user's Account behaves as not found.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if AccountNotFoundError is raised.
def test_create_expense_linked_wrong_owner_account_not_found(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        other_account = _create_account(db_session, other_user_id)

        with pytest.raises(AccountNotFoundError):
            expenses_service.create_expense(
                db_session=db_session,
                expense_data=ExpenseCreate(
                    title="Hijack attempt", amount=Decimal("10.00"), currency="EUR",
                    expense_date=date(2026, 9, 30), source="manual",
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
def test_create_expense_linked_archived_account_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        _archive(db_session, user_id, account.id)

        with pytest.raises(AccountArchivedError):
            expenses_service.create_expense(
                db_session=db_session,
                expense_data=ExpenseCreate(
                    title="Coffee", amount=Decimal("10.00"), currency="EUR",
                    expense_date=date(2026, 9, 30), source="manual",
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
# - None. The test passes if ExpenseAccountCurrencyMismatchError is
#   raised.
def test_create_expense_linked_currency_mismatch_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, currency="USD")

        with pytest.raises(ExpenseAccountCurrencyMismatchError):
            expenses_service.create_expense(
                db_session=db_session,
                expense_data=ExpenseCreate(
                    title="Coffee", amount=Decimal("10.00"), currency="EUR",
                    expense_date=date(2026, 9, 30), source="manual",
                    account_id=account.id,
                ),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that a failure creating the projection AFTER the Expense row has
# already been flushed leaves neither row durable.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to inject the deterministic failure.
# Returns:
# - None. The test passes if no Expense row exists afterward, from a
#   completely separate session.
def test_create_expense_linked_projection_failure_persists_nothing(
    clean_database: None, monkeypatch: MonkeyPatch,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        def _raise_after_expense_flush(*args, **kwargs):
            raise RuntimeError("simulated projection failure")

        monkeypatch.setattr(
            expenses_service.account_transaction_repository,
            "create_expense_projection",
            _raise_after_expense_flush,
        )

        with pytest.raises(RuntimeError):
            expenses_service.create_expense(
                db_session=db_session,
                expense_data=ExpenseCreate(
                    title="Coffee", amount=Decimal("10.00"), currency="EUR",
                    expense_date=date(2026, 9, 30), source="manual",
                    account_id=account.id,
                ),
                user_id=user_id,
            )
    finally:
        db_session.close()

    verify_session = SessionLocal()
    try:
        surviving = (
            verify_session.query(ExpenseModel).filter(ExpenseModel.user_id == user_id).all()
        )
        assert surviving == []
    finally:
        verify_session.close()


# ------------------------------------------------------------------
# READ
# ------------------------------------------------------------------


# Tests that get_expenses correctly derives account_id for a mix of
# linked and unlinked Expense records in one bulk-resolved list.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the linked record reports the Account and
#   the unlinked one reports None.
def test_get_expenses_derives_account_id_for_mixed_list(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)

        expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("100.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual", account_id=account.id,
            ),
            user_id=user_id,
        )
        expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Cash tip", amount=Decimal("5.00"), currency="EUR",
                expense_date=date(2026, 9, 2), source="manual",
            ),
            user_id=user_id,
        )

        records = expenses_service.get_expenses(db_session=db_session, user_id=user_id)
        by_title = {r.title: r for r in records}

        assert by_title["Groceries"].account_id == account.id
        assert by_title["Cash tip"].account_id is None
    finally:
        db_session.close()


# ------------------------------------------------------------------
# UPDATE - sync
# ------------------------------------------------------------------


# Tests that an amount change on a linked Expense synchronizes the
# projection's amount.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the Account balance reflects the new amount.
def test_update_expense_amount_sync_when_linked(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("100.00"), currency="EUR",
                expense_date=date(2026, 9, 30), source="manual", account_id=account.id,
            ),
            user_id=user_id,
        )

        expenses_service.update_expense(
            db_session=db_session, expense_id=created.id,
            expense_data=ExpenseUpdate(amount=Decimal("150.00")), user_id=user_id,
        )

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("-150.00")
    finally:
        db_session.close()


# Tests that an expense_date change on a linked Expense synchronizes the
# projection's transaction_date.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the projection's transaction_date matches
#   the new expense_date.
def test_update_expense_date_sync_when_linked(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("100.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual", account_id=account.id,
            ),
            user_id=user_id,
        )

        expenses_service.update_expense(
            db_session=db_session, expense_id=created.id,
            expense_data=ExpenseUpdate(expense_date=date(2026, 9, 15)), user_id=user_id,
        )

        projection = account_transaction_repository.get_expense_projection(
            db_session=db_session, expense_id=created.id, user_id=user_id,
        )
        assert projection.transaction_date == date(2026, 9, 15)
    finally:
        db_session.close()


# Tests that title/description/source/category updates on a linked
# Expense do not touch the projection at all.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the projection's own amount/date stay
#   exactly as they were after each metadata-only update.
def test_update_expense_metadata_only_does_not_touch_projection(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("100.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual", account_id=account.id,
            ),
            user_id=user_id,
        )
        before = account_transaction_repository.get_expense_projection(
            db_session=db_session, expense_id=created.id, user_id=user_id,
        )

        for update in (
            ExpenseUpdate(title="Weekly groceries"),
            ExpenseUpdate(description="Updated note"),
            ExpenseUpdate(source="receipt"),
        ):
            expenses_service.update_expense(
                db_session=db_session, expense_id=created.id,
                expense_data=update, user_id=user_id,
            )

        after = account_transaction_repository.get_expense_projection(
            db_session=db_session, expense_id=created.id, user_id=user_id,
        )
        assert after.id == before.id
        assert after.amount == before.amount
        assert after.transaction_date == before.transaction_date
        assert after.description is None
    finally:
        db_session.close()


# ------------------------------------------------------------------
# UPDATE - attach / detach / move
# ------------------------------------------------------------------


# Tests attaching a previously-unlinked Expense to an Account.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if a projection is created and the Account
#   balance reflects it.
def test_update_expense_attach_creates_projection(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("300.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual",
            ),
            user_id=user_id,
        )

        result = expenses_service.update_expense(
            db_session=db_session, expense_id=created.id,
            expense_data=ExpenseUpdate(account_id=account.id), user_id=user_id,
        )

        assert result.account_id == account.id
        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("-300.00")
    finally:
        db_session.close()


# Tests detaching a linked Expense.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the projection is gone and the Account
#   balance returns to 0.
def test_update_expense_detach_removes_projection(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("300.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual", account_id=account.id,
            ),
            user_id=user_id,
        )

        result = expenses_service.update_expense(
            db_session=db_session, expense_id=created.id,
            expense_data=ExpenseUpdate(account_id=None), user_id=user_id,
        )

        assert result.account_id is None
        assert account_transaction_repository.get_expense_projection(
            db_session=db_session, expense_id=created.id, user_id=user_id,
        ) is None

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("0.00")
    finally:
        db_session.close()


# Tests moving a linked Expense from Account A to Account B - the
# projection row is updated in place (same id, same created_at), not
# deleted and recreated.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the projection id/created_at are preserved
#   and balances shift correctly between the two Accounts.
def test_update_expense_move_preserves_projection_id(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account_a = _create_account(db_session, user_id, name="A")
        account_b = _create_account(db_session, user_id, name="B")
        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("300.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual", account_id=account_a.id,
            ),
            user_id=user_id,
        )
        before = account_transaction_repository.get_expense_projection(
            db_session=db_session, expense_id=created.id, user_id=user_id,
        )

        result = expenses_service.update_expense(
            db_session=db_session, expense_id=created.id,
            expense_data=ExpenseUpdate(account_id=account_b.id), user_id=user_id,
        )

        after = account_transaction_repository.get_expense_projection(
            db_session=db_session, expense_id=created.id, user_id=user_id,
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
        assert balance_b == Decimal("-300.00")
    finally:
        db_session.close()


# Tests that moving a linked Expense INTO an archived Account is
# rejected.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if AccountArchivedError is raised.
def test_update_expense_move_into_archived_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account_a = _create_account(db_session, user_id, name="A")
        account_b = _create_account(db_session, user_id, name="B")
        _archive(db_session, user_id, account_b.id)

        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("100.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual", account_id=account_a.id,
            ),
            user_id=user_id,
        )

        with pytest.raises(AccountArchivedError):
            expenses_service.update_expense(
                db_session=db_session, expense_id=created.id,
                expense_data=ExpenseUpdate(account_id=account_b.id), user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that moving a linked Expense OUT of an archived Account (into an
# active one) is allowed.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the move succeeds.
def test_update_expense_move_out_of_archived_allowed(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account_a = _create_account(db_session, user_id, name="A")
        account_b = _create_account(db_session, user_id, name="B")

        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("100.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual", account_id=account_a.id,
            ),
            user_id=user_id,
        )

        _archive(db_session, user_id, account_a.id)

        result = expenses_service.update_expense(
            db_session=db_session, expense_id=created.id,
            expense_data=ExpenseUpdate(account_id=account_b.id), user_id=user_id,
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
def test_update_expense_same_account_currency_change_matching_succeeds(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, currency="EUR")
        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("100.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual", account_id=account.id,
            ),
            user_id=user_id,
        )

        result = expenses_service.update_expense(
            db_session=db_session, expense_id=created.id,
            expense_data=ExpenseUpdate(currency="eur"), user_id=user_id,
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
# - None. The test passes if ExpenseAccountCurrencyMismatchError is
#   raised, with no silent auto-detach.
def test_update_expense_same_account_currency_change_mismatched_rejected(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, currency="EUR")
        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("100.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual", account_id=account.id,
            ),
            user_id=user_id,
        )

        with pytest.raises(ExpenseAccountCurrencyMismatchError):
            expenses_service.update_expense(
                db_session=db_session, expense_id=created.id,
                expense_data=ExpenseUpdate(currency="USD"), user_id=user_id,
            )

        # No silent auto-detach: the projection must still exist.
        assert account_transaction_repository.get_expense_projection(
            db_session=db_session, expense_id=created.id, user_id=user_id,
        ) is not None
    finally:
        db_session.close()


# Tests that changing currency AND account_id together in the same PATCH
# is validated against the FINAL combination, not intermediate states -
# EUR Expense on EUR Account A moving to USD Account B while also
# changing to USD succeeds because the final currency matches the final
# Account.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the combined update succeeds.
def test_update_expense_currency_and_account_id_together_final_state_valid(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account_a = _create_account(db_session, user_id, name="A", currency="EUR")
        account_b = _create_account(db_session, user_id, name="B", currency="USD")

        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("100.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual", account_id=account_a.id,
            ),
            user_id=user_id,
        )

        result = expenses_service.update_expense(
            db_session=db_session, expense_id=created.id,
            expense_data=ExpenseUpdate(currency="USD", account_id=account_b.id),
            user_id=user_id,
        )

        assert result.currency == "USD"
        assert result.account_id == account_b.id
    finally:
        db_session.close()


# Tests that changing currency AND detaching in the same PATCH succeeds,
# since the final Expense is unlinked and has no Account currency to
# match at all.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the combined update succeeds.
def test_update_expense_currency_and_detach_together_succeeds(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, currency="EUR")
        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("100.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual", account_id=account.id,
            ),
            user_id=user_id,
        )

        result = expenses_service.update_expense(
            db_session=db_session, expense_id=created.id,
            expense_data=ExpenseUpdate(currency="USD", account_id=None), user_id=user_id,
        )

        assert result.currency == "USD"
        assert result.account_id is None
    finally:
        db_session.close()


# ------------------------------------------------------------------
# UPDATE - virtual field safety
# ------------------------------------------------------------------


# Tests that account_id is never persisted as a stray ORM attribute on
# ExpenseModel.
# This test exists as the direct VF-017E regression mirroring the
# VF-017D Income requirement: Expense has no account_id database column,
# so expenses_repository.update_expense's generic update_data loop must
# structurally exclude it. Calls the repository function directly
# (bypassing the service) with an ExpenseUpdate that sets account_id,
# then re-queries a completely fresh ExpenseModel instance and confirms
# it has no account_id-driven side effect.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the persisted row round-trips with no
#   account_id attribute error and the real columns are correct.
def test_update_expense_virtual_account_id_never_persisted_on_expense_model(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("100.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual",
            ),
            user_id=user_id,
        )

        expense_model = expenses_repository.get_expense_by_id_for_update(
            db_session=db_session, expense_id=created.id, user_id=user_id,
        )

        expenses_repository.update_expense(
            db_session=db_session,
            expense_model=expense_model,
            expense_data=ExpenseUpdate(account_id=account.id, description="test"),
            base_amount=expense_model.base_amount,
            base_currency=expense_model.base_currency,
            fx_rate=expense_model.fx_rate,
            fx_rate_date=expense_model.fx_rate_date,
            fx_source=expense_model.fx_source,
        )
    finally:
        db_session.close()

    verify_session = SessionLocal()
    try:
        fresh = (
            verify_session.query(ExpenseModel).filter(ExpenseModel.id == created.id).first()
        )
        assert fresh is not None
        assert fresh.description == "test"
        assert not hasattr(fresh, "account_id")
        assert "account_id" not in ExpenseModel.__table__.columns
    finally:
        verify_session.close()


# ------------------------------------------------------------------
# UPDATE - archived semantics
# ------------------------------------------------------------------


# Tests that amount/date corrections to an Expense already linked to an
# Account archived AFTERWARD are allowed - this is maintenance of
# existing history, not new activity.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the amount correction succeeds and the
#   Account balance reflects it.
def test_update_expense_amount_correction_on_later_archived_account_allowed(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("100.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual", account_id=account.id,
            ),
            user_id=user_id,
        )

        _archive(db_session, user_id, account.id)

        result = expenses_service.update_expense(
            db_session=db_session, expense_id=created.id,
            expense_data=ExpenseUpdate(amount=Decimal("150.00")), user_id=user_id,
        )
        assert result.amount == Decimal("150.00")

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("-150.00")
    finally:
        db_session.close()


# Tests that detaching a linked Expense from an archived Account is
# allowed.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the detach succeeds.
def test_update_expense_detach_from_archived_account_allowed(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("100.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual", account_id=account.id,
            ),
            user_id=user_id,
        )

        _archive(db_session, user_id, account.id)

        result = expenses_service.update_expense(
            db_session=db_session, expense_id=created.id,
            expense_data=ExpenseUpdate(account_id=None), user_id=user_id,
        )
        assert result.account_id is None
    finally:
        db_session.close()


# ------------------------------------------------------------------
# UPDATE - legacy unresolved FX (VF-017E, mandatory matrix)
# ------------------------------------------------------------------


# Tests that attaching a legacy unresolved-FX Expense to a same-currency
# active Account succeeds without ever calling the FX provider, and the
# Expense's FX snapshot remains fully NULL afterward.
# This test exists as the core VF-017E legacy-FX guarantee: the ledger
# only needs the Expense's own currency/amount, never base_amount, so
# linkage must never become an implicit legacy-FX-backfill mechanism.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to make any FX call fail loudly.
# Returns:
# - None. The test passes if the attach succeeds, the Account balance
#   reflects it, and every FX snapshot field is still None.
def test_update_expense_attach_legacy_unresolved_makes_no_fx_call(
    clean_database: None, monkeypatch: MonkeyPatch,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, currency="USD")
        legacy = _create_legacy_unresolved_expense(db_session, user_id, currency="USD")

        monkeypatch.setattr(
            expenses_service.fx_service, "resolve_fx_rate", _fail_if_fx_called,
        )

        result = expenses_service.update_expense(
            db_session=db_session, expense_id=legacy.id,
            expense_data=ExpenseUpdate(account_id=account.id), user_id=user_id,
        )

        assert result.account_id == account.id
        assert result.base_amount is None
        assert result.base_currency is None
        assert result.fx_rate is None
        assert result.fx_rate_date is None
        assert result.fx_source is None

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("-100.00")
    finally:
        db_session.close()


# Tests that detaching a linked legacy unresolved-FX Expense makes no FX
# call and leaves the snapshot unresolved.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to make any FX call fail loudly.
# Returns:
# - None. The test passes if the detach succeeds with no FX call.
def test_update_expense_detach_legacy_unresolved_makes_no_fx_call(
    clean_database: None, monkeypatch: MonkeyPatch,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, currency="USD")
        legacy = _create_legacy_unresolved_expense(db_session, user_id, currency="USD")
        account_transaction_repository.create_expense_projection(
            db_session=db_session, account_id=account.id, expense_id=legacy.id,
            user_id=user_id, amount=legacy.amount, transaction_date=legacy.expense_date,
        )

        monkeypatch.setattr(
            expenses_service.fx_service, "resolve_fx_rate", _fail_if_fx_called,
        )

        result = expenses_service.update_expense(
            db_session=db_session, expense_id=legacy.id,
            expense_data=ExpenseUpdate(account_id=None), user_id=user_id,
        )

        assert result.account_id is None
        assert result.base_amount is None
        assert account_transaction_repository.get_expense_projection(
            db_session=db_session, expense_id=legacy.id, user_id=user_id,
        ) is None
    finally:
        db_session.close()


# Tests that moving a linked legacy unresolved-FX Expense between two
# same-currency Accounts makes no FX call and leaves the snapshot
# unresolved.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to make any FX call fail loudly.
# Returns:
# - None. The test passes if the move succeeds with no FX call.
def test_update_expense_move_legacy_unresolved_makes_no_fx_call(
    clean_database: None, monkeypatch: MonkeyPatch,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account_a = _create_account(db_session, user_id, name="A", currency="USD")
        account_b = _create_account(db_session, user_id, name="B", currency="USD")
        legacy = _create_legacy_unresolved_expense(db_session, user_id, currency="USD")
        account_transaction_repository.create_expense_projection(
            db_session=db_session, account_id=account_a.id, expense_id=legacy.id,
            user_id=user_id, amount=legacy.amount, transaction_date=legacy.expense_date,
        )

        monkeypatch.setattr(
            expenses_service.fx_service, "resolve_fx_rate", _fail_if_fx_called,
        )

        result = expenses_service.update_expense(
            db_session=db_session, expense_id=legacy.id,
            expense_data=ExpenseUpdate(account_id=account_b.id), user_id=user_id,
        )

        assert result.account_id == account_b.id
        assert result.base_amount is None
    finally:
        db_session.close()


# Tests that a metadata-only update (title) on a linked legacy
# unresolved-FX Expense makes no FX call, leaves the snapshot
# unresolved, and does not touch the projection.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to make any FX call fail loudly.
# Returns:
# - None. The test passes if the update succeeds with no FX call and the
#   projection is unchanged.
def test_update_expense_metadata_only_legacy_unresolved_linked_makes_no_fx_call(
    clean_database: None, monkeypatch: MonkeyPatch,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, currency="USD")
        legacy = _create_legacy_unresolved_expense(db_session, user_id, currency="USD")
        account_transaction_repository.create_expense_projection(
            db_session=db_session, account_id=account.id, expense_id=legacy.id,
            user_id=user_id, amount=legacy.amount, transaction_date=legacy.expense_date,
        )

        monkeypatch.setattr(
            expenses_service.fx_service, "resolve_fx_rate", _fail_if_fx_called,
        )

        result = expenses_service.update_expense(
            db_session=db_session, expense_id=legacy.id,
            expense_data=ExpenseUpdate(title="Renamed legacy expense"), user_id=user_id,
        )

        assert result.title == "Renamed legacy expense"
        assert result.account_id == account.id
        assert result.base_amount is None
    finally:
        db_session.close()


# Tests that an amount update on an already-linked legacy unresolved-FX
# Expense DOES force full FX resolution - this is pre-existing Expense
# behavior (a legacy row receiving any monetary update forces
# resolution), unrelated to and unaffected by Account linkage. Confirms
# linkage does not weaken or bypass this existing rule.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to provide a deterministic FX rate.
# Returns:
# - None. The test passes if the snapshot becomes fully resolved and the
#   projection amount syncs to the new value.
def test_update_expense_amount_change_legacy_unresolved_linked_resolves_fx(
    clean_database: None, monkeypatch: MonkeyPatch,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id, currency="USD")
        legacy = _create_legacy_unresolved_expense(db_session, user_id, currency="USD")
        account_transaction_repository.create_expense_projection(
            db_session=db_session, account_id=account.id, expense_id=legacy.id,
            user_id=user_id, amount=legacy.amount, transaction_date=legacy.expense_date,
        )

        resolve_calls = []

        def fake_resolve_fx_rate(original_currency, base_currency, transaction_date, as_of):
            resolve_calls.append((original_currency, base_currency, transaction_date))
            from app.modules.fx.fx_schemas import FxRateResult
            return FxRateResult(rate=Decimal("0.9"), actual_rate_date=transaction_date, source="ecb")

        monkeypatch.setattr(expenses_service.fx_service, "resolve_fx_rate", fake_resolve_fx_rate)

        result = expenses_service.update_expense(
            db_session=db_session, expense_id=legacy.id,
            expense_data=ExpenseUpdate(amount=Decimal("200.00")), user_id=user_id,
        )

        assert len(resolve_calls) == 1
        assert result.base_amount is not None
        assert result.fx_source == "ecb"

        projection = account_transaction_repository.get_expense_projection(
            db_session=db_session, expense_id=legacy.id, user_id=user_id,
        )
        assert projection.amount == Decimal("200.00")
    finally:
        db_session.close()


# ------------------------------------------------------------------
# DELETE
# ------------------------------------------------------------------


# Tests that deleting a linked Expense removes its projection via
# CASCADE and leaves the Account balance correct, with no orphan row.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the Expense is gone, the projection is
#   gone, and the Account balance returns to 0.
def test_delete_expense_linked_cascades_projection_balance_correct(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("500.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual", account_id=account.id,
            ),
            user_id=user_id,
        )

        expenses_service.delete_expense(
            db_session=db_session, expense_id=created.id, user_id=user_id,
        )

        remaining_expense = (
            db_session.query(ExpenseModel).filter(ExpenseModel.id == created.id).first()
        )
        assert remaining_expense is None

        assert account_transaction_repository.get_expense_projection(
            db_session=db_session, expense_id=created.id, user_id=user_id,
        ) is None

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("0.00")
    finally:
        db_session.close()


# Tests that deleting a linked Expense from an archived Account is
# allowed.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the delete succeeds.
def test_delete_expense_linked_to_archived_account_allowed(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("100.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="manual", account_id=account.id,
            ),
            user_id=user_id,
        )

        _archive(db_session, user_id, account.id)

        expenses_service.delete_expense(
            db_session=db_session, expense_id=created.id, user_id=user_id,
        )

        remaining = (
            db_session.query(ExpenseModel).filter(ExpenseModel.id == created.id).first()
        )
        assert remaining is None
    finally:
        db_session.close()


# ------------------------------------------------------------------
# DELETE - Receipt interaction (VF-017E, mandatory combined test)
# ------------------------------------------------------------------


# Tests that deleting an Expense that is BOTH linked to an Account AND
# referenced by a Receipt correctly fires both independent FK actions
# from the one DELETE statement: the AccountTransaction projection is
# removed via CASCADE, and the Receipt survives with expense_id set to
# NULL via its own, entirely separate SET NULL FK.
# This test exists because this exact combination (two independent child
# tables reacting to one parent DELETE) has never been exercised in this
# codebase before VF-017E.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the Expense and its projection are both
#   gone, the Account balance is restored, and the Receipt still exists
#   with expense_id == None.
def test_delete_expense_linked_to_account_and_receipt_both_fk_actions_fire(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        created = expenses_service.create_expense(
            db_session=db_session,
            expense_data=ExpenseCreate(
                title="Groceries", amount=Decimal("40.00"), currency="EUR",
                expense_date=date(2026, 9, 1), source="receipt", account_id=account.id,
            ),
            user_id=user_id,
        )

        receipt = ReceiptModel(
            user_id=user_id,
            file_url="local://receipts/dummy.jpg",
            storage_path="uploads/receipts/dummy.jpg",
            status="confirmed",
            expense_id=created.id,
        )
        db_session.add(receipt)
        db_session.commit()
        db_session.refresh(receipt)

        expenses_service.delete_expense(
            db_session=db_session, expense_id=created.id, user_id=user_id,
        )

        remaining_expense = (
            db_session.query(ExpenseModel).filter(ExpenseModel.id == created.id).first()
        )
        assert remaining_expense is None

        assert account_transaction_repository.get_expense_projection(
            db_session=db_session, expense_id=created.id, user_id=user_id,
        ) is None

        balance = account_transaction_repository.calculate_ledger_balance(
            db_session=db_session, account_id=account.id, user_id=user_id,
        )
        assert balance == Decimal("0.00")

        surviving_receipt = receipt_repository.get_receipt_by_id(
            db_session=db_session, receipt_id=receipt.id, user_id=user_id,
        )
        assert surviving_receipt is not None
        assert surviving_receipt.expense_id is None
        assert surviving_receipt.status == "confirmed"
    finally:
        db_session.close()
