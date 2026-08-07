"""create initial finance tables

Revision ID: 9a09da6421ec
Revises:
Create Date: 2026-07-02

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9a09da6421ec"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Creates the initial finance tables.

    What:
        Creates categories, expenses, budgets, and goals
        with their initial constraints and indexes.

    Why:
        Allows Alembic to create the complete initial database schema
        from an empty PostgreSQL database.
    """

    op.create_table(
        "categories",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=80),
            nullable=False,
        ),
        sa.Column(
            "color",
            sa.String(length=20),
            nullable=True,
        ),
        sa.Column(
            "icon",
            sa.String(length=50),
            nullable=True,
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            server_default=sa.text("false"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "name",
            name="uq_categories_user_id_name",
        ),
    )

    op.create_index(
        op.f("ix_categories_user_id"),
        "categories",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "expenses",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "category_id",
            sa.UUID(),
            nullable=True,
        ),
        sa.Column(
            "title",
            sa.String(length=120),
            nullable=False,
        ),
        sa.Column(
            "amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default="EUR",
            nullable=False,
        ),
        sa.Column(
            "expense_date",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.String(length=500),
            nullable=True,
        ),
        sa.Column(
            "source",
            sa.String(length=30),
            server_default="manual",
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
        sa.CheckConstraint(
            "amount > 0",
            name="ck_expenses_amount_positive",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_expenses_user_id"),
        "expenses",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_expenses_category_id"),
        "expenses",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_expenses_expense_date"),
        "expenses",
        ["expense_date"],
        unique=False,
    )

    op.create_table(
        "budgets",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "category_id",
            sa.UUID(),
            nullable=True,
        ),
        sa.Column(
            "name",
            sa.String(length=120),
            nullable=False,
        ),
        sa.Column(
            "limit_amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default="EUR",
            nullable=False,
        ),
        sa.Column(
            "period",
            sa.String(length=20),
            server_default="monthly",
            nullable=False,
        ),
        sa.Column(
            "start_date",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "end_date",
            sa.Date(),
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
            "limit_amount > 0",
            name="ck_budgets_limit_amount_positive",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_budgets_user_id"),
        "budgets",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_budgets_category_id"),
        "budgets",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_budgets_start_date"),
        "budgets",
        ["start_date"],
        unique=False,
    )

    op.create_table(
        "goals",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=150),
            nullable=False,
        ),
        sa.Column(
            "target_amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
        ),
        sa.Column(
            "current_amount",
            sa.Numeric(precision=12, scale=2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default="EUR",
            nullable=False,
        ),
        sa.Column(
            "target_date",
            sa.Date(),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default="active",
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
        sa.CheckConstraint(
            "target_amount > 0",
            name="ck_goals_target_amount_positive",
        ),
        sa.CheckConstraint(
            "current_amount >= 0",
            name="ck_goals_current_amount_non_negative",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_goals_user_id"),
        "goals",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_goals_target_date"),
        "goals",
        ["target_date"],
        unique=False,
    )


def downgrade() -> None:
    """
    Removes the initial finance tables.

    What:
        Drops goals, budgets, expenses, and categories
        in reverse dependency order.

    Why:
        Allows the initial schema migration to be rolled back safely.
    """

    op.drop_index(
        op.f("ix_goals_target_date"),
        table_name="goals",
    )
    op.drop_index(
        op.f("ix_goals_user_id"),
        table_name="goals",
    )
    op.drop_table("goals")

    op.drop_index(
        op.f("ix_budgets_start_date"),
        table_name="budgets",
    )
    op.drop_index(
        op.f("ix_budgets_category_id"),
        table_name="budgets",
    )
    op.drop_index(
        op.f("ix_budgets_user_id"),
        table_name="budgets",
    )
    op.drop_table("budgets")

    op.drop_index(
        op.f("ix_expenses_expense_date"),
        table_name="expenses",
    )
    op.drop_index(
        op.f("ix_expenses_category_id"),
        table_name="expenses",
    )
    op.drop_index(
        op.f("ix_expenses_user_id"),
        table_name="expenses",
    )
    op.drop_table("expenses")

    op.drop_index(
        op.f("ix_categories_user_id"),
        table_name="categories",
    )
    op.drop_table("categories")