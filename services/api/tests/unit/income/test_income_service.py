from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pytest import MonkeyPatch

from app.db.database_session import SessionLocal
from app.modules.fx.fx_errors import FxFutureDatedNotSupportedError
from app.modules.fx.fx_schemas import FxRateResult
from app.modules.income import income_service
from app.modules.income.income_errors import IncomeFutureDatedNotSupportedError, IncomeNotFoundError
from app.modules.income.income_schemas import IncomeCreate, IncomeResponse, IncomeUpdate


# Tests that creating a EUR income record produces a complete identity FX
# snapshot with no provider involvement at all (the identity branch in
# fx_service.resolve_fx_rate never calls a provider, so this needs no
# monkeypatching to stay network-free).
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the response carries a complete identity
#   snapshot.
def test_create_income_eur_identity_snapshot(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        result = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("2500.00"), currency="EUR",
                received_at=date(2026, 5, 7), source="salary",
            ),
            user_id=user_id,
        )

        assert isinstance(result, IncomeResponse)
        assert result.base_amount == Decimal("2500.00")
        assert result.base_currency == "EUR"
        assert result.fx_rate == Decimal("1.00000000")
        assert result.fx_rate_date == date(2026, 5, 7)
        assert result.fx_source == "identity"
    finally:
        db_session.close()


# Tests that creating a foreign-currency income record resolves and
# persists a full snapshot from the (monkeypatched) FX resolver.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to replace fx_service.resolve_fx_rate
#   so no real network call happens.
# Returns:
# - None. The test passes if the resolved rate/date/source are persisted
#   and base_amount is computed from the persisted (quantized) rate.
def test_create_income_foreign_currency_resolves_snapshot(
    clean_database: None, monkeypatch: MonkeyPatch,
) -> None:
    resolve_calls = []

    def fake_resolve_fx_rate(original_currency, base_currency, transaction_date, as_of):
        resolve_calls.append((original_currency, base_currency, transaction_date))
        return FxRateResult(rate=Decimal("0.8473"), actual_rate_date=date(2026, 5, 6), source="ecb")

    monkeypatch.setattr(income_service.fx_service, "resolve_fx_rate", fake_resolve_fx_rate)

    db_session = SessionLocal()
    user_id = uuid4()

    try:
        result = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="USD",
                received_at=date(2026, 5, 7), source="freelance",
            ),
            user_id=user_id,
        )

        assert resolve_calls == [("USD", "EUR", date(2026, 5, 7))]
        assert result.base_amount == Decimal("84.73")
        assert result.base_currency == "EUR"
        assert result.fx_rate == Decimal("0.84730000")
        assert result.fx_rate_date == date(2026, 5, 6)
        assert result.fx_source == "ecb"
    finally:
        db_session.close()


# Tests that a future-dated foreign-currency income raises the
# Income-specific error, not the shared fx_service error.
# This test exists as the regression for the requirement that Income
# never leaks Expense's exact public error message: fx_service itself is
# reused completely unmodified (it still raises
# FxFutureDatedNotSupportedError), but income_service must translate that
# into IncomeFutureDatedNotSupportedError before it reaches the client.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to force the future-dated branch
#   deterministically, without depending on the real fx_service lookback
#   window or network access.
# Returns:
# - None. The test passes if IncomeFutureDatedNotSupportedError (not
#   FxFutureDatedNotSupportedError) is raised.
def test_create_income_future_dated_foreign_raises_income_specific_error(
    clean_database: None, monkeypatch: MonkeyPatch,
) -> None:
    def fake_resolve_fx_rate(*args, **kwargs):
        raise FxFutureDatedNotSupportedError()

    monkeypatch.setattr(income_service.fx_service, "resolve_fx_rate", fake_resolve_fx_rate)

    db_session = SessionLocal()
    user_id = uuid4()

    try:
        with pytest.raises(IncomeFutureDatedNotSupportedError):
            income_service.create_income(
                db_session=db_session,
                income_data=IncomeCreate(
                    amount=Decimal("100.00"), currency="USD",
                    received_at=date(2099, 1, 1), source="other",
                ),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that a future-dated BASE-CURRENCY (identity) income is accepted,
# matching Expense's own established semantics: identity conversion needs
# no rate at all, so the future-date restriction (which exists only to
# protect historical rate lookups) never applies to it.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if creation succeeds with an identity snapshot.
def test_create_income_future_dated_base_currency_identity_accepted(
    clean_database: None,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        result = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2099, 1, 1), source="other",
            ),
            user_id=user_id,
        )
        assert result.fx_source == "identity"
    finally:
        db_session.close()


