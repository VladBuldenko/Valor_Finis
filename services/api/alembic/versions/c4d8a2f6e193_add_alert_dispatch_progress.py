"""add alert dispatch progress

Revision ID: c4d8a2f6e193
Revises: a7c3e91d5b24
Create Date: 2026-10-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c4d8a2f6e193'
down_revision: Union[str, Sequence[str], None] = 'a7c3e91d5b24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The new application objects (VF-020E10, persistent alert dispatch fairness).
# Named explicitly (never a schema-wide statement), exactly like 1edb74dc96d8,
# 115998e2e795, 861064d31463, e0503e9ca9d3 and a7c3e91d5b24.
PROGRESS_TABLE_SQL = "public.alert_dispatch_progress"
SERVICE_SEQUENCE_NAME = "alert_dispatch_service_seq"
SERVICE_SEQUENCE_SQL = f"public.{SERVICE_SEQUENCE_NAME}"

# Supabase's Data API (PostgREST) roles - identical to VF-SEC-01. None of them
# exist on local/CI PostgreSQL, so every statement naming one is wrapped in a
# pg_roles existence check and becomes a safe no-op there.
DATA_API_ROLES_ARRAY_SQL = "ARRAY['anon', 'authenticated', 'service_role']"

SERVICE_SEQ_UNIQUE = "uq_alert_dispatch_progress_service_seq"
FAILURES_CHECK = "ck_alert_dispatch_progress_consecutive_failures_valid"
FAILURES_CHECK_SQL = "consecutive_failures >= 0"
SUCCESS_CHECK = "ck_alert_dispatch_progress_last_success_at_valid"
SUCCESS_CHECK_SQL = "last_success_at IS NULL OR last_success_at <= last_attempted_at"
LAST_SUCCESS_INDEX = "ix_alert_dispatch_progress_last_success_at"


def upgrade() -> None:
    """
    Creates the alert dispatch progress table and its service-order sequence
    (VF-020E10, expand only).

    What:
        One private operational table, one row per user the periodic dispatcher
        has attempted to evaluate alerts for, plus a PostgreSQL sequence. The
        dispatcher draws `service_seq = nextval(...)` every time it attempts a
        user, so "least recently attempted first" is a strict, durable total
        order that does not depend on wall-clock timestamps (no ties, no clock
        steps). A user with no row has never been attempted and is served first.

    Why:
        Stateless paging cannot give liveness under partial runs or missed
        ticks. The table has no foreign keys (there is no users table, and a row
        must survive nothing it does not own), stores no amounts and no personal
        data (an identifier, sequence numbers, timestamps, a failure counter and
        an error CODE), and is deleted by the dispatcher when a user no longer
        has an enabled alert rule. It touches no existing table, so it takes no
        lock on any existing relation, needs no backfill, and the deployed
        runtime ignores it.
    """

    op.execute(f"CREATE SEQUENCE {SERVICE_SEQUENCE_SQL} AS BIGINT START WITH 1 INCREMENT BY 1")

    op.create_table(
        "alert_dispatch_progress",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_seq", sa.BigInteger(), nullable=False),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default=sa.text("0"), nullable=False),
        # A short error CODE (exception class name), never a message: messages can
        # carry SQL parameters.
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("user_id", name="alert_dispatch_progress_pkey"),
        sa.UniqueConstraint("service_seq", name=SERVICE_SEQ_UNIQUE),
        sa.CheckConstraint(FAILURES_CHECK_SQL, name=FAILURES_CHECK),
        sa.CheckConstraint(SUCCESS_CHECK_SQL, name=SUCCESS_CHECK),
    )
    op.create_index(LAST_SUCCESS_INDEX, "alert_dispatch_progress", ["last_success_at"])

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
                        'REVOKE ALL PRIVILEGES ON TABLE {PROGRESS_TABLE_SQL} FROM %I',
                        target_role
                    );
                    EXECUTE format(
                        'REVOKE ALL PRIVILEGES ON SEQUENCE {SERVICE_SEQUENCE_SQL} FROM %I',
                        target_role
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    """
    Removes the alert dispatch progress table and its sequence.

    What:
        Drops the index, the table and the sequence. No other object is touched.

    Why:
        The rows are operational scheduling state, not history: losing them only
        resets the dispatcher to "every user never attempted", after which it
        serves users in user_id order and rebuilds the order. A downgrade
        therefore needs no history guard. The runtime falls back to the random
        sample while the table is absent. No privileges are re-granted.
    """

    op.drop_index(LAST_SUCCESS_INDEX, table_name="alert_dispatch_progress")
    op.drop_table("alert_dispatch_progress")
    op.execute(f"DROP SEQUENCE IF EXISTS {SERVICE_SEQUENCE_SQL}")
