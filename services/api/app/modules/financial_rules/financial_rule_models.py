import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base

# These classes map the tables created by migration 861064d31463 (VF-020E4)
# exactly; VF-020E5 adds no migration. The CHECK literals are the single
# source of truth shared with the migration and are verified by the
# metadata-drift tests.

_ALLOCATION_COLUMNS_NULL_SQL = (
    "execution_mode IS NULL AND execution_order IS NULL AND effective_from IS NULL "
    "AND policy IS NULL AND percent IS NULL AND cap_at_target IS NULL "
    "AND allow_partial IS NULL AND income_sources IS NULL"
)


class FinancialRuleModel(Base):
    """
    SQLAlchemy ORM model for the financial_rules table.

    What:
        One rule of one of four v1 types: INCOME_ALLOCATION,
        MINIMUM_UNALLOCATED_FLOOR, OVERCOMMITMENT_ALERT, BUDGET_ALERT.
        Type-specific columns are structurally impossible for other types
        (per-type shape CHECKs).

    Why:
        There is no currency column (currency equality is validated at
        runtime) and no uniqueness on execution_order (duplicate orders and
        gaps are allowed). The safety floor is this table's
        MINIMUM_UNALLOCATED_FLOOR row, never an Account column. VF-020E5
        never executes a rule: allocation rules stay drafts, and nothing here
        creates money rows.

    Fields:
        status: draft | enabled | paused | disabled.
        version: incremented by a material edit; status changes never bump it.
        active_since: set on every transition into enabled.
    """

    __tablename__ = "financial_rules"

    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_financial_rules_id_user_id"),
        ForeignKeyConstraint(
            ["source_account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            name="fk_financial_rules_source_account_id_user_id",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["budget_id", "user_id"],
            ["budgets.id", "budgets.user_id"],
            name="fk_financial_rules_budget_id_user_id",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "rule_type IN ('INCOME_ALLOCATION','MINIMUM_UNALLOCATED_FLOOR',"
            "'OVERCOMMITMENT_ALERT','BUDGET_ALERT')",
            name="ck_financial_rules_rule_type_valid",
        ),
        CheckConstraint(
            "status IN ('draft','enabled','paused','disabled')",
            name="ck_financial_rules_status_valid",
        ),
        CheckConstraint(
            "execution_mode IS NULL OR execution_mode IN ('AUTO','CONFIRM')",
            name="ck_financial_rules_execution_mode_valid",
        ),
        CheckConstraint(
            "policy IS NULL OR policy IN ('FIXED_PER_GOAL','PERCENT_OF_INCOME_WATERFALL')",
            name="ck_financial_rules_policy_valid",
        ),
        CheckConstraint(
            "percent IS NULL OR (percent > 0 AND percent <= 100)",
            name="ck_financial_rules_percent_valid",
        ),
        CheckConstraint(
            "income_sources IS NULL OR (cardinality(income_sources) >= 1 AND "
            "income_sources <@ ARRAY['salary','freelance','refund','gift','other']"
            "::character varying[])",
            name="ck_financial_rules_income_sources_valid",
        ),
        CheckConstraint(
            "floor_amount IS NULL OR floor_amount >= 0",
            name="ck_financial_rules_floor_amount_valid",
        ),
        CheckConstraint("version >= 1", name="ck_financial_rules_version_valid"),
        CheckConstraint(
            "rule_type <> 'INCOME_ALLOCATION' OR ("
            "source_account_id IS NOT NULL AND budget_id IS NULL AND floor_amount IS NULL "
            "AND execution_mode IS NOT NULL AND execution_order IS NOT NULL "
            "AND policy IS NOT NULL AND income_sources IS NOT NULL "
            "AND cap_at_target IS NOT NULL AND allow_partial IS NOT NULL)",
            name="ck_financial_rules_allocation_shape",
        ),
        CheckConstraint(
            "rule_type <> 'MINIMUM_UNALLOCATED_FLOOR' OR ("
            "source_account_id IS NOT NULL AND budget_id IS NULL "
            f"AND floor_amount IS NOT NULL AND {_ALLOCATION_COLUMNS_NULL_SQL})",
            name="ck_financial_rules_floor_shape",
        ),
        CheckConstraint(
            "rule_type <> 'OVERCOMMITMENT_ALERT' OR ("
            "source_account_id IS NOT NULL AND budget_id IS NULL "
            f"AND floor_amount IS NULL AND {_ALLOCATION_COLUMNS_NULL_SQL})",
            name="ck_financial_rules_overcommitment_shape",
        ),
        CheckConstraint(
            "rule_type <> 'BUDGET_ALERT' OR ("
            "budget_id IS NOT NULL AND source_account_id IS NULL "
            f"AND floor_amount IS NULL AND {_ALLOCATION_COLUMNS_NULL_SQL})",
            name="ck_financial_rules_budget_alert_shape",
        ),
        Index(
            "uq_financial_rules_floor_user_id_source_account_id",
            "user_id",
            "source_account_id",
            unique=True,
            postgresql_where=text("rule_type = 'MINIMUM_UNALLOCATED_FLOOR'"),
        ),
        Index(
            "uq_financial_rules_overcommitment_user_id_source_account_id",
            "user_id",
            "source_account_id",
            unique=True,
            postgresql_where=text("rule_type = 'OVERCOMMITMENT_ALERT'"),
        ),
        Index(
            "uq_financial_rules_budget_alert_user_id_budget_id",
            "user_id",
            "budget_id",
            unique=True,
            postgresql_where=text("rule_type = 'BUDGET_ALERT'"),
        ),
        Index(
            "ix_financial_rules_user_id_rule_type_status",
            "user_id",
            "rule_type",
            "status",
        ),
        Index(
            "ix_financial_rules_source_account_id",
            "source_account_id",
            postgresql_where=text("source_account_id IS NOT NULL"),
        ),
        Index(
            "ix_financial_rules_budget_id",
            "budget_id",
            postgresql_where=text("budget_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    name: Mapped[str] = mapped_column(String(150), nullable=False)

    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="draft",
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    active_since: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    source_account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )

    budget_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )

    execution_mode: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    execution_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    effective_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    policy: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)

    cap_at_target: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    allow_partial: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    income_sources: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(String(20)), nullable=True,
    )

    floor_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class FinancialRuleGoalTargetModel(Base):
    """
    SQLAlchemy ORM model for the financial_rule_goal_targets table.

    What:
        One Goal targeted by an INCOME_ALLOCATION rule, with the single
        amount_or_cap column and a configuration position.

    Why:
        position is configuration / UI order only - it is never the
        financial priority (that is the Goal's current priority_rank).
        amount_or_cap is the fixed amount for FIXED_PER_GOAL and an optional
        per-target cap for the percentage policy. Rows are owned by their
        rule (deleted with it) and reference Goals RESTRICT.
    """

    __tablename__ = "financial_rule_goal_targets"

    __table_args__ = (
        UniqueConstraint(
            "rule_id", "goal_id", name="uq_financial_rule_goal_targets_rule_id_goal_id",
        ),
        ForeignKeyConstraint(
            ["rule_id", "user_id"],
            ["financial_rules.id", "financial_rules.user_id"],
            name="fk_financial_rule_goal_targets_rule_id_user_id",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["goal_id", "user_id"],
            ["goals.id", "goals.user_id"],
            name="fk_financial_rule_goal_targets_goal_id_user_id",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "amount_or_cap IS NULL OR amount_or_cap > 0",
            name="ck_financial_rule_goal_targets_amount_or_cap_positive",
        ),
        CheckConstraint(
            "position >= 0",
            name="ck_financial_rule_goal_targets_position_non_negative",
        ),
        Index("ix_financial_rule_goal_targets_goal_id", "goal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    goal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    amount_or_cap: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True,
    )

    position: Mapped[int] = mapped_column(Integer, nullable=False)
