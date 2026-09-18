"""add goal transactions and backfill

Revision ID: e90a257f987b
Revises: 81d194a3e0ff
Create Date: 2026-09-18 09:35:50.873629

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e90a257f987b'
down_revision: Union[str, Sequence[str], None] = '81d194a3e0ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Creates goal_transactions and backfills existing Goal balances.

    What:
        1. Creates goal_transactions, an append-only ledger of
           balance-affecting events for a Goal (opening_balance,
           contribution, withdrawal), with a positive-amount CHECK, a
           type CHECK, a RESTRICT foreign key to goals, and the two
           justified indexes (goal_id, created_at) and (user_id).
        2. Backfills exactly one opening_balance row per existing Goal
           whose current_amount > 0, preserving that balance losslessly
           as ledger history. Goals with current_amount == 0 get no row,
           since there is nothing to record and no money is manufactured.

    Why:
        VF-016 makes the GoalTransaction ledger the future authoritative
        source of truth for a Goal's balance (see goal_transaction_models.py).
        goals.current_amount remains transitional legacy storage in this
        slice - this migration only introduces persistence and a lossless
        historical backfill; no application read/write path is switched
        over yet. created_at is set to each Goal's own created_at (not
        NOW()), since the opening balance represents pre-existing state,
        not a new contribution made during deployment. The backfill is
        guarded with NOT EXISTS so re-running this SQL (e.g. during local
        debugging) never creates a duplicate opening_balance row.
    """

    op.create_table(
        "goal_transactions",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
        ),
        sa.Column(
            "goal_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "type",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "amount",
            sa.Numeric(12, 2),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_goal_transactions_amount_positive",
        ),
        sa.CheckConstraint(
            "type IN ('opening_balance','contribution','withdrawal')",
            name="ck_goal_transactions_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["goal_id"],
            ["goals.id"],
            ondelete="RESTRICT",
        ),
    )

    op.create_index(
        op.f("ix_goal_transactions_user_id"),
        "goal_transactions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_goal_transactions_goal_id_created_at",
        "goal_transactions",
        ["goal_id", "created_at"],
        unique=False,
    )

    # Backfill: one opening_balance row per existing Goal with a non-zero
    # balance. A no-op on an empty database (what CI runs against). The
    # NOT EXISTS guard makes this safe to re-execute.
    op.execute(
        """
        INSERT INTO goal_transactions (
            id, goal_id, user_id, type, amount, description, created_at
        )
        SELECT
            gen_random_uuid(),
            g.id,
            g.user_id,
            'opening_balance',
            g.current_amount,
            NULL,
            g.created_at
        FROM goals g
        WHERE g.current_amount > 0
        AND NOT EXISTS (
            SELECT 1 FROM goal_transactions gt
            WHERE gt.goal_id = g.id AND gt.type = 'opening_balance'
        )
        """
    )


def downgrade() -> None:
    """
    Removes goal_transactions.

    What:
        Drops the two indexes and the goal_transactions table.

    Why:
        Allows Alembic to roll back this migration safely. goals.current_amount
        (the legacy transitional balance) is never touched by either direction
        of this migration, so downgrading loses only the newly introduced
        ledger history, never the Goal's own stored balance.
    """

    op.drop_index(
        "ix_goal_transactions_goal_id_created_at",
        table_name="goal_transactions",
    )
    op.drop_index(
        op.f("ix_goal_transactions_user_id"),
        table_name="goal_transactions",
    )
    op.drop_table("goal_transactions")
