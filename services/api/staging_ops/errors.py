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
