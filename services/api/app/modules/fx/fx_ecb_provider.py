from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Tuple

import httpx

from app.modules.fx.fx_errors import (
    FxProviderUnavailableError,
    FxRateUnavailableError,
)
from app.modules.fx.fx_schemas import FxRateResult

# Official ECB SDMX 2.1 REST API - free, keyless, supports an arbitrary
# per-currency date-range query. Verified live against the real endpoint
# during VF-014B5A/B5C research (not assumed from memory): a plain date
# query for a non-trading day (weekend/holiday) simply returns no
# observation for that day, and an unsupported currency returns 404.
ECB_API_BASE_URL = "https://data-api.ecb.europa.eu/service/data/EXR"

ECB_TIMEOUT_SECONDS = 10.0

# Never search further back than this for a published rate. ECB's longest
# recurring gap (Christmas/New Year) is well under this; a wider search
# would risk an unbounded-feeling retry for a currency that simply has no
# recent data.
ECB_LOOKBACK_DAYS = 10

# The non-EUR currencies ECB publishes daily reference rates for, verified
# live against the ECB SDMX API (eurofxref-daily.xml currency list).
# Notably excludes UAH - see fx_nbu_provider.py.
ECB_SUPPORTED_CURRENCIES = frozenset(
    {
        "AUD", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "GBP", "HKD", "HUF",
        "IDR", "ILS", "INR", "ISK", "JPY", "KRW", "MXN", "MYR", "NOK", "NZD",
        "PHP", "PLN", "RON", "SEK", "SGD", "THB", "TRY", "USD", "ZAR",
    }
)


# Extracts the most recent (currency, EUR) observation from an ECB SDMX
# jsondata response body.
# This function exists to isolate SDMX's nested, index-keyed observation
# structure from the provider's own control flow.
# Parameters:
# - payload: parsed JSON response body from the ECB SDMX data endpoint.
# Returns:
# - (rate, actual_rate_date) as (Decimal, date) for the latest observation
#   in the queried range, or (None, None) if the response shape does not
#   contain a usable observation.
def _extract_latest_observation(
    payload: Any,
) -> Tuple[Optional[Decimal], Optional[date]]:
    try:
        series = payload["dataSets"][0]["series"]
        series_key = next(iter(series))
        observations = series[series_key]["observations"]

        if not observations:
            return None, None

        time_period_values = (
            payload["structure"]["dimensions"]["observation"][0]["values"]
        )

        # Observation keys are string indices ("0","1",...) into
        # time_period_values, in the same chronological order ECB returns
        # them. The highest index is the most recent date in the range.
        latest_index = max(int(key) for key in observations.keys())
        rate_value = observations[str(latest_index)][0]
        actual_rate_date = date.fromisoformat(
            time_period_values[latest_index]["id"],
        )

        # rate_value is a JSON-decoded float. Converting via str() (never
        # Decimal(float) directly) avoids inheriting binary-float noise.
        rate = Decimal(str(rate_value))

        return rate, actual_rate_date
    except (KeyError, IndexError, StopIteration, TypeError, ValueError, InvalidOperation):
        return None, None


class EcbFxRateProvider:
    """
    Resolves historical rates against the official ECB reference rate
    SDMX API.

    What:
        Implements FxRateProvider for any of ECB_SUPPORTED_CURRENCIES
        converting into EUR.

    Why:
        ECB is the official/reference source for euro exchange rates -
        see VF-014B5A. ECB always publishes "units of foreign currency
        per 1 EUR"; this provider inverts that into this project's
        canonical "base per 1 original" direction before returning.
    """

    # Resolves original_currency -> base_currency (base_currency must be
    # EUR - ECB is EUR-centric; a non-EUR base is out of scope for B5C,
    # see the VF-014B5A cross-rate note).
    # Parameters:
    # - original_currency: must be one of ECB_SUPPORTED_CURRENCIES.
    # - base_currency: must be "EUR".
    # - transaction_date: the expense's own date; the lookback searches
    #   backward from this date, never forward.
    # Returns:
    # - FxRateResult with source="ecb".
    # Raises:
    # - FxRateUnavailableError: unsupported currency/base, no observation
    #   in the bounded lookback window, or a non-positive rate.
    # - FxProviderUnavailableError: network/timeout/non-2xx/malformed
    #   response.
    def resolve_rate(
        self,
        original_currency: str,
        base_currency: str,
        transaction_date: date,
    ) -> FxRateResult:
        if base_currency != "EUR" or original_currency not in ECB_SUPPORTED_CURRENCIES:
            raise FxRateUnavailableError()

        start_period = transaction_date - timedelta(days=ECB_LOOKBACK_DAYS)
        url = f"{ECB_API_BASE_URL}/D.{original_currency}.EUR.SP00.A"

        try:
            response = httpx.get(
                url,
                params={
                    "startPeriod": start_period.isoformat(),
                    "endPeriod": transaction_date.isoformat(),
                    "format": "jsondata",
                },
                timeout=ECB_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as error:
            raise FxProviderUnavailableError() from error

        if response.status_code == 404:
            # No observation at all in the queried range - a real,
            # bounded data gap, not a provider outage.
            raise FxRateUnavailableError()

        if response.status_code != 200:
            raise FxProviderUnavailableError()

        try:
            payload = response.json()
        except ValueError as error:
            raise FxProviderUnavailableError() from error

        published_rate, actual_rate_date = _extract_latest_observation(payload)

        if published_rate is None or actual_rate_date is None:
            raise FxRateUnavailableError()

        if published_rate <= 0:
            raise FxRateUnavailableError()

        if actual_rate_date > transaction_date:
            # Defensive: never use a rate published after the transaction
            # date, even though the endPeriod bound should already
            # prevent this.
            raise FxRateUnavailableError()

        # ECB publishes "units of original_currency per 1 EUR" - invert
        # to this project's canonical "base (EUR) per 1 original" direction.
        canonical_rate = Decimal("1") / published_rate

        return FxRateResult(
            rate=canonical_rate,
            actual_rate_date=actual_rate_date,
            source="ecb",
        )
