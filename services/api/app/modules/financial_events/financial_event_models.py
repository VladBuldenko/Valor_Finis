import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


class FinancialEventModel(Base):
    """
    SQLAlchemy ORM model for the financial_events outbox table (VF-020E).

    What:
        One durable event per canonical Income mutation (income.created,
        income.updated, income.deleted), written in the SAME database
        transaction as the mutation (VF-020E3). It carries explicit typed
        provenance and a typed source snapshot, so no eligibility data is
        hidden in JSON.

    Why:
        The table was created by migration 115998e2e795 (VF-020E2); this
        class maps it exactly and the metadata matches the migrated schema.
        aggregate_id is a SOFT reference: there is intentionally no foreign
        key to income, so deleting an Income is never blocked by event
        provenance and income.deleted events survive the deletion. user_id
        is a plain UUID like everywhere else (no local users table).
        E3 only writes pending events; claiming, leases, retries, FIFO
        selection and processing belong to a later stage.

    Fields:
        id: Event identity (one new UUID per canonical mutation event).
        user_id: Owner of the event.
        event_type: income.created | income.updated | income.deleted.
        aggregate_type: Source aggregate type ("income").
        aggregate_id: Soft reference to the source Income id.
        origin: manual | receipt | import | system.
        ingestion_mode: live | historical | correction.
        snap_amount: Income.amount (never base_amount) at the event state.
        snap_currency: Income.currency at the event state.
        snap_received_at: Income.received_at at the event state.
        snap_account_id: Linked Account at the event state, NULL when the
            Income is not linked to an Account.
        snap_income_source: Income.source at the event state.
        snap_aggregate_updated_at: Persisted Income.updated_at at the event
            state.
        occurred_at: Insert-transaction time (server default now()).
        status: Delivery status; new events are pending.
        not_before: Business-date deferral (start of a future received_at
            day) or the insert time.
        attempts: Delivery attempts so far (0..6).
        next_attempt_at / lease_expires_at / claim_token / last_error_code /
        processed_at / outcome_summary: delivery and outcome storage owned
            by a later stage; NULL for newly written events.
    """

    __tablename__ = "financial_events"

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('income.created','income.updated','income.deleted')",
            name="ck_financial_events_event_type_valid",
        ),
        CheckConstraint(
            "origin IN ('manual','receipt','import','system')",
            name="ck_financial_events_origin_valid",
        ),
        CheckConstraint(
            "ingestion_mode IN ('live','historical','correction')",
            name="ck_financial_events_ingestion_mode_valid",
        ),
        CheckConstraint(
            "status IN ('pending','processing','processed','failed_retryable','dead')",
            name="ck_financial_events_status_valid",
        ),
        CheckConstraint(
            "attempts >= 0 AND attempts <= 6",
            name="ck_financial_events_attempts_valid",
        ),
        # At most one income.created event per canonical Income identity.
        Index(
            "uq_financial_events_income_created_aggregate_id",
            "aggregate_id",
            unique=True,
            postgresql_where=text("event_type = 'income.created'"),
        ),
        # Unfinished events per user in (occurred_at, id) order; terminal
        # statuses are excluded and the predicate never narrows to
        # "claimable" rows.
        Index(
            "ix_financial_events_user_id_occurred_at_id_unfinished",
            "user_id",
            "occurred_at",
            "id",
            postgresql_where=text(
                "status IN ('pending','processing','failed_retryable')"
            ),
        ),
        Index(
            "ix_financial_events_status_not_before_next_attempt_at",
            "status",
            "not_before",
            "next_attempt_at",
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
    )

    event_type: Mapped[str] = mapped_column(String(32), nullable=False)

    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)

    aggregate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    origin: Mapped[str] = mapped_column(String(16), nullable=False)

    ingestion_mode: Mapped[str] = mapped_column(String(16), nullable=False)

    snap_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    snap_currency: Mapped[str] = mapped_column(String(3), nullable=False)

    snap_received_at: Mapped[date] = mapped_column(Date, nullable=False)

    snap_account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    snap_income_source: Mapped[str] = mapped_column(String(20), nullable=False)

    snap_aggregate_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="pending",
    )

    not_before: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    claim_token: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    last_error_code: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )

    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    outcome_summary: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
