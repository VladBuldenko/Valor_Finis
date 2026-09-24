from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.db.database_session import SessionLocal
from app.modules.accounts import account_repository, account_transaction_repository
from app.modules.accounts.account_schemas import AccountCreate
from app.modules.accounts.account_transaction_models import AccountTransactionModel
from app.modules.expenses.expenses_models import ExpenseModel
from app.modules.income.income_models import IncomeModel


def _create_account(db_session, user_id, name="Main Checking"):
    return account_repository.create_account(
        db_session=db_session,
        account_data=AccountCreate(name=name, type="checking", currency="EUR"),
        user_id=user_id,
    )


def _create_expense(db_session, user_id, amount=Decimal("50.00")) -> ExpenseModel:
    expense = ExpenseModel(
        user_id=user_id,
        category_id=None,
        title="Groceries",
        amount=amount,
        currency="EUR",
        expense_date=date(2026, 9, 23),
        description=None,
        source="manual",
        base_amount=amount,
        base_currency="EUR",
        fx_rate=Decimal("1.00000000"),
        fx_rate_date=date(2026, 9, 23),
        fx_source="identity",
    )
    db_session.add(expense)
    db_session.commit()
    db_session.refresh(expense)
    return expense


def _create_income(db_session, user_id, amount=Decimal("2500.00")) -> IncomeModel:
    income = IncomeModel(
        user_id=user_id,
        amount=amount,
        currency="EUR",
        received_at=date(2026, 9, 23),
        source="salary",
        base_amount=amount,
        base_currency="EUR",
        fx_rate=Decimal("1.00000000"),
        fx_rate_date=date(2026, 9, 23),
        fx_source="identity",
    )
    db_session.add(income)
    db_session.commit()
    db_session.refresh(income)
    return income


