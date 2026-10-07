import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


class GoalModel(Base):
    """
    SQLAlchemy ORM model for the goals table.

    What:
        Represents user financial goals stored in PostgreSQL.

    Why:
        Allows the application to track financial progress toward a target
        such as savings, emergency fund, or planned purchases.

    Fields:
        id: Unique goal identifier.
        user_id: Owner of the goal.
        name: Human-readable goal name.
        target_amount: Amount the user wants to reach.
        currency: Currency code such as EUR or USD.
        target_date: Optional date when the user wants to reach the goal.
        status: Current goal state such as active, completed, or archived.
        created_at: Record creation timestamp.
        updated_at: Record update timestamp.

    Note (VF-016G): this model has no persisted balance column. A Goal's
    balance exists only as the sum of its goal_transactions ledger rows
    (opening_balance + contribution - withdrawal); it is never stored on
    the Goal row itself. See goal_transaction_repository.py for the
    ledger-balance calculation, and goal_schemas.GoalResponse for the
    public, ledger-derived current_amount field.
    """

    __tablename__ = "goals"

    __table_args__ = (
        CheckConstraint("target_amount > 0", name="ck_goals_target_amount_positive"),
        # VF-020B2: database-level guards for values the API already
        # validates - the status literal and a currency of exactly three
        # ASCII uppercase letters.
        CheckConstraint(
            "status IN ('active','completed','archived')",
            name="ck_goals_status_valid",
        ),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_goals_currency_format",
        ),
        # Composite-unique FK target (VF-020B2): lets goal_transactions
        # carry a (goal_id, user_id) -> goals(id, user_id) foreign key, so a
        # goal transaction can never belong to another user than its goal.
        UniqueConstraint("id", "user_id", name="uq_goals_id_user_id"),
        # Composite-unique FK target (VF-020B4): lets goal_transactions bind
        # (goal_id, user_id, currency) to the goal's own identity, owner and
        # currency at the database level.
        UniqueConstraint(
            "id", "user_id", "currency", name="uq_goals_id_user_id_currency",
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

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    target_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="EUR",
        server_default="EUR",
    )

    target_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="active",
        server_default="active",
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