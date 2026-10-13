"""expand goal priority rank

Revision ID: 4d2f7b91a6c3
Revises: 98acdc7016d2
Create Date: 2026-10-13 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4d2f7b91a6c3'
down_revision: Union[str, Sequence[str], None] = '98acdc7016d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Table lock taken before any DDL or the backfill, in BOTH directions: goals
# is the only table involved (no foreign key is added), ADD/DROP COLUMN needs
# ACCESS EXCLUSIVE anyway, and holding it for the whole transaction keeps the
# backfill consistent - a concurrent insert from the current runtime waits
# and then commits a NULL rank, which this revision permits (see upgrade()).
# No lock_timeout is set here on purpose: how long the migration may wait is
# an execution-time decision (the operator sets lock_timeout for the
# migration transaction before running it).
LOCK_SQL = "LOCK TABLE goals IN ACCESS EXCLUSIVE MODE"

PRIORITY_RANK_CHECK_NAME = "ck_goals_priority_rank_positive"
PRIORITY_RANK_CHECK_SQL = "priority_rank IS NULL OR priority_rank >= 1"
PRIORITY_RANK_UNIQUE_NAME = "uq_goals_user_id_priority_rank"

# Backfill: only existing non-archived Goals are ranked, per user, newest
# first; equal created_at values are ordered by id ASC so the result is
# deterministic. Archived Goals keep NULL. Only goals.priority_rank is
# written - no ledger or other row is touched.
BACKFILL_SQL = """
UPDATE goals AS g
SET priority_rank = ranked.rank
FROM (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY user_id
            ORDER BY created_at DESC, id ASC
        ) AS rank
    FROM goals
    WHERE status IN ('active', 'completed')
) AS ranked
WHERE g.id = ranked.id
"""


def upgrade() -> None:
    """
    Adds the Goal priority rank foundation (VF-020D2, schema expand step).

    What:
        0. Locks goals (ACCESS EXCLUSIVE, LOCK_SQL).
        1. Adds goals.priority_rank INTEGER NULL - no default.
        2. Adds CHECK ck_goals_priority_rank_positive:
           priority_rank IS NULL OR priority_rank >= 1.
        3. Backfills the rank of existing active and completed Goals per
           user by created_at DESC, id ASC (BACKFILL_SQL); archived Goals
           stay NULL.
        4. Adds the UNIQUE CONSTRAINT uq_goals_user_id_priority_rank on
           (user_id, priority_rank), DEFERRABLE INITIALLY DEFERRED. It is a
           constraint, not a partial index; NULL ranks are distinct, so any
           number of archived Goals may have no rank.

    Why:
        Priorities are the ordering foundation for later Goal rules. The
        unique constraint is a database backstop; correctness comes from
        the application's user lock and locked rewrite (VF-020D3). Because
        it is deferred, a reorder may swap ranks inside one transaction.

        This revision is additive and the application is unaware of it: the
        ORM does not map priority_rank until VF-020D3. The lifecycle check
        (status = 'archived') = (priority_rank IS NULL) is deliberately NOT
        added here (it is VF-020D5): between this migration and the D3
        deployment the current runtime keeps creating non-archived Goals
        with a NULL rank, which this schema must accept.

        Atomicity: Alembic runs the whole upgrade in one transaction
        (transactional DDL); any failure leaves the schema untouched.
    """

    op.execute(LOCK_SQL)

    op.add_column(
        "goals",
        sa.Column("priority_rank", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        PRIORITY_RANK_CHECK_NAME,
        "goals",
        PRIORITY_RANK_CHECK_SQL,
    )
    op.execute(BACKFILL_SQL)
    op.create_unique_constraint(
        PRIORITY_RANK_UNIQUE_NAME,
        "goals",
        ["user_id", "priority_rank"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    """
    Reverts VF-020D2 to the VF-020C1 schema.

    What:
        Locks goals, then drops the unique constraint, the positive CHECK
        and finally the priority_rank column.

    Why:
        This is a SCHEMA reversal only. Dropping the column discards every
        rank value (the Goal rows themselves are untouched); no attempt is
        made to reconstruct the pre-backfill order because none is stored.
        Do not downgrade after the D3 runtime has started maintaining
        ranks without a separate decision.
    """

    op.execute(LOCK_SQL)

    op.drop_constraint(
        PRIORITY_RANK_UNIQUE_NAME,
        "goals",
        type_="unique",
    )
    op.drop_constraint(
        PRIORITY_RANK_CHECK_NAME,
        "goals",
        type_="check",
    )
    op.drop_column("goals", "priority_rank")
