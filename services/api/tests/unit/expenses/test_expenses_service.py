from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from pytest import MonkeyPatch
from sqlalchemy.orm import Session

from app.modules.expenses import expenses_service
from app.modules.expenses.expenses_schemas import (
    ExpenseCreate,
    ExpenseResponse,
    ExpenseUpdate,
)
from app.modules.fx.fx_errors import FxRateUnavailableError
from app.modules.fx.fx_schemas import FxRateResult


# A minimal fake Session used across this file: real DB calls are always
# mocked out via monkeypatched repository functions, but VF-017E's
# update_expense/delete_expense now call db_session.commit()/refresh()
# directly (mirroring income_service), so plain object() is no longer
# enough - it needs those two no-op methods.
def _fake_db_session() -> SimpleNamespace:
    return SimpleNamespace(commit=lambda: None, refresh=lambda obj: None)


def _make_existing_expense(
    currency: str = "EUR",
    expense_date: date = date(2026, 5, 7),
    amount: Decimal = Decimal("24.99"),
    base_amount=Decimal("24.99"),
    base_currency="EUR",
    fx_rate=Decimal("1"),
    fx_rate_date=date(2026, 5, 7),
    fx_source="identity",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        category_id=None,
        title="Lidl groceries",
        amount=amount,
        currency=currency,
        expense_date=expense_date,
        description=None,
        source="manual",
        base_amount=base_amount,
        base_currency=base_currency,
        fx_rate=fx_rate,
        fx_rate_date=fx_rate_date,
        fx_source=fx_source,
        created_at=datetime(2026, 5, 7, 10, 30, 0),
        updated_at=datetime(2026, 5, 7, 10, 30, 0),
    )


# Tests that creating a base-currency expense resolves an identity
# snapshot without needing financial_settings_service or fx_service to be
# mocked beyond the base-currency lookup - identity conversion inside the
# real fx_service needs no network call at all.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository behavior.
# Returns:
# - None. The test passes if the persisted snapshot is a correct identity.
def test_service_create_expense_returns_expense_response(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, _fake_db_session())
    expense_id = uuid4()
    user_id = uuid4()

    expense_data = ExpenseCreate(
        category_id=None,
        title="Lidl groceries",
        amount=Decimal("24.99"),
        currency="EUR",
        expense_date=date(2026, 5, 7),
        description="Milk, bread and fruits",
        source="manual",
    )

    create_calls: list[dict] = []

    def fake_get_base_currency(db_session: Session, user_id: UUID, commit: bool = True) -> str:
        return "EUR"

    def fake_create_expense(db_session, expense_data, user_id, **kwargs) -> SimpleNamespace:
        create_calls.append(kwargs)
        return SimpleNamespace(
            id=expense_id,
            user_id=user_id,
            category_id=None,
            title=expense_data.title,
            amount=expense_data.amount,
            currency=expense_data.currency,
            expense_date=expense_data.expense_date,
            description=expense_data.description,
            source=expense_data.source,
            created_at=datetime(2026, 5, 7, 10, 30, 0),
            updated_at=datetime(2026, 5, 7, 10, 30, 0),
            **kwargs,
        )

    monkeypatch.setattr(
        expenses_service.financial_settings_service,
        "get_base_currency",
        fake_get_base_currency,
    )
    monkeypatch.setattr(
        expenses_service.expenses_repository,
        "create_expense",
        fake_create_expense,
    )

    # Act
    created_expense = expenses_service.create_expense(
        db_session=db_session,
        expense_data=expense_data,
        user_id=user_id,
    )

    # Assert
    assert isinstance(created_expense, ExpenseResponse)
    assert created_expense.id == expense_id
    assert created_expense.amount == Decimal("24.99")
    assert create_calls[0]["commit"] is True
    assert create_calls[0]["base_amount"] == Decimal("24.99")
    assert create_calls[0]["base_currency"] == "EUR"
    assert create_calls[0]["fx_rate"] == Decimal("1")
    assert create_calls[0]["fx_rate_date"] == date(2026, 5, 7)
    assert create_calls[0]["fx_source"] == "identity"


