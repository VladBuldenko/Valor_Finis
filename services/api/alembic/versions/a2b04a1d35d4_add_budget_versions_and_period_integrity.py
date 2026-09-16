"""add budget versions and period integrity

Revision ID: a2b04a1d35d4
Revises: 60fc06f3baba
Create Date: 2026-09-16 12:18:53.367061

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2b04a1d35d4'
down_revision: Union[str, Sequence[str], None] = '60fc06f3baba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Adds period integrity to budgets and introduces budget_versions.

    What:
        1. Adds a CHECK constraint so budgets.period can only ever be
           weekly/monthly/yearly at the database level, not only in Pydantic.
        2. Replaces the budgets.category_id foreign key's ON DELETE SET NULL
           with ON DELETE RESTRICT, so a category still referenced by a
           budget cannot be deleted at all (defense in depth behind the new
           service-layer CategoryInUseByBudgetError guard).
        3. Creates budget_versions, an append-only history of a budget's
           limit_amount/category_id over time, and backfills exactly one
           'initial' row per existing budget.

    Why:
        VF-014 makes budgets.limit_amount a recurring per-period limit that
        can be edited mid-lifecycle. Without a history table, editing it
        would silently rewrite the meaning of already-completed periods.
        The SET NULL -> RESTRICT change closes an existing live bug: deleting
        a category a budget still scopes to previously turned that budget
        into an all-expenses budget.
    """

    op.create_check_constraint(
        "ck_budgets_period_valid",
        "budgets",
        "period IN ('weekly','monthly','yearly')",
    )

    # The original FK was created unnamed in 9a09da6421ec, so PostgreSQL
    # auto-named it. Verified against the live dev database rather than
    # assumed.
    op.drop_constraint(
        "budgets_category_id_fkey",
        "budgets",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_budgets_category_id",
        "budgets",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "budget_versions",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
        ),
        sa.Column(
            "budget_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "effective_from",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "effective_until",
            sa.Date(),
            nullable=True,
        ),
        sa.Column(
            "limit_amount",
            sa.Numeric(12, 2),
            nullable=False,
        ),
        sa.Column(
            "category_id",
            sa.UUID(),
            nullable=True,
        ),
        sa.Column(
            "change_reason",
            sa.String(length=30),
            server_default="user_edit",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "limit_amount > 0",
            name="ck_budget_versions_limit_amount_positive",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_budget_versions_effective_range",
        ),
        sa.CheckConstraint(
            "change_reason IN ('initial','user_edit','category_change')",
            name="ck_budget_versions_change_reason_valid",
        ),
        sa.ForeignKeyConstraint(
            ["budget_id"],
            ["budgets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            ondelete="RESTRICT",
        ),
    )

    op.create_index(
        op.f("ix_budget_versions_budget_id"),
        "budget_versions",
        ["budget_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_budget_versions_user_id"),
        "budget_versions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_budget_versions_budget_id_effective_from",
        "budget_versions",
        ["budget_id", "effective_from"],
        unique=False,
    )

    # Backfill: one 'initial' version per existing budget, effective_from
    # floored to the period start containing its start_date. A no-op on an
    # empty database (what CI runs against).
    op.execute(
        """
        INSERT INTO budget_versions (
            id, budget_id, user_id, effective_from, effective_until,
            limit_amount, category_id, change_reason, created_at
        )
        SELECT
            gen_random_uuid(),
            b.id,
            b.user_id,
            CASE b.period
                WHEN 'weekly' THEN date_trunc('week', b.start_date)::date
                WHEN 'monthly' THEN date_trunc('month', b.start_date)::date
                WHEN 'yearly' THEN date_trunc('year', b.start_date)::date
            END,
            NULL,
            b.limit_amount,
            b.category_id,
            'initial',
            b.created_at
        FROM budgets b
        """
    )


def downgrade() -> None:
    """
    Reverts budget_versions and the budgets period/category-FK changes.

    What:
        Drops budget_versions (its history is lost on downgrade, expected
        for a newly created table), restores budgets.category_id's foreign
        key to ON DELETE SET NULL, and drops the period CHECK constraint.

    Why:
        Allows Alembic to roll back this migration safely.
    """

    op.drop_index(
        "ix_budget_versions_budget_id_effective_from",
        table_name="budget_versions",
    )
    op.drop_index(
        op.f("ix_budget_versions_user_id"),
        table_name="budget_versions",
    )
    op.drop_index(
        op.f("ix_budget_versions_budget_id"),
        table_name="budget_versions",
    )
    op.drop_table("budget_versions")

    op.drop_constraint(
        "fk_budgets_category_id",
        "budgets",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "budgets_category_id_fkey",
        "budgets",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint(
        "ck_budgets_period_valid",
        "budgets",
        type_="check",
    )
