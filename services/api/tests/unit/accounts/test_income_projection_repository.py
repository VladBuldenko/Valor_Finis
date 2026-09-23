from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.db.database_session import SessionLocal
from app.modules.accounts import account_repository, account_transaction_repository
from app.modules.accounts.account_schemas import AccountCreate
from app.modules.income.income_models import IncomeModel


def _create_account(db_session, user_id, name="Main Checking"):
    return account_repository.create_account(
        db_session=db_session,
        account_data=AccountCreate(name=name, type="checking", currency="EUR"),
        user_id=user_id,
    )


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


# Tests that get_income_projection returns None for an unlinked Income.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the result is None.
def test_get_income_projection_none_when_unlinked(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        income = _create_income(db_session, user_id)

        projection = account_transaction_repository.get_income_projection(
            db_session=db_session, income_id=income.id, user_id=user_id,
        )
        assert projection is None
    finally:
        db_session.close()


# Tests that create_income_projection hardcodes kind="income",
# direction="credit", description=None, and correctly links account_id/
# income_id/amount/transaction_date.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the created row has exactly these values.
def test_create_income_projection_hardcodes_kind_and_direction(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        income = _create_income(db_session, user_id)

        projection = account_transaction_repository.create_income_projection(
            db_session=db_session,
            account_id=account.id,
            income_id=income.id,
            user_id=user_id,
            amount=Decimal("2500.00"),
            transaction_date=date(2026, 9, 23),
        )

        assert projection.kind == "income"
        assert projection.direction == "credit"
        assert projection.description is None
        assert projection.account_id == account.id
        assert projection.income_id == income.id
        assert projection.amount == Decimal("2500.00")

        resolved = account_transaction_repository.get_income_projection(
            db_session=db_session, income_id=income.id, user_id=user_id,
        )
        assert resolved is not None
        assert resolved.id == projection.id
    finally:
        db_session.close()


# Tests that update_income_projection changes only the fields explicitly
# passed, leaving the others untouched.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only amount changes when only amount is
#   passed, and account_id/transaction_date stay the same.
def test_update_income_projection_changes_only_given_fields(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        income = _create_income(db_session, user_id)

        projection = account_transaction_repository.create_income_projection(
            db_session=db_session, account_id=account.id, income_id=income.id,
            user_id=user_id, amount=Decimal("100.00"), transaction_date=date(2026, 9, 1),
        )

        updated = account_transaction_repository.update_income_projection(
            db_session=db_session, projection=projection, amount=Decimal("150.00"),
        )

        assert updated.amount == Decimal("150.00")
        assert updated.account_id == account.id
        assert updated.transaction_date == date(2026, 9, 1)
    finally:
        db_session.close()


# Tests that update_income_projection can move a projection's account_id.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if account_id changes and the row id is
#   preserved (updated in place, not delete+insert).
def test_update_income_projection_can_move_account_id(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account_a = _create_account(db_session, user_id, name="A")
        account_b = _create_account(db_session, user_id, name="B")
        income = _create_income(db_session, user_id)

        projection = account_transaction_repository.create_income_projection(
            db_session=db_session, account_id=account_a.id, income_id=income.id,
            user_id=user_id, amount=Decimal("100.00"), transaction_date=date(2026, 9, 1),
        )
        original_id = projection.id
        original_created_at = projection.created_at

        moved = account_transaction_repository.update_income_projection(
            db_session=db_session, projection=projection, account_id=account_b.id,
        )

        assert moved.id == original_id
        assert moved.created_at == original_created_at
        assert moved.account_id == account_b.id
    finally:
        db_session.close()


# Tests that delete_income_projection removes the row, and the Income
# itself is unaffected (still queryable).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the projection is gone and the Income row
#   still exists.
def test_delete_income_projection_removes_row_keeps_income(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        income = _create_income(db_session, user_id)

        projection = account_transaction_repository.create_income_projection(
            db_session=db_session, account_id=account.id, income_id=income.id,
            user_id=user_id, amount=Decimal("100.00"), transaction_date=date(2026, 9, 1),
        )

        account_transaction_repository.delete_income_projection(
            db_session=db_session, projection=projection,
        )

        assert account_transaction_repository.get_income_projection(
            db_session=db_session, income_id=income.id, user_id=user_id,
        ) is None

        still_exists = (
            db_session.query(IncomeModel).filter(IncomeModel.id == income.id).first()
        )
        assert still_exists is not None
    finally:
        db_session.close()


# Tests that get_income_account_links_for_user resolves multiple Incomes'
# links in one bulk query, correctly, and omits unlinked Incomes.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if linked Incomes map to their Account and
#   an unlinked Income has no entry.
def test_get_income_account_links_for_user_bulk_correct(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        linked_income = _create_income(db_session, user_id, amount=Decimal("100.00"))
        unlinked_income = _create_income(db_session, user_id, amount=Decimal("200.00"))

        account_transaction_repository.create_income_projection(
            db_session=db_session, account_id=account.id, income_id=linked_income.id,
            user_id=user_id, amount=Decimal("100.00"), transaction_date=date(2026, 9, 1),
        )

        links = account_transaction_repository.get_income_account_links_for_user(
            db_session=db_session, user_id=user_id,
        )

        assert links == {linked_income.id: account.id}
        assert unlinked_income.id not in links
    finally:
        db_session.close()


# Tests that another user's Income-to-Account links never leak into this
# user's bulk lookup.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the requesting user's link appears.
def test_get_income_account_links_for_user_ownership_isolation(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        account = _create_account(db_session, user_id)
        income = _create_income(db_session, user_id)
        account_transaction_repository.create_income_projection(
            db_session=db_session, account_id=account.id, income_id=income.id,
            user_id=user_id, amount=Decimal("10.00"), transaction_date=date(2026, 9, 1),
        )

        other_account = _create_account(db_session, other_user_id)
        other_income = _create_income(db_session, other_user_id, amount=Decimal("9999.00"))
        account_transaction_repository.create_income_projection(
            db_session=db_session, account_id=other_account.id, income_id=other_income.id,
            user_id=other_user_id, amount=Decimal("9999.00"), transaction_date=date(2026, 9, 1),
        )

        links = account_transaction_repository.get_income_account_links_for_user(
            db_session=db_session, user_id=user_id,
        )
        assert links == {income.id: account.id}
    finally:
        db_session.close()