# Tests that creating a foreign-currency expense resolves through
# fx_service and persists the resolved snapshot.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository/fx behavior.
# Returns:
# - None. The test passes if base_amount is computed from the mocked rate.
def test_service_create_expense_foreign_currency_resolves_snapshot(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, _fake_db_session())
    user_id = uuid4()

    expense_data = ExpenseCreate(
        category_id=None,
        title="NYC taxi",
        amount=Decimal("100.00"),
        currency="USD",
        expense_date=date(2026, 5, 7),
        description=None,
        source="manual",
    )

    resolve_calls: list[tuple] = []
    create_calls: list[dict] = []

    monkeypatch.setattr(
        expenses_service.financial_settings_service,
        "get_base_currency",
        lambda db_session, user_id, commit=True: "EUR",
    )

    def fake_resolve_fx_rate(original_currency, base_currency, transaction_date, as_of):
        resolve_calls.append((original_currency, base_currency, transaction_date))
        return FxRateResult(rate=Decimal("0.8473"), actual_rate_date=date(2026, 5, 6), source="ecb")

    monkeypatch.setattr(expenses_service.fx_service, "resolve_fx_rate", fake_resolve_fx_rate)

    def fake_create_expense(db_session, expense_data, user_id, **kwargs) -> SimpleNamespace:
        create_calls.append(kwargs)
        return SimpleNamespace(
            id=uuid4(), user_id=user_id, category_id=None,
            title=expense_data.title, amount=expense_data.amount,
            currency=expense_data.currency, expense_date=expense_data.expense_date,
            description=expense_data.description, source=expense_data.source,
            created_at=datetime(2026, 5, 7, 10, 30, 0), updated_at=datetime(2026, 5, 7, 10, 30, 0),
            **kwargs,
        )

    monkeypatch.setattr(expenses_service.expenses_repository, "create_expense", fake_create_expense)

    # Act
    expenses_service.create_expense(db_session=db_session, expense_data=expense_data, user_id=user_id)

    # Assert
    assert resolve_calls == [("USD", "EUR", date(2026, 5, 7))]
    assert create_calls[0]["base_amount"] == Decimal("84.73")
    assert create_calls[0]["base_currency"] == "EUR"
    assert create_calls[0]["fx_rate"] == Decimal("0.8473")
    assert create_calls[0]["fx_rate_date"] == date(2026, 5, 6)
    assert create_calls[0]["fx_source"] == "ecb"


# Tests the VF-014B5C financial-integrity correction: base_amount must be
# derived from the fx_rate at exactly the precision that will be
# persisted (NUMERIC(18,8)), not from the wider raw provider value. ECB
# publishing "6" makes canonical_rate = 1/6 a repeating decimal whose raw
# and 8dp-quantized forms diverge by exactly one cent at amount=999.99 -
# chosen deliberately so this test cannot pass under the old (bugged)
# implementation that quantized fx_rate for base_amount computation but
# then persisted a differently-rounded fx_rate.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository/fx behavior.
# Returns:
# - None. The test passes only if both the repository call's fx_rate and
#   its base_amount reflect the same 8dp-normalized rate.
def test_service_create_expense_normalizes_fx_rate_before_computing_base_amount(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, _fake_db_session())
    user_id = uuid4()

    expense_data = ExpenseCreate(
        category_id=None,
        title="Repeating rate",
        amount=Decimal("999.99"),
        currency="USD",
        expense_date=date(2026, 5, 7),
        description=None,
        source="manual",
    )

    create_calls: list[dict] = []

    monkeypatch.setattr(
        expenses_service.financial_settings_service, "get_base_currency",
        lambda db_session, user_id, commit=True: "EUR",
    )

    raw_provider_rate = Decimal("1") / Decimal("6")  # repeating decimal

    def fake_resolve_fx_rate(original_currency, base_currency, transaction_date, as_of):
        return FxRateResult(rate=raw_provider_rate, actual_rate_date=date(2026, 5, 7), source="ecb")

    monkeypatch.setattr(expenses_service.fx_service, "resolve_fx_rate", fake_resolve_fx_rate)
    monkeypatch.setattr(
        expenses_service.expenses_repository, "create_expense",
        lambda db_session, expense_data, user_id, **kwargs: create_calls.append(kwargs) or SimpleNamespace(
            id=uuid4(), user_id=user_id, category_id=None,
            title=expense_data.title, amount=expense_data.amount,
            currency=expense_data.currency, expense_date=expense_data.expense_date,
            description=expense_data.description, source=expense_data.source,
            created_at=datetime(2026, 5, 7, 10, 30, 0), updated_at=datetime(2026, 5, 7, 10, 30, 0),
            **kwargs,
        ),
    )

    # Act
    expenses_service.create_expense(db_session=db_session, expense_data=expense_data, user_id=user_id)

    # Assert
    stored_fx_rate = raw_provider_rate.quantize(expenses_service.FX_RATE_DECIMAL_PLACES)
    raw_derived_base_amount = (Decimal("999.99") * raw_provider_rate).quantize(Decimal("0.01"))
    correct_base_amount = (Decimal("999.99") * stored_fx_rate).quantize(Decimal("0.01"))
    assert raw_derived_base_amount != correct_base_amount, "fixture must be precision-sensitive"

    # A/B: the persisted fx_rate is normalized to exactly 8 decimal places.
    assert create_calls[0]["fx_rate"] == stored_fx_rate
    assert create_calls[0]["fx_rate"] != raw_provider_rate

    # C: base_amount was computed from that normalized rate, not the raw one.
    assert create_calls[0]["base_amount"] == correct_base_amount
    assert create_calls[0]["base_amount"] != raw_derived_base_amount


