import pytest
from pytest import MonkeyPatch

from app.core.app_config import (
    AppSettings,
    get_auth_mode,
    get_receipt_ocr_driver,
    get_receipt_ocr_max_image_pixels,
    get_receipt_ocr_timeout_seconds,
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


# Tests that Tesseract is used when RECEIPT_OCR_DRIVER is missing.
# This test exists to keep receipt OCR functional out of the box
# in local development and production without extra configuration.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_get_receipt_ocr_driver_returns_tesseract_by_default(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.delenv(
        "RECEIPT_OCR_DRIVER",
        raising=False,
    )

    # Act
    ocr_driver = get_receipt_ocr_driver()

    # Assert
    assert ocr_driver == "tesseract"


# Tests that supported receipt OCR drivers are normalized.
# This test exists to allow harmless spaces and letter-case differences
# in environment configuration.
# Parameters:
# - configured_value: OCR driver value placed in the environment.
# - expected_value: normalized OCR driver value.
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
@pytest.mark.parametrize(
    ("configured_value", "expected_value"),
    [
        ("tesseract", "tesseract"),
        ("TESSERACT", "tesseract"),
        (" unconfigured ", "unconfigured"),
        ("UNCONFIGURED", "unconfigured"),
    ],
)
def test_get_receipt_ocr_driver_normalizes_supported_values(
    configured_value: str,
    expected_value: str,
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "RECEIPT_OCR_DRIVER",
        configured_value,
    )

    # Act
    ocr_driver = get_receipt_ocr_driver()

    # Assert
    assert ocr_driver == expected_value


# Tests that unsupported receipt OCR drivers are rejected.
# This test exists to fail fast when RECEIPT_OCR_DRIVER contains
# an invalid or misspelled value instead of silently disabling OCR.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_get_receipt_ocr_driver_rejects_unsupported_value(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "RECEIPT_OCR_DRIVER",
        "google-vision",
    )

    # Act
    with pytest.raises(ValueError) as error:
        get_receipt_ocr_driver()

    # Assert
    assert str(error.value) == (
        "Unsupported RECEIPT_OCR_DRIVER 'google-vision'. "
        "Supported values: tesseract, unconfigured."
    )


# Tests that AppSettings exposes the configured receipt OCR driver.
# This test exists to confirm that application configuration surfaces
# the OCR driver used by the receipt OCR provider selection.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_app_settings_exposes_configured_receipt_ocr_driver(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "RECEIPT_OCR_DRIVER",
        "unconfigured",
    )

    # Act
    settings = AppSettings()

    # Assert
    assert settings.receipt_ocr_driver == "unconfigured"


# Tests that a safe default pixel budget is used when
# RECEIPT_OCR_MAX_IMAGE_PIXELS is missing.
# This test exists to keep decompression-bomb protection active
# out of the box without requiring extra configuration.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_get_receipt_ocr_max_image_pixels_returns_default(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.delenv(
        "RECEIPT_OCR_MAX_IMAGE_PIXELS",
        raising=False,
    )

    # Act
    max_image_pixels = get_receipt_ocr_max_image_pixels()

    # Assert
    assert max_image_pixels == 30_000_000


# Tests that a configured positive pixel budget is honored.
# This test exists to confirm that operators can tune the pixel limit
# without changing application code.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_get_receipt_ocr_max_image_pixels_accepts_configured_value(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "RECEIPT_OCR_MAX_IMAGE_PIXELS",
        "1000",
    )

    # Act
    max_image_pixels = get_receipt_ocr_max_image_pixels()

    # Assert
    assert max_image_pixels == 1000


# Tests that a non-numeric pixel budget is rejected.
# This test exists to fail fast on misconfiguration instead of
# silently disabling the pixel-budget protection.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_get_receipt_ocr_max_image_pixels_rejects_non_numeric_value(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "RECEIPT_OCR_MAX_IMAGE_PIXELS",
        "not-a-number",
    )

    # Act
    with pytest.raises(ValueError) as error:
        get_receipt_ocr_max_image_pixels()

    # Assert
    assert "RECEIPT_OCR_MAX_IMAGE_PIXELS" in str(error.value)


