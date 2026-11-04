"""
Refusal type for the staging identity guard.

What:
    One exception with a stable machine-readable code and a fixed message.

Why:
    A refusal must never echo a URL, host, user name, password or key, so
    messages are fixed text chosen per code. Callers and tests branch on the
    code, operators read the message.
"""


class StagingRefused(Exception):
    """Raised when a staging operation must stop before any mutation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        # Set by the orchestrators: True when a mutation had already begun.
        self.mutated = False


# Wraps any non-refusal exception so no driver or library message (which can
# name a host or user) reaches the terminal, a log or an evidence record.
# Parameters:
# - error: the exception that stopped the operation.
# Returns:
# - A StagingRefused carrying only the exception type name.
def unexpected(error: BaseException) -> StagingRefused:
    return StagingRefused("UNEXPECTED", f"{type(error).__name__}: an unexpected error stopped the operation; details are withheld")