# Tests that get_expense_projection returns None for an unlinked Expense.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the result is None.
def test_get_expense_projection_none_when_unlinked(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        expense = _create_expense(db_session, user_id)

        projection = account_transaction_repository.get_expense_projection(
            db_session=db_session, expense_id=expense.id, user_id=user_id,
        )
        assert projection is None
    finally:
        db_session.close()


# Tests that create_expense_projection hardcodes kind="expense",
# direction="debit", description=None, and correctly links account_id/
# expense_id/amount/transaction_date.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the created row has exactly these values.
def test_create_expense_projection_hardcodes_kind_and_direction(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        expense = _create_expense(db_session, user_id)

        projection = account_transaction_repository.create_expense_projection(
            db_session=db_session,
            account_id=account.id,
            expense_id=expense.id,
            user_id=user_id,
            amount=Decimal("50.00"),
            transaction_date=date(2026, 9, 23),
        )

        assert projection.kind == "expense"
        assert projection.direction == "debit"
        assert projection.description is None
        assert projection.account_id == account.id
        assert projection.expense_id == expense.id
        assert projection.income_id is None
        assert projection.amount == Decimal("50.00")

        resolved = account_transaction_repository.get_expense_projection(
            db_session=db_session, expense_id=expense.id, user_id=user_id,
        )
        assert resolved is not None
        assert resolved.id == projection.id
    finally:
        db_session.close()


# Tests that update_expense_projection changes only the fields explicitly
# passed, leaving the others untouched.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only amount changes when only amount is
#   passed, and account_id/transaction_date stay the same.
def test_update_expense_projection_changes_only_given_fields(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        expense = _create_expense(db_session, user_id)

        projection = account_transaction_repository.create_expense_projection(
            db_session=db_session, account_id=account.id, expense_id=expense.id,
            user_id=user_id, amount=Decimal("50.00"), transaction_date=date(2026, 9, 1),
        )

        updated = account_transaction_repository.update_expense_projection(
            db_session=db_session, projection=projection, amount=Decimal("75.00"),
        )

        assert updated.amount == Decimal("75.00")
        assert updated.account_id == account.id
        assert updated.transaction_date == date(2026, 9, 1)
    finally:
        db_session.close()


# Tests that update_expense_projection can move a projection's account_id.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if account_id changes and the row id is
#   preserved (updated in place, not delete+insert).
def test_update_expense_projection_can_move_account_id(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account_a = _create_account(db_session, user_id, name="A")
        account_b = _create_account(db_session, user_id, name="B")
        expense = _create_expense(db_session, user_id)

        projection = account_transaction_repository.create_expense_projection(
            db_session=db_session, account_id=account_a.id, expense_id=expense.id,
            user_id=user_id, amount=Decimal("50.00"), transaction_date=date(2026, 9, 1),
        )
        original_id = projection.id
        original_created_at = projection.created_at

        moved = account_transaction_repository.update_expense_projection(
            db_session=db_session, projection=projection, account_id=account_b.id,
        )

        assert moved.id == original_id
        assert moved.created_at == original_created_at
        assert moved.account_id == account_b.id
    finally:
        db_session.close()


# Tests that delete_expense_projection removes the row, and the Expense
# itself is unaffected (still queryable).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the projection is gone and the Expense row
#   still exists.
def test_delete_expense_projection_removes_row_keeps_expense(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        expense = _create_expense(db_session, user_id)

        projection = account_transaction_repository.create_expense_projection(
            db_session=db_session, account_id=account.id, expense_id=expense.id,
            user_id=user_id, amount=Decimal("50.00"), transaction_date=date(2026, 9, 1),
        )

        account_transaction_repository.delete_expense_projection(
            db_session=db_session, projection=projection,
        )

        assert account_transaction_repository.get_expense_projection(
            db_session=db_session, expense_id=expense.id, user_id=user_id,
        ) is None

        still_exists = (
            db_session.query(ExpenseModel).filter(ExpenseModel.id == expense.id).first()
        )
        assert still_exists is not None
    finally:
        db_session.close()


# Tests that get_expense_account_links_for_user resolves multiple
# Expenses' links in one bulk query, correctly, and omits unlinked
# Expenses.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if linked Expenses map to their Account and an
#   unlinked Expense has no entry.
def test_get_expense_account_links_for_user_bulk_correct(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        linked_expense = _create_expense(db_session, user_id, amount=Decimal("50.00"))
        unlinked_expense = _create_expense(db_session, user_id, amount=Decimal("20.00"))

        account_transaction_repository.create_expense_projection(
            db_session=db_session, account_id=account.id, expense_id=linked_expense.id,
            user_id=user_id, amount=Decimal("50.00"), transaction_date=date(2026, 9, 1),
        )

        links = account_transaction_repository.get_expense_account_links_for_user(
            db_session=db_session, user_id=user_id,
        )

        assert links == {linked_expense.id: account.id}
        assert unlinked_expense.id not in links
    finally:
        db_session.close()


# Tests that another user's Expense-to-Account links never leak into this
# user's bulk lookup.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the requesting user's link appears.
def test_get_expense_account_links_for_user_ownership_isolation(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        expense = _create_expense(db_session, user_id)
        account_transaction_repository.create_expense_projection(
            db_session=db_session, account_id=account.id, expense_id=expense.id,
            user_id=user_id, amount=Decimal("10.00"), transaction_date=date(2026, 9, 1),
        )

        other_account = _create_account(db_session, other_user_id)
        other_expense = _create_expense(db_session, other_user_id, amount=Decimal("999.00"))
        account_transaction_repository.create_expense_projection(
            db_session=db_session, account_id=other_account.id, expense_id=other_expense.id,
            user_id=other_user_id, amount=Decimal("999.00"), transaction_date=date(2026, 9, 1),
        )

        links = account_transaction_repository.get_expense_account_links_for_user(
            db_session=db_session, user_id=user_id,
        )
        assert links == {expense.id: account.id}
    finally:
        db_session.close()


# Tests that update_expense_projection refuses to mutate a direct
# adjustment row (not an Expense projection) - mirrors the guard test
# proven for Income projections.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if a ValueError is raised and the row's
#   amount/account_id/transaction_date are unchanged afterward.
def test_update_expense_projection_rejects_direct_adjustment_row(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        direct_row = account_transaction_repository.create_transaction(
            db_session=db_session, account_id=account.id, user_id=user_id,
            kind="adjustment", direction="debit", amount=Decimal("100.00"),
            transaction_date=date(2026, 9, 1), description=None,
        )

        try:
            account_transaction_repository.update_expense_projection(
                db_session=db_session, projection=direct_row, amount=Decimal("999.00"),
            )
            assert False, "expected ValueError"
        except ValueError:
            pass

        db_session.refresh(direct_row)
        assert direct_row.amount == Decimal("100.00")
        assert direct_row.account_id == account.id
        assert direct_row.transaction_date == date(2026, 9, 1)
    finally:
        db_session.close()


# Tests that delete_expense_projection refuses to delete a direct
# adjustment row (not an Expense projection).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if a ValueError is raised and the row still
#   exists in the database afterward.
def test_delete_expense_projection_rejects_direct_adjustment_row(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        direct_row = account_transaction_repository.create_transaction(
            db_session=db_session, account_id=account.id, user_id=user_id,
            kind="adjustment", direction="debit", amount=Decimal("100.00"),
            transaction_date=date(2026, 9, 1), description=None,
        )
        direct_row_id = direct_row.id

        try:
            account_transaction_repository.delete_expense_projection(
                db_session=db_session, projection=direct_row,
            )
            assert False, "expected ValueError"
        except ValueError:
            pass

        still_exists = (
            db_session.query(AccountTransactionModel)
            .filter(AccountTransactionModel.id == direct_row_id)
            .first()
        )
        assert still_exists is not None
    finally:
        db_session.close()


# Tests that update_expense_projection and delete_expense_projection also
# refuse to touch a genuine Income projection row - proving a mistaken
# cross-source call can never mutate the wrong source's row, not merely
# that direct opening_balance/adjustment rows are protected.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both calls raise ValueError and the Income
#   projection is left completely unchanged.
def test_expense_projection_mutators_reject_income_projection_row(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        income = _create_income(db_session, user_id)
        income_projection = account_transaction_repository.create_income_projection(
            db_session=db_session, account_id=account.id, income_id=income.id,
            user_id=user_id, amount=Decimal("2500.00"), transaction_date=date(2026, 9, 1),
        )
        projection_id = income_projection.id

        try:
            account_transaction_repository.update_expense_projection(
                db_session=db_session, projection=income_projection, amount=Decimal("999.00"),
            )
            assert False, "expected ValueError"
        except ValueError:
            pass

        try:
            account_transaction_repository.delete_expense_projection(
                db_session=db_session, projection=income_projection,
            )
            assert False, "expected ValueError"
        except ValueError:
            pass

        db_session.refresh(income_projection)
        assert income_projection.id == projection_id
        assert income_projection.amount == Decimal("2500.00")
        assert income_projection.kind == "income"
    finally:
        db_session.close()
