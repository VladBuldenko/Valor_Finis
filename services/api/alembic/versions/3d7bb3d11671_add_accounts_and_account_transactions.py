"""add accounts and account transactions

Revision ID: 3d7bb3d11671
Revises: 220b12b15adc
Create Date: 2026-09-23 14:14:20.336857

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d7bb3d11671'
down_revision: Union[str, Sequence[str], None] = '220b12b15adc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Creates accounts and account_transactions (VF-017B).

    What:
        1. Creates accounts: id, user_id, name, type (CHECK
           checking/savings/cash), currency, status (CHECK
           active/archived), created_at, updated_at. No balance column.
        2. Creates account_transactions: an append-only ledger of
           balance-affecting events for an Account (opening_balance,
           adjustment only in this slice), with a positive-amount CHECK,
           a kind CHECK, a direction CHECK (credit/debit), a RESTRICT
           foreign key to accounts, a partial unique index enforcing at
           most one opening_balance row per account, and the two
           justified indexes (account_id, transaction_date) and
           (user_id).

    Why:
        Accounts represents where a user's real money is held (checking,
        savings, cash) - a new domain, independent of Budgets (spending
        limits, never a cash source) and Goals (aspirational targets, not
        yet connected to Accounts). Its balance is ledger-derived only,
        matching the VF-016G Goal architecture, but unlike Goal an
        Account's balance may legitimately be negative, so there is no
        equivalent of ck_goals_current_amount_non_negative here.

    No pre-existing data to backfill: accounts/account_transactions are
    brand-new tables with no prior column to migrate from, so this
    migration is pure schema creation - no op.execute() data movement.
    """

    op.create_table(
        "accounts",
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
            "name",
            sa.String(length=120),
            nullable=False,
        ),
        sa.Column(
            "type",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="EUR",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
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
            "type IN ('checking','savings','cash')",
            name="ck_accounts_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('active','archived')",
            name="ck_accounts_status_valid",
        ),
    )

    op.create_index(
        op.f("ix_accounts_user_id"),
        "accounts",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "account_transactions",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
        ),
        sa.Column(
            "account_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "direction",
            sa.String(length=10),
            nullable=False,
        ),
        sa.Column(
            "amount",
            sa.Numeric(12, 2),
            nullable=False,
        ),
        sa.Column(
            "transaction_date",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.String(length=500),
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
            name="ck_account_transactions_amount_positive",
        ),
        sa.CheckConstraint(
            "kind IN ('opening_balance','adjustment')",
            name="ck_account_transactions_kind_valid",
        ),
        sa.CheckConstraint(
            "direction IN ('credit','debit')",
            name="ck_account_transactions_direction_valid",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
        ),
    )

    op.create_index(
        op.f("ix_account_transactions_user_id"),
        "account_transactions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_account_transactions_account_id_transaction_date",
        "account_transactions",
        ["account_id", "transaction_date"],
        unique=False,
    )
    op.create_index(
        "uq_account_transactions_one_opening_balance_per_account",
        "account_transactions",
        ["account_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'opening_balance'"),
    )


def downgrade() -> None:
    """
    Drops account_transactions and accounts (VF-017B).

    What:
        Drops account_transactions first (it holds the FK to accounts),
        then drops accounts.

    Why:
        No data reconstruction is needed in either direction: both tables
        are new in this migration, so there is nothing pre-existing for
        downgrade to restore - this is the inverse of pure schema
        creation, not a data-losing rollback.
    """

    op.drop_index(
        "uq_account_transactions_one_opening_balance_per_account",
        table_name="account_transactions",
    )
    op.drop_index(
        "ix_account_transactions_account_id_transaction_date",
        table_name="account_transactions",
    )
    op.drop_index(
        op.f("ix_account_transactions_user_id"),
        table_name="account_transactions",
    )
    op.drop_table("account_transactions")

    op.drop_index(
        op.f("ix_accounts_user_id"),
        table_name="accounts",
    )
    op.drop_table("accounts")
