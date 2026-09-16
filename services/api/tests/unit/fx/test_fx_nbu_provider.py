from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import httpx
import pytest

from app.modules.fx import fx_nbu_provider
from app.modules.fx.fx_errors import (
    FxProviderUnavailableError,
    FxRateUnavailableError,
)


def _mock_response(status_code: int = 200, json_body=None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body if json_body is not None else []
    return response


def _nbu_entry(rate: float, exchangedate: str) -> list:
    return [{"r030": 978, "txt": "Євро", "rate": rate, "cc": "EUR", "exchangedate": exchangedate, "special": None}]


# Tests that a successful UAH->EUR resolution inverts NBU's published
# "units of UAH per 1 EUR" into this project's canonical "EUR per 1 UAH"
# direction.
# Parameters:
# - monkeypatch: pytest fixture used to replace the module-level httpx client.
# Returns:
# - None. The test passes if the returned rate is the correct inversion.
def test_resolve_rate_uah_to_eur_canonical_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    get_mock = MagicMock(
        return_value=_mock_response(json_body=_nbu_entry(51.5231, "15.09.2026")),
    )
    monkeypatch.setattr(fx_nbu_provider.httpx, "get", get_mock)

    # Act
    result = fx_nbu_provider.NbuFxRateProvider().resolve_rate(
        original_currency="UAH", base_currency="EUR", transaction_date=date(2026, 9, 15),
    )

    # Assert
    assert result.rate == Decimal("1") / Decimal("51.5231")
    assert result.actual_rate_date == date(2026, 9, 15)
    assert result.source == "nbu"


# Tests that a weekend date - which NBU already carries the preceding
# rate forward under its own date, per live-verified behavior - resolves
# on the first attempt with no extra lookback needed.
# Parameters:
# - monkeypatch: pytest fixture used to replace the module-level httpx client.
# Returns:
# - None. The test passes if exactly one HTTP call is made and the
#   returned date matches the requested weekend date.
def test_resolve_rate_weekend_resolves_on_first_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange - Saturday 2026-09-12
    get_mock = MagicMock(
        return_value=_mock_response(json_body=_nbu_entry(51.7643, "12.09.2026")),
    )
    monkeypatch.setattr(fx_nbu_provider.httpx, "get", get_mock)

    # Act
    result = fx_nbu_provider.NbuFxRateProvider().resolve_rate(
        original_currency="UAH", base_currency="EUR", transaction_date=date(2026, 9, 12),
    )

    # Assert
    assert result.actual_rate_date == date(2026, 9, 12)
    assert get_mock.call_count == 1


# Tests that a genuine gap (empty array for the requested date) falls
# back to searching earlier dates within the bounded lookback, stopping
# at the first date with data.
# Parameters:
# - monkeypatch: pytest fixture used to replace the module-level httpx client.
# Returns:
# - None. The test passes if the second (one day earlier) query's result
#   is used.
def test_resolve_rate_gap_falls_back_within_bounded_lookback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange - first call (target date) returns empty, second (target - 1) has data
    responses = [
        _mock_response(json_body=[]),
        _mock_response(json_body=_nbu_entry(51.0, "14.09.2026")),
    ]
    get_mock = MagicMock(side_effect=responses)
    monkeypatch.setattr(fx_nbu_provider.httpx, "get", get_mock)

    # Act
    result = fx_nbu_provider.NbuFxRateProvider().resolve_rate(
        original_currency="UAH", base_currency="EUR", transaction_date=date(2026, 9, 15),
    )

    # Assert
    assert result.actual_rate_date == date(2026, 9, 14)
    assert get_mock.call_count == 2


# Tests that an empty response on every attempt within the bounded
# lookback raises FxRateUnavailableError, without an unbounded search.
# Parameters:
# - monkeypatch: pytest fixture used to replace the module-level httpx client.
# Returns:
# - None. The test passes if FxRateUnavailableError is raised after
#   exactly NBU_LOOKBACK_DAYS + 1 attempts.
def test_resolve_rate_bounded_lookback_exhausted_raises_rate_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    get_mock = MagicMock(return_value=_mock_response(json_body=[]))
    monkeypatch.setattr(fx_nbu_provider.httpx, "get", get_mock)

    # Act / Assert
    with pytest.raises(FxRateUnavailableError):
        fx_nbu_provider.NbuFxRateProvider().resolve_rate(
            original_currency="UAH", base_currency="EUR", transaction_date=date(2026, 9, 15),
        )

    assert get_mock.call_count == fx_nbu_provider.NBU_LOOKBACK_DAYS + 1


# Tests that a currency other than UAH is rejected without an HTTP call -
# NBU is deliberately not generalized beyond UAH->EUR in B5C.
# Parameters:
# - monkeypatch: pytest fixture used to assert no HTTP call is attempted.
# Returns:
# - None. The test passes if FxRateUnavailableError is raised and httpx.get
#   is never called.
def test_resolve_rate_non_uah_currency_never_calls_http(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    get_mock = MagicMock()
    monkeypatch.setattr(fx_nbu_provider.httpx, "get", get_mock)

    # Act / Assert
    with pytest.raises(FxRateUnavailableError):
        fx_nbu_provider.NbuFxRateProvider().resolve_rate(
            original_currency="USD", base_currency="EUR", transaction_date=date(2026, 9, 15),
        )

    get_mock.assert_not_called()


# Tests that a network timeout is reported as a transient provider
# failure and does not trigger the bounded-lookback retry loop (a real
# outage does not become "more available" by trying an earlier date).
# Parameters:
# - monkeypatch: pytest fixture used to replace the module-level httpx client.
# Returns:
# - None. The test passes if FxProviderUnavailableError is raised after
#   exactly one attempt.
def test_resolve_rate_timeout_raises_provider_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    get_mock = MagicMock(side_effect=httpx.TimeoutException("timed out"))
    monkeypatch.setattr(fx_nbu_provider.httpx, "get", get_mock)

    # Act / Assert
    with pytest.raises(FxProviderUnavailableError):
        fx_nbu_provider.NbuFxRateProvider().resolve_rate(
            original_currency="UAH", base_currency="EUR", transaction_date=date(2026, 9, 15),
        )

    assert get_mock.call_count == 1


# Tests that a malformed (non-JSON) response body is a provider failure.
# Parameters:
# - monkeypatch: pytest fixture used to replace the module-level httpx client.
# Returns:
# - None. The test passes if FxProviderUnavailableError is raised.
def test_resolve_rate_malformed_response_raises_provider_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    response = _mock_response(status_code=200)
    response.json.side_effect = ValueError("not json")
    monkeypatch.setattr(fx_nbu_provider.httpx, "get", MagicMock(return_value=response))

    # Act / Assert
    with pytest.raises(FxProviderUnavailableError):
        fx_nbu_provider.NbuFxRateProvider().resolve_rate(
            original_currency="UAH", base_currency="EUR", transaction_date=date(2026, 9, 15),
        )


# Tests that a zero published rate is rejected rather than propagated or
# divided by.
# Parameters:
# - monkeypatch: pytest fixture used to replace the module-level httpx client.
# Returns:
# - None. The test passes if FxRateUnavailableError is raised.
def test_resolve_rate_zero_rate_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    get_mock = MagicMock(return_value=_mock_response(json_body=_nbu_entry(0.0, "15.09.2026")))
    monkeypatch.setattr(fx_nbu_provider.httpx, "get", get_mock)

    # Act / Assert
    with pytest.raises(FxRateUnavailableError):
        fx_nbu_provider.NbuFxRateProvider().resolve_rate(
            original_currency="UAH", base_currency="EUR", transaction_date=date(2026, 9, 15),
        )


# Tests that a negative published rate is rejected.
# Parameters:
# - monkeypatch: pytest fixture used to replace the module-level httpx client.
# Returns:
# - None. The test passes if FxRateUnavailableError is raised.
def test_resolve_rate_negative_rate_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    get_mock = MagicMock(return_value=_mock_response(json_body=_nbu_entry(-5.0, "15.09.2026")))
    monkeypatch.setattr(fx_nbu_provider.httpx, "get", get_mock)

    # Act / Assert
    with pytest.raises(FxRateUnavailableError):
        fx_nbu_provider.NbuFxRateProvider().resolve_rate(
            original_currency="UAH", base_currency="EUR", transaction_date=date(2026, 9, 15),
        )


# Tests that requesting a non-EUR base currency is rejected without an
# HTTP call.
# Parameters:
# - monkeypatch: pytest fixture used to assert no HTTP call is attempted.
# Returns:
# - None. The test passes if FxRateUnavailableError is raised and httpx.get
#   is never called.
def test_resolve_rate_non_eur_base_never_calls_http(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    get_mock = MagicMock()
    monkeypatch.setattr(fx_nbu_provider.httpx, "get", get_mock)

    # Act / Assert
    with pytest.raises(FxRateUnavailableError):
        fx_nbu_provider.NbuFxRateProvider().resolve_rate(
            original_currency="UAH", base_currency="USD", transaction_date=date(2026, 9, 15),
        )

    get_mock.assert_not_called()
