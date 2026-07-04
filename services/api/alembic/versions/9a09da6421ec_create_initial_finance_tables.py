"""add unique constraint to budgets

Revision ID: 091f1c229ace
Revises: 9a09da6421ec
Create Date: 2026-07-02 08:12:30.653421

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "9a09da6421ec"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Applies the database change.

    What:
        Adds a unique constraint to the budgets table.

    Why:
        Prevents one user from creating the same budget
        for the same period and start date more than once.
    """

    op.create_unique_constraint(
        "uq_budgets_user_id_name_period_start_date",
        "budgets",
        ["user_id", "name", "period", "start_date"],
    )


def downgrade() -> None:
    """
    Reverts the database change.

    What:
        Removes the unique constraint from the budgets table.

    Why:
        Allows Alembic to safely roll back this migration if needed.
    """

    op.drop_constraint(
        "uq_budgets_user_id_name_period_start_date",
        "budgets",
        type_="unique",
    )