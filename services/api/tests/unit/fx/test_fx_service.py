from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.modules.fx import fx_service
from app.modules.fx.fx_errors import (
    FxFutureDatedNotSupportedError,
    FxRateUnavailableError,
)


# Tests that an identity conversion (original == base) never makes an
# HTTP call, at either provider.
# Parameters:
# - monkeypatch: pytest fixture used to assert no HTTP call is attempted.
# Returns:
# - None. The test passes if rate is exactly 1 and no network call happens.
def test_resolve_fx_rate_identity_never_calls_http(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    get_mock = MagicMock()
    from app.modules.fx import fx_ecb_provider, fx_nbu_provider
    monkeypatch.setattr(fx_ecb_provider, "httpx", MagicMock(get=get_mock))
    monkeypatch.setattr(fx_nbu_provider, "httpx", MagicMock(get=get_mock))

    # Act
    result = fx_service.resolve_fx_rate(
        original_currency="EUR", base_currency="EUR",
        transaction_date=date(2026, 5, 1), as_of=date(2026, 9, 16),
    )

    # Assert
    assert result.rate == Decimal("1")
    assert result.actual_rate_date == date(2026, 5, 1)
    assert result.source == "identity"
    get_mock.assert_not_called()


# Tests that identity conversion is allowed even for a future-dated
# expense - no rate is needed, so there is nothing to reject.
# Parameters:
# - None.
# Returns:
# - None. The test passes if a future-dated identity conversion succeeds.
def test_resolve_fx_rate_identity_allows_future_date() -> None:
    # Act
    result = fx_service.resolve_fx_rate(
        original_currency="EUR", base_currency="EUR",
        transaction_date=date(2026, 12, 1), as_of=date(2026, 9, 16),
    )

    # Assert
    assert result.rate == Decimal("1")


# Tests that a future-dated foreign-currency transaction is rejected
# before any provider is consulted.
# Parameters:
# - monkeypatch: pytest fixture used to assert no provider is called.
# Returns:
# - None. The test passes if FxFutureDatedNotSupportedError is raised and
#   neither provider is invoked.
def test_resolve_fx_rate_future_dated_foreign_currency_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    ecb_calls: list = []
    nbu_calls: list = []
    monkeypatch.setattr(
        fx_service._ecb_provider, "resolve_rate", lambda *a, **k: ecb_calls.append(1),
    )
    monkeypatch.setattr(
        fx_service._nbu_provider, "resolve_rate", lambda *a, **k: nbu_calls.append(1),
    )

    # Act / Assert
    with pytest.raises(FxFutureDatedNotSupportedError):
        fx_service.resolve_fx_rate(
            original_currency="USD", base_currency="EUR",
            transaction_date=date(2026, 12, 1), as_of=date(2026, 9, 16),
        )

    assert ecb_calls == []
    assert nbu_calls == []


# Tests that an ECB-supported currency is routed to the ECB provider.
# Parameters:
# - monkeypatch: pytest fixture used to replace the provider instances.
# Returns:
# - None. The test passes if only the ECB provider is called.
def test_resolve_fx_rate_routes_ecb_supported_currency_to_ecb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    ecb_calls: list = []
    nbu_calls: list = []

    def fake_ecb_resolve(original_currency, base_currency, transaction_date):
        ecb_calls.append((original_currency, base_currency, transaction_date))
        return fx_service.FxRateResult(rate=Decimal("0.9"), actual_rate_date=transaction_date, source="ecb")

    monkeypatch.setattr(fx_service._ecb_provider, "resolve_rate", fake_ecb_resolve)
    monkeypatch.setattr(
        fx_service._nbu_provider, "resolve_rate", lambda *a, **k: nbu_calls.append(1),
    )

    # Act
    result = fx_service.resolve_fx_rate(
        original_currency="USD", base_currency="EUR",
        transaction_date=date(2026, 9, 15), as_of=date(2026, 9, 16),
    )

    # Assert
    assert ecb_calls == [("USD", "EUR", date(2026, 9, 15))]
    assert nbu_calls == []
    assert result.source == "ecb"


# Tests that UAH -> EUR is routed to the NBU provider, not ECB.
# Parameters:
# - monkeypatch: pytest fixture used to replace the provider instances.
# Returns:
# - None. The test passes if only the NBU provider is called.
def test_resolve_fx_rate_routes_uah_to_nbu(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    ecb_calls: list = []
    nbu_calls: list = []

    def fake_nbu_resolve(original_currency, base_currency, transaction_date):
        nbu_calls.append((original_currency, base_currency, transaction_date))
        return fx_service.FxRateResult(rate=Decimal("0.02"), actual_rate_date=transaction_date, source="nbu")

    monkeypatch.setattr(
        fx_service._ecb_provider, "resolve_rate", lambda *a, **k: ecb_calls.append(1),
    )
    monkeypatch.setattr(fx_service._nbu_provider, "resolve_rate", fake_nbu_resolve)

    # Act
    result = fx_service.resolve_fx_rate(
        original_currency="UAH", base_currency="EUR",
        transaction_date=date(2026, 9, 15), as_of=date(2026, 9, 16),
    )

    # Assert
    assert nbu_calls == [("UAH", "EUR", date(2026, 9, 15))]
    assert ecb_calls == []
    assert result.source == "nbu"


# Tests that a currency neither identity, ECB, nor NBU covers is rejected
# deterministically (rule D), without falling through to try a provider
# that should not handle it.
# Parameters:
# - monkeypatch: pytest fixture used to assert neither provider is called.
# Returns:
# - None. The test passes if FxRateUnavailableError is raised and neither
#   provider is invoked.
def test_resolve_fx_rate_unsupported_pairing_raises_without_calling_any_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    ecb_calls: list = []
    nbu_calls: list = []
    monkeypatch.setattr(
        fx_service._ecb_provider, "resolve_rate", lambda *a, **k: ecb_calls.append(1),
    )
    monkeypatch.setattr(
        fx_service._nbu_provider, "resolve_rate", lambda *a, **k: nbu_calls.append(1),
    )

    # Act / Assert - RUB is not ECB-supported and is not UAH
    with pytest.raises(FxRateUnavailableError):
        fx_service.resolve_fx_rate(
            original_currency="RUB", base_currency="EUR",
            transaction_date=date(2026, 9, 15), as_of=date(2026, 9, 16),
        )

    assert ecb_calls == []
    assert nbu_calls == []
