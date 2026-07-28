import os
from typing import Optional

from dotenv import load_dotenv


load_dotenv()


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

    auth_mode: str = os.getenv(
        "AUTH_MODE",
        "development",
    ).lower()

    supabase_url: Optional[str] = os.getenv("SUPABASE_URL")

    supabase_publishable_key: Optional[str] = os.getenv(
        "SUPABASE_PUBLISHABLE_KEY",
        os.getenv("SUPABASE_ANON_KEY"),
    )

    receipt_storage_driver: str = os.getenv(
        "RECEIPT_STORAGE_DRIVER",
        "local",
    ).lower()

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