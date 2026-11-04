"""
Redaction and one-way identifier fingerprints.

What:
    Removes credentials, URLs and known secret values from text that may be
    printed, logged or written to evidence, and fingerprints identifiers.

Why:
    Subprocess output and driver errors can contain connection details. The
    staging tooling prints and stores only redacted text. The fingerprint is
    the same `fp1:` form the QA-0 register uses (SHA-256, first 16 hex
    characters) so a reviewer can compare identities without the repository
    naming a host.
"""

import hashlib
import re
from typing import Iterable

REDACTED = "<redacted>"

_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^\s'\"<>]+")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]*")
_SB_KEY = re.compile(r"\bsb_(?:publishable|secret)_[A-Za-z0-9_\-]+")
_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|apikey|api_key)\s*[=:]\s*[^\s,;'\"]+",
)
# libpq / psycopg2 / SQLAlchemy connection errors name the server and its address.
_SERVER_AT = re.compile(r'(?i)(server at )"[^"]*"(?:\s*\([^)]*\))?')
_HOST_NAME = re.compile(r'(?i)(host(?: name)? )"[^"]*"(?:\s*\([^)]*\))?')
_BARE_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


# Returns text that is safe to print or store.
# URLs, bearer tokens, JWTs, Supabase keys, password-like assignments, IP
# addresses and libpq server fragments are replaced by a fixed marker, then
# every known secret value is removed by exact match.
# Parameters:
# - text: raw text, for example subprocess output.
# - secrets: exact values that must never appear (passwords, keys, URLs).
# Returns:
# - Redacted text.
def redact(text: str, secrets: Iterable[str] = ()) -> str:
    cleaned = text

    # Patterns first: replacing a secret inside a URL would otherwise leave
    # "<redacted>" markers that cut the URL pattern short and expose the host.
    for pattern in (_URL, _BEARER, _JWT, _SB_KEY, _ASSIGNMENT, _BARE_IP):
        cleaned = pattern.sub(REDACTED, cleaned)

    for pattern in (_SERVER_AT, _HOST_NAME):
        cleaned = pattern.sub(lambda match: match.group(1) + REDACTED, cleaned)

    for secret in sorted({value for value in secrets if value}, key=len, reverse=True):
        cleaned = cleaned.replace(secret, REDACTED)

    return cleaned


# Returns a one-way, non-secret fingerprint of an identifier.
# Parameters:
# - kind: what the value identifies, for example "db-host" (domain separation).
# - value: the identifier (already normalized by the caller).
# Returns:
# - "fp1:" plus the first 16 hex characters of SHA-256 over "kind:value".
def fingerprint(kind: str, value: str) -> str:
    digest = hashlib.sha256(f"{kind}:{value}".encode("utf-8")).hexdigest()

    return f"fp1:{digest[:16]}"
