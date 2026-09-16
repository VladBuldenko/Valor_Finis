"""add user financial settings

Revision ID: 0e300e8d7162
Revises: a2b04a1d35d4
Create Date: 2026-09-16 14:43:45.865343

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0e300e8d7162'
down_revision: Union[str, Sequence[str], None] = 'a2b04a1d35d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Creates the user_financial_settings table.

    What:
        One row per user, holding the single authoritative financial-
        domain base currency for that user (VF-014B5B). user_id is the
        primary key directly - this is an inherent one-to-one, user-owned
        settings row, so a surrogate id column would add nothing.

    Why:
        VF-014B5's Expense FX conversion (a later slice) needs one place
        to resolve "what currency does this user's normalized data live
        in." Supabase auth metadata is not the financial-domain source of
        truth for this, so this is a local table instead.

    Deliberately does not backfill from budgets/expenses/goals/categories:
    there is no authoritative local users table, so "every user_id that
    appears somewhere" is not the same thing as "every real user," and
    guessing would risk creating settings rows for stale/test data instead
    of real accounts. Rows are created lazily, on first access, by
    financial_settings_repository.get_or_create_financial_settings -
    exactly the same race-safe bootstrap pattern already used for default
    categories.
    """

    op.create_table(
        "user_financial_settings",
        sa.Column(
            "user_id",
            sa.UUID(),
            primary_key=True,
        ),
        sa.Column(
            "base_currency",
            sa.String(length=3),
            server_default="EUR",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """
    Drops the user_financial_settings table.

    What:
        Reverts the table created in upgrade.

    Why:
        Allows Alembic to roll back this migration safely. Data loss on
        downgrade is expected for a newly created table.
    """

    op.drop_table("user_financial_settings")
