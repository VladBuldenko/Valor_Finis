from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.app_config import settings


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# Creates a database session for a single request.
# This function exists to provide database access to repositories and API dependencies.
# Parameters:
# - None.
# Returns:
# - SQLAlchemy Session object. The session is closed after usage.
def get_db_session() -> Generator[Session, None, None]:
    db_session = SessionLocal()

    try:
        yield db_session
    finally:
        db_session.close()