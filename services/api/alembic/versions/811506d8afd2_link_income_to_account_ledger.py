"""link income to account ledger

Revision ID: 811506d8afd2
Revises: c6b5afc1cc43
Create Date: 2026-09-23 19:24:25.857761

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '811506d8afd2'
down_revision: Union[str, Sequence[str], None] = 'c6b5afc1cc43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Adds Income <-> Account ledger linkage (VF-017D).

    What:
        1. Adds composite unique constraints uq_accounts_id_user_id and
           uq_income_id_user_id - FK targets for the ownership-safe
           composite foreign keys below.
        2. Adds account_transactions.income_id (nullable UUID).
        3. Adds composite foreign keys so account_transactions.user_id
           must agree with BOTH the referenced Account and the referenced
           Income, at the database level:
               (account_id, user_id) -> accounts(id, user_id) RESTRICT
               (income_id, user_id)  -> income(id, user_id)  CASCADE
           The existing plain account_id -> accounts.id FK (added in
           3d7bb3d11671) is left in place as additional defense-in-depth,
           not replaced.
        4. Adds UNIQUE(income_id) - at most one AccountTransaction
           projection per Income (NULLs never collide, so every direct
           opening_balance/adjustment row is unaffected).
        5. Extends ck_account_transactions_kind_valid to include 'income'.
        6. Adds ck_account_transactions_income_linkage_valid: an
           income-kind row always has income_id set and direction
           'credit'; a direct (opening_balance/adjustment) row always has
           income_id NULL. This is the single constraint that makes a
           direct row and an Income projection structurally
           indistinguishable-by-mistake.

    Why:
        Income is the canonical business record (VF-017D); the
        AccountTransaction row it produces is a synchronized ledger
        projection of it, not an independent editable event - see
        account_transaction_models.py's updated docstring. Adding
        income_id here (rather than an income.account_id column) keeps
        exactly one place the relationship is stored, avoiding the
        two-independent-writers drift risk a denormalized column on both
        sides would introduce. ON DELETE CASCADE from income is
        deliberate and is the opposite of account_id's RESTRICT: RESTRICT
        protects a record's own deletion when it has dependent history;
        here Income owns its projection, so the projection must vanish
        with its source rather than block it.

        No changes to the income table's own columns: the public API's
        account_id remains entirely derived from this table at read time,
        never persisted on income (see income_service.py).

    No production data backfill is needed: this is purely additive to a
    schema that, at the time this migration is written, has zero rows in
    accounts/account_transactions/income in production - but the design
    itself requires no backfill regardless of row count, since every
    existing account_transactions row simply gets income_id = NULL,
    which already satisfies the new linkage CHECK's second branch.
    """

    op.create_unique_constraint(
        "uq_accounts_id_user_id",
        "accounts",
        ["id", "user_id"],
    )
    op.create_unique_constraint(
        "uq_income_id_user_id",
        "income",
        ["id", "user_id"],
    )

    op.add_column(
        "account_transactions",
        sa.Column("income_id", sa.UUID(), nullable=True),
    )

    op.create_foreign_key(
        "fk_account_transactions_account_id_user_id",
        "account_transactions",
        "accounts",
        ["account_id", "user_id"],
        ["id", "user_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_account_transactions_income_id_user_id",
        "account_transactions",
        "income",
        ["income_id", "user_id"],
        ["id", "user_id"],
        ondelete="CASCADE",
    )

    op.create_unique_constraint(
        "uq_account_transactions_income_id",
        "account_transactions",
        ["income_id"],
    )

    op.drop_constraint(
        "ck_account_transactions_kind_valid",
        "account_transactions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_account_transactions_kind_valid",
        "account_transactions",
        "kind IN ('opening_balance','adjustment','income')",
    )

    op.create_check_constraint(
        "ck_account_transactions_income_linkage_valid",
        "account_transactions",
        "(kind = 'income' AND income_id IS NOT NULL AND direction = 'credit') "
        "OR (kind IN ('opening_balance','adjustment') AND income_id IS NULL)",
    )


def downgrade() -> None:
    """
    Removes Income <-> Account ledger linkage (VF-017D).

    What:
        Deletes any kind='income' AccountTransaction rows, then removes
        the linkage CHECK, restores the original 2-value kind CHECK,
        drops the income_id unique constraint and both composite foreign
        keys, drops the income_id column, and drops the two composite
        unique constraints added by upgrade().

    Why:
        The kind='income' rows must be deleted BEFORE the kind CHECK is
        narrowed back to ('opening_balance','adjustment') - restoring
        that narrower constraint while an 'income'-kind row still exists
        would make the downgrade fail outright with a constraint
        violation, not silently roll back. This downgrade therefore loses
        any Account ledger projection/linkage data created while this
        revision was active - it does NOT delete the canonical Income
        rows themselves, only their AccountTransaction projections and
        the linkage columns/constraints. There is no way to reconstruct
        "which Income was linked to which Account" after this downgrade,
        since that fact lived only in the now-deleted projection rows.
    """

    op.execute("DELETE FROM account_transactions WHERE kind = 'income'")

    op.drop_constraint(
        "ck_account_transactions_income_linkage_valid",
        "account_transactions",
        type_="check",
    )
    op.drop_constraint(
        "ck_account_transactions_kind_valid",
        "account_transactions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_account_transactions_kind_valid",
        "account_transactions",
        "kind IN ('opening_balance','adjustment')",
    )

    op.drop_constraint(
        "uq_account_transactions_income_id",
        "account_transactions",
        type_="unique",
    )
    op.drop_constraint(
        "fk_account_transactions_income_id_user_id",
        "account_transactions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_account_transactions_account_id_user_id",
        "account_transactions",
        type_="foreignkey",
    )

    op.drop_column("account_transactions", "income_id")

    op.drop_constraint("uq_income_id_user_id", "income", type_="unique")
    op.drop_constraint("uq_accounts_id_user_id", "accounts", type_="unique")
