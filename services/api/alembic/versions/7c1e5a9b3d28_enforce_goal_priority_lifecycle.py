"""enforce goal priority lifecycle

Revision ID: 7c1e5a9b3d28
Revises: 4d2f7b91a6c3
Create Date: 2026-10-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '7c1e5a9b3d28'
down_revision: Union[str, Sequence[str], None] = '4d2f7b91a6c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Table lock taken before the normalization and the constraint, in BOTH
# directions (the D2 pattern): goals is the only table involved, ADD/DROP
# CONSTRAINT needs a strong lock anyway, and holding ACCESS EXCLUSIVE for the
# whole transaction keeps the normalization consistent - a concurrent insert
# from a runtime that does not rank new Goals waits and would then be
# rejected by the new constraint, never slipped past it. No lock_timeout is
# set here on purpose: how long the migration may wait is an execution-time
# decision (the operator sets lock_timeout for the migration transaction).
LOCK_SQL = "LOCK TABLE goals IN ACCESS EXCLUSIVE MODE"

LIFECYCLE_CHECK_NAME = "ck_goals_priority_rank_lifecycle"
LIFECYCLE_CHECK_SQL = "(status = 'archived') = (priority_rank IS NULL)"

# Normalization of rollout stragglers: non-archived Goals whose priority_rank
# is still NULL (created between the D2 migration and the D3 runtime).
# Per user, they are appended AFTER that user's current maximum non-NULL rank,
# ordered by created_at ASC, id ASC, so existing ranks and gaps are never
# touched (existing 1, 3 + three stragglers -> 4, 5, 6). Only
# goals.priority_rank of those rows is written. Archived Goals are not
# selected; an archived Goal with a non-NULL rank (not expected) is left
# alone and will make the CHECK below fail loudly instead of being hidden.
NORMALIZE_STRAGGLERS_SQL = """
WITH user_max AS (
    SELECT user_id, COALESCE(MAX(priority_rank), 0) AS max_rank
    FROM goals
    GROUP BY user_id
),
stragglers AS (
    SELECT
        g.id,
        user_max.max_rank + row_number() OVER (
            PARTITION BY g.user_id
            ORDER BY g.created_at ASC, g.id ASC
        ) AS new_rank
    FROM goals AS g
    JOIN user_max ON user_max.user_id = g.user_id
    WHERE g.status IN ('active', 'completed')
      AND g.priority_rank IS NULL
)
UPDATE goals AS target
SET priority_rank = stragglers.new_rank
FROM stragglers
WHERE target.id = stragglers.id
"""


def upgrade() -> None:
    """
    Enforces the Goal priority lifecycle (VF-020D5, contract step).

    What:
        0. Locks goals (ACCESS EXCLUSIVE, LOCK_SQL).
        1. Ranks every non-archived Goal that still has a NULL
           priority_rank (NORMALIZE_STRAGGLERS_SQL).
        2. Adds CHECK ck_goals_priority_rank_lifecycle:
           (status = 'archived') = (priority_rank IS NULL) - archived Goals
           have no rank, active and completed Goals always have one.

    Why:
        The D2 expand migration deliberately allowed NULL ranks for
        non-archived Goals so the runtime that predates priorities could
        keep creating Goals. From VF-020D3 the runtime always ranks
        non-archived Goals, so the invariant can now be enforced by the
        database. The existing D2 objects (the nullable INTEGER column,
        ck_goals_priority_rank_positive and the deferrable unique
        uq_goals_user_id_priority_rank) are unchanged.

        Production note: this must be applied only after the D3 runtime is
        deployed, otherwise an old runtime creating a non-archived Goal with
        a NULL rank would be rejected.

        Atomicity: Alembic runs the whole upgrade in one transaction; if
        the CHECK finds unexpected data (for example an archived Goal with
        a rank) the migration fails and nothing is changed.
    """

    op.execute(LOCK_SQL)
    op.execute(NORMALIZE_STRAGGLERS_SQL)
    op.create_check_constraint(
        LIFECYCLE_CHECK_NAME,
        "goals",
        LIFECYCLE_CHECK_SQL,
    )


def downgrade() -> None:
    """
    Reverts VF-020D5 to the VF-020D2 constraint set.

    What:
        Locks goals and drops ONLY the lifecycle CHECK.

    Why:
        Which ranks were normalized stragglers is no longer knowable, so
        they are not reconstructed: the normalized ranks stay. The D2
        column, positive CHECK and deferrable unique are not touched.
    """

    op.execute(LOCK_SQL)
    op.drop_constraint(
        LIFECYCLE_CHECK_NAME,
        "goals",
        type_="check",
    )
