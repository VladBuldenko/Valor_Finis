import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Sequence,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base

# These classes map the tables created by migration e0503e9ca9d3 (VF-020E6)
# exactly. VF-020E6 is schema-only: nothing in the application creates, reads
# or updates these rows yet (the first runtime that does is E7). For the same
# reason goal_transactions.rule_execution_id (and its foreign key / index and the
# goal_transactions ownership unique key) is deliberately NOT mapped on
# GoalTransactionModel yet: mapping a column that production does not have until
# its migration would break every GoalTransaction query in the window between
# deployment and migration. The E7 runtime maps it. The CHECK
# literals are shared with the migration and verified by the metadata-drift
# tests.

# The hold-order sequence (P80). It is deliberately NOT a column default:
# only a CONFIRM proposal takes nextval (E8), once, under L0. A NULL
# hold_sequence means "never a proposal"; a populated value is retained
# forever, also after the proposal is terminal.
RULE_EXECUTION_HOLD_SEQUENCE = Sequence(
    "rule_execution_hold_sequence", metadata=Base.metadata, start=1, increment=1,
)


class RuleExecutionModel(Base):
    """
    SQLAlchemy ORM model for rule_executions.

    What:
        One rule's committed decision about one source (an Income). Statuses
        are exactly awaiting_confirmation, executed, executed_partial, skipped,
        blocked, rejected, expired and cancelled; there is no pending, applied
        or failed state because a technical failure rolls the row back.

    Why:
        UNIQUE(user_id, rule_id, source_type, source_id) is the exactly-once
        idempotency key (the rule version is deliberately not part of it).
        source_id and triggering_event_id are SOFT references. hold_sequence
        and expires_at are set together when a CONFIRM proposal is created and
        are never changed; the CHECK ties them to each other, not to the
        current status.
    """

    __tablename__ = "rule_executions"

    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_rule_executions_id_user_id"),
        UniqueConstraint(
            "user_id", "rule_id", "source_type", "source_id",
            name="uq_rule_executions_user_id_rule_id_source_type_source_id",
        ),
        ForeignKeyConstraint(
            ["rule_id", "user_id"],
            ["financial_rules.id", "financial_rules.user_id"],
            name="fk_rule_executions_rule_id_user_id",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('awaiting_confirmation','executed','executed_partial','skipped',"
            "'blocked','rejected','expired','cancelled')",
            name="ck_rule_executions_status_valid",
        ),
        CheckConstraint("rule_version >= 1", name="ck_rule_executions_rule_version_valid"),
        CheckConstraint("source_type IN ('income')", name="ck_rule_executions_source_type_valid"),
        CheckConstraint(
            "(hold_sequence IS NULL) = (expires_at IS NULL)",
            name="ck_rule_executions_hold_sequence_expires_at_paired",
        ),
        Index(
            "uq_rule_executions_hold_sequence",
            "hold_sequence",
            unique=True,
            postgresql_where=text("hold_sequence IS NOT NULL"),
        ),
        Index("ix_rule_executions_rule_id", "rule_id"),
        Index(
            "ix_rule_executions_user_id_source_type_source_id",
            "user_id", "source_type", "source_id",
        ),
        Index(
            "ix_rule_executions_user_id_hold_sequence_awaiting",
            "user_id", "hold_sequence",
            postgresql_where=text("status = 'awaiting_confirmation'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    rule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    params_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    triggering_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    source_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source_received_at: Mapped[date] = mapped_column(Date, nullable=False)
    source_account_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_income_source: Mapped[str] = mapped_column(String(20), nullable=False)
    capacity_reservable: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    capacity_floor: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    capacity_holds: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    hold_sequence: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )


class RuleExecutionItemModel(Base):
    """
    SQLAlchemy ORM model for rule_execution_items.

    What:
        One planned (and, once applied, written) allocation of an execution to
        one Goal, with the real GoalTransaction it produced.

    Why:
        goal_transaction_id is UNIQUE and references the actual
        GoalTransaction: the applied item -> transaction link is part of the
        exactly-once / audit proof. position is plan order only, never the
        financial priority. A pending CONFIRM proposal's planned_amount is the
        source of its soft hold.
    """

    __tablename__ = "rule_execution_items"

    __table_args__ = (
        UniqueConstraint("execution_id", "goal_id", name="uq_rule_execution_items_execution_id_goal_id"),
        UniqueConstraint("goal_transaction_id", name="uq_rule_execution_items_goal_transaction_id"),
        ForeignKeyConstraint(
            ["execution_id", "user_id"],
            ["rule_executions.id", "rule_executions.user_id"],
            name="fk_rule_execution_items_execution_id_user_id",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["goal_id", "user_id"],
            ["goals.id", "goals.user_id"],
            name="fk_rule_execution_items_goal_id_user_id",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            name="fk_rule_execution_items_account_id_user_id",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["goal_transaction_id", "user_id"],
            ["goal_transactions.id", "goal_transactions.user_id"],
            name="fk_rule_execution_items_goal_transaction_id_user_id",
            ondelete="RESTRICT",
        ),
        CheckConstraint("planned_amount > 0", name="ck_rule_execution_items_planned_amount_positive"),
        CheckConstraint(
            "applied_amount IS NULL OR applied_amount > 0",
            name="ck_rule_execution_items_applied_amount_positive",
        ),
        CheckConstraint("position >= 0", name="ck_rule_execution_items_position_non_negative"),
        CheckConstraint(
            "goal_transaction_id IS NULL OR applied_amount IS NOT NULL",
            name="ck_rule_execution_items_transaction_requires_applied_amount",
        ),
        Index("ix_rule_execution_items_goal_id", "goal_id"),
        Index("ix_rule_execution_items_account_id", "account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    goal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    applied_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    goal_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)


class RuleExecutionAuditModel(Base):
    """
    SQLAlchemy ORM model for rule_execution_audit.

    What:
        Append-only record of every execution transition and annotation, with
        an approved code, an actor and non-monetary details.

    Why:
        Completed executions are never rewritten: later events only append
        annotations (source_changed, source_deleted). related_event_id is a
        SOFT reference. Append-only behavior is a runtime rule (no update or
        delete path exists); the table has no mutable columns by design.
    """

    __tablename__ = "rule_execution_audit"

    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_id", "user_id"],
            ["rule_executions.id", "rule_executions.user_id"],
            name="fk_rule_execution_audit_execution_id_user_id",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "code IN ('proposed','applied','applied_partial','skipped','blocked','confirmed',"
            "'rejected','expired','cancelled','source_changed','source_deleted')",
            name="ck_rule_execution_audit_code_valid",
        ),
        CheckConstraint("actor IN ('system','user')", name="ck_rule_execution_audit_actor_valid"),
        Index("ix_rule_execution_audit_execution_id_created_at", "execution_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    actor: Mapped[str] = mapped_column(String(8), nullable=False)
    related_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
