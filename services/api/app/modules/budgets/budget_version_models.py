import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


class BudgetVersionModel(Base):
    """
    SQLAlchemy ORM model for the budget_versions table.

    What:
        Append-only history of a budget's limit_amount and category_id over
        time. One row per period-defining change (creation, limit edit,
        category change).

    Why:
        budgets.limit_amount/category_id are mutable in place, so editing a
        budget mid-lifecycle would otherwise silently rewrite the meaning of
        already-completed periods. This table preserves what each period
        actually meant at the time, without persisting period windows
        themselves (those stay dynamically resolved by budget_period.py).

    Fields:
        id: Unique version identifier.
        budget_id: Budget this version belongs to.
        user_id: Owner of the budget. Denormalized, no FK, matching the
            Supabase-owned-identity pattern used on every other table.
        effective_from: First period start this version applies to.
        effective_until: Last period end this version applies to, or None
            for open-ended (every version written today is open-ended;
            a bounded effective_until is reserved for future single-period
            overrides).
        limit_amount: The limit that was in effect from effective_from.
        category_id: The category scope that was in effect from
            effective_from. Null means an all-expenses budget.
        change_reason: Why this version was written.
        created_at: Record creation timestamp, used as the tie-break when
            two versions share the same effective_from.
    """

    __tablename__ = "budget_versions"

    __table_args__ = (
        CheckConstraint("limit_amount > 0", name="ck_budget_versions_limit_amount_positive"),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_budget_versions_effective_range",
        ),
        CheckConstraint(
            "change_reason IN ('initial','user_edit','category_change')",
            name="ck_budget_versions_change_reason_valid",
        ),
        Index(
            "ix_budget_versions_budget_id_effective_from",
            "budget_id",
            "effective_from",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    budget_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("budgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    effective_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    effective_until: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )

    limit_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=True,
    )

    change_reason: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="user_edit",
        server_default="user_edit",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
