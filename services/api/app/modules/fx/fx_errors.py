class FxProviderUnavailableError(Exception):
    """
    Raised when an official FX provider is transiently unreachable.

    What:
        Represents a timeout, connection failure, or invalid/non-2xx HTTP
        response from a provider that should otherwise be able to answer.

    Why:
        Distinguishes "try again shortly" transient failures from
        FxRateUnavailableError's durable, not-retriable-right-now facts
        (unsupported currency, no rate in the lookback window). A
        provider failure is never permission to invent a rate or fall
        back to a different economic data source.
    """

    pass


class FxRateUnavailableError(Exception):
    """
    Raised when no FX rate can be resolved for a request.

    What:
        Represents an unsupported currency/base pairing, a bounded
        lookback window with no published rate, or a malformed/zero/
        negative rate value from an otherwise-reachable provider.

    Why:
        This is a durable fact about the specific request (this currency,
        this date), not a transient outage - retrying immediately would
        not help. Never silently substituted with an estimate or 1.
    """

    pass


class FxFutureDatedNotSupportedError(Exception):
    """
    Raised when a foreign-currency expense is dated in the future.

    What:
        Represents an attempt to resolve a historical FX snapshot for a
        transaction date that has not happened yet.

    Why:
        A future rate does not exist. Using today's rate as an estimate
        would create a fake, immutable "historical" snapshot indistinguishable
        later from a real one - exactly what this project's FX architecture
        forbids. Base-currency expenses are unaffected (identity conversion
        needs no rate).
    """

    pass
