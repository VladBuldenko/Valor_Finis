"""expand goal transaction account link

Revision ID: 98acdc7016d2
Revises: 8799b7fd923d
Create Date: 2026-10-08 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '98acdc7016d2'
down_revision: Union[str, Sequence[str], None] = '8799b7fd923d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# MIGRATION table-lock order, in BOTH directions: accounts FIRST, then
# goal_transactions. This is deliberately NOT the future C2 runtime row-lock
# order (Goal -> Account -> GoalTransaction interaction); the two are
# different resources and are not claimed to be the same. It does not
# conflict with the runtime, because this migration is applied to production
# BEFORE any code that reads or writes goal_transactions.account_id is
# deployed. No lock_timeout is set here on purpose: how long the migration
# may wait is an execution-time decision (the operator sets lock_timeout for
# the migration transaction before running it).
#
# The two directions need DIFFERENT strengths on accounts, so they are
# separate constants:
# - upgrade: ADD FOREIGN KEY needs only SHARE ROW EXCLUSIVE on the referenced
#   table, so plain reads of accounts continue while the migration runs;
# - downgrade: DROP CONSTRAINT of that foreign key needs ACCESS EXCLUSIVE on
#   accounts. Taking it up front avoids promoting a weaker accounts lock to
#   ACCESS EXCLUSIVE later, while ACCESS EXCLUSIVE on goal_transactions is
#   already held (a lock promotion that deadlocks with a transaction that
#   reads accounts and then goal_transactions).
# goal_transactions is ACCESS EXCLUSIVE in both directions (it gains or loses
# a column, constraints and an index).
UPGRADE_LOCKS_SQL = (
    "LOCK TABLE accounts IN SHARE ROW EXCLUSIVE MODE",
    "LOCK TABLE goal_transactions IN ACCESS EXCLUSIVE MODE",
)
DOWNGRADE_LOCKS_SQL = (
    "LOCK TABLE accounts IN ACCESS EXCLUSIVE MODE",
    "LOCK TABLE goal_transactions IN ACCESS EXCLUSIVE MODE",
)

ACCOUNT_FK_NAME = "fk_goal_transactions_account_id_user_id_currency"
OPENING_BALANCE_CHECK_NAME = "ck_goal_transactions_opening_balance_unlinked"
KEY_CHECK_NAME = "ck_goal_transactions_linked_requires_client_request_id"
DATE_CHECK_NAME = "ck_goal_transactions_linked_requires_effective_date"
LINKED_INDEX_NAME = "ix_goal_transactions_linked_account_id"

OPENING_BALANCE_CHECK_SQL = "type <> 'opening_balance' OR account_id IS NULL"
KEY_CHECK_SQL = "account_id IS NULL OR client_request_id IS NOT NULL"
DATE_CHECK_SQL = "account_id IS NULL OR effective_date IS NOT NULL"


def upgrade() -> None:
    """
    Adds the database foundation for Account-linked Goal reservations
    (VF-020C1, schema expand step).

    What:
        0. Locks accounts (SHARE ROW EXCLUSIVE), then goal_transactions
           (ACCESS EXCLUSIVE) (UPGRADE_LOCKS_SQL).
        1. Adds goal_transactions.account_id UUID NULL - no default, no
           backfill: every existing row stays NULL (tracked / unlinked).
        2. Adds three CHECK constraints that only constrain rows with an
           account_id: an opening_balance can never be linked, and a linked
           row must carry a client_request_id and an effective_date.
        3. Adds the partial index (account_id) WHERE account_id IS NOT NULL.
        4. Adds fk_goal_transactions_account_id_user_id_currency:
           (account_id, user_id, currency) -> accounts(id, user_id,
           currency) ON DELETE RESTRICT, reusing the existing
           uq_accounts_id_user_id_currency. With the default MATCH SIMPLE
           behavior a row whose account_id is NULL is not constrained.

    Why:
        For a linked row the database now guarantees that the Account
        exists, belongs to the row's user and has the row's currency.
        Because goal_transactions.currency already equals the Goal's
        currency (VF-020B4 foreign key), Goal currency = Account currency
        follows for linked rows. A referenced Account can no longer be
        deleted or have its currency changed underneath linked history
        (RESTRICT); the controlled API 409 for that arrives with C2.

        This revision is additive and the application is unaware of it: the
        ORM deliberately does not map account_id until C2, so the code
        deployed with this revision runs unchanged against the schema both
        before and after the migration (new writes simply leave the column
        NULL). The date rule "linked rows carry today's date" is a service
        rule (C2) and is not enforced by the database.

        Atomicity: Alembic runs the whole upgrade in one transaction
        (transactional DDL); any failure leaves the schema untouched.
        Validating the new foreign key scans goal_transactions under the
        lock; every existing row has account_id NULL, so it passes.
    """

    for lock_statement in UPGRADE_LOCKS_SQL:
        op.execute(lock_statement)

    op.add_column(
        "goal_transactions",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        OPENING_BALANCE_CHECK_NAME,
        "goal_transactions",
        OPENING_BALANCE_CHECK_SQL,
    )
    op.create_check_constraint(
        KEY_CHECK_NAME,
        "goal_transactions",
        KEY_CHECK_SQL,
    )
    op.create_check_constraint(
        DATE_CHECK_NAME,
        "goal_transactions",
        DATE_CHECK_SQL,
    )
    op.create_index(
        LINKED_INDEX_NAME,
        "goal_transactions",
        ["account_id"],
        postgresql_where=sa.text("account_id IS NOT NULL"),
    )
    op.create_foreign_key(
        ACCOUNT_FK_NAME,
        "goal_transactions",
        "accounts",
        ["account_id", "user_id", "currency"],
        ["id", "user_id", "currency"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """
    Reverts VF-020C1 to the VF-020B4 schema.

    What:
        Locks accounts and then goal_transactions, both ACCESS EXCLUSIVE
        (DOWNGRADE_LOCKS_SQL; the same table order as upgrade, a stronger
        lock on accounts, taken first so it is never promoted later), then
        drops the Account foreign key, the partial index, the three CHECK
        constraints and finally the account_id column.

    Why:
        This is a SCHEMA reversal only. Dropping the column permanently
        discards every account_id value: once C2 has created Account-linked
        Goal transactions, a downgrade would remove their Account
        association (the rows themselves, with their currency, amount and
        dates, remain and become tracked rows). No data migration is
        attempted and no linked row is converted or deleted. Do not
        downgrade after linked data exists without a separate decision.
    """

    for lock_statement in DOWNGRADE_LOCKS_SQL:
        op.execute(lock_statement)

    op.drop_constraint(
        ACCOUNT_FK_NAME,
        "goal_transactions",
        type_="foreignkey",
    )
    op.drop_index(
        LINKED_INDEX_NAME,
        table_name="goal_transactions",
        postgresql_where=sa.text("account_id IS NOT NULL"),
    )
    op.drop_constraint(DATE_CHECK_NAME, "goal_transactions", type_="check")
    op.drop_constraint(KEY_CHECK_NAME, "goal_transactions", type_="check")
    op.drop_constraint(
        OPENING_BALANCE_CHECK_NAME,
        "goal_transactions",
        type_="check",
    )
    op.drop_column("goal_transactions", "account_id")