# Tests the same financial-integrity correction on the update path's
# re-resolve branch (currency/date change), which independently computes
# its own base_amount from a freshly resolved fx_result.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository/fx behavior.
# Returns:
# - None. The test passes only if the persisted fx_rate and base_amount
#   are derived from the same 8dp-normalized rate.
def test_service_update_expense_normalizes_fx_rate_before_computing_base_amount(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, _fake_db_session())
    user_id = uuid4()
    existing = _make_existing_expense(
        currency="EUR", expense_date=date(2026, 5, 7), amount=Decimal("999.99"),
    )

    monkeypatch.setattr(
        expenses_service.expenses_repository, "get_expense_by_id_for_update",
        lambda **kwargs: existing,
    )
    monkeypatch.setattr(
        expenses_service.account_transaction_repository, "get_expense_projection",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        expenses_service.financial_settings_service, "get_base_currency",
        lambda db_session, user_id, commit=True: "EUR",
    )

    raw_provider_rate = Decimal("1") / Decimal("6")

    def fake_resolve_fx_rate(original_currency, base_currency, transaction_date, as_of):
        return FxRateResult(rate=raw_provider_rate, actual_rate_date=date(2026, 5, 7), source="ecb")

    monkeypatch.setattr(expenses_service.fx_service, "resolve_fx_rate", fake_resolve_fx_rate)

    update_calls: list[dict] = []
    monkeypatch.setattr(
        expenses_service.expenses_repository, "update_expense",
        lambda db_session, expense_model, expense_data, **kwargs: update_calls.append(kwargs) or SimpleNamespace(
            id=existing.id, user_id=existing.user_id, category_id=None,
            title=existing.title, amount=existing.amount, currency="USD",
            expense_date=existing.expense_date, description=existing.description,
            source=existing.source, created_at=existing.created_at, updated_at=existing.updated_at,
            **kwargs,
        ),
    )

    # Act - currency change forces the re-resolve branch.
    expenses_service.update_expense(
        db_session=db_session,
        expense_id=existing.id,
        expense_data=ExpenseUpdate(currency="USD"),
        user_id=user_id,
    )

    # Assert
    stored_fx_rate = raw_provider_rate.quantize(expenses_service.FX_RATE_DECIMAL_PLACES)
    correct_base_amount = (Decimal("999.99") * stored_fx_rate).quantize(Decimal("0.01"))
    raw_derived_base_amount = (Decimal("999.99") * raw_provider_rate).quantize(Decimal("0.01"))
    assert raw_derived_base_amount != correct_base_amount, "fixture must be precision-sensitive"

    assert update_calls[0]["fx_rate"] == stored_fx_rate
    assert update_calls[0]["base_amount"] == correct_base_amount


