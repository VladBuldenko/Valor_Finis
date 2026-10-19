"""add financial events

Revision ID: 115998e2e795
Revises: 7c1e5a9b3d28
Create Date: 2026-10-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '115998e2e795'
down_revision: Union[str, Sequence[str], None] = '7c1e5a9b3d28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The single new application table this migration creates (VF-020E2). Named
# explicitly (never a schema-wide statement), exactly like the
# account_transfers migration 1edb74dc96d8 and VF-SEC-01 (edcfdf3f7114): this
# migration governs the security posture of its own object only.
FINANCIAL_EVENTS_TABLE_SQL = "public.financial_events"

# Supabase's Data API (PostgREST) roles - identical to VF-SEC-01. None of them
# exist on local/CI PostgreSQL, so the statement naming them is wrapped in a
# pg_roles existence check and becomes a safe no-op there.
DATA_API_ROLES_ARRAY_SQL = "ARRAY['anon', 'authenticated', 'service_role']"

# Approved enumerations (E1 contract section 12 / 19.3, P83). The CHECK
# literals are the single source of truth; the tests read them back from
# PostgreSQL.
EVENT_TYPE_CHECK_SQL = (
    "event_type IN ('income.created','income.updated','income.deleted')"
)
ORIGIN_CHECK_SQL = "origin IN ('manual','receipt','import','system')"
INGESTION_MODE_CHECK_SQL = "ingestion_mode IN ('live','historical','correction')"
STATUS_CHECK_SQL = (
    "status IN ('pending','processing','processed','failed_retryable','dead')"
)
# max_attempts = 6 (P82): an attempt 7 can never be stored.
ATTEMPTS_CHECK_SQL = "attempts >= 0 AND attempts <= 6"

# Created-event uniqueness: at most one income.created event per canonical
# Income identity. Deliberately NOT broadened to update/delete events.
UNIQUE_CREATED_INDEX = "uq_financial_events_income_created_aggregate_id"
UNIQUE_CREATED_PREDICATE_SQL = "event_type = 'income.created'"

# P52 head-first FIFO support: the user's unfinished events in
# (occurred_at, id) order. Terminal statuses (processed, dead) are excluded;
# the predicate does NOT filter to "claimable" rows, because the FIFO head
# must be selected among ALL unfinished non-deferred events first.
FIFO_INDEX = "ix_financial_events_user_id_occurred_at_id_unfinished"
FIFO_PREDICATE_SQL = "status IN ('pending','processing','failed_retryable')"

# Due/status index (E1 section 19.3).
DUE_INDEX = "ix_financial_events_status_not_before_next_attempt_at"


def upgrade() -> None:
    """
    Creates the financial_events outbox table (VF-020E2, expand only).

    What:
        1. Creates financial_events with typed provenance and a typed Income
           snapshot (no core eligibility data hidden in JSONB), the delivery
           and ordering fields, and the approved CHECK constraints.
        2. Creates the partial UNIQUE index for income.created, the partial
           FIFO index over unfinished statuses, and the due/status index.
        3. Revokes every privilege on the new table from the Supabase Data
           API roles (guarded by pg_roles).

    Why:
        This is a new table only: no existing table is altered, locked or
        read, no Income row is touched, and nothing is backfilled - an Income
        that exists before the E3 runtime has no creation event and is
        therefore historical and never retroactively AUTO-eligible.
        aggregate_id is a SOFT reference: there is intentionally no foreign
        key to income, so deleting an Income is never blocked by event
        provenance and income.deleted events survive the deletion. user_id is
        a plain UUID like everywhere else (no local users table).
        The application does not read or write the table until E3, so the
        previous runtime keeps working unchanged before and after this
        migration. No lock_timeout is set here on purpose: how long the
        migration may wait is an execution-time decision.
    """

    op.create_table(
        "financial_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("aggregate_type", sa.String(length=32), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("ingestion_mode", sa.String(length=16), nullable=False),
        # Typed Income snapshot; types mirror the income table.
        sa.Column("snap_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("snap_currency", sa.String(length=3), nullable=False),
        sa.Column("snap_received_at", sa.Date(), nullable=False),
        # NULL = an Income that is not linked to an Account.
        sa.Column("snap_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("snap_income_source", sa.String(length=20), nullable=False),
        sa.Column(
            "snap_aggregate_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        # Delivery and ordering. occurred_at defaults to the insert
        # transaction's now(); not_before NULL = due immediately.
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "outcome_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_financial_events"),
        sa.CheckConstraint(
            EVENT_TYPE_CHECK_SQL, name="ck_financial_events_event_type_valid",
        ),
        sa.CheckConstraint(
            ORIGIN_CHECK_SQL, name="ck_financial_events_origin_valid",
        ),
        sa.CheckConstraint(
            INGESTION_MODE_CHECK_SQL,
            name="ck_financial_events_ingestion_mode_valid",
        ),
        sa.CheckConstraint(
            STATUS_CHECK_SQL, name="ck_financial_events_status_valid",
        ),
        sa.CheckConstraint(
            ATTEMPTS_CHECK_SQL, name="ck_financial_events_attempts_valid",
        ),
    )

    op.create_index(
        UNIQUE_CREATED_INDEX,
        "financial_events",
        ["aggregate_id"],
        unique=True,
        postgresql_where=sa.text(UNIQUE_CREATED_PREDICATE_SQL),
    )
    op.create_index(
        FIFO_INDEX,
        "financial_events",
        ["user_id", "occurred_at", "id"],
        postgresql_where=sa.text(FIFO_PREDICATE_SQL),
    )
    op.create_index(
        DUE_INDEX,
        "financial_events",
        ["status", "not_before", "next_attempt_at"],
    )

    op.execute(
        f"""
        DO $$
        DECLARE
            target_role text;
        BEGIN
            FOREACH target_role IN ARRAY {DATA_API_ROLES_ARRAY_SQL}
            LOOP
                IF EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = target_role
                ) THEN
                    EXECUTE format(
                        'REVOKE ALL PRIVILEGES ON TABLE {FINANCIAL_EVENTS_TABLE_SQL} FROM %I',
                        target_role
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    """
    Removes the financial_events outbox table (VF-020E2).

    What:
        Drops the three indexes, then the table.

    Why:
        Only E2-owned objects are removed; no pre-E2 table or row is touched.
        This permanently destroys every stored event (none exist before the
        E3 runtime writes them). No privileges are re-granted: dropping the
        table drops its ACL with it, and a downgrade must never reopen Data
        API access.
    """

    op.drop_index(DUE_INDEX, table_name="financial_events")
    op.drop_index(FIFO_INDEX, table_name="financial_events")
    op.drop_index(UNIQUE_CREATED_INDEX, table_name="financial_events")
    op.drop_table("financial_events")
