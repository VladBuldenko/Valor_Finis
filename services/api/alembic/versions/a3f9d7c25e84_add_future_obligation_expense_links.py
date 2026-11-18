"""add future obligation expense links

Revision ID: a3f9d7c25e84
Revises: e4a8c2d91b36
Create Date: 2026-11-18 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a3f9d7c25e84'
down_revision: Union[str, Sequence[str], None] = 'e4a8c2d91b36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The new application table (VF-GOALS-PLANNING-002C2). Named explicitly, like every
# earlier table-creating migration: this migration governs the security posture
# of its own object.
LINKS_TABLE = "future_obligation_expense_links"
LINKS_TABLE_SQL = f"public.{LINKS_TABLE}"

# Supabase's Data API (PostgREST) roles - identical to VF-SEC-01. None of them
# exist on local/CI PostgreSQL, so the statement naming them is wrapped in a
# pg_roles existence check and becomes a safe no-op there.
DATA_API_ROLES_ARRAY_SQL = "ARRAY['anon', 'authenticated', 'service_role']"

OBLIGATION_OWNER_UNIQUE = "uq_future_obligations_id_user_id"
OBLIGATION_OWNER_FK = "fk_future_obligation_links_obligation_owner"
EXPENSE_OWNER_FK = "fk_future_obligation_links_expense_owner"
EXPENSE_UNIQUE = "uq_future_obligation_links_expense_id"
OCCURRENCE_UNIQUE = "uq_future_obligation_links_obligation_id_due_date"
DUE_DATE_CHECK = "ck_future_obligation_links_due_date_range"
USER_DUE_DATE_INDEX = "ix_future_obligation_links_user_id_due_date"


def _guard_downgrade_has_no_links() -> None:
    # A link is a choice the user made by hand and cannot be recreated from
    # anything else: a downgrade must never destroy links silently. The guard is a
    # no-op for a rollback before any link was made and a loud stop otherwise.
    count = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {LINKS_TABLE}")).scalar_one()

    if count:
        raise RuntimeError(
            "Refusing to downgrade: future obligation expense links exist. They are chosen by hand and must not be destroyed."
        )


def upgrade() -> None:
    """
    Creates future_obligation_expense_links (VF-GOALS-PLANNING-002C2, expand only).

    What:
        One additive table: id, user_id, obligation_id, due_date, expense_id,
        created_at. Composite foreign keys (obligation_id, user_id) ->
        future_obligations(id, user_id) and (expense_id, user_id) ->
        expenses(id, user_id), both ON DELETE RESTRICT; UNIQUE (expense_id) and
        UNIQUE (obligation_id, due_date); a due-date range CHECK; an index on
        (user_id, due_date); and the Data API REVOKE. The one change to an
        existing table is the new UNIQUE (id, user_id) on future_obligations, the
        target of the composite foreign key (expenses already has its own).

    Why:
        A link is relationship metadata ("this Expense corresponds to this
        occurrence"), not a transaction: no balance, Goal or analytics figure is
        touched and no row of Expenses or obligations is changed or backfilled.
        The composite foreign keys make a link between two users' records
        impossible whatever the application does, RESTRICT means neither a linked
        Expense nor a linked obligation can disappear silently, and the two unique
        keys mean one Expense is never counted for two occurrences and an
        occurrence never has two Expenses.
    """

    op.create_unique_constraint(OBLIGATION_OWNER_UNIQUE, "future_obligations", ["id", "user_id"])

    op.create_table(
        LINKS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("obligation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("expense_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="future_obligation_expense_links_pkey"),
        sa.ForeignKeyConstraint(
            ["obligation_id", "user_id"],
            ["future_obligations.id", "future_obligations.user_id"],
            name=OBLIGATION_OWNER_FK,
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["expense_id", "user_id"],
            ["expenses.id", "expenses.user_id"],
            name=EXPENSE_OWNER_FK,
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("expense_id", name=EXPENSE_UNIQUE),
        sa.UniqueConstraint("obligation_id", "due_date", name=OCCURRENCE_UNIQUE),
        sa.CheckConstraint(
            "due_date BETWEEN DATE '2000-01-01' AND DATE '2100-12-31'",
            name=DUE_DATE_CHECK,
        ),
    )

    op.create_index(USER_DUE_DATE_INDEX, LINKS_TABLE, ["user_id", "due_date"])

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
                        'REVOKE ALL PRIVILEGES ON TABLE {LINKS_TABLE_SQL} FROM %I',
                        target_role
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    """
    Removes the link table and the unique key added for it (VF-GOALS-PLANNING-002C2).

    What:
        Refuses to continue if any link exists, then drops the index, the table
        and the future_obligations (id, user_id) unique key.

    Why:
        Only this migration's objects are removed; every earlier table and row is
        untouched. Hand-made links are never destroyed silently. No privileges are
        re-granted: dropping the table drops its ACL with it.
    """

    op.execute(f"LOCK TABLE {LINKS_TABLE} IN ACCESS EXCLUSIVE MODE")

    _guard_downgrade_has_no_links()

    op.drop_index(USER_DUE_DATE_INDEX, table_name=LINKS_TABLE)
    op.drop_table(LINKS_TABLE)
    op.drop_constraint(OBLIGATION_OWNER_UNIQUE, "future_obligations", type_="unique")