# Tests that a provider failure during creation results in no expense
# being persisted at all.
# This test exists to verify the "no Expense row created on FX failure"
# invariant end to end at the service layer.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository/fx behavior.
# Returns:
# - None. The test passes if the repository's create_expense is never called.
def test_service_create_expense_provider_failure_creates_no_expense(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, _fake_db_session())
    user_id = uuid4()

    expense_data = ExpenseCreate(
        category_id=None, title="Bad currency", amount=Decimal("10"),
        currency="ZZZ", expense_date=date(2026, 5, 7), description=None, source="manual",
    )

    create_calls: list[dict] = []

    monkeypatch.setattr(
        expenses_service.financial_settings_service, "get_base_currency",
        lambda db_session, user_id, commit=True: "EUR",
    )

    def fake_resolve_fx_rate(*args, **kwargs):
        raise FxRateUnavailableError()

    monkeypatch.setattr(expenses_service.fx_service, "resolve_fx_rate", fake_resolve_fx_rate)
    monkeypatch.setattr(
        expenses_service.expenses_repository, "create_expense",
        lambda *a, **k: create_calls.append(k),
    )

    # Act / Assert
    with pytest.raises(FxRateUnavailableError):
        expenses_service.create_expense(db_session=db_session, expense_data=expense_data, user_id=user_id)

    assert create_calls == []


# Tests that the service returns expense response objects for a specific user.
# This test exists to verify that the service passes user_id to the repository and maps returned models to responses.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository behavior.
# Returns:
# - None. The test passes if a list of ExpenseResponse objects is returned.
def test_service_get_expenses_returns_expense_responses_for_user(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, _fake_db_session())
    expected_db_session = db_session

    expense_id = uuid4()
    user_id = uuid4()
    expected_user_id = user_id

    created_at = datetime(2026, 5, 7, 10, 30, 0)
    updated_at = datetime(2026, 5, 7, 10, 30, 0)

    expense_model = SimpleNamespace(
        id=expense_id,
        user_id=user_id,
        category_id=None,
        title="Lidl groceries",
        amount=Decimal("24.99"),
        currency="EUR",
        expense_date=date(2026, 5, 7),
        description="Milk, bread and fruits",
        source="manual",
        base_amount=Decimal("24.99"),
        base_currency="EUR",
        fx_rate=Decimal("1"),
        fx_rate_date=date(2026, 5, 7),
        fx_source="identity",
        created_at=created_at,
        updated_at=updated_at,
    )

    def fake_get_expenses(
        db_session: Session,
        user_id: UUID,
    ) -> list[SimpleNamespace]:
        assert db_session is expected_db_session
        assert user_id == expected_user_id

        return [expense_model]

    monkeypatch.setattr(
        expenses_service.expenses_repository,
        "get_expenses",
        fake_get_expenses,
    )
    monkeypatch.setattr(
        expenses_service.account_transaction_repository,
        "get_expense_account_links_for_user",
        lambda db_session, user_id: {},
    )

    # Act
    expenses = expenses_service.get_expenses(
        db_session=db_session,
        user_id=user_id,
    )

    # Assert
    assert len(expenses) == 1
    assert isinstance(expenses[0], ExpenseResponse)
    assert expenses[0].id == expense_id
    assert expenses[0].base_amount == Decimal("24.99")


# ---------------------------------------------------------------------------
# update_expense - VF-014B5C snapshot rules
# ---------------------------------------------------------------------------


# Tests that an amount-only update reuses the stored FX snapshot rather
# than re-resolving.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository/fx behavior.
# Returns:
# - None. The test passes if base_amount is recomputed but rate/date/
#   source are copied unchanged, and fx_service is never called.
def test_service_update_expense_amount_only_reuses_snapshot(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, _fake_db_session())
    existing = _make_existing_expense(
        base_amount=Decimal("24.99"), fx_rate=Decimal("2"),
        fx_rate_date=date(2026, 5, 6), fx_source="ecb",
    )
    update_calls: list[dict] = []
    resolve_calls: list = []

    monkeypatch.setattr(
        expenses_service.expenses_repository, "get_expense_by_id_for_update",
        lambda db_session, expense_id, user_id: existing,
    )
    monkeypatch.setattr(
        expenses_service.account_transaction_repository, "get_expense_projection",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        expenses_service.fx_service, "resolve_fx_rate",
        lambda *a, **k: resolve_calls.append((a, k)),
    )

    def fake_update_expense(db_session, expense_model, expense_data, **kwargs):
        update_calls.append(kwargs)
        return SimpleNamespace(**{**existing.__dict__, **kwargs})

    monkeypatch.setattr(expenses_service.expenses_repository, "update_expense", fake_update_expense)

    # Act
    expenses_service.update_expense(
        db_session=db_session, expense_id=existing.id,
        expense_data=ExpenseUpdate(amount=Decimal("50.00")), user_id=existing.user_id,
    )

    # Assert
    assert resolve_calls == []
    assert update_calls[0]["fx_rate"] == Decimal("2")
    assert update_calls[0]["fx_rate_date"] == date(2026, 5, 6)
    assert update_calls[0]["fx_source"] == "ecb"
    assert update_calls[0]["base_amount"] == Decimal("100.00")  # 50.00 * 2


