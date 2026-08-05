import pytest
from pytest import MonkeyPatch

from app.core.app_config import get_auth_mode


# Tests that development mode is used when AUTH_MODE is missing.
# This test exists to keep local development configuration predictable.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_get_auth_mode_returns_development_by_default(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.delenv(
        "AUTH_MODE",
        raising=False,
    )

    # Act
    auth_mode = get_auth_mode()

    # Assert
    assert auth_mode == "development"


# Tests that supported authentication modes are normalized.
# This test exists to allow harmless spaces and letter-case differences
# in environment configuration.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
@pytest.mark.parametrize(
    ("configured_value", "expected_value"),
    [
        ("development", "development"),
        ("DEVELOPMENT", "development"),
        (" supabase ", "supabase"),
        ("SUPABASE", "supabase"),
    ],
)
def test_get_auth_mode_normalizes_supported_values(
    configured_value: str,
    expected_value: str,
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "AUTH_MODE",
        configured_value,
    )

    # Act
    auth_mode = get_auth_mode()

    # Assert
    assert auth_mode == expected_value


# Tests that unsupported authentication modes are rejected.
# This test exists to fail fast when AUTH_MODE contains
# an invalid or misspelled value.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_get_auth_mode_rejects_unsupported_value(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "AUTH_MODE",
        "production",
    )

    # Act
    with pytest.raises(ValueError) as error:
        get_auth_mode()

    # Assert
    assert str(error.value) == (
        "Unsupported AUTH_MODE 'production'. "
        "Supported values: development, supabase."
    )