# Tests that an amount-only update reuses the existing snapshot's rate,
# using a monkeypatched creation (to stay network-free for the foreign
# currency involved) followed by a real amount-only update.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to replace fx_service.resolve_fx_rate
#   during creation and to assert it is not called during the update.
# Returns:
# - None. The test passes if fx_rate/fx_rate_date/fx_source are unchanged
#   and base_amount reflects the new amount at the same rate.
def test_update_income_amount_only_reuses_snapshot_end_to_end(
    clean_database: None, monkeypatch: MonkeyPatch,
) -> None:
    def fake_resolve_fx_rate(original_currency, base_currency, transaction_date, as_of):
        return FxRateResult(rate=Decimal("0.8473"), actual_rate_date=date(2026, 5, 6), source="ecb")

    monkeypatch.setattr(income_service.fx_service, "resolve_fx_rate", fake_resolve_fx_rate)

    db_session = SessionLocal()
    user_id = uuid4()

    try:
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="USD",
                received_at=date(2026, 5, 7), source="freelance",
            ),
            user_id=user_id,
        )

        def fail_if_called(*args, **kwargs):
            raise AssertionError("resolve_fx_rate must not be called for an amount-only update")

        monkeypatch.setattr(income_service.fx_service, "resolve_fx_rate", fail_if_called)

        updated = income_service.update_income(
            db_session=db_session,
            income_id=created.id,
            income_data=IncomeUpdate(amount=Decimal("200.00")),
            user_id=user_id,
        )

        assert updated.fx_rate == Decimal("0.84730000")
        assert updated.fx_rate_date == date(2026, 5, 6)
        assert updated.fx_source == "ecb"
        assert updated.base_amount == Decimal("169.46")
    finally:
        db_session.close()


# Tests that a currency change re-resolves a full new snapshot.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to replace fx_service.resolve_fx_rate.
# Returns:
# - None. The test passes if the resolver is called with the new
#   currency and the response reflects the fresh snapshot.
def test_update_income_currency_change_re_resolves(
    clean_database: None, monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        income_service.fx_service, "resolve_fx_rate",
        lambda *a, **k: FxRateResult(rate=Decimal("1"), actual_rate_date=date(2026, 5, 7), source="identity"),
    )

    db_session = SessionLocal()
    user_id = uuid4()

    try:
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 5, 7), source="salary",
            ),
            user_id=user_id,
        )

        resolve_calls = []

        def fake_resolve_fx_rate(original_currency, base_currency, transaction_date, as_of):
            resolve_calls.append((original_currency, base_currency, transaction_date))
            return FxRateResult(rate=Decimal("0.8473"), actual_rate_date=date(2026, 5, 6), source="ecb")

        monkeypatch.setattr(income_service.fx_service, "resolve_fx_rate", fake_resolve_fx_rate)

        updated = income_service.update_income(
            db_session=db_session,
            income_id=created.id,
            income_data=IncomeUpdate(currency="USD"),
            user_id=user_id,
        )

        assert resolve_calls == [("USD", "EUR", date(2026, 5, 7))]
        assert updated.fx_source == "ecb"
        assert updated.base_amount == Decimal("84.73")
    finally:
        db_session.close()


# Tests that a received_at change re-resolves a full new snapshot.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to replace fx_service.resolve_fx_rate.
# Returns:
# - None. The test passes if the resolver is called with the new date.
def test_update_income_received_at_change_re_resolves(
    clean_database: None, monkeypatch: MonkeyPatch,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 5, 7), source="salary",
            ),
            user_id=user_id,
        )

        resolve_calls = []

        def fake_resolve_fx_rate(original_currency, base_currency, transaction_date, as_of):
            resolve_calls.append(transaction_date)
            return FxRateResult(rate=Decimal("1"), actual_rate_date=transaction_date, source="identity")

        monkeypatch.setattr(income_service.fx_service, "resolve_fx_rate", fake_resolve_fx_rate)

        income_service.update_income(
            db_session=db_session,
            income_id=created.id,
            income_data=IncomeUpdate(received_at=date(2026, 6, 1)),
            user_id=user_id,
        )

        assert resolve_calls == [date(2026, 6, 1)]
    finally:
        db_session.close()


