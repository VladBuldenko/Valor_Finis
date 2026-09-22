import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


class GoalTransactionModel(Base):
    """
    SQLAlchemy ORM model for the goal_transactions table.

    What:
        Append-only ledger of balance-affecting events for a Goal:
        opening_balance (migration-created historical balance),
        contribution (money added), and withdrawal (money removed).

    Why:
        VF-016 replaces goals.current_amount (formerly a freely
        client-editable field) with a derived balance backed by
        transaction history, so overfunding/withdrawals/history become
        representable without an independently-editable source of truth.
        This table is THE authoritative source of a Goal's balance: the
        Goal row itself has no balance column at all (removed in VF-016G,
        after VF-016B introduced this ledger with a lossless backfill of
        pre-existing balances, and VF-016C-D switched all reads/writes over
        to it). A Goal's balance is always computed here, at read time,
        from opening_balance + contribution - withdrawal - never cached or
        stored anywhere on the Goal row.

    Fields:
        id: Unique transaction identifier.
        goal_id: Goal this transaction belongs to. RESTRICT on delete, not
            CASCADE, so a Goal's financial history cannot silently
            disappear if the Goal row is deleted.
        user_id: Owner of the goal. Denormalized, no FK, matching the
            Supabase-owned-identity pattern used on every other
            user-owned table (see budget_versions.user_id).
        type: One of opening_balance, contribution, withdrawal. Enforced
            at the database level via CHECK, not only application
            validation. opening_balance is reserved for migration/system
            backfill - public APIs must never let a client create one.
        amount: Always positive; direction is carried by type, not sign.
        description: Optional free-text note.
        created_at: Record creation timestamp. For backfilled
            opening_balance rows this is set to the source Goal's own
            created_at (not migration execution time), since the opening
            balance represents pre-existing state, not a new event.
    """

    __tablename__ = "goal_transactions"

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_goal_transactions_amount_positive"),
        CheckConstraint(
            "type IN ('opening_balance','contribution','withdrawal')",
            name="ck_goal_transactions_type_valid",
        ),
        Index(
            "ix_goal_transactions_goal_id_created_at",
            "goal_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("goals.id", ondelete="RESTRICT"),
        nullable=False,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    description: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
