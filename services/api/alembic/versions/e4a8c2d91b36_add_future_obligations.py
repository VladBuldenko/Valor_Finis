"""add future obligations

Revision ID: e4a8c2d91b36
Revises: b8e2c5d1f739
Create Date: 2026-11-17 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e4a8c2d91b36'
down_revision: Union[str, Sequence[str], None] = 'b8e2c5d1f739'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The new application table (VF-GOALS-PLANNING-002C1). Named explicitly (never a
# schema-wide statement), like every earlier table-creating migration: this
# migration governs the security posture of its own object.
FUTURE_OBLIGATIONS_TABLE_SQL = "public.future_obligations"

# Supabase's Data API (PostgREST) roles - identical to VF-SEC-01. None of them
# exist on local/CI PostgreSQL, so the statement naming them is wrapped in a
# pg_roles existence check and becomes a safe no-op there.
DATA_API_ROLES_ARRAY_SQL = "ARRAY['anon', 'authenticated', 'service_role']"

# The accepted range of a due date (see future_obligation_schedule).
DUE_DATE_RANGE_SQL = "BETWEEN DATE '2000-01-01' AND DATE '2100-12-31'"

AMOUNT_CHECK = "ck_future_obligations_amount_positive"
SCHEDULE_CHECK = "ck_future_obligations_schedule_valid"
STATUS_CHECK = "ck_future_obligations_status_valid"
CURRENCY_CHECK = "ck_future_obligations_currency_format"
NAME_CHECK = "ck_future_obligations_name_not_blank"
FIRST_RANGE_CHECK = "ck_future_obligations_first_due_date_range"
FINAL_RANGE_CHECK = "ck_future_obligations_final_due_date_range"
FINAL_ORDER_CHECK = "ck_future_obligations_final_not_before_first"
ONE_TIME_CHECK = "ck_future_obligations_one_time_has_no_final"
CLIENT_REQUEST_CHECK = "ck_future_obligations_client_request_all_or_none"
CLIENT_REQUEST_UNIQUE = "uq_future_obligations_user_id_client_request_id"
USER_STATUS_INDEX = "ix_future_obligations_user_id_status"


def _guard_downgrade_has_no_obligations() -> None:
    # Future obligations are data the user typed in by hand and cannot be
    # recreated from anything else: a downgrade must never destroy them
    # silently. The guard is a no-op for a rollback before any was recorded and
    # a loud stop otherwise.
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM future_obligations")).scalar_one()

    if count:
        raise RuntimeError(
            "Refusing to downgrade: future obligations exist. They are entered by hand and must not be destroyed."
        )


def upgrade() -> None:
    """
    Creates the future_obligations table (VF-GOALS-PLANNING-002C1, expand only).

    What:
        One additive table for the user's manually entered future obligations
        (a one-time bill or a monthly one): id, user_id, name, description,
        schedule, amount, currency, first_due_date, final_due_date, status, the
        create-idempotency pair and timestamps. CHECK constraints for a
        positive amount, the schedule and status literals, a 3-letter uppercase
        currency, a non-blank name, due dates in 2000-2100, a final due date not
        before the first, and no final due date on a one-time obligation; a
        UNIQUE (user_id, client_request_id) with its all-or-none CHECK; one
        index on (user_id, status); and the Data API REVOKE.

    Why:
        An obligation is a forecast input the user typed in, not a transaction:
        it has no foreign key to Expenses, Accounts, Goals or Budgets, because
        nothing may be inferred from or posted to them. The database enforces
        the shapes the API already validates, so no write path can store an
        invalid schedule. Existing tables and rows are untouched; no data is
        read or backfilled.
    """

    op.create_table(
        "future_obligations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("schedule", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("first_due_date", sa.Date(), nullable=False),
        sa.Column("final_due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="active", nullable=False),
        sa.Column("client_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="future_obligations_pkey"),
        sa.CheckConstraint("amount > 0", name=AMOUNT_CHECK),
        sa.CheckConstraint("schedule IN ('one_time','monthly')", name=SCHEDULE_CHECK),
        sa.CheckConstraint("status IN ('active','archived')", name=STATUS_CHECK),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=CURRENCY_CHECK),
        sa.CheckConstraint("length(btrim(name)) > 0", name=NAME_CHECK),
        sa.CheckConstraint(f"first_due_date {DUE_DATE_RANGE_SQL}", name=FIRST_RANGE_CHECK),
        sa.CheckConstraint(
            f"final_due_date IS NULL OR final_due_date {DUE_DATE_RANGE_SQL}", name=FINAL_RANGE_CHECK
        ),
        sa.CheckConstraint(
            "final_due_date IS NULL OR final_due_date >= first_due_date", name=FINAL_ORDER_CHECK
        ),
        sa.CheckConstraint("schedule <> 'one_time' OR final_due_date IS NULL", name=ONE_TIME_CHECK),
        sa.CheckConstraint(
            "(client_request_id IS NULL) = (client_request_fingerprint IS NULL)",
            name=CLIENT_REQUEST_CHECK,
        ),
        sa.UniqueConstraint("user_id", "client_request_id", name=CLIENT_REQUEST_UNIQUE),
    )

    op.create_index(USER_STATUS_INDEX, "future_obligations", ["user_id", "status"])

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
                        'REVOKE ALL PRIVILEGES ON TABLE {FUTURE_OBLIGATIONS_TABLE_SQL} FROM %I',
                        target_role
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    """
    Removes the future_obligations table (VF-GOALS-PLANNING-002C1).

    What:
        Refuses to continue if any obligation exists, then drops the index and
        the table.

    Why:
        Only this migration's object is removed; every earlier table and row is
        untouched. Hand-entered data is never destroyed silently. No privileges
        are re-granted: dropping the table drops its ACL with it, and a
        downgrade must never reopen Data API access.
    """

    op.execute("LOCK TABLE future_obligations IN ACCESS EXCLUSIVE MODE")

    _guard_downgrade_has_no_obligations()

    op.drop_index(USER_STATUS_INDEX, table_name="future_obligations")
    op.drop_table("future_obligations")