# Tests that a description-only update preserves the existing FX snapshot
# and never calls the FX resolver.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to force a hard failure if the
#   resolver is called at all.
# Returns:
# - None. The test passes if the snapshot is unchanged and no exception
#   is raised (proving the resolver was never invoked).
def test_update_income_description_only_preserves_snapshot_no_provider_call(
    clean_database: None, monkeypatch: MonkeyPatch,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 5, 7), source="salary",
            ),
            user_id=user_id,
        )

        def fail_if_called(*args, **kwargs):
            raise AssertionError("resolve_fx_rate must not be called for a description-only update")

        monkeypatch.setattr(income_service.fx_service, "resolve_fx_rate", fail_if_called)

        updated = income_service.update_income(
            db_session=db_session,
            income_id=created.id,
            income_data=IncomeUpdate(description="Updated note"),
            user_id=user_id,
        )

        assert updated.description == "Updated note"
        assert updated.base_amount == created.base_amount
        assert updated.fx_rate == created.fx_rate
        assert updated.fx_source == created.fx_source
    finally:
        db_session.close()


# Tests that a source-only update preserves the existing FX snapshot and
# never calls the FX resolver.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# - monkeypatch: pytest fixture used to force a hard failure if the
#   resolver is called at all.
# Returns:
# - None. The test passes if the snapshot is unchanged and no exception
#   is raised.
def test_update_income_source_only_preserves_snapshot_no_provider_call(
    clean_database: None, monkeypatch: MonkeyPatch,
) -> None:
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        created = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 5, 7), source="salary",
            ),
            user_id=user_id,
        )

        def fail_if_called(*args, **kwargs):
            raise AssertionError("resolve_fx_rate must not be called for a source-only update")

        monkeypatch.setattr(income_service.fx_service, "resolve_fx_rate", fail_if_called)

        updated = income_service.update_income(
            db_session=db_session,
            income_id=created.id,
            income_data=IncomeUpdate(source="gift"),
            user_id=user_id,
        )

        assert updated.source == "gift"
        assert updated.base_amount == created.base_amount
        assert updated.fx_rate == created.fx_rate
    finally:
        db_session.close()


# Tests that updating a missing/other-user income record raises
# IncomeNotFoundError.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if IncomeNotFoundError is raised.
def test_update_income_missing_record_raises_not_found(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        other_income = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 5, 7), source="salary",
            ),
            user_id=other_user_id,
        )

        with pytest.raises(IncomeNotFoundError):
            income_service.update_income(
                db_session=db_session,
                income_id=other_income.id,
                income_data=IncomeUpdate(source="gift"),
                user_id=user_id,
            )
    finally:
        db_session.close()


# Tests that get_income returns only the authenticated user's records.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if only the requesting user's income is
#   returned.
def test_get_income_ownership_isolation(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 5, 7), source="salary",
            ),
            user_id=user_id,
        )
        income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("200.00"), currency="EUR",
                received_at=date(2026, 5, 8), source="gift",
            ),
            user_id=other_user_id,
        )

        records = income_service.get_income(db_session=db_session, user_id=user_id)
        assert len(records) == 1
        assert records[0].amount == Decimal("100.00")
    finally:
        db_session.close()


# Tests that deleting a missing/other-user income record raises
# IncomeNotFoundError.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if IncomeNotFoundError is raised.
def test_delete_income_missing_record_raises_not_found(clean_database: None) -> None:
    db_session = SessionLocal()
    user_id = uuid4()
    other_user_id = uuid4()

    try:
        other_income = income_service.create_income(
            db_session=db_session,
            income_data=IncomeCreate(
                amount=Decimal("100.00"), currency="EUR",
                received_at=date(2026, 5, 7), source="salary",
            ),
            user_id=other_user_id,
        )

        with pytest.raises(IncomeNotFoundError):
            income_service.delete_income(
                db_session=db_session, income_id=other_income.id, user_id=user_id,
            )
    finally:
        db_session.close()
