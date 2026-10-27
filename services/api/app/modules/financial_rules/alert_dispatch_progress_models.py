from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base

# This class maps the table created by migration c4d8a2f6e193 (VF-020E10).
# Only the periodic dispatcher (through alert_dispatch_progress_repository) reads
# or writes it; no router, API schema or other service imports it.


class AlertDispatchProgressModel(Base):
    """
    SQLAlchemy ORM model for alert_dispatch_progress.

    What:
        One row per user the dispatcher has attempted to evaluate alerts for.

    Fields:
        user_id: the user (no foreign key: there is no users table).
        service_seq: strictly increasing service order, drawn from the sequence
            alert_dispatch_service_seq on EVERY attempt (success or failure). The
            smallest value is the least recently attempted user. Unique, so the
            order is total and never depends on clocks.
        last_attempted_at / last_success_at: monitoring timestamps only (never
            used for ordering).
        consecutive_failures / last_error_code: limited failure metadata (a
            counter and an exception class name), no messages or amounts.

    Why:
        Persisted progress is what makes "every user within ceil(M/n) runs" a
        provable bound under crashes, partial runs and missed scheduler ticks.
    """

    __tablename__ = "alert_dispatch_progress"

    __table_args__ = (
        UniqueConstraint("service_seq", name="uq_alert_dispatch_progress_service_seq"),
        CheckConstraint("consecutive_failures >= 0", name="ck_alert_dispatch_progress_consecutive_failures_valid"),
        CheckConstraint(
            "last_success_at IS NULL OR last_success_at <= last_attempted_at",
            name="ck_alert_dispatch_progress_last_success_at_valid",
        ),
        Index("ix_alert_dispatch_progress_last_success_at", "last_success_at"),
    )

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    service_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
