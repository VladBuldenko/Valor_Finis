from datetime import date as Date
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Date as SQLDate
from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


class BudgetModel(Base):
    """
    SQLAlchemy ORM model for the budgets table.

    This model represents how budget limit records are stored in PostgreSQL.
    """

    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )

    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    monthly_limit: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    month: Mapped[Date] = mapped_column(
        SQLDate,
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )