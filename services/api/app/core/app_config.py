import os
from typing import Optional

from dotenv import load_dotenv


load_dotenv()


SUPPORTED_AUTH_MODES = {
    "development",
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


class AppSettings:
    """
    Application settings.

    This class stores environment-based configuration values.

    Fields:
    - database_url: PostgreSQL database connection string.
    - auth_mode: authentication mode used by the API.
    - supabase_url: Supabase project URL used for JWT validation.
    - supabase_publishable_key: Supabase public API key used for Auth API calls.
    - receipt_storage_driver: Storage backend used for receipt files.
    - receipt_upload_dir: Local directory used for receipt file uploads.
    - receipt_max_file_size_mb: Maximum receipt file size in megabytes.
    """

    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/valor",
    )

    auth_mode: str = get_auth_mode()

    supabase_url: Optional[str] = os.getenv(
        "SUPABASE_URL",
    )

    supabase_publishable_key: Optional[str] = os.getenv(
        "SUPABASE_PUBLISHABLE_KEY",
        os.getenv("SUPABASE_ANON_KEY"),
    )

    receipt_storage_driver: str = os.getenv(
        "RECEIPT_STORAGE_DRIVER",
        "local",
    ).strip().lower()

    receipt_upload_dir: str = os.getenv(
        "RECEIPT_UPLOAD_DIR",
        "uploads/receipts",
    )

    receipt_max_file_size_mb: int = int(
        os.getenv(
            "RECEIPT_MAX_FILE_SIZE_MB",
            "10",
        )
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