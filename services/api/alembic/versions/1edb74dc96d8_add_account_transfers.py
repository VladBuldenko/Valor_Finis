"""add account transfers

Revision ID: 1edb74dc96d8
Revises: 7dd404d0d20e
Create Date: 2026-09-28 18:38:02.869258

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1edb74dc96d8'
down_revision: Union[str, Sequence[str], None] = '7dd404d0d20e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The single new application table this migration creates. Named
# explicitly (never "ALL TABLES IN SCHEMA public") for the same reason as
# VF-SEC-01 (edcfdf3f7114): this migration governs the security posture of
# its own object only.
ACCOUNT_TRANSFERS_TABLE_SQL = "public.account_transfers"

# Supabase's Data API (PostgREST) roles - identical to VF-SEC-01. None of
# them exist on local/CI PostgreSQL, so every statement naming one is
# wrapped in a pg_roles existence check and becomes a safe no-op there.
DATA_API_ROLES_ARRAY_SQL = "ARRAY['anon', 'authenticated', 'service_role']"

_KIND_VALID_WITH_TRANSFER_SQL = (
    "kind IN ('opening_balance','adjustment','income','expense','transfer')"
)
_KIND_VALID_WITHOUT_TRANSFER_SQL = (
    "kind IN ('opening_balance','adjustment','income','expense')"
)

_SOURCE_LINKAGE_WITH_TRANSFER_SQL = (
    "(kind = 'income' AND income_id IS NOT NULL AND expense_id IS NULL "
    "AND transfer_id IS NULL AND direction = 'credit') "
    "OR (kind = 'expense' AND expense_id IS NOT NULL AND income_id IS NULL "
    "AND transfer_id IS NULL AND direction = 'debit') "
    "OR (kind = 'transfer' AND transfer_id IS NOT NULL "
    "AND income_id IS NULL AND expense_id IS NULL) "
    "OR (kind IN ('opening_balance','adjustment') "
    "AND income_id IS NULL AND expense_id IS NULL AND transfer_id IS NULL)"
)
# Exactly the 3-branch CHECK created by 7dd404d0d20e, restored on
# downgrade.
_SOURCE_LINKAGE_WITHOUT_TRANSFER_SQL = (
    "(kind = 'income' AND income_id IS NOT NULL AND expense_id IS NULL "
    "AND direction = 'credit') "
    "OR (kind = 'expense' AND expense_id IS NOT NULL AND income_id IS NULL "
    "AND direction = 'debit') "
    "OR (kind IN ('opening_balance','adjustment') "
    "AND income_id IS NULL AND expense_id IS NULL)"
)


def upgrade() -> None:
    """
    Adds the Account Transfers schema foundation (VF-018B).

    What:
        1. Adds uq_accounts_id_user_id_currency on accounts - the FK target
           for the currency-bearing composite foreign keys below.
        2. Creates account_transfers: the canonical transfer record, with
           status (planned/posted), planned_date/effective_date/posted_at,
           client_request_id, CHECKs for amount > 0, distinct accounts,
           valid status, and lifecycle/date consistency, UNIQUE(id,
           user_id), UNIQUE(user_id, client_request_id), and composite
           (account_id, user_id, currency) -> accounts(id, user_id,
           currency) RESTRICT foreign keys for source and destination.
        3. Indexes source_account_id and destination_account_id.
        4. Adds account_transactions.transfer_id (nullable UUID) with a
           composite (transfer_id, user_id) -> account_transfers(id,
           user_id) ON DELETE CASCADE foreign key and UNIQUE(transfer_id,
           direction).
        5. Extends ck_account_transactions_kind_valid with 'transfer'.
        6. Replaces ck_account_transactions_source_linkage_valid with a
           4-branch version that adds the transfer branch (transfer_id set,
           income_id/expense_id NULL, direction free) and requires
           transfer_id IS NULL on every income, expense, and direct row.
        7. Explicitly revokes all privileges on account_transfers from the
           Supabase Data API roles that exist on the connected cluster.

    Why:
        See docs/modules/account-transfers.md (VF-018A contract, D1/D2/D11/
        D17/D18). account_transfers is canonical and owns its ledger
        projections, so transfer_id CASCADEs exactly like income_id/
        expense_id. Including currency in the Account foreign keys makes
        "source, destination, and transfer share one currency" and "a
        referenced Account's currency cannot change" database-level
        guarantees. The lifecycle CHECK deliberately leaves planned_date
        unconstrained for posted rows, so both an immediately posted
        transfer (planned_date NULL) and a planned-then-posted one
        (planned_date kept) are valid. "Exactly two projections for a
        posted transfer, none for a planned one" stays a service-level
        atomicity invariant - no trigger is introduced; UNIQUE(transfer_id,
        direction) only guarantees at most one debit and one credit.

        account_transfers is the first new business table created after
        VF-SEC-01. VF-SEC-01 already revoked the postgres role's default
        privileges for future tables, but that has never been exercised by
        a new table in production, so the REVOKE in step 7 makes the
        intended posture explicit rather than inherited. Every statement
        naming a Data API role is guarded by a pg_roles existence check,
        so this is a no-op on local/CI PostgreSQL.

    No backfill is needed and none is performed: account_transfers is new,
    and every existing account_transactions row gets transfer_id = NULL,
    which satisfies the new CHECK's unchanged income/expense/direct
    branches.
    """

    op.create_unique_constraint(
        "uq_accounts_id_user_id_currency",
        "accounts",
        ["id", "user_id", "currency"],
    )

    op.create_table(
        "account_transfers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("client_request_id", sa.UUID(), nullable=False),
        sa.Column("source_account_id", sa.UUID(), nullable=False),
        sa.Column("destination_account_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("planned_date", sa.Date(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "amount > 0",
            name="ck_account_transfers_amount_positive",
        ),
        sa.CheckConstraint(
            "source_account_id <> destination_account_id",
            name="ck_account_transfers_distinct_accounts",
        ),
        sa.CheckConstraint(
            "status IN ('planned','posted')",
            name="ck_account_transfers_status_valid",
        ),
        sa.CheckConstraint(
            "(status = 'planned' AND planned_date IS NOT NULL "
            "AND effective_date IS NULL AND posted_at IS NULL) "
            "OR (status = 'posted' AND effective_date IS NOT NULL "
            "AND posted_at IS NOT NULL)",
            name="ck_account_transfers_lifecycle_consistent",
        ),
        sa.UniqueConstraint(
            "id",
            "user_id",
            name="uq_account_transfers_id_user_id",
        ),
        sa.UniqueConstraint(
            "user_id",
            "client_request_id",
            name="uq_account_transfers_user_id_client_request_id",
        ),
        sa.ForeignKeyConstraint(
            ["source_account_id", "user_id", "currency"],
            ["accounts.id", "accounts.user_id", "accounts.currency"],
            name="fk_account_transfers_source_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["destination_account_id", "user_id", "currency"],
            ["accounts.id", "accounts.user_id", "accounts.currency"],
            name="fk_account_transfers_destination_account",
            ondelete="RESTRICT",
        ),
    )

    op.create_index(
        "ix_account_transfers_source_account_id",
        "account_transfers",
        ["source_account_id"],
    )
    op.create_index(
        "ix_account_transfers_destination_account_id",
        "account_transfers",
        ["destination_account_id"],
    )

    op.add_column(
        "account_transactions",
        sa.Column("transfer_id", sa.UUID(), nullable=True),
    )

    op.create_foreign_key(
        "fk_account_transactions_transfer_id_user_id",
        "account_transactions",
        "account_transfers",
        ["transfer_id", "user_id"],
        ["id", "user_id"],
        ondelete="CASCADE",
    )

    op.create_unique_constraint(
        "uq_account_transactions_transfer_id_direction",
        "account_transactions",
        ["transfer_id", "direction"],
    )

    op.drop_constraint(
        "ck_account_transactions_kind_valid",
        "account_transactions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_account_transactions_kind_valid",
        "account_transactions",
        _KIND_VALID_WITH_TRANSFER_SQL,
    )

    op.drop_constraint(
        "ck_account_transactions_source_linkage_valid",
        "account_transactions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_account_transactions_source_linkage_valid",
        "account_transactions",
        _SOURCE_LINKAGE_WITH_TRANSFER_SQL,
    )

    op.execute(
        f"""
        DO $$
        DECLARE
            target_role text;
        BEGIN
            FOREACH target_role IN ARRAY {DATA_API_ROLES_ARRAY_SQL}
            LOOP
                IF EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = target_role
                ) THEN
                    EXECUTE format(
                        'REVOKE ALL PRIVILEGES ON TABLE {ACCOUNT_TRANSFERS_TABLE_SQL} FROM %I',
                        target_role
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    """
    Removes the Account Transfers schema foundation (VF-018B).

    What (reverses upgrade() in dependency order):
        1. Deletes every kind='transfer' account_transactions row.
        2. Restores the 3-branch source-linkage CHECK and the 4-value kind
           CHECK exactly as 7dd404d0d20e created them.
        3. Drops UNIQUE(transfer_id, direction), the transfer_id composite
           foreign key, and the transfer_id column.
        4. Drops the account_transfers indexes and table.
        5. Drops uq_accounts_id_user_id_currency.

    Why:
        The transfer-kind rows must be deleted BEFORE the kind CHECK is
        narrowed back - restoring the narrower constraint while such a row
        still exists would fail the downgrade outright (identical
        reasoning to 811506d8afd2 / 7dd404d0d20e). The DELETE targets only
        kind='transfer' rows, so opening_balance, adjustment, income, and
        expense rows are untouched.

        This downgrade permanently destroys all transfer data - planned
        and posted account_transfers rows and their ledger projections.
        Account balances lose the effect of every posted transfer. There
        is no way to reconstruct them after this downgrade.

        No privileges are re-granted: dropping account_transfers drops its
        ACL with it, and a downgrade must never reopen Data API access.
    """

    op.execute("DELETE FROM account_transactions WHERE kind = 'transfer'")

    op.drop_constraint(
        "ck_account_transactions_source_linkage_valid",
        "account_transactions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_account_transactions_source_linkage_valid",
        "account_transactions",
        _SOURCE_LINKAGE_WITHOUT_TRANSFER_SQL,
    )

    op.drop_constraint(
        "ck_account_transactions_kind_valid",
        "account_transactions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_account_transactions_kind_valid",
        "account_transactions",
        _KIND_VALID_WITHOUT_TRANSFER_SQL,
    )

    op.drop_constraint(
        "uq_account_transactions_transfer_id_direction",
        "account_transactions",
        type_="unique",
    )
    op.drop_constraint(
        "fk_account_transactions_transfer_id_user_id",
        "account_transactions",
        type_="foreignkey",
    )
    op.drop_column("account_transactions", "transfer_id")

    op.drop_index(
        "ix_account_transfers_destination_account_id",
        table_name="account_transfers",
    )
    op.drop_index(
        "ix_account_transfers_source_account_id",
        table_name="account_transfers",
    )
    op.drop_table("account_transfers")

    op.drop_constraint(
        "uq_accounts_id_user_id_currency",
        "accounts",
        type_="unique",
    )
