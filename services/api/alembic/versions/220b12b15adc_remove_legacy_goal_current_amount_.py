"""remove legacy goal current_amount storage

Revision ID: 220b12b15adc
Revises: e90a257f987b
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '220b12b15adc'
down_revision: Union[str, Sequence[str], None] = 'e90a257f987b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Removes the legacy transitional goals.current_amount column.

    What:
        Drops ck_goals_current_amount_non_negative, then drops
        goals.current_amount.

    Why:
        goal_transactions has been the authoritative balance ledger since
        VF-016B (backfilled losslessly at that time), and every public
        Goal/GoalProgress read has been ledger-derived since VF-016D
        (goal_service.py, analytics_service.py). Since then this column has
        been dead transitional storage, kept only for rollback safety
        during the VF-016 migration. This slice removes it entirely - a
        Goal's balance now exists only as SUM(opening_balance +
        contribution - withdrawal) over its goal_transactions rows,
        computed at read time.

    No ledger data is touched by this migration in either direction:
    goal_transactions rows are never read, inserted, updated, or deleted
    here. This is schema cleanup only.
    """

    op.drop_constraint(
        "ck_goals_current_amount_non_negative",
        "goals",
        type_="check",
    )
    op.drop_column("goals", "current_amount")


def downgrade() -> None:
    """
    Re-adds goals.current_amount, reconstructed from the ledger.

    What:
        Adds back current_amount (NUMERIC(12,2) NOT NULL, matching the
        original column's server default of 0) and
        ck_goals_current_amount_non_negative, then reconstructs every
        Goal's value from its goal_transactions history.

    Why:
        A rollback to the application version this migration precedes
        expects goals.current_amount to exist and to be a truthful
        balance, not an arbitrary default. There is no old value to
        restore - the column was dropped by upgrade() and that data no
        longer exists anywhere - so the ledger (the same data upgrade()
        already trusted) is the only correct source to reconstruct it
        from.

    A Goal with no goal_transactions rows keeps the newly added column's
    own 0 default (added via ADD COLUMN ... DEFAULT, which PostgreSQL
    applies to every existing row automatically). Every other Goal's value
    is overwritten by the UPDATE below, computed entirely in PostgreSQL
    NUMERIC arithmetic (opening_balance/contribution positive, withdrawal
    negative, summed and grouped by goal_id) - never Python float - so the
    reconstructed value matches the ledger exactly.
    """

    op.add_column(
        "goals",
        sa.Column(
            "current_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
    )

    op.execute(
        """
        UPDATE goals
        SET current_amount = ledger.balance
        FROM (
            SELECT
                goal_id,
                SUM(
                    CASE
                        WHEN type = 'withdrawal' THEN -amount
                        ELSE amount
                    END
                ) AS balance
            FROM goal_transactions
            GROUP BY goal_id
        ) AS ledger
        WHERE goals.id = ledger.goal_id
        """
    )

    op.create_check_constraint(
        "ck_goals_current_amount_non_negative",
        "goals",
        "current_amount >= 0",
    )
