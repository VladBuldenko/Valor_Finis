"""add financial rules

Revision ID: 861064d31463
Revises: 115998e2e795
Create Date: 2026-10-20 14:07:49.200546

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '861064d31463'
down_revision: Union[str, Sequence[str], None] = '115998e2e795'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The two new application tables (VF-020E4). Named explicitly (never a
# schema-wide statement), exactly like 1edb74dc96d8 and 115998e2e795: this
# migration governs the security posture of its own objects only.
FINANCIAL_RULES_TABLE_SQL = "public.financial_rules"
FINANCIAL_RULE_GOAL_TARGETS_TABLE_SQL = "public.financial_rule_goal_targets"

# Supabase's Data API (PostgREST) roles - identical to VF-SEC-01. None of them
# exist on local/CI PostgreSQL, so the statement naming them is wrapped in a
# pg_roles existence check and becomes a safe no-op there.
DATA_API_ROLES_ARRAY_SQL = "ARRAY['anon', 'authenticated', 'service_role']"

# Table locks taken before any DDL, in the application's own order (Goal ->
# Account) and with budgets last. The new tables' foreign keys take a
# SHARE ROW EXCLUSIVE lock on goals and accounts; the composite unique key on
# budgets needs ACCESS EXCLUSIVE. Taking them explicitly and in one fixed
# order keeps the migration's own lock acquisition deterministic. The downgrade
# drops the foreign keys together with the tables and the budgets key, so it
# takes ACCESS EXCLUSIVE on all three in the same order. No lock_timeout is set
# here on purpose: how long the migration may wait is an execution-time
# decision (the operator sets a transaction-local lock_timeout).
UPGRADE_LOCKS = (
    "LOCK TABLE goals IN SHARE ROW EXCLUSIVE MODE",
    "LOCK TABLE accounts IN SHARE ROW EXCLUSIVE MODE",
    "LOCK TABLE budgets IN ACCESS EXCLUSIVE MODE",
)
DOWNGRADE_LOCKS = (
    "LOCK TABLE goals IN ACCESS EXCLUSIVE MODE",
    "LOCK TABLE accounts IN ACCESS EXCLUSIVE MODE",
    "LOCK TABLE budgets IN ACCESS EXCLUSIVE MODE",
)

BUDGETS_COMPOSITE_UNIQUE = "uq_budgets_id_user_id"

# Approved enumerations (E1 contract sections 10 and 19.3, P84, P88).
# GOAL_DEADLINE_ALERT is deliberately NOT a supported type.
RULE_TYPE_CHECK_SQL = (
    "rule_type IN ('INCOME_ALLOCATION','MINIMUM_UNALLOCATED_FLOOR',"
    "'OVERCOMMITMENT_ALERT','BUDGET_ALERT')"
)
STATUS_CHECK_SQL = "status IN ('draft','enabled','paused','disabled')"
EXECUTION_MODE_CHECK_SQL = (
    "execution_mode IS NULL OR execution_mode IN ('AUTO','CONFIRM')"
)
POLICY_CHECK_SQL = (
    "policy IS NULL OR policy IN ('FIXED_PER_GOAL','PERCENT_OF_INCOME_WATERFALL')"
)
PERCENT_CHECK_SQL = "percent IS NULL OR (percent > 0 AND percent <= 100)"
# Subset of the closed Income.source set, never empty when present.
INCOME_SOURCES_CHECK_SQL = (
    "income_sources IS NULL OR (cardinality(income_sources) >= 1 AND "
    "income_sources <@ ARRAY['salary','freelance','refund','gift','other']"
    "::character varying[])"
)
FLOOR_AMOUNT_CHECK_SQL = "floor_amount IS NULL OR floor_amount >= 0"
VERSION_CHECK_SQL = "version >= 1"

# Type-specific shapes. Cross-type columns are made structurally impossible
# at the database level instead of relying on service validation alone.
# Allocation-only columns: execution_mode, execution_order, effective_from,
# policy, percent, cap_at_target, allow_partial, income_sources.
# effective_from and percent stay nullable for allocation rules: the first
# activation fills effective_from, and percent only applies to the percentage
# policy (runtime validation, section 10).
_ALLOCATION_COLUMNS_NULL_SQL = (
    "execution_mode IS NULL AND execution_order IS NULL AND effective_from IS NULL "
    "AND policy IS NULL AND percent IS NULL AND cap_at_target IS NULL "
    "AND allow_partial IS NULL AND income_sources IS NULL"
)
ALLOCATION_SHAPE_CHECK_SQL = (
    "rule_type <> 'INCOME_ALLOCATION' OR ("
    "source_account_id IS NOT NULL AND budget_id IS NULL AND floor_amount IS NULL "
    "AND execution_mode IS NOT NULL AND execution_order IS NOT NULL "
    "AND policy IS NOT NULL AND income_sources IS NOT NULL "
    "AND cap_at_target IS NOT NULL AND allow_partial IS NOT NULL)"
)
FLOOR_SHAPE_CHECK_SQL = (
    "rule_type <> 'MINIMUM_UNALLOCATED_FLOOR' OR ("
    "source_account_id IS NOT NULL AND budget_id IS NULL "
    f"AND floor_amount IS NOT NULL AND {_ALLOCATION_COLUMNS_NULL_SQL})"
)
OVERCOMMITMENT_SHAPE_CHECK_SQL = (
    "rule_type <> 'OVERCOMMITMENT_ALERT' OR ("
    "source_account_id IS NOT NULL AND budget_id IS NULL "
    f"AND floor_amount IS NULL AND {_ALLOCATION_COLUMNS_NULL_SQL})"
)
BUDGET_ALERT_SHAPE_CHECK_SQL = (
    "rule_type <> 'BUDGET_ALERT' OR ("
    "budget_id IS NOT NULL AND source_account_id IS NULL "
    f"AND floor_amount IS NULL AND {_ALLOCATION_COLUMNS_NULL_SQL})"
)

FLOOR_UNIQUE_INDEX = "uq_financial_rules_floor_user_id_source_account_id"
OVERCOMMITMENT_UNIQUE_INDEX = "uq_financial_rules_overcommitment_user_id_source_account_id"
BUDGET_ALERT_UNIQUE_INDEX = "uq_financial_rules_budget_alert_user_id_budget_id"


def upgrade() -> None:
    """
    Creates the rules definition schema (VF-020E4, expand only).

    What:
        1. Locks goals, accounts and budgets in a fixed order.
        2. Adds UNIQUE (id, user_id) to budgets, the ownership key that the
           BUDGET_ALERT foreign key needs.
        3. Creates financial_rules with the approved type-specific shape
           CHECKs, the partial uniques for the floor, the overcommitment alert
           and the budget alert, and composite ownership foreign keys to
           accounts and budgets (ON DELETE RESTRICT).
        4. Creates financial_rule_goal_targets with composite ownership foreign
           keys to financial_rules (CASCADE) and goals (RESTRICT).
        5. Revokes every privilege on both new tables from the Supabase Data
           API roles (guarded by pg_roles).

    Why:
        New tables only, plus one additive unique key on budgets. No existing
        row is read, updated or backfilled, no rule is created, and the
        application neither maps nor queries the new tables until E5, so the
        previous runtime keeps working unchanged before and after this
        migration. There is deliberately NO currency column on a rule (currency
        equality is validated at runtime), NO UNIQUE (user_id, execution_order)
        (duplicate orders and gaps are allowed, P28), and NO floor column on
        accounts (the floor is a rule row, P78). rule_alerts, executions and
        the hold sequence belong to later stages.
    """

    for statement in UPGRADE_LOCKS:
        op.execute(statement)

    op.create_unique_constraint(
        BUDGETS_COMPOSITE_UNIQUE, "budgets", ["id", "user_id"],
    )

    op.create_table(
        "financial_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("rule_type", sa.String(length=32), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="draft", nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("active_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("budget_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Allocation-only columns.
        sa.Column("execution_mode", sa.String(length=16), nullable=True),
        sa.Column("execution_order", sa.Integer(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("policy", sa.String(length=40), nullable=True),
        sa.Column("percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("cap_at_target", sa.Boolean(), nullable=True),
        sa.Column("allow_partial", sa.Boolean(), nullable=True),
        sa.Column(
            "income_sources",
            postgresql.ARRAY(sa.String(length=20)),
            nullable=True,
        ),
        # Floor-only column.
        sa.Column("floor_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_financial_rules"),
        sa.UniqueConstraint("id", "user_id", name="uq_financial_rules_id_user_id"),
        sa.ForeignKeyConstraint(
            ["source_account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            name="fk_financial_rules_source_account_id_user_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["budget_id", "user_id"],
            ["budgets.id", "budgets.user_id"],
            name="fk_financial_rules_budget_id_user_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(RULE_TYPE_CHECK_SQL, name="ck_financial_rules_rule_type_valid"),
        sa.CheckConstraint(STATUS_CHECK_SQL, name="ck_financial_rules_status_valid"),
        sa.CheckConstraint(
            EXECUTION_MODE_CHECK_SQL, name="ck_financial_rules_execution_mode_valid",
        ),
        sa.CheckConstraint(POLICY_CHECK_SQL, name="ck_financial_rules_policy_valid"),
        sa.CheckConstraint(PERCENT_CHECK_SQL, name="ck_financial_rules_percent_valid"),
        sa.CheckConstraint(
            INCOME_SOURCES_CHECK_SQL, name="ck_financial_rules_income_sources_valid",
        ),
        sa.CheckConstraint(
            FLOOR_AMOUNT_CHECK_SQL, name="ck_financial_rules_floor_amount_valid",
        ),
        sa.CheckConstraint(VERSION_CHECK_SQL, name="ck_financial_rules_version_valid"),
        sa.CheckConstraint(
            ALLOCATION_SHAPE_CHECK_SQL, name="ck_financial_rules_allocation_shape",
        ),
        sa.CheckConstraint(
            FLOOR_SHAPE_CHECK_SQL, name="ck_financial_rules_floor_shape",
        ),
        sa.CheckConstraint(
            OVERCOMMITMENT_SHAPE_CHECK_SQL, name="ck_financial_rules_overcommitment_shape",
        ),
        sa.CheckConstraint(
            BUDGET_ALERT_SHAPE_CHECK_SQL, name="ck_financial_rules_budget_alert_shape",
        ),
    )

    op.create_index(
        FLOOR_UNIQUE_INDEX,
        "financial_rules",
        ["user_id", "source_account_id"],
        unique=True,
        postgresql_where=sa.text("rule_type = 'MINIMUM_UNALLOCATED_FLOOR'"),
    )
    op.create_index(
        OVERCOMMITMENT_UNIQUE_INDEX,
        "financial_rules",
        ["user_id", "source_account_id"],
        unique=True,
        postgresql_where=sa.text("rule_type = 'OVERCOMMITMENT_ALERT'"),
    )
    op.create_index(
        BUDGET_ALERT_UNIQUE_INDEX,
        "financial_rules",
        ["user_id", "budget_id"],
        unique=True,
        postgresql_where=sa.text("rule_type = 'BUDGET_ALERT'"),
    )
    op.create_index(
        "ix_financial_rules_user_id_rule_type_status",
        "financial_rules",
        ["user_id", "rule_type", "status"],
    )
    # Support the RESTRICT foreign-key checks on Account / Budget deletes.
    op.create_index(
        "ix_financial_rules_source_account_id",
        "financial_rules",
        ["source_account_id"],
        postgresql_where=sa.text("source_account_id IS NOT NULL"),
    )
    op.create_index(
        "ix_financial_rules_budget_id",
        "financial_rules",
        ["budget_id"],
        postgresql_where=sa.text("budget_id IS NOT NULL"),
    )

    op.create_table(
        "financial_rule_goal_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("goal_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Fixed amount for FIXED_PER_GOAL, optional per-target cap for the
        # percentage policy; the policy-level rule is runtime validation.
        sa.Column("amount_or_cap", sa.Numeric(12, 2), nullable=True),
        # Configuration / UI order only - never the financial priority.
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_financial_rule_goal_targets"),
        sa.UniqueConstraint(
            "rule_id", "goal_id", name="uq_financial_rule_goal_targets_rule_id_goal_id",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id", "user_id"],
            ["financial_rules.id", "financial_rules.user_id"],
            name="fk_financial_rule_goal_targets_rule_id_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["goal_id", "user_id"],
            ["goals.id", "goals.user_id"],
            name="fk_financial_rule_goal_targets_goal_id_user_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "amount_or_cap IS NULL OR amount_or_cap > 0",
            name="ck_financial_rule_goal_targets_amount_or_cap_positive",
        ),
        sa.CheckConstraint(
            "position >= 0", name="ck_financial_rule_goal_targets_position_non_negative",
        ),
    )
    # Supports the RESTRICT foreign-key check on Goal deletes.
    op.create_index(
        "ix_financial_rule_goal_targets_goal_id",
        "financial_rule_goal_targets",
        ["goal_id"],
    )

    op.execute(
        f"""
        DO $$
        DECLARE
            target_role text;
            target_table text;
        BEGIN
            FOREACH target_table IN ARRAY ARRAY[
                '{FINANCIAL_RULES_TABLE_SQL}',
                '{FINANCIAL_RULE_GOAL_TARGETS_TABLE_SQL}'
            ]
            LOOP
                FOREACH target_role IN ARRAY {DATA_API_ROLES_ARRAY_SQL}
                LOOP
                    IF EXISTS (
                        SELECT 1 FROM pg_roles WHERE rolname = target_role
                    ) THEN
                        EXECUTE format(
                            'REVOKE ALL PRIVILEGES ON TABLE %s FROM %I',
                            target_table,
                            target_role
                        );
                    END IF;
                END LOOP;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    """
    Removes the rules definition schema (VF-020E4).

    What:
        Locks goals, accounts and budgets, drops financial_rule_goal_targets,
        then financial_rules, then the budgets composite unique key.

    Why:
        Only E4-owned objects are removed, in dependency order (the targets
        reference the rules; the rules reference the budgets key). financial_events
        and every other pre-E4 table and row are untouched. This permanently
        destroys every stored rule and target (none exist before the E5
        runtime creates them). No privileges are re-granted: dropping the
        tables drops their ACLs with them, and a downgrade must never reopen
        Data API access.
    """

    for statement in DOWNGRADE_LOCKS:
        op.execute(statement)

    op.drop_index(
        "ix_financial_rule_goal_targets_goal_id",
        table_name="financial_rule_goal_targets",
    )
    op.drop_table("financial_rule_goal_targets")

    for index_name in (
        "ix_financial_rules_budget_id",
        "ix_financial_rules_source_account_id",
        "ix_financial_rules_user_id_rule_type_status",
        BUDGET_ALERT_UNIQUE_INDEX,
        OVERCOMMITMENT_UNIQUE_INDEX,
        FLOOR_UNIQUE_INDEX,
    ):
        op.drop_index(index_name, table_name="financial_rules")
    op.drop_table("financial_rules")

    op.drop_constraint(BUDGETS_COMPOSITE_UNIQUE, "budgets", type_="unique")
