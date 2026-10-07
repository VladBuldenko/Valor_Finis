"""contract goal transaction currency

Revision ID: 8799b7fd923d
Revises: 1e921a4a4412
Create Date: 2026-10-07 10:31:29.946561

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8799b7fd923d'
down_revision: Union[str, Sequence[str], None] = '1e921a4a4412'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Explicit table locks taken before any schema change, goals FIRST and
# goal_transactions SECOND - the same order as the VF-020B2 migration and
# every application path (it reads/locks a goal, then its transactions), so
# this migration can never form a lock-order cycle with live goal traffic.
# No lock_timeout is set here on purpose: how long the migration may wait
# is an execution-time decision (the operator can set lock_timeout for the
# session before running the upgrade).
LOCK_GOAL_TABLES_SQL = (
    "LOCK TABLE goals IN ACCESS EXCLUSIVE MODE",
    "LOCK TABLE goal_transactions IN ACCESS EXCLUSIVE MODE",
)

# Fills ONLY rows whose currency is still NULL (history written before
# VF-020B3, and the VF-020B2 -> VF-020B3 deployment window) with the owning
# goal's currency. A row that already has a currency is never touched, so a
# wrong currency can never be silently "repaired" here - it is caught by the
# mismatch gate below instead.
BACKFILL_NULL_CURRENCY_SQL = """
UPDATE goal_transactions AS gt
SET currency = g.currency
FROM goals AS g
WHERE gt.goal_id = g.id
  AND gt.currency IS NULL
"""

# Gate 1: after the backfill no NULL currency may remain. A leftover NULL
# means the row has no owning goal, which the foreign keys make impossible
# - so it signals a broken database and must stop the migration.
COUNT_NULL_CURRENCY_SQL = """
SELECT count(*) FROM goal_transactions WHERE currency IS NULL
"""

# Gate 2: no transaction may carry a currency different from its goal's.
COUNT_CURRENCY_MISMATCH_SQL = """
SELECT count(*)
FROM goal_transactions AS gt
JOIN goals AS g ON g.id = gt.goal_id
WHERE gt.currency IS DISTINCT FROM g.currency
"""


def _count(sql: str) -> int:
    return op.get_bind().execute(sa.text(sql)).scalar_one()


def upgrade() -> None:
    """
    Closes the goal transaction currency contract (VF-020B4, contract step).

    What:
        0. Locks goals, then goal_transactions (LOCK_GOAL_TABLES_SQL).
        1. Backfills goal_transactions.currency from the owning goal for
           every row where it is still NULL - and only those rows.
        2. Gate: fails if any NULL currency remains.
        3. Gate: fails if any non-NULL transaction currency differs from
           its goal's currency. Such rows are never rewritten.
        4. Adds uq_goals_id_user_id_currency UNIQUE (id, user_id,
           currency) - the target of the final foreign key. The B2
           uq_goals_id_user_id stays.
        5. Sets goal_transactions.currency NOT NULL (no default).
        6. Adds fk_goal_transactions_goal_id_user_id_currency:
           (goal_id, user_id, currency) -> goals(id, user_id, currency)
           ON DELETE RESTRICT, so the database binds every transaction to
           a goal with the same identity, owner and currency. The original
           goal_id foreign key and the B2 (goal_id, user_id) ownership
           foreign key stay as layered defenses.

    Why:
        VF-020B2 added currency as nullable and VF-020B3 made the
        application write it for every new transaction. This is the final
        step of that expand/contract rollout: no transaction can exist
        without a currency, and no transaction can disagree with its
        goal's currency. A goal's currency cannot change once it has
        history (VF-016E), so the equality can never be invalidated later.

        effective_date and client_request_id deliberately stay nullable:
        older history has no business date, and the idempotency key is
        still optional for older clients.

        Order: the NOT NULL change comes after both gates and before the
        foreign key, because a foreign key on a column that can still be
        NULL would not constrain those rows (MATCH SIMPLE).

        Atomicity: Alembic runs the whole upgrade in one transaction
        (transactional DDL). A failed gate raises, and nothing - including
        the backfill - is committed. Invalid data is never rewritten here;
        the VF-020B4 production preflight is expected to catch it first.

        No new table is created, so no Supabase Data API privilege change
        is needed.
    """

    for lock_statement in LOCK_GOAL_TABLES_SQL:
        op.execute(lock_statement)

    op.execute(BACKFILL_NULL_CURRENCY_SQL)

    remaining_nulls = _count(COUNT_NULL_CURRENCY_SQL)

    if remaining_nulls:
        raise RuntimeError(
            "VF-020B4 aborted: %d goal transaction(s) still have a NULL "
            "currency after the backfill (no owning goal)." % remaining_nulls
        )

    mismatches = _count(COUNT_CURRENCY_MISMATCH_SQL)

    if mismatches:
        raise RuntimeError(
            "VF-020B4 aborted: %d goal transaction(s) have a currency that "
            "differs from their goal's currency. Rows are never rewritten "
            "by this migration; repair them explicitly first." % mismatches
        )

    op.create_unique_constraint(
        "uq_goals_id_user_id_currency",
        "goals",
        ["id", "user_id", "currency"],
    )
    op.alter_column(
        "goal_transactions",
        "currency",
        existing_type=sa.String(length=3),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_goal_transactions_goal_id_user_id_currency",
        "goal_transactions",
        "goals",
        ["goal_id", "user_id", "currency"],
        ["id", "user_id", "currency"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """
    Reverts the VF-020B4 schema contract to the VF-020B2/B3 shape.

    What:
        Locks goals, then goal_transactions (same order and reason as in
        upgrade), then drops the final three-column foreign key, makes
        goal_transactions.currency nullable again, and finally drops
        uq_goals_id_user_id_currency (only after the foreign key that
        references it). Every earlier constraint - the goal_id foreign
        key, the B2 ownership foreign key, uq_goals_id_user_id and the
        idempotency unique constraint - is left untouched.

    Why:
        This is a schema reversal, not a data reversal. Transaction
        currency values are kept as they are: which rows were NULL before
        the upgrade's backfill cannot be reconstructed, so they are not set
        back to NULL.
    """

    for lock_statement in LOCK_GOAL_TABLES_SQL:
        op.execute(lock_statement)

    op.drop_constraint(
        "fk_goal_transactions_goal_id_user_id_currency",
        "goal_transactions",
        type_="foreignkey",
    )
    op.alter_column(
        "goal_transactions",
        "currency",
        existing_type=sa.String(length=3),
        nullable=True,
    )
    op.drop_constraint(
        "uq_goals_id_user_id_currency",
        "goals",
        type_="unique",
    )
