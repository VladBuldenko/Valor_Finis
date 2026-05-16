from datetime import date as Date
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Date as SQLDate
from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


class GoalModel(Base):
    """
    SQLAlchemy ORM model for the goals table.

    This model represents how financial goal records are stored in PostgreSQL.
    """

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    target_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    current_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0"),
    )

    deadline: Mapped[Date] = mapped_column(
        SQLDate,
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )