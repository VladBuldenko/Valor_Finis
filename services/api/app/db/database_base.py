from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy database models.

    This class exists so all ORM models share one metadata object.

    Fields:
    - metadata: SQLAlchemy metadata used by Alembic migrations.
    """

    pass