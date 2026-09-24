"""link expense to account ledger

Revision ID: 7dd404d0d20e
Revises: edcfdf3f7114
Create Date: 2026-09-24 12:54:41.562493

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7dd404d0d20e'
down_revision: Union[str, Sequence[str], None] = 'edcfdf3f7114'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Adds Expense <-> Account ledger linkage (VF-017E).

    What:
        1. Adds a composite unique constraint uq_expenses_id_user_id - a
           new FK target for the ownership-safe composite foreign key
           below (expenses had no such constraint before this; Income and
           Account both already got theirs in 811506d8afd2).
        2. Adds account_transactions.expense_id (nullable UUID).
        3. Adds a composite foreign key so account_transactions.user_id
           must agree with the referenced Expense, at the database level:
               (expense_id, user_id) -> expenses(id, user_id) CASCADE
           mirroring income_id's own composite FK exactly (same CASCADE
           direction, same rationale - see "Why" below). The existing
           account_id/income_id composite FKs from 811506d8afd2 are left
           completely untouched.
        4. Adds UNIQUE(expense_id) - at most one AccountTransaction
           projection per Expense (NULLs never collide, so every direct
           opening_balance/adjustment row and every income-kind row is
           unaffected).
        5. Extends ck_account_transactions_kind_valid to include
           'expense'.
        6. Replaces ck_account_transactions_income_linkage_valid with
           ck_account_transactions_source_linkage_valid, a three-branch
           CHECK covering income, expense, and direct rows in one
           constraint: an income-kind row always has income_id set,
           expense_id NULL, and direction 'credit'; an expense-kind row
           always has expense_id set, income_id NULL, and direction
           'debit'; a direct (opening_balance/adjustment) row always has
           both income_id and expense_id NULL. Because kind is a single
           scalar value, these three branches are mutually exclusive by
           construction - no row can satisfy more than one, which is what
           makes "both income_id and expense_id populated" and every
           other invalid combination structurally impossible.

    Why:
        Expense is the canonical business record (mirroring Income,
        VF-017D); the AccountTransaction row it produces is a
        synchronized ledger projection of it, not an independently
        editable event - see account_transaction_models.py's updated
        docstring. Adding expense_id here (rather than an
        expenses.account_id column) keeps exactly one place the
        relationship is stored, for the same two-independent-writers
        drift-avoidance reason income_id was chosen over
        income.account_id. ON DELETE CASCADE from expenses is
        deliberate and matches income_id's own CASCADE, not account_id's
        RESTRICT: RESTRICT protects a record's own deletion when it has
        dependent history; here Expense owns its projection, so the
        projection must vanish with its source rather than block it -
        Receipt's own independent expense_id -> expenses.id ON DELETE
        SET NULL FK is unaffected and fires from the same DELETE
        statement with no ordering conflict.

        No changes to the expenses table's own columns: the public API's
        account_id remains entirely derived from account_transactions at
        read time, never persisted on expenses (see expenses_service.py).

    No production data backfill is needed, and none is performed: this is
    purely additive to the existing schema. Every existing
    account_transactions row simply gets expense_id = NULL, which already
    satisfies the new linkage CHECK's direct-row branch, and no existing
    Expense is auto-linked - a brand new AccountTransaction row is only
    ever created going forward, through an explicit client request.
    """

    op.create_unique_constraint(
        "uq_expenses_id_user_id",
        "expenses",
        ["id", "user_id"],
    )

    op.add_column(
        "account_transactions",
        sa.Column("expense_id", sa.UUID(), nullable=True),
    )

    op.create_foreign_key(
        "fk_account_transactions_expense_id_user_id",
        "account_transactions",
        "expenses",
        ["expense_id", "user_id"],
        ["id", "user_id"],
        ondelete="CASCADE",
    )

    op.create_unique_constraint(
        "uq_account_transactions_expense_id",
        "account_transactions",
        ["expense_id"],
    )

    op.drop_constraint(
        "ck_account_transactions_kind_valid",
        "account_transactions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_account_transactions_kind_valid",
        "account_transactions",
        "kind IN ('opening_balance','adjustment','income','expense')",
    )

    op.drop_constraint(
        "ck_account_transactions_income_linkage_valid",
        "account_transactions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_account_transactions_source_linkage_valid",
        "account_transactions",
        "(kind = 'income' AND income_id IS NOT NULL AND expense_id IS NULL "
        "AND direction = 'credit') "
        "OR (kind = 'expense' AND expense_id IS NOT NULL AND income_id IS NULL "
        "AND direction = 'debit') "
        "OR (kind IN ('opening_balance','adjustment') "
        "AND income_id IS NULL AND expense_id IS NULL)",
    )


def downgrade() -> None:
    """
    Removes Expense <-> Account ledger linkage (VF-017E).

    What:
        Deletes any kind='expense' AccountTransaction rows, then removes
        the combined source-linkage CHECK and restores the Income-only
        2-branch version, restores the original 3-value kind CHECK
        (opening_balance/adjustment/income), drops the expense_id unique
        constraint and its composite foreign key, drops the expense_id
        column, and drops the composite unique constraint added by
        upgrade().

    Why:
        The kind='expense' rows must be deleted BEFORE the kind CHECK is
        narrowed back to exclude 'expense' - restoring that narrower
        constraint while an 'expense'-kind row still exists would make
        the downgrade fail outright with a constraint violation, not
        silently roll back (identical reasoning to 811506d8afd2's own
        downgrade). This downgrade therefore loses any Account ledger
        projection/linkage data created while this revision was active -
        it does NOT delete the canonical Expense rows themselves, only
        their AccountTransaction projections and the linkage
        columns/constraints. There is no way to reconstruct "which
        Expense was linked to which Account" after this downgrade, since
        that fact lived only in the now-deleted projection rows. Income
        rows and their own projections/constraints are entirely
        unaffected - this downgrade only ever touches expense-kind rows
        and the combined CHECK/column it added.
    """

    op.execute("DELETE FROM account_transactions WHERE kind = 'expense'")

    op.drop_constraint(
        "ck_account_transactions_source_linkage_valid",
        "account_transactions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_account_transactions_income_linkage_valid",
        "account_transactions",
        "(kind = 'income' AND income_id IS NOT NULL AND direction = 'credit') "
        "OR (kind IN ('opening_balance','adjustment') AND income_id IS NULL)",
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

    op.drop_constraint(
        "uq_account_transactions_expense_id",
        "account_transactions",
        type_="unique",
    )
    op.drop_constraint(
        "fk_account_transactions_expense_id_user_id",
        "account_transactions",
        type_="foreignkey",
    )

    op.drop_column("account_transactions", "expense_id")

    op.drop_constraint("uq_expenses_id_user_id", "expenses", type_="unique")
