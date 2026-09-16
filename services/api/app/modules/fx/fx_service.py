from datetime import date
from decimal import Decimal

from app.modules.fx.fx_ecb_provider import ECB_SUPPORTED_CURRENCIES, EcbFxRateProvider
from app.modules.fx.fx_errors import FxFutureDatedNotSupportedError, FxRateUnavailableError
from app.modules.fx.fx_nbu_provider import NbuFxRateProvider
from app.modules.fx.fx_schemas import FxRateResult

IDENTITY_SOURCE = "identity"

_ecb_provider = EcbFxRateProvider()
_nbu_provider = NbuFxRateProvider()


# Resolves the canonical FX rate for a transaction, selecting the correct
# provider deterministically.
# This function exists as the single entry point expenses_service uses for
# FX resolution, so provider selection (identity/ECB/NBU/unsupported) is
# decided in exactly one place per Section 10's rules A-D, and never
# silently falls through from one economic data source to another after a
# provider that should have handled a currency returns bad data.
# Parameters:
# - original_currency: the transaction's own currency code.
# - base_currency: the user's base currency code (from financial_settings).
# - transaction_date: the expense's own date - the historical date FX
#   truth is resolved for, never revalued using a later date.
# - as_of: reference "today" used only to reject a future-dated foreign
#   transaction (identity conversions are unaffected - no rate needed).
#   Explicit, not read from a hidden clock, so this stays deterministic
#   and testable, matching this project's existing as_of convention
#   (budget_period.py, analytics_service.py).
# Returns:
# - FxRateResult in the canonical base-per-original direction.
# Raises:
# - FxFutureDatedNotSupportedError: a foreign-currency transaction dated
#   after as_of.
# - FxRateUnavailableError: original_currency/base_currency is not one of
#   identity/ECB/NBU's supported pairings (rule D), or the selected
#   provider could not resolve a rate.
# - FxProviderUnavailableError: the selected provider failed transiently.
def resolve_fx_rate(
    original_currency: str,
    base_currency: str,
    transaction_date: date,
    as_of: date,
) -> FxRateResult:
    if original_currency == base_currency:
        # Rule A: identity. No network call, no future-date restriction -
        # a "conversion" to itself is always deterministically rate=1.
        return FxRateResult(
            rate=Decimal("1"),
            actual_rate_date=transaction_date,
            source=IDENTITY_SOURCE,
        )

    if transaction_date > as_of:
        raise FxFutureDatedNotSupportedError()

    if base_currency == "EUR" and original_currency in ECB_SUPPORTED_CURRENCIES:
        # Rule B.
        return _ecb_provider.resolve_rate(
            original_currency=original_currency,
            base_currency=base_currency,
            transaction_date=transaction_date,
        )

    if original_currency == "UAH" and base_currency == "EUR":
        # Rule C.
        return _nbu_provider.resolve_rate(
            original_currency=original_currency,
            base_currency=base_currency,
            transaction_date=transaction_date,
        )

    # Rule D: no official source covers this pairing in B5C.
    raise FxRateUnavailableError()
