import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


class FutureObligationModel(Base):
    """
    SQLAlchemy ORM model for the future_obligations table.

    What:
        A financial obligation the user EXPECTS to owe in the future and has
        entered by hand: a one-time bill (insurance renewal, a planned tax
        payment) or a monthly one (rent, a subscription, a loan installment).

    Why:
        It is an independent forecast input for later cash-flow planning. It is
        NOT a transaction: nothing here is paid, reserved or recorded as an
        Expense, and no Account or Goal is touched. It is also never inferred
        from past Expenses or Budget limits. Keeping it a separate domain avoids
        counting a bill that history already contains a second time.

    Fields:
        id: Unique identifier.
        user_id: Owner. Every read and write is scoped to it.
        name: Short label, 1 to 100 characters after trimming.
        description: Optional note, up to 500 characters.
        schedule: 'one_time' or 'monthly'. Immutable after creation.
        amount: Positive amount per occurrence, in `currency`, 2 decimal places.
        currency: Explicit ISO-style code (3 uppercase letters). Never
            converted: the projection keeps currencies apart.
        first_due_date: The due date of a one-time obligation, or the FIRST due
            date of a monthly one. Its day of the month is the monthly anchor.
        final_due_date: Optional last due date of a monthly obligation; always
            NULL for a one-time obligation.
        status: 'active' or 'archived'. An archived obligation stays stored but
            contributes no occurrences.
        client_request_id / client_request_fingerprint: create idempotency, set
            together or not at all; never exposed except the id.
        created_at / updated_at: timestamps.

    Recurrence (see future_obligation_schedule): the monthly anchor day is the
    day of first_due_date; in a shorter month the due date is clamped to the last
    day, and the anchor itself is never changed, so there is no drift.
    """

    __tablename__ = "future_obligations"

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_future_obligations_amount_positive"),
        CheckConstraint(
            "schedule IN ('one_time','monthly')",
            name="ck_future_obligations_schedule_valid",
        ),
        CheckConstraint(
            "status IN ('active','archived')",
            name="ck_future_obligations_status_valid",
        ),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_future_obligations_currency_format",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_future_obligations_name_not_blank",
        ),
        CheckConstraint(
            "first_due_date BETWEEN DATE '2000-01-01' AND DATE '2100-12-31'",
            name="ck_future_obligations_first_due_date_range",
        ),
        CheckConstraint(
            "final_due_date IS NULL OR final_due_date BETWEEN DATE '2000-01-01' AND DATE '2100-12-31'",
            name="ck_future_obligations_final_due_date_range",
        ),
        CheckConstraint(
            "final_due_date IS NULL OR final_due_date >= first_due_date",
            name="ck_future_obligations_final_not_before_first",
        ),
        CheckConstraint(
            "schedule <> 'one_time' OR final_due_date IS NULL",
            name="ck_future_obligations_one_time_has_no_final",
        ),
        # Create idempotency, the convention Income and Expense use: NULL keys
        # never collide, and the key and its fingerprint exist together or not
        # at all.
        UniqueConstraint(
            "user_id",
            "client_request_id",
            name="uq_future_obligations_user_id_client_request_id",
        ),
        CheckConstraint(
            "(client_request_id IS NULL) = (client_request_fingerprint IS NULL)",
            name="ck_future_obligations_client_request_all_or_none",
        ),
        # Composite-unique FK target (VF-GOALS-PLANNING-002C2): lets a reconciliation
        # link carry an (obligation_id, user_id) -> future_obligations(id, user_id)
        # foreign key, so a link to another user's obligation cannot be stored.
        UniqueConstraint("id", "user_id", name="uq_future_obligations_id_user_id"),
        # The two reads: the list and the bounded projection both filter by user
        # and, for the projection, by status.
        Index("ix_future_obligations_user_id_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    schedule: Mapped[str] = mapped_column(String(10), nullable=False)

    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    first_due_date: Mapped[date] = mapped_column(Date, nullable=False)

    final_due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="active",
        server_default="active",
    )

    client_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    client_request_fingerprint: Mapped[Optional[str]] = mapped_column(
        String(64),
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
