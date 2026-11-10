"""add income and expense create idempotency

Revision ID: b8e2c5d1f739
Revises: c4d8a2f6e193
Create Date: 2026-11-11 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b8e2c5d1f739'
down_revision: Union[str, Sequence[str], None] = 'c4d8a2f6e193'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, unique constraint, all-or-none check). Income first, then expenses: no
# application path holds one of these tables while waiting for the other, so the
# order is only for determinism.
TABLES = (
    ("income", "uq_income_user_id_client_request_id", "ck_income_client_request_all_or_none"),
    ("expenses", "uq_expenses_user_id_client_request_id", "ck_expenses_client_request_all_or_none"),
)

ALL_OR_NONE_SQL = "(client_request_id IS NULL) = (client_request_fingerprint IS NULL)"


def upgrade() -> None:
    """
    Adds the create-idempotency key to income and expenses (VF-MVP-CORE-002,
    expand only).

    What:
        On each of the two tables: two NULLABLE columns (client_request_id UUID,
        client_request_fingerprint VARCHAR(64)), UNIQUE (user_id,
        client_request_id) and a CHECK that the two columns are set together or
        not at all.

    Why:
        Lets POST /income and POST /expenses be retried safely after a lost
        response. Every existing row keeps NULL in both columns, which satisfies
        the CHECK and never collides in the UNIQUE (NULLs are distinct), so no
        historical row is rewritten, backfilled or interpreted: the migration
        contains no data statement, and the deployed runtime that does not know
        the columns keeps working (they are nullable and have no default).
        Adding a nullable column without a default is a catalog-only change;
        the UNIQUE constraint builds an index over the existing rows, and each
        ALTER TABLE takes a short ACCESS EXCLUSIVE lock. No lock_timeout is set
        here on purpose: how long the migration may wait is an execution-time
        decision (the operator can set lock_timeout for the session before
        running the upgrade). No new relation is created, so no privilege or
        Data API statement is needed: the new columns inherit the existing table
        privileges.
    """

    for table_name, unique_name, check_name in TABLES:
        op.add_column(table_name, sa.Column("client_request_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.add_column(table_name, sa.Column("client_request_fingerprint", sa.String(length=64), nullable=True))
        op.create_unique_constraint(unique_name, table_name, ["user_id", "client_request_id"])
        op.create_check_constraint(check_name, table_name, ALL_OR_NONE_SQL)


def downgrade() -> None:
    """
    Reverts VF-MVP-CORE-002 to the exact pre-stage schema.

    What:
        Drops, per table and in dependency order, the all-or-none CHECK, the
        UNIQUE constraint and the two columns. Every other object is untouched.

    Why:
        Downgrading discards the recorded keys and fingerprints. Once the stage
        is deployed that removes the evidence that makes a retried create a
        replay instead of a duplicate, so a downgrade after deployment must be
        weighed separately. No income or expense record is changed or removed.
    """

    for table_name, unique_name, check_name in reversed(TABLES):
        op.drop_constraint(check_name, table_name, type_="check")
        op.drop_constraint(unique_name, table_name, type_="unique")
        op.drop_column(table_name, "client_request_fingerprint")
        op.drop_column(table_name, "client_request_id")
