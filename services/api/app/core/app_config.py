import os
from typing import Optional

from dotenv import load_dotenv


load_dotenv()


SUPPORTED_AUTH_MODES = {
    "development",
    "supabase",
}

SUPPORTED_RECEIPT_STORAGE_DRIVERS = {
    "local",
    "supabase",
}


# Returns and validates the configured authentication mode.
# This function exists to fail fast when AUTH_MODE contains
# an unsupported or misspelled value.
# Parameters:
# - None.
# Returns:
# - Validated authentication mode.
# Raises:
# - ValueError when AUTH_MODE is unsupported.
def get_auth_mode() -> str:
    auth_mode = os.getenv(
        "AUTH_MODE",
        "development",
    ).strip().lower()

    if auth_mode not in SUPPORTED_AUTH_MODES:
        supported_modes = ", ".join(
            sorted(SUPPORTED_AUTH_MODES),
        )

        raise ValueError(
            "Unsupported AUTH_MODE "
            f"'{auth_mode}'. "
            f"Supported values: {supported_modes}."
        )

    return auth_mode


# Returns and validates the configured receipt storage driver.
# This function exists to fail fast when RECEIPT_STORAGE_DRIVER
# contains an unsupported or misspelled value.
# Parameters:
# - None.
# Returns:
# - Validated receipt storage driver.
# Raises:
# - ValueError when RECEIPT_STORAGE_DRIVER is unsupported.
def get_receipt_storage_driver() -> str:
    storage_driver = os.getenv(
        "RECEIPT_STORAGE_DRIVER",
        "local",
    ).strip().lower()

    if storage_driver not in SUPPORTED_RECEIPT_STORAGE_DRIVERS:
        supported_drivers = ", ".join(
            sorted(SUPPORTED_RECEIPT_STORAGE_DRIVERS),
        )

        raise ValueError(
            "Unsupported RECEIPT_STORAGE_DRIVER "
            f"'{storage_driver}'. "
            f"Supported values: {supported_drivers}."
        )

    return storage_driver


# Validates authentication-related application configuration.
# This function exists to fail fast during application startup
# when Supabase authentication is enabled but required settings
# are missing.
# Parameters:
# - auth_mode: configured authentication mode.
# - supabase_url: configured Supabase project URL.
# - supabase_publishable_key: configured Supabase publishable key.
# Returns:
# - None.
# Raises:
# - ValueError when required Supabase authentication
#   configuration is missing.
def validate_auth_configuration(
    auth_mode: str,
    supabase_url: Optional[str],
    supabase_publishable_key: Optional[str],
) -> None:
    if auth_mode != "supabase":
        return

    missing_settings = []

    if not supabase_url:
        missing_settings.append(
            "SUPABASE_URL",
        )

    if not supabase_publishable_key:
        missing_settings.append(
            "SUPABASE_PUBLISHABLE_KEY",
        )

    if missing_settings:
        missing_settings_text = ", ".join(
            missing_settings,
        )

        raise ValueError(
            "Missing required Supabase configuration: "
            f"{missing_settings_text}."
        )


# Validates receipt storage configuration.
# This function exists to fail fast during application startup
# when Supabase receipt storage is enabled but required settings
# are missing.
# Parameters:
# - storage_driver: configured receipt storage driver.
# - supabase_url: configured Supabase project URL.
# - supabase_secret_key: configured Supabase backend secret key.
# - receipt_storage_bucket: configured Supabase Storage bucket.
# Returns:
# - None.
# Raises:
# - ValueError when required Supabase Storage configuration
#   is missing.
def validate_receipt_storage_configuration(
    storage_driver: str,
    supabase_url: Optional[str],
    supabase_secret_key: Optional[str],
    receipt_storage_bucket: str,
) -> None:
    if storage_driver != "supabase":
        return

    missing_settings = []

    if not supabase_url:
        missing_settings.append(
            "SUPABASE_URL",
        )

    if not supabase_secret_key:
        missing_settings.append(
            "SUPABASE_SECRET_KEY",
        )

    if not receipt_storage_bucket:
        missing_settings.append(
            "RECEIPT_STORAGE_BUCKET",
        )

    if missing_settings:
        missing_settings_text = ", ".join(
            missing_settings,
        )

        raise ValueError(
            "Missing required Supabase receipt storage configuration: "
            f"{missing_settings_text}."
        )


class AppSettings:
    """
    Application settings.

    This class stores and validates environment-based
    application configuration.

    Fields:
    - database_url: PostgreSQL database connection string.
    - auth_mode: authentication mode used by the API.
    - supabase_url: Supabase project URL.
    - supabase_publishable_key: Supabase publishable key used for Auth.
    - supabase_secret_key: Supabase secret key used by trusted backend services.
    - receipt_storage_driver: Storage backend used for receipt files.
    - receipt_storage_bucket: Supabase Storage bucket used for receipts.
    - receipt_upload_dir: Local directory used for receipt file uploads.
    - receipt_max_file_size_mb: Maximum receipt file size in megabytes.
    """

    def __init__(self) -> None:
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/valor",
        )

        self.auth_mode = get_auth_mode()

        self.supabase_url = (
            os.getenv("SUPABASE_URL") or None
        )

        self.supabase_publishable_key = (
            os.getenv("SUPABASE_PUBLISHABLE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
            or None
        )

        self.supabase_secret_key = (
            os.getenv("SUPABASE_SECRET_KEY")
            or None
        )

        self.receipt_storage_driver = (
            get_receipt_storage_driver()
        )

        self.receipt_storage_bucket = os.getenv(
            "RECEIPT_STORAGE_BUCKET",
            "receipts",
        ).strip()

        self.receipt_upload_dir = os.getenv(
            "RECEIPT_UPLOAD_DIR",
            "uploads/receipts",
        )

        self.receipt_max_file_size_mb = int(
            os.getenv(
                "RECEIPT_MAX_FILE_SIZE_MB",
                "10",
            )
        )

        validate_auth_configuration(
            auth_mode=self.auth_mode,
            supabase_url=self.supabase_url,
            supabase_publishable_key=self.supabase_publishable_key,
        )

        validate_receipt_storage_configuration(
            storage_driver=self.receipt_storage_driver,
            supabase_url=self.supabase_url,
            supabase_secret_key=self.supabase_secret_key,
            receipt_storage_bucket=self.receipt_storage_bucket,
        )

    @property
    def receipt_max_file_size_bytes(self) -> int:
        """
        Returns the maximum allowed receipt file size in bytes.

        What:
            Converts the configured megabyte limit into bytes.

        Why:
            Keeps file size conversion outside the receipt storage service.
        """

        return self.receipt_max_file_size_mb * 1024 * 1024


settings = AppSettings()