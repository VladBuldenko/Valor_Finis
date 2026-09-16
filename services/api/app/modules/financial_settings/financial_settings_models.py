from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base

DEFAULT_BASE_CURRENCY = "EUR"


class UserFinancialSettingsModel(Base):
    """
    SQLAlchemy ORM model for the user_financial_settings table.

    What:
        Stores the single authoritative financial-domain setting owned by
        each user: their base currency.

    Why:
        VF-014B5 needs one place that answers "what currency does this
        user's normalized financial data live in." Supabase auth metadata
        is not a financial-domain source of truth, so this is a local
        table instead. This is a one-to-one, user-owned settings row, so
        user_id is the primary key directly - no surrogate id column.

    Fields:
        user_id: Owner of this settings row. No FK: matches the
            denormalized, Supabase-owned-identity pattern used by every
            other user-owned table (budgets, expenses, goals, categories,
            receipts, budget_versions).
        base_currency: The user's base currency. Defaults to EUR.
            Immutable in VF-014B5B - no public API changes it yet.
        created_at: Record creation timestamp.
        updated_at: Record update timestamp.
    """

    __tablename__ = "user_financial_settings"

    user_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
    )

    base_currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default=DEFAULT_BASE_CURRENCY,
        server_default=DEFAULT_BASE_CURRENCY,
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
