import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base

# This class maps the table created by migration a7c3e91d5b24 (VF-020E9A)
# exactly. VF-020E9A is schema-only: nothing in the application reads or writes
# rule_alerts yet (the first runtime that does is E9B), and no router, service or
# repository imports this model. The CHECK literals are shared with the
# migration and verified by the metadata-drift tests.


class RuleAlertModel(Base):
    """
    SQLAlchemy ORM model for rule_alerts.

    What:
        One informational alert about a Budget level transition or an Account
        floor / overcommitment episode.

    Fields:
        rule_id: NULL after the originating rule was deleted (composite FK,
            ON DELETE SET NULL (rule_id)); the alert survives its rule.
        rule_type: snapshot of the originating rule's type.
        subject_type / subject_id: 'account' or 'budget' and a SOFT reference
            (no foreign key) so deleting the subject is never blocked.
        period_key: the Budget period start (ISO date) for a Budget alert, or
            the Account episode number 'E1', 'E2', ... for an Account alert.
        level: 'watch' | 'at_risk' | 'exceeded' (Budget) or 'breached' (Account).
        acknowledged_at: when the user acknowledged the alert.
        resolved_at: when an Account episode ended (the Account recovered);
            always NULL for a Budget alert.

    Why:
        UNIQUE (user_id, rule_type, subject_id, period_key, level) alerts each
        Budget level at most once per period and each Account episode once; a
        partial UNIQUE index allows one open Account episode per Account and
        alert type, so a breach after recovery is a new episode and a new row.
        Floor breach and overcommitment are separate rule types and never
        conflated; a manual floor warning and a soft hold are not alerts.
    """

    __tablename__ = "rule_alerts"

    __table_args__ = (
        ForeignKeyConstraint(
            ["rule_id", "user_id"],
            ["financial_rules.id", "financial_rules.user_id"],
            name="fk_rule_alerts_rule_id_user_id",
            ondelete="SET NULL (rule_id)",
        ),
        UniqueConstraint(
            "user_id", "rule_type", "subject_id", "period_key", "level",
            name="uq_rule_alerts_alert_key",
        ),
        CheckConstraint(
            "rule_type IN ('MINIMUM_UNALLOCATED_FLOOR','OVERCOMMITMENT_ALERT','BUDGET_ALERT')",
            name="ck_rule_alerts_rule_type_valid",
        ),
        CheckConstraint(
            "subject_type IN ('account','budget')", name="ck_rule_alerts_subject_type_valid",
        ),
        CheckConstraint(
            "level IN ('watch','at_risk','exceeded','breached')", name="ck_rule_alerts_level_valid",
        ),
        CheckConstraint(
            "(rule_type = 'BUDGET_ALERT' AND subject_type = 'budget' "
            "AND level IN ('watch','at_risk','exceeded') "
            "AND period_key ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' AND resolved_at IS NULL) "
            "OR (rule_type IN ('MINIMUM_UNALLOCATED_FLOOR','OVERCOMMITMENT_ALERT') "
            "AND subject_type = 'account' AND level = 'breached' "
            "AND period_key ~ '^E[1-9][0-9]{0,8}$')",
            name="ck_rule_alerts_type_shape",
        ),
        CheckConstraint(
            "acknowledged_at IS NULL OR acknowledged_at >= created_at",
            name="ck_rule_alerts_acknowledged_at_valid",
        ),
        CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= created_at",
            name="ck_rule_alerts_resolved_at_valid",
        ),
        Index(
            "uq_rule_alerts_open_account_episode",
            "user_id", "rule_type", "subject_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL AND rule_type <> 'BUDGET_ALERT'"),
        ),
        Index(
            "ix_rule_alerts_user_id_unacknowledged",
            "user_id", "created_at", "id",
            postgresql_where=text("acknowledged_at IS NULL"),
        ),
        Index(
            "ix_rule_alerts_rule_id",
            "rule_id",
            postgresql_where=text("rule_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    rule_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period_key: Mapped[str] = mapped_column(String(40), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