# Tests that a currency-only update re-resolves the FX snapshot.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository/fx behavior.
# Returns:
# - None. The test passes if fx_service.resolve_fx_rate is called with the
#   new currency and the original expense_date.
def test_service_update_expense_currency_change_re_resolves(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, _fake_db_session())
    existing = _make_existing_expense(currency="EUR", expense_date=date(2026, 5, 7))
    resolve_calls: list = []

    monkeypatch.setattr(
        expenses_service.expenses_repository, "get_expense_by_id_for_update",
        lambda db_session, expense_id, user_id: existing,
    )
    monkeypatch.setattr(
        expenses_service.account_transaction_repository, "get_expense_projection",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        expenses_service.financial_settings_service, "get_base_currency",
        lambda db_session, user_id, commit=True: "EUR",
    )

    def fake_resolve_fx_rate(original_currency, base_currency, transaction_date, as_of):
        resolve_calls.append((original_currency, base_currency, transaction_date))
        return FxRateResult(rate=Decimal("0.9"), actual_rate_date=transaction_date, source="ecb")

    monkeypatch.setattr(expenses_service.fx_service, "resolve_fx_rate", fake_resolve_fx_rate)
    monkeypatch.setattr(
        expenses_service.expenses_repository, "update_expense",
        lambda db_session, expense_model, expense_data, **kwargs: SimpleNamespace(
            **{**existing.__dict__, **kwargs},
        ),
    )

    # Act
    expenses_service.update_expense(
        db_session=db_session, expense_id=existing.id,
        expense_data=ExpenseUpdate(currency="USD"), user_id=existing.user_id,
    )

    # Assert
    assert resolve_calls == [("USD", "EUR", date(2026, 5, 7))]


# Tests that an expense_date-only update re-resolves the FX snapshot.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository/fx behavior.
# Returns:
# - None. The test passes if fx_service.resolve_fx_rate is called with the
#   original currency and the new expense_date.
def test_service_update_expense_date_change_re_resolves(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, _fake_db_session())
    existing = _make_existing_expense(currency="USD", expense_date=date(2026, 5, 7))
    resolve_calls: list = []

    monkeypatch.setattr(
        expenses_service.expenses_repository, "get_expense_by_id_for_update",
        lambda db_session, expense_id, user_id: existing,
    )
    monkeypatch.setattr(
        expenses_service.account_transaction_repository, "get_expense_projection",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        expenses_service.financial_settings_service, "get_base_currency",
        lambda db_session, user_id, commit=True: "EUR",
    )

    def fake_resolve_fx_rate(original_currency, base_currency, transaction_date, as_of):
        resolve_calls.append((original_currency, base_currency, transaction_date))
        return FxRateResult(rate=Decimal("0.9"), actual_rate_date=transaction_date, source="ecb")

    monkeypatch.setattr(expenses_service.fx_service, "resolve_fx_rate", fake_resolve_fx_rate)
    monkeypatch.setattr(
        expenses_service.expenses_repository, "update_expense",
        lambda db_session, expense_model, expense_data, **kwargs: SimpleNamespace(
            **{**existing.__dict__, **kwargs},
        ),
    )

    # Act
    expenses_service.update_expense(
        db_session=db_session, expense_id=existing.id,
        expense_data=ExpenseUpdate(expense_date=date(2026, 6, 1)), user_id=existing.user_id,
    )

    # Assert
    assert resolve_calls == [("USD", "EUR", date(2026, 6, 1))]


