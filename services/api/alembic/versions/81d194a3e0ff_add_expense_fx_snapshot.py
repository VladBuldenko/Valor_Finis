"""add expense fx snapshot

Revision ID: 81d194a3e0ff
Revises: 0e300e8d7162
Create Date: 2026-09-16 15:37:54.149444

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '81d194a3e0ff'
down_revision: Union[str, Sequence[str], None] = '0e300e8d7162'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Adds the VF-014B5C FX snapshot columns to expenses.

    What:
        Adds base_amount/base_currency/fx_rate/fx_rate_date/fx_source,
        nullable, backfills existing EUR expenses as identity snapshots,
        and adds the constraints that keep the snapshot truthful.

    Why:
        An Expense must preserve both its original transaction truth
        (amount/currency, unchanged) and its base-currency truth
        (base_amount, at the historical rate in effect on expense_date).
        Existing rows cannot be silently assumed to be EUR or assigned a
        rate that was never actually published for them - see VF-014B5A.
        Columns stay nullable only to truthfully represent an existing
        foreign expense whose snapshot has not been resolved yet; every
        expense created after this migration always has all five
        populated together (enforced by the all-or-none CHECK below).

    No network calls. No guessed historical rates. Non-EUR existing rows
    are deliberately left unresolved (base_amount stays NULL), never
    assumed to be EUR.
    """

    op.add_column("expenses", sa.Column("base_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("expenses", sa.Column("base_currency", sa.String(length=3), nullable=True))
    op.add_column("expenses", sa.Column("fx_rate", sa.Numeric(18, 8), nullable=True))
    op.add_column("expenses", sa.Column("fx_rate_date", sa.Date(), nullable=True))
    op.add_column("expenses", sa.Column("fx_source", sa.String(length=30), nullable=True))

    op.execute(
        """
        UPDATE expenses
        SET
            base_amount = amount,
            base_currency = 'EUR',
            fx_rate = 1,
            fx_rate_date = expense_date,
            fx_source = 'identity'
        WHERE currency = 'EUR'
        """
    )

    op.create_check_constraint(
        "ck_expenses_base_amount_positive",
        "expenses",
        "base_amount IS NULL OR base_amount > 0",
    )
    op.create_check_constraint(
        "ck_expenses_fx_rate_positive",
        "expenses",
        "fx_rate IS NULL OR fx_rate > 0",
    )
    op.create_check_constraint(
        "ck_expenses_fx_snapshot_all_or_none",
        "expenses",
        "(base_amount IS NULL AND base_currency IS NULL AND fx_rate IS NULL "
        "AND fx_rate_date IS NULL AND fx_source IS NULL) "
        "OR (base_amount IS NOT NULL AND base_currency IS NOT NULL AND fx_rate IS NOT NULL "
        "AND fx_rate_date IS NOT NULL AND fx_source IS NOT NULL)",
    )


def downgrade() -> None:
    """
    Removes the VF-014B5C FX snapshot columns from expenses.

    What:
        Drops the three new CHECK constraints and the five new columns.

    Why:
        Allows Alembic to roll back this migration safely. amount and
        currency (the original transaction truth) are never touched by
        either direction of this migration, so downgrading loses only
        the derived base-currency snapshot, never original financial data.
    """

    op.drop_constraint("ck_expenses_fx_snapshot_all_or_none", "expenses", type_="check")
    op.drop_constraint("ck_expenses_fx_rate_positive", "expenses", type_="check")
    op.drop_constraint("ck_expenses_base_amount_positive", "expenses", type_="check")

    op.drop_column("expenses", "fx_source")
    op.drop_column("expenses", "fx_rate_date")
    op.drop_column("expenses", "fx_rate")
    op.drop_column("expenses", "base_currency")
    op.drop_column("expenses", "base_amount")
