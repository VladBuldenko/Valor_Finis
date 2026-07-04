import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


class BudgetModel(Base):
    """
    SQLAlchemy ORM model for the budgets table.

    What:
        Represents user budget limits stored in PostgreSQL.

    Why:
        Allows the application to control spending limits by category,
        period, and user.

    Fields:
        id: Unique budget identifier.
        user_id: Owner of the budget.
        category_id: Optional category connected to this budget.
        name: Human-readable budget name.
        limit_amount: Maximum allowed spending amount.
        currency: Currency code such as EUR or USD.
        period: Budget period such as weekly, monthly, or yearly.
        start_date: Date when the budget period starts.
        end_date: Optional date when the budget period ends.
        created_at: Record creation timestamp.
        updated_at: Record update timestamp.
    """

    __tablename__ = "budgets"

    __table_args__ = (
        CheckConstraint("limit_amount > 0", name="ck_budgets_limit_amount_positive"),
        UniqueConstraint(
            "user_id",
            "name",
            "period",
            "start_date",
            name="uq_budgets_user_id_name_period_start_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    limit_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="EUR",
        server_default="EUR",
    )

    period: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="monthly",
        server_default="monthly",
    )

    start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    end_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )