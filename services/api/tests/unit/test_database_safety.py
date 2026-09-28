import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.database_safety import UnsafeTestDatabaseError, validate_test_database_url

# services/api (tests/unit/<this file> -> parents[2]).
_API_ROOT = Path(__file__).resolve().parents[2]
_REPOSITORY_ROOT = _API_ROOT.parents[1]
_CI_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github" / "workflows" / "backend-ci.yml"


# Tests that dedicated *_test PostgreSQL databases are accepted, whatever
# the driver, credentials escaping, or query parameters.
# These tests never connect to a database: validation is pure URL parsing.
# Parameters:
# - database_url: candidate URL.
# - expected_database_name: the name the guard must detect.
# Returns:
# - None.
@pytest.mark.parametrize(
    ("database_url", "expected_database_name"),
    [
        ("postgresql://postgres:postgres@localhost:5432/valor_test", "valor_test"),
        (
            "postgresql://postgres:postgres@localhost:5432/valor_integration_test",
            "valor_integration_test",
        ),
        ("postgresql+psycopg2://postgres:postgres@localhost:5432/valor_test", "valor_test"),
        (
            "postgresql://postgres:postgres@localhost:5432/valor_test?sslmode=require&application_name=valor",
            "valor_test",
        ),
        ("postgresql://postgres:p%40ss%2Fword@localhost:5432/valor_test", "valor_test"),
    ],
)
def test_validate_test_database_url_accepts_dedicated_test_database(
    database_url: str,
    expected_database_name: str,
) -> None:
    assert validate_test_database_url(database_url) == expected_database_name


# Tests that PostgreSQL databases whose name does not end exactly with
# "_test" are rejected, and that the message names the detected database.
# Parameters:
# - database_name: rejected database name.
# Returns:
# - None.
@pytest.mark.parametrize(
    "database_name",
    ["valor", "postgres", "valor_testing", "test_valor", "VALOR_TEST"],
)
def test_validate_test_database_url_rejects_non_test_database_names(
    database_name: str,
) -> None:
    with pytest.raises(UnsafeTestDatabaseError) as error_info:
        validate_test_database_url(
            f"postgresql://postgres:postgres@localhost:5432/{database_name}"
        )

    message = str(error_info.value)

    assert f"'{database_name}'" in message
    assert "_test" in message


# Tests that query parameters cannot smuggle a "_test" name past the guard:
# the database name is taken from the parsed URL path only.
# Parameters:
# - None.
# Returns:
# - None.
def test_validate_test_database_url_ignores_test_suffix_in_query_params() -> None:
    with pytest.raises(UnsafeTestDatabaseError) as error_info:
        validate_test_database_url(
            "postgresql://postgres:postgres@localhost:5432/valor"
            "?application_name=valor_test&options=valor_test"
        )

    assert "'valor'" in str(error_info.value)


# Tests that a PostgreSQL URL without a database name is rejected.
# Parameters:
# - database_url: URL with no database name.
# Returns:
# - None.
@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://postgres:postgres@localhost:5432/",
        "postgresql://localhost",
    ],
)
def test_validate_test_database_url_rejects_missing_database_name(
    database_url: str,
) -> None:
    with pytest.raises(UnsafeTestDatabaseError, match="no database name"):
        validate_test_database_url(database_url)


# Tests that non-PostgreSQL URLs are rejected even when the database name
# looks like a test database.
# Parameters:
# - None.
# Returns:
# - None.
def test_validate_test_database_url_rejects_non_postgresql_backend() -> None:
    with pytest.raises(UnsafeTestDatabaseError, match="does not point to PostgreSQL"):
        validate_test_database_url("sqlite:///valor_test")


# Tests that malformed URLs are rejected without echoing any of their text
# (the raw string could contain credentials), including through the
# exception chain.
# Parameters:
# - malformed_url: unparseable URL.
# Returns:
# - None.
@pytest.mark.parametrize(
    "malformed_url",
    [
        "not a url with s3cr3t-token",
        "postgresql://guard_user:guard_secret@localhost:notaport/valor_test",
        "",
    ],
)
def test_validate_test_database_url_rejects_malformed_url_without_echo(
    malformed_url: str,
) -> None:
    with pytest.raises(UnsafeTestDatabaseError, match="could not be parsed") as error_info:
        validate_test_database_url(malformed_url)

    message = str(error_info.value)

    for fragment in ("s3cr3t-token", "guard_user", "guard_secret", "notaport"):
        assert fragment not in message

    assert error_info.value.__cause__ is None
    assert error_info.value.__suppress_context__ is True


# Tests that a rejected URL's username and password never appear in the
# error message.
# Parameters:
# - None.
# Returns:
# - None.
def test_validate_test_database_url_error_does_not_leak_credentials() -> None:
    with pytest.raises(UnsafeTestDatabaseError) as error_info:
        validate_test_database_url(
            "postgresql://guard_user:guard_secret_pw@db.example.com:5432/valor"
        )

    message = str(error_info.value)

    assert "guard_user" not in message
    assert "guard_secret_pw" not in message
    assert "db.example.com" not in message


# Tests that the CI workflow's DATABASE_URL satisfies the guard, so CI
# keeps running against a dedicated test database.
# Parameters:
# - None.
# Returns:
# - None.
def test_ci_workflow_database_url_is_a_dedicated_test_database() -> None:
    workflow_text = _CI_WORKFLOW_PATH.read_text()

    database_urls = re.findall(r"^\s*DATABASE_URL:\s*(\S+)\s*$", workflow_text, re.MULTILINE)

    assert database_urls, "backend CI workflow no longer sets DATABASE_URL"

    for database_url in database_urls:
        assert validate_test_database_url(database_url).endswith("_test")


# Tests the real wiring end to end: a pytest run pointed at an unsafe
# database must abort during configuration with a usage error.
# --collect-only guarantees no test body can run even if the guard ever
# regresses, and the target is this pure test module, which never touches
# a database. The unsafe database does not need to exist: the guard fires
# before any connection is opened.
# Parameters:
# - None.
# Returns:
# - None.
def test_pytest_run_against_unsafe_database_aborts_before_collection() -> None:
    environment = dict(os.environ)
    environment["DATABASE_URL"] = (
        "postgresql://guard_user:guard_secret_pw@localhost:5432/valor"
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/unit/test_database_safety.py",
        ],
        cwd=_API_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )

    output = completed.stdout + completed.stderr

    assert completed.returncode == pytest.ExitCode.USAGE_ERROR, output
    assert "Refusing to run backend tests against database 'valor'" in output
    assert "guard_user" not in output
    assert "guard_secret_pw" not in output
