"""add rule execution schema

Revision ID: e0503e9ca9d3
Revises: 861064d31463
Create Date: 2026-10-21 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e0503e9ca9d3'
down_revision: Union[str, Sequence[str], None] = '861064d31463'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The new application tables and sequence (VF-020E6). Named explicitly (never a
# schema-wide statement), exactly like 1edb74dc96d8, 115998e2e795 and
# 861064d31463: this migration governs the security posture of its own objects.
RULE_EXECUTIONS_TABLE_SQL = "public.rule_executions"
RULE_EXECUTION_ITEMS_TABLE_SQL = "public.rule_execution_items"
RULE_EXECUTION_AUDIT_TABLE_SQL = "public.rule_execution_audit"
HOLD_SEQUENCE_NAME = "rule_execution_hold_sequence"
HOLD_SEQUENCE_SQL = f"public.{HOLD_SEQUENCE_NAME}"

# Supabase's Data API (PostgREST) roles - identical to VF-SEC-01. None of them
# exist on local/CI PostgreSQL, so every statement naming one is wrapped in a
# pg_roles existence check and becomes a safe no-op there.
DATA_API_ROLES_ARRAY_SQL = "ARRAY['anon', 'authenticated', 'service_role']"

# Table locks taken before any DDL, in the application's own order
# (Goal -> Account -> goal_transactions) with financial_rules in between. The new
# tables' foreign keys take SHARE ROW EXCLUSIVE on goals, accounts and
# financial_rules; goal_transactions gets a new column, a replaced CHECK, a new
# unique key and a new foreign key, which need ACCESS EXCLUSIVE. Taking them
# explicitly and in one fixed order keeps the lock acquisition deterministic.
# The downgrade drops the foreign keys together with the new objects, so it
# takes ACCESS EXCLUSIVE on all four in the same order. No lock_timeout is set
# here on purpose: how long the migration may wait is an execution-time
# decision (the operator sets a transaction-local lock_timeout).
UPGRADE_LOCKS = (
    "LOCK TABLE goals IN SHARE ROW EXCLUSIVE MODE",
    "LOCK TABLE accounts IN SHARE ROW EXCLUSIVE MODE",
    "LOCK TABLE financial_rules IN SHARE ROW EXCLUSIVE MODE",
    "LOCK TABLE goal_transactions IN ACCESS EXCLUSIVE MODE",
)
DOWNGRADE_LOCKS = (
    "LOCK TABLE goals IN ACCESS EXCLUSIVE MODE",
    "LOCK TABLE accounts IN ACCESS EXCLUSIVE MODE",
    "LOCK TABLE financial_rules IN ACCESS EXCLUSIVE MODE",
    "LOCK TABLE goal_transactions IN ACCESS EXCLUSIVE MODE",
)

OLD_LINKED_KEY_CHECK = "ck_goal_transactions_linked_requires_client_request_id"
OLD_LINKED_KEY_CHECK_SQL = "account_id IS NULL OR client_request_id IS NOT NULL"
NEW_LINKED_ORIGIN_CHECK = "ck_goal_transactions_linked_requires_origin"
# Broadened linked-origin CHECK: a linked row needs a client key (manual) OR a
# rule execution (rule-generated). It accepts every row the old CHECK accepted.
NEW_LINKED_ORIGIN_CHECK_SQL = (
    "account_id IS NULL OR client_request_id IS NOT NULL OR rule_execution_id IS NOT NULL"
)
ORIGIN_EXCLUSIVE_CHECK = "ck_goal_transactions_origin_exclusive"
ORIGIN_EXCLUSIVE_CHECK_SQL = "client_request_id IS NULL OR rule_execution_id IS NULL"
RULE_ROW_SHAPE_CHECK = "ck_goal_transactions_rule_execution_shape"
RULE_ROW_SHAPE_CHECK_SQL = (
    "rule_execution_id IS NULL OR (account_id IS NOT NULL AND type = 'contribution')"
)
GOAL_TRANSACTIONS_ID_USER_ID_UNIQUE = "uq_goal_transactions_id_user_id"
GOAL_TRANSACTIONS_RULE_EXECUTION_FK = "fk_goal_transactions_rule_execution_id_user_id"
GOAL_TRANSACTIONS_RULE_EXECUTION_INDEX = "ix_goal_transactions_rule_execution_id"

# Committed execution states (contract section 13.3). A technical failure rolls
# the row back, so there is no pending / applied / failed state.
EXECUTION_STATUS_CHECK_SQL = (
    "status IN ('awaiting_confirmation','executed','executed_partial','skipped',"
    "'blocked','rejected','expired','cancelled')"
)
# Approved audit codes (contract section 11.5). Cancellation reasons
# (superseded, stale, source_changed, source_deleted, rule_inactive) live in
# rule_executions.reason_code, not here.
AUDIT_CODE_CHECK_SQL = (
    "code IN ('proposed','applied','applied_partial','skipped','blocked','confirmed',"
    "'rejected','expired','cancelled','source_changed','source_deleted')"
)


def _guard_downgrade_has_no_execution_history() -> None:
    # Rule execution history and rule-generated GoalTransactions are financial
    # records: a downgrade must never destroy them silently, and the old linked
    # CHECK would reject rule-generated rows anyway. No such rows can exist
    # before the first runtime that creates executions (E7), so the guard is a
    # no-op for a normal rollback and a loud stop otherwise.
    connection = op.get_bind()
    execution_rows = connection.execute(sa.text("SELECT count(*) FROM rule_executions")).scalar_one()
    rule_transactions = connection.execute(
        sa.text("SELECT count(*) FROM goal_transactions WHERE rule_execution_id IS NOT NULL")
    ).scalar_one()

    if execution_rows or rule_transactions:
        raise RuntimeError(
            "Refusing to downgrade: rule executions or rule-generated goal "
            "transactions exist. Their history must not be destroyed."
        )


def upgrade() -> None:
    """
    Creates the rule execution schema (VF-020E6, expand only).

    What:
        1. Locks goals, accounts, financial_rules and goal_transactions in a
           fixed order.
        2. Adds UNIQUE (id, user_id) to goal_transactions (the ownership key
           the item -> transaction foreign key needs).
        3. Creates rule_executions (with the hold_sequence mechanism: a
           PostgreSQL sequence, a nullable BIGINT column and the
           hold_sequence IS NULL <=> expires_at IS NULL CHECK),
           rule_execution_items and rule_execution_audit with composite
           ownership foreign keys.
        4. Adds goal_transactions.rule_execution_id, its composite foreign key
           to rule_executions, the broadened linked-origin CHECK (replacing the
           C1 key CHECK), the mutual-exclusivity CHECK and the rule-row-shape
           CHECK.
        5. Revokes every privilege on the new tables and the sequence from the
           Supabase Data API roles (guarded by pg_roles).

    Why:
        New tables, one nullable column and replaced / added constraints only.
        No existing row is changed: every new CHECK is a no-op while
        rule_execution_id is NULL, and the replacement CHECK accepts every row
        the old one accepted, so the previous runtime keeps working unchanged.
        The application does not read or write the new objects until E7.
        hold_sequence has no column default: only a CONFIRM proposal takes
        nextval (E8), so a NULL hold_sequence means "never a proposal" and the
        value stays populated after the proposal is terminal; the CHECK ties it
        to expires_at only, never to the current status. All execution-history
        foreign keys are RESTRICT (history is never deleted by cascade).
    """

    for statement in UPGRADE_LOCKS:
        op.execute(statement)

    op.create_unique_constraint(
        GOAL_TRANSACTIONS_ID_USER_ID_UNIQUE, "goal_transactions", ["id", "user_id"],
    )

    op.execute(f"CREATE SEQUENCE {HOLD_SEQUENCE_SQL} AS BIGINT START WITH 1 INCREMENT BY 1")

    op.create_table(
        "rule_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        # Parameter snapshot of the rule version that decided (financial inputs
        # and target set); amounts are stored as strings inside the document.
        sa.Column("params_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        # SOFT reference to the source Income (no foreign key): Income CRUD is
        # never blocked and the history survives the Income's deletion.
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        # SOFT reference to the triggering financial_events row.
        sa.Column("triggering_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Typed source snapshot (mirrors the event snapshot).
        sa.Column("source_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("source_currency", sa.String(length=3), nullable=False),
        sa.Column("source_received_at", sa.Date(), nullable=False),
        sa.Column("source_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_income_source", sa.String(length=20), nullable=False),
        # Capacity snapshot at decision time (signed; wider than a money row
        # because an Account balance is a sum of arbitrarily many rows).
        sa.Column("capacity_reservable", sa.Numeric(18, 2), nullable=True),
        sa.Column("capacity_floor", sa.Numeric(18, 2), nullable=True),
        sa.Column("capacity_holds", sa.Numeric(18, 2), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=True),
        # Assigned once from rule_execution_hold_sequence when a CONFIRM
        # proposal is created; immutable; NULL = never a proposal.
        sa.Column("hold_sequence", sa.BigInteger(), nullable=True),
        # Immutable proposal expiry; NULL <=> hold_sequence NULL.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rule_executions"),
        sa.UniqueConstraint("id", "user_id", name="uq_rule_executions_id_user_id"),
        # Idempotency key. The rule version is deliberately NOT part of it.
        sa.UniqueConstraint(
            "user_id", "rule_id", "source_type", "source_id",
            name="uq_rule_executions_user_id_rule_id_source_type_source_id",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id", "user_id"],
            ["financial_rules.id", "financial_rules.user_id"],
            name="fk_rule_executions_rule_id_user_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(EXECUTION_STATUS_CHECK_SQL, name="ck_rule_executions_status_valid"),
        sa.CheckConstraint("rule_version >= 1", name="ck_rule_executions_rule_version_valid"),
        sa.CheckConstraint("source_type IN ('income')", name="ck_rule_executions_source_type_valid"),
        sa.CheckConstraint(
            "(hold_sequence IS NULL) = (expires_at IS NULL)",
            name="ck_rule_executions_hold_sequence_expires_at_paired",
        ),
    )
    op.create_index(
        "uq_rule_executions_hold_sequence",
        "rule_executions",
        ["hold_sequence"],
        unique=True,
        postgresql_where=sa.text("hold_sequence IS NOT NULL"),
    )
    op.create_index("ix_rule_executions_rule_id", "rule_executions", ["rule_id"])
    op.create_index(
        "ix_rule_executions_user_id_source_type_source_id",
        "rule_executions",
        ["user_id", "source_type", "source_id"],
    )
    # Open proposals per user in hold order (active holds / confirm capacity).
    op.create_index(
        "ix_rule_executions_user_id_hold_sequence_awaiting",
        "rule_executions",
        ["user_id", "hold_sequence"],
        postgresql_where=sa.text("status = 'awaiting_confirmation'"),
    )
    op.execute(f"ALTER SEQUENCE {HOLD_SEQUENCE_SQL} OWNED BY rule_executions.hold_sequence")

    op.create_table(
        "rule_execution_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("goal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Configuration / plan order only - never a financial priority.
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("planned_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("applied_amount", sa.Numeric(12, 2), nullable=True),
        # The real GoalTransaction written for this item (exactly-once /
        # audit linkage); at most one item per transaction.
        sa.Column("goal_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_rule_execution_items"),
        sa.UniqueConstraint(
            "execution_id", "goal_id", name="uq_rule_execution_items_execution_id_goal_id",
        ),
        sa.UniqueConstraint(
            "goal_transaction_id", name="uq_rule_execution_items_goal_transaction_id",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id", "user_id"],
            ["rule_executions.id", "rule_executions.user_id"],
            name="fk_rule_execution_items_execution_id_user_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["goal_id", "user_id"],
            ["goals.id", "goals.user_id"],
            name="fk_rule_execution_items_goal_id_user_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            name="fk_rule_execution_items_account_id_user_id",
            ondelete="RESTRICT",
        ),
        # With the default MATCH SIMPLE behavior a NULL goal_transaction_id is
        # not constrained.
        sa.ForeignKeyConstraint(
            ["goal_transaction_id", "user_id"],
            ["goal_transactions.id", "goal_transactions.user_id"],
            name="fk_rule_execution_items_goal_transaction_id_user_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("planned_amount > 0", name="ck_rule_execution_items_planned_amount_positive"),
        sa.CheckConstraint(
            "applied_amount IS NULL OR applied_amount > 0",
            name="ck_rule_execution_items_applied_amount_positive",
        ),
        sa.CheckConstraint("position >= 0", name="ck_rule_execution_items_position_non_negative"),
        sa.CheckConstraint(
            "goal_transaction_id IS NULL OR applied_amount IS NOT NULL",
            name="ck_rule_execution_items_transaction_requires_applied_amount",
        ),
    )
    op.create_index("ix_rule_execution_items_goal_id", "rule_execution_items", ["goal_id"])
    op.create_index("ix_rule_execution_items_account_id", "rule_execution_items", ["account_id"])

    op.create_table(
        "rule_execution_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=24), nullable=False),
        sa.Column("actor", sa.String(length=8), nullable=False),
        # SOFT reference to the related financial_events row.
        sa.Column("related_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Non-monetary codes only.
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rule_execution_audit"),
        sa.ForeignKeyConstraint(
            ["execution_id", "user_id"],
            ["rule_executions.id", "rule_executions.user_id"],
            name="fk_rule_execution_audit_execution_id_user_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(AUDIT_CODE_CHECK_SQL, name="ck_rule_execution_audit_code_valid"),
        sa.CheckConstraint("actor IN ('system','user')", name="ck_rule_execution_audit_actor_valid"),
    )
    op.create_index(
        "ix_rule_execution_audit_execution_id_created_at",
        "rule_execution_audit",
        ["execution_id", "created_at"],
    )

    op.add_column(
        "goal_transactions",
        sa.Column("rule_execution_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        GOAL_TRANSACTIONS_RULE_EXECUTION_FK,
        "goal_transactions",
        "rule_executions",
        ["rule_execution_id", "user_id"],
        ["id", "user_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(OLD_LINKED_KEY_CHECK, "goal_transactions", type_="check")
    op.create_check_constraint(NEW_LINKED_ORIGIN_CHECK, "goal_transactions", NEW_LINKED_ORIGIN_CHECK_SQL)
    op.create_check_constraint(ORIGIN_EXCLUSIVE_CHECK, "goal_transactions", ORIGIN_EXCLUSIVE_CHECK_SQL)
    op.create_check_constraint(RULE_ROW_SHAPE_CHECK, "goal_transactions", RULE_ROW_SHAPE_CHECK_SQL)
    op.create_index(
        GOAL_TRANSACTIONS_RULE_EXECUTION_INDEX,
        "goal_transactions",
        ["rule_execution_id"],
        postgresql_where=sa.text("rule_execution_id IS NOT NULL"),
    )

    op.execute(
        f"""
        DO $$
        DECLARE
            target_role text;
            target_table text;
        BEGIN
            FOREACH target_role IN ARRAY {DATA_API_ROLES_ARRAY_SQL}
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = target_role) THEN
                    FOREACH target_table IN ARRAY ARRAY[
                        '{RULE_EXECUTIONS_TABLE_SQL}',
                        '{RULE_EXECUTION_ITEMS_TABLE_SQL}',
                        '{RULE_EXECUTION_AUDIT_TABLE_SQL}'
                    ]
                    LOOP
                        EXECUTE format(
                            'REVOKE ALL PRIVILEGES ON TABLE %s FROM %I',
                            target_table,
                            target_role
                        );
                    END LOOP;

                    EXECUTE format(
                        'REVOKE ALL PRIVILEGES ON SEQUENCE {HOLD_SEQUENCE_SQL} FROM %I',
                        target_role
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    """
    Removes the rule execution schema (VF-020E6).

    What:
        Locks the four tables, refuses to continue if any execution or
        rule-generated GoalTransaction exists, then drops (in dependency
        order) the goal_transactions additions, the audit, items and
        executions tables, the hold sequence and the goal_transactions unique
        key, and restores the C1 linked-key CHECK.

    Why:
        Only E6-owned objects are removed; financial_events, rules, targets and
        every pre-E6 row are untouched. Execution history is never destroyed
        silently (the guard). No privileges are re-granted: dropping the
        objects drops their ACLs with them, and a downgrade must never reopen
        Data API access.
    """

    for statement in DOWNGRADE_LOCKS:
        op.execute(statement)

    _guard_downgrade_has_no_execution_history()

    op.drop_index(GOAL_TRANSACTIONS_RULE_EXECUTION_INDEX, table_name="goal_transactions")
    op.drop_constraint(RULE_ROW_SHAPE_CHECK, "goal_transactions", type_="check")
    op.drop_constraint(ORIGIN_EXCLUSIVE_CHECK, "goal_transactions", type_="check")
    op.drop_constraint(NEW_LINKED_ORIGIN_CHECK, "goal_transactions", type_="check")
    op.create_check_constraint(OLD_LINKED_KEY_CHECK, "goal_transactions", OLD_LINKED_KEY_CHECK_SQL)
    op.drop_constraint(GOAL_TRANSACTIONS_RULE_EXECUTION_FK, "goal_transactions", type_="foreignkey")
    op.drop_column("goal_transactions", "rule_execution_id")

    op.drop_index("ix_rule_execution_audit_execution_id_created_at", table_name="rule_execution_audit")
    op.drop_table("rule_execution_audit")

    op.drop_index("ix_rule_execution_items_account_id", table_name="rule_execution_items")
    op.drop_index("ix_rule_execution_items_goal_id", table_name="rule_execution_items")
    op.drop_table("rule_execution_items")

    for index_name in (
        "ix_rule_executions_user_id_hold_sequence_awaiting",
        "ix_rule_executions_user_id_source_type_source_id",
        "ix_rule_executions_rule_id",
        "uq_rule_executions_hold_sequence",
    ):
        op.drop_index(index_name, table_name="rule_executions")
    op.drop_table("rule_executions")
    op.execute(f"DROP SEQUENCE IF EXISTS {HOLD_SEQUENCE_SQL}")

    op.drop_constraint(GOAL_TRANSACTIONS_ID_USER_ID_UNIQUE, "goal_transactions", type_="unique")
