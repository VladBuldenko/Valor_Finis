"""add rule alerts schema

Revision ID: a7c3e91d5b24
Revises: e0503e9ca9d3
Create Date: 2026-10-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7c3e91d5b24'
down_revision: Union[str, Sequence[str], None] = 'e0503e9ca9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The new application table (VF-020E9A). Named explicitly (never a schema-wide
# statement), exactly like 1edb74dc96d8, 115998e2e795, 861064d31463 and
# e0503e9ca9d3: this migration governs the security posture of its own object.
RULE_ALERTS_TABLE_SQL = "public.rule_alerts"

# Supabase's Data API (PostgREST) roles - identical to VF-SEC-01. None of them
# exist on local/CI PostgreSQL, so every statement naming one is wrapped in a
# pg_roles existence check and becomes a safe no-op there.
DATA_API_ROLES_ARRAY_SQL = "ARRAY['anon', 'authenticated', 'service_role']"

# The only existing table the new foreign key touches. SHARE ROW EXCLUSIVE is
# what ADD FOREIGN KEY needs on the referenced table; the downgrade drops the
# foreign key together with the table and takes ACCESS EXCLUSIVE. No
# lock_timeout is set here on purpose: how long the migration may wait is an
# execution-time decision (the operator sets a transaction-local lock_timeout).
UPGRADE_LOCKS = ("LOCK TABLE financial_rules IN SHARE ROW EXCLUSIVE MODE",)
DOWNGRADE_LOCKS = (
    "LOCK TABLE financial_rules IN ACCESS EXCLUSIVE MODE",
    "LOCK TABLE rule_alerts IN ACCESS EXCLUSIVE MODE",
)

RULE_TYPE_CHECK = "ck_rule_alerts_rule_type_valid"
RULE_TYPE_CHECK_SQL = "rule_type IN ('MINIMUM_UNALLOCATED_FLOOR','OVERCOMMITMENT_ALERT','BUDGET_ALERT')"
SUBJECT_TYPE_CHECK = "ck_rule_alerts_subject_type_valid"
SUBJECT_TYPE_CHECK_SQL = "subject_type IN ('account','budget')"
LEVEL_CHECK = "ck_rule_alerts_level_valid"
LEVEL_CHECK_SQL = "level IN ('watch','at_risk','exceeded','breached')"
# Which (rule_type, subject_type, level, period_key, resolved_at) combinations
# exist. A Budget alert is keyed by the Budget period start (an ISO date) and
# never resolves; an Account alert (floor breach or overcommitment) is one
# EPISODE numbered E1, E2, ... that is resolved when the Account recovers, so a
# later breach is a new episode and a new row.
TYPE_SHAPE_CHECK = "ck_rule_alerts_type_shape"
TYPE_SHAPE_CHECK_SQL = (
    "(rule_type = 'BUDGET_ALERT' AND subject_type = 'budget' "
    "AND level IN ('watch','at_risk','exceeded') "
    "AND period_key ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' AND resolved_at IS NULL) "
    "OR (rule_type IN ('MINIMUM_UNALLOCATED_FLOOR','OVERCOMMITMENT_ALERT') "
    "AND subject_type = 'account' AND level = 'breached' "
    "AND period_key ~ '^E[1-9][0-9]{0,8}$')"
)
ACKNOWLEDGED_CHECK = "ck_rule_alerts_acknowledged_at_valid"
ACKNOWLEDGED_CHECK_SQL = "acknowledged_at IS NULL OR acknowledged_at >= created_at"
RESOLVED_CHECK = "ck_rule_alerts_resolved_at_valid"
RESOLVED_CHECK_SQL = "resolved_at IS NULL OR resolved_at >= created_at"

ALERT_KEY_UNIQUE = "uq_rule_alerts_alert_key"
OPEN_EPISODE_INDEX = "uq_rule_alerts_open_account_episode"
UNACKNOWLEDGED_INDEX = "ix_rule_alerts_user_id_unacknowledged"
RULE_ID_INDEX = "ix_rule_alerts_rule_id"
RULE_FK = "fk_rule_alerts_rule_id_user_id"


def _guard_downgrade_has_no_alert_history() -> None:
    # Alerts are the user's notification history: a downgrade must never
    # destroy it silently. No row can exist before the first runtime that
    # writes alerts (E9B), so the guard is a no-op for a normal rollback and a
    # loud stop otherwise.
    alerts = op.get_bind().execute(sa.text("SELECT count(*) FROM rule_alerts")).scalar_one()

    if alerts:
        raise RuntimeError(
            "Refusing to downgrade: rule alerts exist. Their history must not be destroyed."
        )


def upgrade() -> None:
    """
    Creates the rule_alerts table (VF-020E9A, expand only).

    What:
        One additive table with a composite ownership foreign key to
        financial_rules that NULLs only rule_id when the rule is deleted
        (ON DELETE SET NULL (rule_id), PostgreSQL 15+), typed identity columns,
        CHECKs for the allowed combinations, the alert-key UNIQUE constraint,
        a partial UNIQUE index that allows one open Account episode, two
        supporting indexes and the Data API REVOKE.

    Why:
        Budget alerts need "each level once per Budget period" and Account
        alerts need "a new row for a new breach after recovery"; both are
        enforced by the database so concurrent inserts have exactly one winner.
        Alerts are informational history: a rule without executions stays
        deletable (P57), so the rule link is nulled instead of blocking or
        cascading, and the subject is a SOFT reference so Account and Budget
        deletion is never blocked. Existing rows and the deployed E8 runtime
        are untouched; no data is read or backfilled.
    """

    for statement in UPGRADE_LOCKS:
        op.execute(statement)

    op.create_table(
        "rule_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        # NULL after the originating rule was deleted; the alert survives.
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Snapshot of the originating rule's type; survives the rule.
        sa.Column("rule_type", sa.String(length=32), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        # SOFT reference to the Account or Budget (no foreign key), so deleting
        # the subject is never blocked and the history survives it.
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_key", sa.String(length=40), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="rule_alerts_pkey"),
        sa.ForeignKeyConstraint(
            ["rule_id", "user_id"],
            ["financial_rules.id", "financial_rules.user_id"],
            name=RULE_FK,
            ondelete="SET NULL (rule_id)",
        ),
        sa.UniqueConstraint(
            "user_id", "rule_type", "subject_id", "period_key", "level", name=ALERT_KEY_UNIQUE,
        ),
        sa.CheckConstraint(RULE_TYPE_CHECK_SQL, name=RULE_TYPE_CHECK),
        sa.CheckConstraint(SUBJECT_TYPE_CHECK_SQL, name=SUBJECT_TYPE_CHECK),
        sa.CheckConstraint(LEVEL_CHECK_SQL, name=LEVEL_CHECK),
        sa.CheckConstraint(TYPE_SHAPE_CHECK_SQL, name=TYPE_SHAPE_CHECK),
        sa.CheckConstraint(ACKNOWLEDGED_CHECK_SQL, name=ACKNOWLEDGED_CHECK),
        sa.CheckConstraint(RESOLVED_CHECK_SQL, name=RESOLVED_CHECK),
    )

    # At most one OPEN (unresolved) episode per Account alert type and Account.
    op.create_index(
        OPEN_EPISODE_INDEX,
        "rule_alerts",
        ["user_id", "rule_type", "subject_id"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL AND rule_type <> 'BUDGET_ALERT'"),
    )
    op.create_index(
        UNACKNOWLEDGED_INDEX,
        "rule_alerts",
        ["user_id", "created_at", "id"],
        postgresql_where=sa.text("acknowledged_at IS NULL"),
    )
    op.create_index(
        RULE_ID_INDEX,
        "rule_alerts",
        ["rule_id"],
        postgresql_where=sa.text("rule_id IS NOT NULL"),
    )

    op.execute(
        f"""
        DO $$
        DECLARE
            target_role text;
        BEGIN
            FOREACH target_role IN ARRAY {DATA_API_ROLES_ARRAY_SQL}
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = target_role) THEN
                    EXECUTE format(
                        'REVOKE ALL PRIVILEGES ON TABLE {RULE_ALERTS_TABLE_SQL} FROM %I',
                        target_role
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    """
    Removes the rule_alerts table (VF-020E9A).

    What:
        Locks financial_rules and rule_alerts, refuses to continue if any alert
        exists, then drops the indexes and the table.

    Why:
        Only the E9A object is removed; every earlier table and row is
        untouched. Alert history is never destroyed silently. No privileges are
        re-granted: dropping the table drops its ACL with it, and a downgrade
        must never reopen Data API access.
    """

    for statement in DOWNGRADE_LOCKS:
        op.execute(statement)

    _guard_downgrade_has_no_alert_history()

    op.drop_index(RULE_ID_INDEX, table_name="rule_alerts")
    op.drop_index(UNACKNOWLEDGED_INDEX, table_name="rule_alerts")
    op.drop_index(OPEN_EPISODE_INDEX, table_name="rule_alerts")
    op.drop_table("rule_alerts")