# Tests that changing currency and expense_date together resolves exactly
# once, using both final values.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository/fx behavior.
# Returns:
# - None. The test passes if resolve_fx_rate is called exactly once with
#   both new values.
def test_service_update_expense_currency_and_date_change_resolves_once(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, _fake_db_session())
    existing = _make_existing_expense(currency="EUR", expense_date=date(2026, 5, 7))
    resolve_calls: list = []

    monkeypatch.setattr(
        expenses_service.expenses_repository, "get_expense_by_id_for_update",
        lambda db_session, expense_id, user_id: existing,
    )
    monkeypatch.setattr(
        expenses_service.account_transaction_repository, "get_expense_projection",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        expenses_service.financial_settings_service, "get_base_currency",
        lambda db_session, user_id, commit=True: "EUR",
    )

    def fake_resolve_fx_rate(original_currency, base_currency, transaction_date, as_of):
        resolve_calls.append((original_currency, base_currency, transaction_date))
        return FxRateResult(rate=Decimal("0.9"), actual_rate_date=transaction_date, source="ecb")

    monkeypatch.setattr(expenses_service.fx_service, "resolve_fx_rate", fake_resolve_fx_rate)
    monkeypatch.setattr(
        expenses_service.expenses_repository, "update_expense",
        lambda db_session, expense_model, expense_data, **kwargs: SimpleNamespace(
            **{**existing.__dict__, **kwargs},
        ),
    )

    # Act
    expenses_service.update_expense(
        db_session=db_session, expense_id=existing.id,
        expense_data=ExpenseUpdate(currency="GBP", expense_date=date(2026, 6, 1)),
        user_id=existing.user_id,
    )

    # Assert
    assert len(resolve_calls) == 1
    assert resolve_calls[0] == ("GBP", "EUR", date(2026, 6, 1))


# Tests that a metadata-only update never calls the FX provider and
# leaves the snapshot byte-for-byte unchanged.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository/fx behavior.
# Returns:
# - None. The test passes if neither financial_settings_service nor
#   fx_service is ever called.
def test_service_update_expense_metadata_only_does_not_resolve(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, _fake_db_session())
    existing = _make_existing_expense(fx_rate=Decimal("2"), fx_source="ecb")
    base_currency_calls: list = []
    resolve_calls: list = []
    update_calls: list[dict] = []

    monkeypatch.setattr(
        expenses_service.expenses_repository, "get_expense_by_id_for_update",
        lambda db_session, expense_id, user_id: existing,
    )
    monkeypatch.setattr(
        expenses_service.account_transaction_repository, "get_expense_projection",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        expenses_service.financial_settings_service, "get_base_currency",
        lambda db_session, user_id, commit=True: base_currency_calls.append(1),
    )
    monkeypatch.setattr(
        expenses_service.fx_service, "resolve_fx_rate",
        lambda *a, **k: resolve_calls.append((a, k)),
    )

    def fake_update_expense(db_session, expense_model, expense_data, **kwargs):
        update_calls.append(kwargs)
        return SimpleNamespace(**{**existing.__dict__, **kwargs})

    monkeypatch.setattr(expenses_service.expenses_repository, "update_expense", fake_update_expense)

    # Act
    expenses_service.update_expense(
        db_session=db_session, expense_id=existing.id,
        expense_data=ExpenseUpdate(title="Renamed"), user_id=existing.user_id,
    )

    # Assert
    assert base_currency_calls == []
    assert resolve_calls == []
    assert update_calls[0]["base_amount"] == existing.base_amount
    assert update_calls[0]["fx_rate"] == Decimal("2")
    assert update_calls[0]["fx_source"] == "ecb"


