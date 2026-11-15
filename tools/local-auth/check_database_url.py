"""Validate the DISPOSABLE local application database URL for tools/local-auth/api-env.sh.

The URL is read from the LOCAL_AUTH_APP_DATABASE_URL environment variable (never from argv) and is parsed with
SQLAlchemy's own URL parser, the same parser the API uses, so nothing is checked by substring or regex.
Exit 0: acceptable. Exit 1: rejected, with a fixed reason on stderr. The URL and any password in it are never printed.
Pure parsing: this script never opens a connection.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

ALLOWED_DRIVERS = {"postgresql", "postgresql+psycopg2"}  # the API uses psycopg2
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
REQUIRED_PORT = 54332
REQUIRED_DATABASE = "valor_localauth"


def rejection_reason(raw: str) -> str | None:
    try:
        url = make_url(raw)
    except (ArgumentError, ValueError):
        return "not a valid database URL"
    if url.drivername not in ALLOWED_DRIVERS:
        return "driver must be postgresql (psycopg2)"
    if url.query:
        # libpq lets query parameters (host, hostaddr, port, dbname, service, ...) override the URL authority
        return "query parameters are not allowed"
    if url.host not in ALLOWED_HOSTS:
        return "host must be an explicit loopback host (127.0.0.1, localhost or ::1)"
    if url.port != REQUIRED_PORT:
        return f"port must be exactly {REQUIRED_PORT}"
    if url.database != REQUIRED_DATABASE:
        return f"database must be exactly {REQUIRED_DATABASE}"
    if url.render_as_string(hide_password=False) != raw:
        return "URL is not in canonical form"  # catches stray whitespace, fragments and odd encodings
    return None


def main() -> int:
    raw = os.environ.get("LOCAL_AUTH_APP_DATABASE_URL", "")
    reason = rejection_reason(raw) if raw else "LOCAL_AUTH_APP_DATABASE_URL is not set"
    if reason:
        print(f"refusing: DATABASE_URL rejected: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
