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


settings = AppSettings()