# Tests that a legacy unresolved expense receiving a monetary update
# resolves a full snapshot.
# This test exists to verify Section 17's rule: an all-NULL snapshot must
# be resolved once real monetary truth changes, even if currency/date are
# unchanged from their (unresolved) stored values.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository/fx behavior.
# Returns:
# - None. The test passes if resolve_fx_rate is called and the update
#   receives a fully populated snapshot.
def test_service_update_expense_legacy_unresolved_monetary_update_resolves(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, _fake_db_session())
    existing = _make_existing_expense(
        currency="USD", expense_date=date(2026, 5, 7),
        base_amount=None, base_currency=None, fx_rate=None, fx_rate_date=None, fx_source=None,
    )
    resolve_calls: list = []

    monkeypatch.setattr(
        expenses_service.expenses_repository, "get_expense_by_id_for_update",
        lambda db_session, expense_id, user_id: existing,
    )
    monkeypatch.setattr(
        expenses_service.account_transaction_repository, "get_expense_projection",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        expenses_service.financial_settings_service, "get_base_currency",
        lambda db_session, user_id, commit=True: "EUR",
    )

    def fake_resolve_fx_rate(original_currency, base_currency, transaction_date, as_of):
        resolve_calls.append((original_currency, base_currency, transaction_date))
        return FxRateResult(rate=Decimal("0.85"), actual_rate_date=transaction_date, source="ecb")

    monkeypatch.setattr(expenses_service.fx_service, "resolve_fx_rate", fake_resolve_fx_rate)

    update_calls: list[dict] = []

    def fake_update_expense(db_session, expense_model, expense_data, **kwargs):
        update_calls.append(kwargs)
        return SimpleNamespace(**{**existing.__dict__, **kwargs})

    monkeypatch.setattr(expenses_service.expenses_repository, "update_expense", fake_update_expense)

    # Act - amount changes, currency/date do not (still the unresolved USD/date)
    expenses_service.update_expense(
        db_session=db_session, expense_id=existing.id,
        expense_data=ExpenseUpdate(amount=Decimal("100")), user_id=existing.user_id,
    )

    # Assert
    assert resolve_calls == [("USD", "EUR", date(2026, 5, 7))]
    assert update_calls[0]["base_amount"] == Decimal("85.00")
    assert update_calls[0]["fx_source"] == "ecb"


# Tests that a legacy unresolved expense receiving only a metadata update
# stays fully unresolved (all NULL), never forcing network resolution.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository/fx behavior.
# Returns:
# - None. The test passes if the snapshot stays all-None and no provider
#   call is attempted.
def test_service_update_expense_legacy_unresolved_metadata_update_stays_unresolved(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, _fake_db_session())
    existing = _make_existing_expense(
        currency="USD",
        base_amount=None, base_currency=None, fx_rate=None, fx_rate_date=None, fx_source=None,
    )
    resolve_calls: list = []
    base_currency_calls: list = []

    monkeypatch.setattr(
        expenses_service.expenses_repository, "get_expense_by_id_for_update",
        lambda db_session, expense_id, user_id: existing,
    )
    monkeypatch.setattr(
        expenses_service.account_transaction_repository, "get_expense_projection",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        expenses_service.financial_settings_service, "get_base_currency",
        lambda db_session, user_id, commit=True: base_currency_calls.append(1),
    )
    monkeypatch.setattr(
        expenses_service.fx_service, "resolve_fx_rate",
        lambda *a, **k: resolve_calls.append(1),
    )

    update_calls: list[dict] = []

    def fake_update_expense(db_session, expense_model, expense_data, **kwargs):
        update_calls.append(kwargs)
        return SimpleNamespace(**{**existing.__dict__, **kwargs})

    monkeypatch.setattr(expenses_service.expenses_repository, "update_expense", fake_update_expense)

    # Act
    expenses_service.update_expense(
        db_session=db_session, expense_id=existing.id,
        expense_data=ExpenseUpdate(title="Renamed only"), user_id=existing.user_id,
    )

    # Assert
    assert base_currency_calls == []
    assert resolve_calls == []
    assert update_calls[0]["base_amount"] is None
    assert update_calls[0]["fx_source"] is None


# Tests that updating an expense with an explicit category_id validates
# ownership of that category before delegating to the repository.
# This test exists to verify that a user cannot silently attach another
# user's category to their own expense during an update.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository/service behavior.
# Returns:
# - None. The test passes if get_category_by_id is called with the update's category_id and user_id.
def test_service_update_expense_validates_category_when_category_id_is_set(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, _fake_db_session())
    existing = _make_existing_expense()
    category_id = uuid4()

    expense_data = ExpenseUpdate(category_id=category_id)

    validated_category_calls: list[tuple[UUID, UUID]] = []

    def fake_get_category_by_id(
        db_session: Session,
        category_id: UUID,
        user_id: UUID,
    ) -> SimpleNamespace:
        validated_category_calls.append((category_id, user_id))
        return SimpleNamespace(id=category_id, user_id=user_id)

    monkeypatch.setattr(
        expenses_service.expenses_repository, "get_expense_by_id_for_update",
        lambda db_session, expense_id, user_id: existing,
    )
    monkeypatch.setattr(
        expenses_service.account_transaction_repository, "get_expense_projection",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        expenses_service.categories_service,
        "get_category_by_id",
        fake_get_category_by_id,
    )
    monkeypatch.setattr(
        expenses_service.expenses_repository, "update_expense",
        lambda db_session, expense_model, expense_data, **kwargs: SimpleNamespace(
            **{**existing.__dict__, **kwargs, "category_id": category_id},
        ),
    )

    # Act
    expenses_service.update_expense(
        db_session=db_session,
        expense_id=existing.id,
        expense_data=expense_data,
        user_id=existing.user_id,
    )

    # Assert
    assert validated_category_calls == [(category_id, existing.user_id)]


