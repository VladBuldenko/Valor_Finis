from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from app.modules.fx.fx_errors import (
    FxProviderUnavailableError,
    FxRateUnavailableError,
)
from app.modules.fx.fx_schemas import FxRateResult

# Official National Bank of Ukraine exchange-rate API - free, keyless.
# Exists specifically so UAH is not permanently unsupported merely because
# ECB does not publish it (verified live: ECB returns 404 for UAH).
# Verified live during VF-014B5C research (not assumed): unlike ECB, this
# endpoint only accepts a single `date`, not a range, and returns HTTP 200
# with an empty JSON array `[]` for a date/currency with no data - not a
# non-2xx status. It also already carries a weekend rate forward under
# that weekend's own date (Sat/Sun both returned a value equal to the
# preceding Friday's), so a bounded backward search here mostly exists for
# genuine gaps (e.g. an unsupported code), not routine weekends.
NBU_API_BASE_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"

NBU_TIMEOUT_SECONDS = 10.0

NBU_LOOKBACK_DAYS = 10


class NbuFxRateProvider:
    """
    Resolves historical UAH -> EUR rates against the official NBU
    exchange-rate API.

    What:
        Implements FxRateProvider for UAH converting into EUR only - see
        VF-014B5's "minimum required official support," which deliberately
        does not generalize NBU to other currency pairs.

    Why:
        NBU publishes "units of UAH per 1 EUR" (the same EUR-denominator
        convention as its own EUR/UAH reference quote); this provider
        inverts that into this project's canonical "base per 1 original"
        direction before returning.
    """

    # Resolves UAH -> EUR.
    # Parameters:
    # - original_currency: must be "UAH".
    # - base_currency: must be "EUR".
    # - transaction_date: the expense's own date; the lookback searches
    #   backward from this date, never forward.
    # Returns:
    # - FxRateResult with source="nbu".
    # Raises:
    # - FxRateUnavailableError: unsupported pairing, no observation in the
    #   bounded lookback window, or a non-positive rate.
    # - FxProviderUnavailableError: network/timeout/non-2xx/malformed
    #   response.
    def resolve_rate(
        self,
        original_currency: str,
        base_currency: str,
        transaction_date: date,
    ) -> FxRateResult:
        if original_currency != "UAH" or base_currency != "EUR":
            raise FxRateUnavailableError()

        for days_back in range(NBU_LOOKBACK_DAYS + 1):
            candidate_date = transaction_date - timedelta(days=days_back)

            try:
                response = httpx.get(
                    NBU_API_BASE_URL,
                    params={
                        "date": candidate_date.strftime("%Y%m%d"),
                        "valcode": "EUR",
                        "json": "",
                    },
                    timeout=NBU_TIMEOUT_SECONDS,
                )
            except httpx.HTTPError as error:
                raise FxProviderUnavailableError() from error

            if response.status_code != 200:
                raise FxProviderUnavailableError()

            try:
                payload = response.json()
            except ValueError as error:
                raise FxProviderUnavailableError() from error

            if not payload:
                # No data for this date - a real gap, keep searching
                # backward within the bounded window.
                continue

            entry = payload[0]
            raw_rate = entry.get("rate")
            raw_date = entry.get("exchangedate")

            if raw_rate is None or raw_date is None:
                continue

            try:
                # raw_rate is a JSON-decoded float. Converting via str()
                # (never Decimal(float) directly) avoids inheriting
                # binary-float noise.
                published_rate = Decimal(str(raw_rate))
                actual_rate_date = datetime.strptime(raw_date, "%d.%m.%Y").date()
            except (InvalidOperation, ValueError):
                continue

            if published_rate <= 0:
                raise FxRateUnavailableError()

            if actual_rate_date > transaction_date:
                # Defensive: never use a rate published after the
                # transaction date.
                continue

            # NBU publishes "units of UAH per 1 EUR" - invert to this
            # project's canonical "base (EUR) per 1 original (UAH)"
            # direction.
            canonical_rate = Decimal("1") / published_rate

            return FxRateResult(
                rate=canonical_rate,
                actual_rate_date=actual_rate_date,
                source="nbu",
            )

        raise FxRateUnavailableError()
