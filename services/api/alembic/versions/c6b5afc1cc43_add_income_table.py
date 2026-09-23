"""add income table

Revision ID: c6b5afc1cc43
Revises: 3d7bb3d11671
Create Date: 2026-09-23 15:29:45.714675

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6b5afc1cc43'
down_revision: Union[str, Sequence[str], None] = '3d7bb3d11671'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Creates income (VF-017C).

    What:
        Creates income: id, user_id, amount, currency, received_at,
        source (CHECK salary/freelance/refund/gift/other), description,
        plus the same five-column FX snapshot Expense uses (base_amount,
        base_currency, fx_rate, fx_rate_date, fx_source, all-or-none
        CHECK), created_at, updated_at. Indexes on user_id and
        received_at, following the expenses table's exact index
        conventions.

    Why:
        Income is a standalone financial domain representing money the
        user received, reusing the existing FX architecture (app.modules.fx,
        financial_settings) exactly as Expense already established in
        81d194a3e0ff/0e300e8d7162, rather than a new FX implementation.
        There is deliberately no account_id column: linking Income to an
        Account, and having that link actually affect Account balance, is
        VF-017D's job, not this one.

    No production/backfill logic is needed here: income is a brand-new
    table with no pre-existing data to migrate.
    """

    op.create_table(
        "income",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "amount",
            sa.Numeric(12, 2),
            nullable=False,
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default="EUR",
            nullable=False,
        ),
        sa.Column(
            "received_at",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.String(length=500),
            nullable=True,
        ),
        sa.Column(
            "base_amount",
            sa.Numeric(12, 2),
            nullable=True,
        ),
        sa.Column(
            "base_currency",
            sa.String(length=3),
            nullable=True,
        ),
        sa.Column(
            "fx_rate",
            sa.Numeric(18, 8),
            nullable=True,
        ),
        sa.Column(
            "fx_rate_date",
            sa.Date(),
            nullable=True,
        ),
        sa.Column(
            "fx_source",
            sa.String(length=30),
            nullable=True,
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
        sa.CheckConstraint(
            "amount > 0",
            name="ck_income_amount_positive",
        ),
        sa.CheckConstraint(
            "source IN ('salary','freelance','refund','gift','other')",
            name="ck_income_source_valid",
        ),
        sa.CheckConstraint(
            "base_amount IS NULL OR base_amount > 0",
            name="ck_income_base_amount_positive",
        ),
        sa.CheckConstraint(
            "fx_rate IS NULL OR fx_rate > 0",
            name="ck_income_fx_rate_positive",
        ),
        sa.CheckConstraint(
            "(base_amount IS NULL AND base_currency IS NULL AND fx_rate IS NULL "
            "AND fx_rate_date IS NULL AND fx_source IS NULL) "
            "OR (base_amount IS NOT NULL AND base_currency IS NOT NULL AND fx_rate IS NOT NULL "
            "AND fx_rate_date IS NOT NULL AND fx_source IS NOT NULL)",
            name="ck_income_fx_snapshot_all_or_none",
        ),
    )

    op.create_index(
        op.f("ix_income_user_id"),
        "income",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_income_received_at"),
        "income",
        ["received_at"],
        unique=False,
    )


def downgrade() -> None:
    """
    Drops income (VF-017C).

    What:
        Drops the income table (and its indexes/constraints along with it).

    Why:
        No data reconstruction is needed here, because there is no
        PRE-EXISTING data this migration's upgrade() ever read from or
        depended on - income did not exist before this revision.

        This downgrade IS a data-losing rollback for anything created
        while VF-017C was active: any real Income row a user created
        after upgrading to this revision is permanently deleted the
        moment this downgrade runs. There is nothing to preserve it into,
        since the schema being rolled back to (3d7bb3d11671) has no
        income table at all.
    """

    op.drop_index(
        op.f("ix_income_received_at"),
        table_name="income",
    )
    op.drop_index(
        op.f("ix_income_user_id"),
        table_name="income",
    )
    op.drop_table("income")
