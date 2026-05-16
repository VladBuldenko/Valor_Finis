from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date as SQLDate
from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


class ExpenseModel(Base):
    """
    SQLAlchemy ORM model for the expenses table.

    This model represents how expense records are stored in PostgreSQL.
    """

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    description: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    date: Mapped[Date] = mapped_column(
        SQLDate,
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )