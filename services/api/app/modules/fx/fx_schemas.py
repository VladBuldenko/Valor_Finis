from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class FxRateResult:
    """
    A resolved FX rate, in this project's canonical direction.

    Fields:
        rate: units of base currency per 1 unit of the original currency.
            base_amount = original_amount * rate.
        actual_rate_date: the real published-rate date used. May differ
            from the requested transaction date (weekends/holidays,
            bounded lookback) but is never later than it.
        source: which provider resolved this rate, e.g. "identity", "ecb",
            "nbu".
    """

    rate: Decimal
    actual_rate_date: date
    source: str


class FxRateProvider(Protocol):
    """
    Interface for official FX rate providers.

    What:
        Defines the operation required from any FX rate provider.

    Why:
        Lets the resolver call ECB/NBU (or a future official source)
        interchangeably without callers needing to know which one
        answered. Mirrors the existing ReceiptOcrProvider Protocol
        pattern (receipt_ocr_service.py).
    """

    def resolve_rate(
        self,
        original_currency: str,
        base_currency: str,
        transaction_date: date,
    ) -> FxRateResult:
        """
        Resolves the historical rate for original_currency -> base_currency
        as of transaction_date.

        Parameters:
        - original_currency: the transaction's own currency code.
        - base_currency: the user's base currency code.
        - transaction_date: the expense's own date - never today's date
          for a historical lookup.

        Returns:
        - FxRateResult in the canonical base-per-original direction.

        Raises:
        - FxRateUnavailableError: unsupported currency/base pairing, no
          rate within the bounded lookback, or a malformed/non-positive
          rate value.
        - FxProviderUnavailableError: the provider was reachable-in-
          principle but failed transiently (timeout, connection error,
          non-2xx/malformed response).
        """

        ...
