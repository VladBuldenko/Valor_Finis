"""expand goal ledger integrity

Revision ID: 1e921a4a4412
Revises: 1edb74dc96d8
Create Date: 2026-10-05 15:15:42.724249

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1e921a4a4412'
down_revision: Union[str, Sequence[str], None] = '1edb74dc96d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


GOAL_STATUS_VALID_SQL = "status IN ('active','completed','archived')"

# Explicit table locks taken before any schema change, goals FIRST and
# goal_transactions SECOND - the same order every application path uses
# (it reads/locks a goal, then its transactions). Without them, the first
# ALTER TABLE would lock goal_transactions and the later goals DDL would
# then wait for goals, while an application request holding goals could be
# waiting for goal_transactions: a lock-order cycle that PostgreSQL would
# break by aborting one side. Two separate statements make the order
# explicit. No lock_timeout is set here on purpose: how long the migration
# may wait is an execution-time decision (the operator can set
# lock_timeout for the session before running the upgrade).
LOCK_GOAL_TABLES_SQL = (
    "LOCK TABLE goals IN ACCESS EXCLUSIVE MODE",
    "LOCK TABLE goal_transactions IN ACCESS EXCLUSIVE MODE",
)

# Exactly three ASCII uppercase letters. PostgreSQL regex bracket ranges
# are evaluated by character code, so [A-Z] never matches non-ASCII
# letters such as "É" or "ı"; tests/integration/goals/
# test_goal_ledger_expand_migration.py proves this against the real server.
GOAL_CURRENCY_FORMAT_SQL = "currency ~ '^[A-Z]{3}$'"

# Copies each goal transaction's currency from its owning goal. Only rows
# whose currency is still NULL are touched, so re-running it never changes
# an already filled row. Kept as a module constant so the migration test
# executes exactly this statement.
BACKFILL_GOAL_TRANSACTION_CURRENCY_SQL = """
UPDATE goal_transactions AS gt
SET currency = g.currency
FROM goals AS g
WHERE gt.goal_id = g.id
  AND gt.currency IS NULL