# Tests that a zero or negative pixel budget is rejected.
# This test exists to prevent a misconfiguration from disabling OCR
# entirely (a zero/negative budget would reject every image) without
# a clear startup error.
# Parameters:
# - configured_value: pixel budget value placed in the environment.
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
@pytest.mark.parametrize(
    "configured_value",
    ["0", "-5"],
)
def test_get_receipt_ocr_max_image_pixels_rejects_non_positive_value(
    configured_value: str,
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "RECEIPT_OCR_MAX_IMAGE_PIXELS",
        configured_value,
    )

    # Act
    with pytest.raises(ValueError) as error:
        get_receipt_ocr_max_image_pixels()

    # Assert
    assert "RECEIPT_OCR_MAX_IMAGE_PIXELS" in str(error.value)


# Tests that a safe default Tesseract timeout is used when
# RECEIPT_OCR_TIMEOUT_SECONDS is missing.
# This test exists to keep OCR CPU-time protection active out of the
# box without requiring extra configuration.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_get_receipt_ocr_timeout_seconds_returns_default(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.delenv(
        "RECEIPT_OCR_TIMEOUT_SECONDS",
        raising=False,
    )

    # Act
    timeout_seconds = get_receipt_ocr_timeout_seconds()

    # Assert
    assert timeout_seconds == 20


# Tests that a configured positive Tesseract timeout is honored.
# This test exists to confirm that operators can tune the OCR timeout
# without changing application code.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_get_receipt_ocr_timeout_seconds_accepts_configured_value(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "RECEIPT_OCR_TIMEOUT_SECONDS",
        "45",
    )

    # Act
    timeout_seconds = get_receipt_ocr_timeout_seconds()

    # Assert
    assert timeout_seconds == 45


# Tests that a non-numeric Tesseract timeout is rejected.
# This test exists to fail fast on misconfiguration instead of
# silently running OCR without a bounded timeout.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_get_receipt_ocr_timeout_seconds_rejects_non_numeric_value(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "RECEIPT_OCR_TIMEOUT_SECONDS",
        "soon",
    )

    # Act
    with pytest.raises(ValueError) as error:
        get_receipt_ocr_timeout_seconds()

    # Assert
    assert "RECEIPT_OCR_TIMEOUT_SECONDS" in str(error.value)


# Tests that a zero or negative Tesseract timeout is rejected.
# This test exists to prevent a misconfiguration from disabling the
# timeout protection (pytesseract treats timeout=0 as "no timeout").
# Parameters:
# - configured_value: timeout value placed in the environment.
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
@pytest.mark.parametrize(
    "configured_value",
    ["0", "-1"],
)
def test_get_receipt_ocr_timeout_seconds_rejects_non_positive_value(
    configured_value: str,
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "RECEIPT_OCR_TIMEOUT_SECONDS",
        configured_value,
    )

    # Act
    with pytest.raises(ValueError) as error:
        get_receipt_ocr_timeout_seconds()

    # Assert
    assert "RECEIPT_OCR_TIMEOUT_SECONDS" in str(error.value)


# Tests that AppSettings exposes the configured OCR pixel budget
# and Tesseract timeout.
# This test exists to confirm that the OCR hardening configuration
# is wired into application settings and reachable by the OCR provider.
# Parameters:
# - monkeypatch: pytest fixture used to modify environment variables.
# Returns:
# - None.
def test_app_settings_exposes_receipt_ocr_hardening_configuration(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "RECEIPT_OCR_MAX_IMAGE_PIXELS",
        "12345",
    )
    monkeypatch.setenv(
        "RECEIPT_OCR_TIMEOUT_SECONDS",
        "30",
    )

    # Act
    settings = AppSettings()

    # Assert
    assert settings.receipt_ocr_max_image_pixels == 12345
    assert settings.receipt_ocr_timeout_seconds == 30