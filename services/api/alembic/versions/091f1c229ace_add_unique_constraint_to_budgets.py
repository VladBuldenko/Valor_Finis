"""add unique constraint to budgets

Revision ID: 091f1c229ace
Revises: 9a09da6421ec
Create Date: 2026-07-02 08:12:30.653421

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "091f1c229ace"
down_revision: Union[str, Sequence[str], None] = "9a09da6421ec"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Adds a unique constraint to the budgets table.

    What:
        Prevents duplicate budgets for the same user, name, period, and start date.

    Why:
        Keeps budget analytics correct and prevents duplicated budget limits.
    """

    op.create_unique_constraint(
        "uq_budgets_user_id_name_period_start_date",
        "budgets",
        ["user_id", "name", "period", "start_date"],
    )

def downgrade() -> None:
    """
    Removes the unique constraint from the budgets table.

    What:
        Reverts the unique constraint added in upgrade.

    Why:
        Allows Alembic to roll back this migration safely.
    """

    op.drop_constraint(
        "uq_budgets_user_id_name_period_start_date",
        "budgets",
        type_="unique",
    )