"""


def upgrade() -> None:
    """
    Expands the goal ledger schema for VF-020B (expand step, VF-020B2).

    What:
        0. Locks goals, then goal_transactions (LOCK_GOAL_TABLES_SQL), so
           the migration acquires the tables in the application's order.
        1. Adds three NULLABLE columns to goal_transactions, with no server
           defaults: currency VARCHAR(3), effective_date DATE and
           client_request_id UUID.
        2. Backfills goal_transactions.currency from the owning goal's
           currency for every existing row. effective_date and
           client_request_id stay NULL for all existing rows.
        3. Adds uq_goals_id_user_id - the target of the composite
           ownership foreign key below.
        4. Adds ck_goals_status_valid (active/completed/archived) and
           ck_goals_currency_format (exactly three ASCII uppercase
           letters).
        5. Adds fk_goal_transactions_goal_id_user_id:
           (goal_id, user_id) -> goals(id, user_id) ON DELETE RESTRICT, so
           a goal transaction can never belong to a different user than its
           goal at the database level. The existing single-column
           goal_id -> goals.id foreign key is kept as additional defense.
        6. Adds uq_goal_transactions_user_id_client_request_id. PostgreSQL
           treats NULLs as distinct in a UNIQUE constraint, so any number of
           rows without a key are allowed, while a non-null key is unique
           per user.

    Why:
        This is the backward-compatible expand step of the VF-020B
        expand/contract rollout. The application deployed at this point
        (VF-020B1) neither reads nor writes the new columns: SQLAlchemy only
        selects mapped columns, and the new columns are nullable without
        defaults, so goal transactions it creates simply get NULL in all
        three. The ORM mapping, the write path for currency, effective_date
        and client_request_id arrive in VF-020B3; currency becomes NOT NULL
        in VF-020B4, which first fills the NULLs created in between.

        The currency backfill is deterministic: a goal transaction's amount
        has always been expressed in its goal's currency, and a goal's
        currency cannot change once it has transaction history (VF-016E).
        effective_date is deliberately NOT backfilled from created_at -
        the recording time is not a proven business date (VF-020A P13).

        Invalid existing data (a goal currency or status outside the new
        rules, or a goal transaction whose owner differs from its goal's)
        is never rewritten here: the new constraints fail instead, and the
        VF-020B2 production preflight is expected to catch such data
        before this migration runs in production.

        Locking: Alembic runs the whole upgrade inside one transaction
        (transactional DDL), so every lock taken below is held until the
        final commit; the constraints are validated immediately, and the
        whole change is atomic - it applies completely or not at all.
        NOT VALID + VALIDATE CONSTRAINT would not shorten lock holding
        inside that single transaction. Both tables are locked up front in
        the application's order (step 0), so the migration cannot form a
        lock-order cycle with live goal traffic; it may instead wait for
        in-flight requests to finish. Whether the lock duration and any
        lock_timeout are acceptable is decided from the production
        preflight row counts before this migration is applied to
        production.

        No new table is created, so no Supabase Data API privilege change
        is needed: the new columns inherit the privileges already revoked
        on goals and goal_transactions (VF-SEC-01).
    """

    for lock_statement in LOCK_GOAL_TABLES_SQL:
        op.execute(lock_statement)

    op.add_column(
        "goal_transactions",
        sa.Column("currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "goal_transactions",
        sa.Column("effective_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "goal_transactions",
        sa.Column("client_request_id", sa.UUID(), nullable=True),
    )

    op.execute(BACKFILL_GOAL_TRANSACTION_CURRENCY_SQL)

    op.create_unique_constraint(
        "uq_goals_id_user_id",
        "goals",
        ["id", "user_id"],
    )
    op.create_check_constraint(
        "ck_goals_status_valid",
        "goals",
        GOAL_STATUS_VALID_SQL,
    )
    op.create_check_constraint(
        "ck_goals_currency_format",
        "goals",
        GOAL_CURRENCY_FORMAT_SQL,
    )
    op.create_foreign_key(
        "fk_goal_transactions_goal_id_user_id",
        "goal_transactions",
        "goals",
        ["goal_id", "user_id"],
        ["id", "user_id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_goal_transactions_user_id_client_request_id",
        "goal_transactions",
        ["user_id", "client_request_id"],
    )


def downgrade() -> None:
    """
    Reverts VF-020B2 to the exact pre-expand schema.

    What:
        Locks goals, then goal_transactions (same order and reason as in
        upgrade), then drops, in dependency order, the client_request_id
        uniqueness, the composite ownership foreign key, the two goals CHECK
        constraints, uq_goals_id_user_id (only after the foreign key that
        references it), and finally the three added goal_transactions
        columns. Every
        pre-existing constraint - including the single-column
        goal_id -> goals.id foreign key - is left untouched.

    Why:
        Downgrading drops the values held in the three columns. At the
        VF-020B2 stage that is acceptable: currency is derivable from the
        owning goal, and no application code reads or writes any of the
        three columns yet. Once VF-020B3 is deployed, downgrading this
        revision would discard recorded effective dates and idempotency
        keys, so it must then be weighed separately.
    """

    for lock_statement in LOCK_GOAL_TABLES_SQL:
        op.execute(lock_statement)

    op.drop_constraint(
        "uq_goal_transactions_user_id_client_request_id",
        "goal_transactions",
        type_="unique",
    )
    op.drop_constraint(
        "fk_goal_transactions_goal_id_user_id",
        "goal_transactions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_goals_currency_format",
        "goals",
        type_="check",
    )
    op.drop_constraint(
        "ck_goals_status_valid",
        "goals",
        type_="check",
    )
    op.drop_constraint(
        "uq_goals_id_user_id",
        "goals",
        type_="unique",
    )
    op.drop_column("goal_transactions", "client_request_id")
    op.drop_column("goal_transactions", "effective_date")
    op.drop_column("goal_transactions", "currency")
