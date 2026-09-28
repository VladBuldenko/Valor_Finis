"""
Test database safety guard.

What:
    Validates that the database the backend test suite is about to use is a
    dedicated PostgreSQL test database: its name must end exactly with
    "_test" (for example valor_test).

Why:
    tests/conftest.py's clean_database fixture deletes every row of the
    application tables, for all users. The app configuration falls back to
    the local development database ("valor") when DATABASE_URL is not
    overridden, so an unguarded pytest run could wipe development data -
    or, if pytest were ever run inside a deployed container, production
    data. This guard makes the suite fail closed instead.

    This protects against accidental destruction; it is not a security
    boundary. It lives under tests/ on purpose: it is test-infrastructure
    logic and never runs in the application itself.
"""

from typing import Union

from sqlalchemy.engine import URL, make_url

REQUIRED_DATABASE_NAME_SUFFIX = "_test"

SAFE_COMMAND_EXAMPLE = (
    "DATABASE_URL=postgresql://<user>:<password>@localhost:5432/valor_test "
    ".venv/bin/python -m pytest -q"
)


class UnsafeTestDatabaseError(Exception):
    """
    Raised when the backend test suite is pointed at a database that is not
    a dedicated PostgreSQL *_test database.

    What:
        Signals that destructive test fixtures must not run.

    Why:
        Lets pytest abort before any cleanup DELETE can reach a development
        or production database. The message never contains the database
        URL, username, or password.
    """

    pass


# Returns the database name of a URL that is safe for the destructive
# backend test suite, or raises.
# This function exists so the pytest session guard (pytest_configure) and
# the clean_database fixture enforce one identical rule. The URL is parsed
# with SQLAlchemy's own URL parser (never substring-matched), so escaped
# credentials and query parameters cannot influence the detected database
# name. Every failure message is built only from the parsed database name
# (never the raw URL), so credentials are never echoed; a URL that cannot
# be parsed is rejected without repeating any of its text.
# Parameters:
# - database_url: the effective database URL (a string or an already
#   parsed sqlalchemy.engine.URL, e.g. engine.url).
# Returns:
# - The validated database name.
# Raises:
# - UnsafeTestDatabaseError: when the URL cannot be parsed, is not a
#   PostgreSQL URL, has no database name, or the database name does not
#   end exactly with "_test".
def validate_test_database_url(database_url: Union[str, URL]) -> str:
    try:
        parsed_url = make_url(database_url)
    except Exception:
        # Any parse failure (ArgumentError, or e.g. ValueError for a bad
        # port) is rejected. "from None" drops the original exception so
        # none of the raw URL text can surface through the traceback chain.
        raise UnsafeTestDatabaseError(
            "Refusing to run backend tests: DATABASE_URL could not be parsed. "
            "Tests require a dedicated PostgreSQL database whose name ends "
            f"with '{REQUIRED_DATABASE_NAME_SUFFIX}'. Example: "
            f"{SAFE_COMMAND_EXAMPLE}"
        ) from None

    if parsed_url.get_backend_name() != "postgresql":
        raise UnsafeTestDatabaseError(
            "Refusing to run backend tests: DATABASE_URL does not point to "
            "PostgreSQL. Tests require a dedicated PostgreSQL database whose "
            f"name ends with '{REQUIRED_DATABASE_NAME_SUFFIX}'. Example: "
            f"{SAFE_COMMAND_EXAMPLE}"
        )

    database_name = parsed_url.database

    if not database_name:
        raise UnsafeTestDatabaseError(
            "Refusing to run backend tests: DATABASE_URL has no database "
            "name. Tests require a dedicated PostgreSQL database whose name "
            f"ends with '{REQUIRED_DATABASE_NAME_SUFFIX}'. Example: "
            f"{SAFE_COMMAND_EXAMPLE}"
        )

    # Exact, case-sensitive suffix: ambiguous names such as "VALOR_TEST"
    # or "valor_testing" are rejected (fail closed).
    if not database_name.endswith(REQUIRED_DATABASE_NAME_SUFFIX):
        raise UnsafeTestDatabaseError(
            "Refusing to run backend tests against database "
            f"'{database_name}': the test suite deletes all application "
            "data, so it requires a dedicated PostgreSQL database whose name "
            f"ends with '{REQUIRED_DATABASE_NAME_SUFFIX}' (for example "
            "valor_test). Set DATABASE_URL explicitly, e.g. "
            f"{SAFE_COMMAND_EXAMPLE}"
        )

    return database_name
