from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.database_session import SessionLocal
from app.modules.income import income_repository
from app.modules.income.income_errors import IncomeNotFoundError
from app.modules.income.income_models import IncomeModel
from app.modules.income.income_schemas import IncomeCreate, IncomeUpdate


def _create_income(db_session, user_id, received_at=date(2026, 5, 7), amount=Decimal("2500.00")):
    return income_repository.create_income(
        db_session=db_session,
        income_data=IncomeCreate(
            amount=amount, currency="EUR", received_at=received_at, source="salary",
        ),
        user_id=user_id,
        base_amount=amount,
        base_currency="EUR",
        fx_rate=Decimal("1.00000000"),
        fx_rate_date=received_at,
        fx_source="identity",
    )


# Tests that the repository creates a new income record with its FX
# snapshot.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the created model contains the expected
#   values.
def test_create_income_creates_new_income(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        created = _create_income(db_session, user_id)

        assert isinstance(created, IncomeModel)
        assert created.user_id == user_id
        assert created.amount == Decimal("2500.00")
        assert created.currency == "EUR"
        assert created.source == "salary"
        assert created.base_amount == Decimal("2500.00")
        assert created.fx_source == "identity"
        assert created.id is not None
    finally:
        db_session.close()


# Tests that the repository returns only the requesting user's income
# records, newest received_at first.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if ownership scoping and ordering are correct.
def test_get_income_returns_owned_records_newest_first(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        older = _create_income(db_session, user_id, received_at=date(2026, 5, 1))
        newer = _create_income(db_session, user_id, received_at=date(2026, 5, 10))
        _create_income(db_session, other_user_id, received_at=date(2026, 5, 15))

        records = income_repository.get_income(db_session=db_session, user_id=user_id)

        assert [r.id for r in records] == [newer.id, older.id]
    finally:
        db_session.close()


# Tests that get_income_by_id raises IncomeNotFoundError for a missing or
# other-user income record.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if IncomeNotFoundError is raised.
def test_get_income_by_id_raises_not_found_for_other_user(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        income = _create_income(db_session, other_user_id)

        with pytest.raises(IncomeNotFoundError):
            income_repository.get_income_by_id(
                db_session=db_session, income_id=income.id, user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that update_income applies field changes and the given FX
# snapshot together.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both the field change and snapshot are
#   persisted.
def test_update_income_applies_fields_and_snapshot(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        income = _create_income(db_session, user_id)

        updated = income_repository.update_income(
            db_session=db_session,
            income_model=income,
            income_data=IncomeUpdate(amount=Decimal("3000.00")),
            base_amount=Decimal("3000.00"),
            base_currency="EUR",
            fx_rate=Decimal("1.00000000"),
            fx_rate_date=date(2026, 5, 7),
            fx_source="identity",
        )

        assert updated.amount == Decimal("3000.00")
        assert updated.base_amount == Decimal("3000.00")
    finally:
        db_session.close()


# Tests that delete_income removes the record.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if a subsequent lookup raises IncomeNotFoundError.
def test_delete_income_removes_record(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        income = _create_income(db_session, user_id)

        income_repository.delete_income(
            db_session=db_session, income_model=income,
        )

        with pytest.raises(IncomeNotFoundError):
            income_repository.get_income_by_id(
                db_session=db_session, income_id=income.id, user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that get_income_by_id_for_update returns the owned income record,
# locked.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the correct IncomeModel instance is
#   returned.
def test_get_income_by_id_for_update_returns_owned_income(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        income = _create_income(db_session, user_id)

        locked = income_repository.get_income_by_id_for_update(
            db_session=db_session, income_id=income.id, user_id=user_id,
        )

        assert locked.id == income.id
        assert locked.user_id == user_id
    finally:
        db_session.close()


# Tests that get_income_by_id_for_update raises IncomeNotFoundError for a
# missing or other-user income record.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if IncomeNotFoundError is raised.
def test_get_income_by_id_for_update_raises_not_found_for_other_user(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        income = _create_income(db_session, other_user_id)

        with pytest.raises(IncomeNotFoundError):
            income_repository.get_income_by_id_for_update(
                db_session=db_session, income_id=income.id, user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that get_income_in_date_range returns exactly the user's records
# whose received_at falls inside the inclusive [start_date, end_date]
# window (VF-019B) - both boundary days included, the days just outside
# excluded.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the in-range records are returned.
def test_get_income_in_date_range_is_inclusive_and_bounded(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        before = _create_income(db_session, user_id, received_at=date(2026, 8, 31))
        first_day = _create_income(db_session, user_id, received_at=date(2026, 9, 1))
        middle = _create_income(db_session, user_id, received_at=date(2026, 9, 15))
        last_day = _create_income(db_session, user_id, received_at=date(2026, 9, 30))
        after = _create_income(db_session, user_id, received_at=date(2026, 10, 1))

        found = income_repository.get_income_in_date_range(
            db_session=db_session,
            user_id=user_id,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        )

        found_ids = {income.id for income in found}
        assert found_ids == {first_day.id, middle.id, last_day.id}
        assert before.id not in found_ids
        assert after.id not in found_ids
    finally:
        db_session.close()


# Tests that get_income_in_date_range never returns another user's income,
# even on the same dates (VF-019B ownership).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the requesting user's record is returned.
def test_get_income_in_date_range_is_user_scoped(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        own = _create_income(db_session, user_id, received_at=date(2026, 9, 10))
        _create_income(db_session, other_user_id, received_at=date(2026, 9, 10))

        found = income_repository.get_income_in_date_range(
            db_session=db_session,
            user_id=user_id,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        )

        assert [income.id for income in found] == [own.id]
    finally:
        db_session.close()
