from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import httpx
import pytest

from app.modules.fx import fx_ecb_provider
from app.modules.fx.fx_errors import (
    FxProviderUnavailableError,
    FxRateUnavailableError,
)


# Builds a synthetic ECB SDMX jsondata response body matching the real
# shape verified live during VF-014B5A/B5C research: an "observations"
# dict keyed by string index, paired with a "TIME_PERIOD" dimension values
# list in the same order.
# Parameters:
# - observations: list of (iso_date_str, rate) tuples in chronological order.
# Returns:
# - A dict matching the real ECB SDMX response shape.
def _build_ecb_payload(observations: list) -> dict:
    return {
        "dataSets": [
            {
                "series": {
                    "0:0:0:0:0": {
                        "observations": {
                            str(index): [rate, 0, 0, None, None]
                            for index, (_, rate) in enumerate(observations)
                        },
                    },
                },
            },
        ],
        "structure": {
            "dimensions": {
                "observation": [
                    {
                        "id": "TIME_PERIOD",
                        "values": [
                            {"id": date_str} for date_str, _ in observations
                        ],
                    },
                ],
            },
        },
    }


def _mock_response(status_code: int = 200, json_body=None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    if json_body is not None:
        response.json.return_value = json_body
    return response


# Tests that a successful USD->EUR resolution inverts ECB's published
# "units of USD per 1 EUR" into this project's canonical "EUR per 1 USD"
# direction.
# Parameters:
# - monkeypatch: pytest fixture used to replace the module-level httpx client.
# Returns:
# - None. The test passes if the returned rate is the correct inversion.
def test_resolve_rate_usd_to_eur_canonical_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    payload = _build_ecb_payload([("2026-09-15", 1.1539)])
    get_mock = MagicMock(return_value=_mock_response(json_body=payload))
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", get_mock)

    # Act
    result = fx_ecb_provider.EcbFxRateProvider().resolve_rate(
        original_currency="USD", base_currency="EUR", transaction_date=date(2026, 9, 15),
    )

    # Assert
    assert result.rate == Decimal("1") / Decimal("1.1539")
    assert result.actual_rate_date == date(2026, 9, 15)
    assert result.source == "ecb"


# Tests that the provider picks the most recent observation in the queried
# range - the mechanism a weekend/holiday gap relies on, since ECB simply
# omits non-trading days rather than forward-filling them.
# Parameters:
# - monkeypatch: pytest fixture used to replace the module-level httpx client.
# Returns:
# - None. The test passes if the Friday observation is used even though
#   the request's endPeriod was the following Sunday.
def test_resolve_rate_weekend_uses_latest_prior_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange - Friday 09-11 is the only observation; 09-12/09-13 (Sat/Sun)
    # simply do not appear, matching ECB's real behavior.
    payload = _build_ecb_payload([("2026-09-11", 1.17)])
    get_mock = MagicMock(return_value=_mock_response(json_body=payload))
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", get_mock)

    # Act - as_of Sunday 2026-09-13
    result = fx_ecb_provider.EcbFxRateProvider().resolve_rate(
        original_currency="USD", base_currency="EUR", transaction_date=date(2026, 9, 13),
    )

    # Assert
    assert result.actual_rate_date == date(2026, 9, 11)
    assert result.rate == Decimal("1") / Decimal("1.17")


# Tests that no observation at all within the bounded lookback (ECB
# returns 404 for a currency/range with nothing published) raises
# FxRateUnavailableError, not a provider failure.
# Parameters:
# - monkeypatch: pytest fixture used to replace the module-level httpx client.
# Returns:
# - None. The test passes if FxRateUnavailableError is raised.
def test_resolve_rate_bounded_lookback_exhausted_raises_rate_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    get_mock = MagicMock(return_value=_mock_response(status_code=404))
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", get_mock)

    # Act / Assert
    with pytest.raises(FxRateUnavailableError):
        fx_ecb_provider.EcbFxRateProvider().resolve_rate(
            original_currency="USD", base_currency="EUR", transaction_date=date(2026, 9, 15),
        )


# Tests that a currency ECB does not publish (e.g. UAH) is rejected
# without ever making an HTTP call.
# Parameters:
# - monkeypatch: pytest fixture used to assert no HTTP call is attempted.
# Returns:
# - None. The test passes if FxRateUnavailableError is raised and httpx.get
#   is never called.
def test_resolve_rate_unsupported_currency_never_calls_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    get_mock = MagicMock()
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", get_mock)

    # Act / Assert
    with pytest.raises(FxRateUnavailableError):
        fx_ecb_provider.EcbFxRateProvider().resolve_rate(
            original_currency="UAH", base_currency="EUR", transaction_date=date(2026, 9, 15),
        )

    get_mock.assert_not_called()


# Tests that a network timeout is reported as a transient provider
# failure, distinct from a durable "no rate" fact.
# Parameters:
# - monkeypatch: pytest fixture used to replace the module-level httpx client.
# Returns:
# - None. The test passes if FxProviderUnavailableError is raised.
def test_resolve_rate_timeout_raises_provider_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    get_mock = MagicMock(side_effect=httpx.TimeoutException("timed out"))
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", get_mock)

    # Act / Assert
    with pytest.raises(FxProviderUnavailableError):
        fx_ecb_provider.EcbFxRateProvider().resolve_rate(
            original_currency="USD", base_currency="EUR", transaction_date=date(2026, 9, 15),
        )


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
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", MagicMock(return_value=response))

    # Act / Assert
    with pytest.raises(FxProviderUnavailableError):
        fx_ecb_provider.EcbFxRateProvider().resolve_rate(
            original_currency="USD", base_currency="EUR", transaction_date=date(2026, 9, 15),
        )


# Tests that a zero published rate is rejected rather than propagated or
# divided by.
# Parameters:
# - monkeypatch: pytest fixture used to replace the module-level httpx client.
# Returns:
# - None. The test passes if FxRateUnavailableError is raised.
def test_resolve_rate_zero_rate_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    payload = _build_ecb_payload([("2026-09-15", 0.0)])
    monkeypatch.setattr(
        fx_ecb_provider.httpx, "get", MagicMock(return_value=_mock_response(json_body=payload)),
    )

    # Act / Assert
    with pytest.raises(FxRateUnavailableError):
        fx_ecb_provider.EcbFxRateProvider().resolve_rate(
            original_currency="USD", base_currency="EUR", transaction_date=date(2026, 9, 15),
        )


# Tests that a negative published rate is rejected.
# Parameters:
# - monkeypatch: pytest fixture used to replace the module-level httpx client.
# Returns:
# - None. The test passes if FxRateUnavailableError is raised.
def test_resolve_rate_negative_rate_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    payload = _build_ecb_payload([("2026-09-15", -1.1)])
    monkeypatch.setattr(
        fx_ecb_provider.httpx, "get", MagicMock(return_value=_mock_response(json_body=payload)),
    )

    # Act / Assert
    with pytest.raises(FxRateUnavailableError):
        fx_ecb_provider.EcbFxRateProvider().resolve_rate(
            original_currency="USD", base_currency="EUR", transaction_date=date(2026, 9, 15),
        )


# Tests that requesting a non-EUR base currency is rejected without an
# HTTP call - ECB is EUR-centric and general cross-rate support is out of
# scope for B5C.
# Parameters:
# - monkeypatch: pytest fixture used to assert no HTTP call is attempted.
# Returns:
# - None. The test passes if FxRateUnavailableError is raised and httpx.get
#   is never called.
def test_resolve_rate_non_eur_base_never_calls_http(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    get_mock = MagicMock()
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", get_mock)

    # Act / Assert
    with pytest.raises(FxRateUnavailableError):
        fx_ecb_provider.EcbFxRateProvider().resolve_rate(
            original_currency="USD", base_currency="GBP", transaction_date=date(2026, 9, 15),
        )

    get_mock.assert_not_called()


# Tests that the request uses a bounded lookback window (not an unbounded
# search), sent as explicit startPeriod/endPeriod query parameters.
# Parameters:
# - monkeypatch: pytest fixture used to capture the call arguments.
# Returns:
# - None. The test passes if the date range spans exactly
#   ECB_LOOKBACK_DAYS.
def test_resolve_rate_uses_bounded_lookback_window(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    payload = _build_ecb_payload([("2026-09-15", 1.1539)])
    get_mock = MagicMock(return_value=_mock_response(json_body=payload))
    monkeypatch.setattr(fx_ecb_provider.httpx, "get", get_mock)

    # Act
    fx_ecb_provider.EcbFxRateProvider().resolve_rate(
        original_currency="USD", base_currency="EUR", transaction_date=date(2026, 9, 15),
    )

    # Assert
    call_kwargs = get_mock.call_args.kwargs
    params = call_kwargs["params"]
    start = date.fromisoformat(params["startPeriod"])
    end = date.fromisoformat(params["endPeriod"])
    assert (end - start).days == fx_ecb_provider.ECB_LOOKBACK_DAYS
    assert end == date(2026, 9, 15)
