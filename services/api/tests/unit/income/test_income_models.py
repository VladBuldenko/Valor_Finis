from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.db.database_session import SessionLocal
from app.modules.income.income_models import IncomeModel


def _base_kwargs(user_id):
    return dict(
        user_id=user_id,
        amount=Decimal("2500.00"),
        currency="EUR",
        received_at=date(2026, 5, 7),
        source="salary",
    )


# Tests that an income row with valid fields and a full identity FX
# snapshot persists.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the row is persisted with the expected fields.
def test_income_with_valid_fields_persists(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        income = IncomeModel(
            **_base_kwargs(user_id),
            base_amount=Decimal("2500.00"),
            base_currency="EUR",
            fx_rate=Decimal("1.00000000"),
            fx_rate_date=date(2026, 5, 7),
            fx_source="identity",
        )
        db_session.add(income)
        db_session.commit()
        db_session.refresh(income)

        assert income.id is not None
        assert income.user_id == user_id
        assert income.amount == Decimal("2500.00")
        assert income.currency == "EUR"
        assert income.received_at == date(2026, 5, 7)
        assert income.source == "salary"
        assert income.base_amount == Decimal("2500.00")
        assert income.created_at is not None
        assert income.updated_at is not None
    finally:
        db_session.close()


# Tests that a zero amount is rejected by the amount > 0 CHECK constraint.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_income_zero_amount_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        kwargs = _base_kwargs(user_id)
        kwargs["amount"] = Decimal("0.00")
        db_session.add(IncomeModel(**kwargs))

        try:
            db_session.commit()
            assert False, "expected IntegrityError for zero amount"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a negative amount is rejected by the amount > 0 CHECK
# constraint.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_income_negative_amount_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        kwargs = _base_kwargs(user_id)
        kwargs["amount"] = Decimal("-50.00")
        db_session.add(IncomeModel(**kwargs))

        try:
            db_session.commit()
            assert False, "expected IntegrityError for negative amount"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that every allowed source value is accepted by the source CHECK
# constraint.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if all five rows persist successfully.
def test_income_all_allowed_sources_accepted(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        for allowed_source in ("salary", "freelance", "refund", "gift", "other"):
            kwargs = _base_kwargs(user_id)
            kwargs["source"] = allowed_source
            db_session.add(IncomeModel(**kwargs))
        db_session.commit()

        rows = (
            db_session.query(IncomeModel).filter(IncomeModel.user_id == user_id).all()
        )
        assert {row.source for row in rows} == {
            "salary", "freelance", "refund", "gift", "other",
        }
    finally:
        db_session.close()


# Tests that a source outside the allowed set is rejected.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_income_invalid_source_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        kwargs = _base_kwargs(user_id)
        kwargs["source"] = "lottery"
        db_session.add(IncomeModel(**kwargs))

        try:
            db_session.commit()
            assert False, "expected IntegrityError for invalid source"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a partially-populated FX snapshot is rejected by the
# all-or-none CHECK constraint.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_income_partial_fx_snapshot_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        kwargs = _base_kwargs(user_id)
        kwargs["base_amount"] = Decimal("2500.00")
        # base_currency, fx_rate, fx_rate_date, fx_source left unset (NULL).
        db_session.add(IncomeModel(**kwargs))

        try:
            db_session.commit()
            assert False, "expected IntegrityError for partial FX snapshot"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a fully-NULL FX snapshot is allowed by the all-or-none CHECK
# constraint (both directions of the OR are valid).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the row persists with all five fields NULL.
def test_income_fully_null_fx_snapshot_allowed(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        db_session.add(IncomeModel(**_base_kwargs(user_id)))
        db_session.commit()
    finally:
        db_session.close()


# Tests that a negative fx_rate is rejected by the fx_rate positive CHECK
# constraint.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_income_negative_fx_rate_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        income = IncomeModel(
            **_base_kwargs(user_id),
            base_amount=Decimal("2000.00"),
            base_currency="EUR",
            fx_rate=Decimal("-0.85"),
            fx_rate_date=date(2026, 5, 7),
            fx_source="ecb",
        )
        db_session.add(income)

        try:
            db_session.commit()
            assert False, "expected IntegrityError for negative fx_rate"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that a non-positive base_amount is rejected by the base_amount
# positive CHECK constraint.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if committing raises IntegrityError.
def test_income_zero_base_amount_rejected(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        income = IncomeModel(
            **_base_kwargs(user_id),
            base_amount=Decimal("0.00"),
            base_currency="EUR",
            fx_rate=Decimal("1.00000000"),
            fx_rate_date=date(2026, 5, 7),
            fx_source="identity",
        )
        db_session.add(income)

        try:
            db_session.commit()
            assert False, "expected IntegrityError for zero base_amount"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()


# Tests that IncomeModel has no account_id column at all.
# This test exists as the definitive VF-017C invariant: linking Income to
# an Account is deferred to VF-017D, not partially scaffolded here.
# Parameters:
# - None.
# Returns:
# - None. The test passes if "account_id" is not a mapped column.
def test_income_model_has_no_account_id_column() -> None:
    column_names = {column.name for column in IncomeModel.__table__.columns}
    assert "account_id" not in column_names
