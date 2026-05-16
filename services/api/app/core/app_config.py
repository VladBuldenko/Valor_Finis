import os

from dotenv import load_dotenv


load_dotenv()


class AppSettings:
    """
    Application settings.

    This class stores environment-based configuration values.

    Fields:
    - database_url: PostgreSQL database connection string
    """

    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/valor",
    )


settings = AppSettings()