# Tests that updating an expense without setting category_id does not
# trigger a category ownership check.
# This test exists to verify that omitted fields are left untouched and do
# not cause unnecessary repository/service calls.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository/service behavior.
# Returns:
# - None. The test passes if get_category_by_id is never called.
def test_service_update_expense_skips_category_validation_when_category_id_omitted(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    db_session = cast(Session, _fake_db_session())
    existing = _make_existing_expense()

    expense_data = ExpenseUpdate(title="Rewe groceries")

    validated_category_calls: list[UUID] = []

    def fake_get_category_by_id(
        db_session: Session,
        category_id: UUID,
        user_id: UUID,
    ) -> SimpleNamespace:
        validated_category_calls.append(category_id)
        return SimpleNamespace(id=category_id, user_id=user_id)

    monkeypatch.setattr(
        expenses_service.expenses_repository, "get_expense_by_id_for_update",
        lambda db_session, expense_id, user_id: existing,
    )
    monkeypatch.setattr(
        expenses_service.account_transaction_repository, "get_expense_projection",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        expenses_service.categories_service,
        "get_category_by_id",
        fake_get_category_by_id,
    )
    monkeypatch.setattr(
        expenses_service.expenses_repository, "update_expense",
        lambda db_session, expense_model, expense_data, **kwargs: SimpleNamespace(
            **{**existing.__dict__, **kwargs},
        ),
    )

    # Act
    expenses_service.update_expense(
        db_session=db_session,
        expense_id=existing.id,
        expense_data=expense_data,
        user_id=existing.user_id,
    )

    # Assert
    assert validated_category_calls == []


# Tests that the service deletes an expense by locking it, resolving its
# (absent) projection, and delegating to the repository, committing once.
# This test exists to verify the VF-017E lock-then-delete sequence for an
# unlinked Expense: no Account is ever locked when there is no projection
# to resolve.
# Parameters:
# - monkeypatch: pytest fixture used to replace repository behavior.
# Returns:
# - None. The test passes if the repository's delete_expense is called
#   with the locked model and the session is committed exactly once.
def test_service_delete_expense_calls_repository_delete(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    commit_calls: list[None] = []
    db_session = cast(Session, SimpleNamespace(commit=lambda: commit_calls.append(None)))
    expense_id = uuid4()
    user_id = uuid4()
    expense_model = SimpleNamespace(id=expense_id, user_id=user_id)

    locked_calls: list[tuple[UUID, UUID]] = []
    projection_calls: list[tuple[UUID, UUID]] = []
    delete_calls: list[tuple[Session, SimpleNamespace, bool]] = []

    def fake_get_expense_by_id_for_update(db_session, expense_id, user_id):
        locked_calls.append((expense_id, user_id))
        return expense_model

    def fake_get_expense_projection(db_session, expense_id, user_id):
        projection_calls.append((expense_id, user_id))
        return None

    def fake_delete_expense(db_session, expense_model, commit=True):
        delete_calls.append((db_session, expense_model, commit))

    monkeypatch.setattr(
        expenses_service.expenses_repository,
        "get_expense_by_id_for_update",
        fake_get_expense_by_id_for_update,
    )
    monkeypatch.setattr(
        expenses_service.account_transaction_repository,
        "get_expense_projection",
        fake_get_expense_projection,
    )
    monkeypatch.setattr(
        expenses_service.expenses_repository,
        "delete_expense",
        fake_delete_expense,
    )

    # Act
    result = expenses_service.delete_expense(
        db_session=db_session,
        expense_id=expense_id,
        user_id=user_id,
    )

    # Assert
    assert result is None
    assert locked_calls == [(expense_id, user_id)]
    assert projection_calls == [(expense_id, user_id)]
    assert delete_calls == [(db_session, expense_model, False)]
    assert commit_calls == [None]
