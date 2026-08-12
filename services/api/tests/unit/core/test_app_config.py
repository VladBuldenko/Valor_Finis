import pytest
from pytest import MonkeyPatch

from app.core.app_config import (
    AppSettings,
    get_auth_mode,
)


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
# - configured_value: authentication mode value placed in the environment.
# - expected_value: normalized authentication mode.
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


# Tests that development authentication does not require Supabase settings.
# This test exists to keep standalone local development possible
# without configuring Supabase.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_app_settings_allows_missing_supabase_settings_in_development(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "AUTH_MODE",
        "development",
    )
    monkeypatch.delenv(
        "SUPABASE_URL",
        raising=False,
    )
    monkeypatch.delenv(
        "SUPABASE_PUBLISHABLE_KEY",
        raising=False,
    )
    monkeypatch.delenv(
        "SUPABASE_ANON_KEY",
        raising=False,
    )

    # Act
    settings = AppSettings()

    # Assert
    assert settings.auth_mode == "development"
    assert settings.supabase_url is None
    assert settings.supabase_publishable_key is None


# Tests that Supabase authentication requires a project URL.
# This test exists to prevent the API from starting with
# incomplete production authentication configuration.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_app_settings_rejects_missing_supabase_url(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "AUTH_MODE",
        "supabase",
    )
    monkeypatch.delenv(
        "SUPABASE_URL",
        raising=False,
    )
    monkeypatch.setenv(
        "SUPABASE_PUBLISHABLE_KEY",
        "test-publishable-key",
    )

    # Act
    with pytest.raises(ValueError) as error:
        AppSettings()

    # Assert
    assert str(error.value) == (
        "Missing required Supabase configuration: SUPABASE_URL."
    )


# Tests that Supabase authentication requires a publishable key.
# This test exists to prevent the API from starting with
# incomplete production authentication configuration.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_app_settings_rejects_missing_supabase_publishable_key(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "AUTH_MODE",
        "supabase",
    )
    monkeypatch.setenv(
        "SUPABASE_URL",
        "https://example.supabase.co",
    )
    monkeypatch.delenv(
        "SUPABASE_PUBLISHABLE_KEY",
        raising=False,
    )
    monkeypatch.delenv(
        "SUPABASE_ANON_KEY",
        raising=False,
    )

    # Act
    with pytest.raises(ValueError) as error:
        AppSettings()

    # Assert
    assert str(error.value) == (
        "Missing required Supabase configuration: "
        "SUPABASE_PUBLISHABLE_KEY."
    )


# Tests that all missing Supabase settings are reported together.
# This test exists to make configuration failures easier to diagnose.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_app_settings_reports_all_missing_supabase_settings(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "AUTH_MODE",
        "supabase",
    )
    monkeypatch.delenv(
        "SUPABASE_URL",
        raising=False,
    )
    monkeypatch.delenv(
        "SUPABASE_PUBLISHABLE_KEY",
        raising=False,
    )
    monkeypatch.delenv(
        "SUPABASE_ANON_KEY",
        raising=False,
    )

    # Act
    with pytest.raises(ValueError) as error:
        AppSettings()

    # Assert
    assert str(error.value) == (
        "Missing required Supabase configuration: "
        "SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY."
    )


# Tests that complete Supabase authentication configuration is accepted.
# This test exists to confirm that production authentication settings
# allow application configuration to initialize successfully.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_app_settings_accepts_complete_supabase_configuration(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "AUTH_MODE",
        "supabase",
    )
    monkeypatch.setenv(
        "SUPABASE_URL",
        "https://example.supabase.co",
    )
    monkeypatch.setenv(
        "SUPABASE_PUBLISHABLE_KEY",
        "test-publishable-key",
    )

    # Act
    settings = AppSettings()

    # Assert
    assert settings.auth_mode == "supabase"
    assert settings.supabase_url == (
        "https://example.supabase.co"
    )
    assert settings.supabase_publishable_key == (
        "test-publishable-key"
    )