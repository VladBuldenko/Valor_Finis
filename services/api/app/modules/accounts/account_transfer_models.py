import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


class AccountTransferModel(Base):
    """
    SQLAlchemy ORM model for the account_transfers table.

    What:
        The canonical record of money moving between two Accounts owned by
        the same user, in the same currency (VF-018, contract in
        docs/modules/account-transfers.md). A transfer is either planned
        (expected in the future, no ledger effect) or posted (happened,
        reflected in the Account ledger by exactly two synchronized
        account_transactions projections: a debit on the source Account and
        a credit on the destination Account).

    Why:
        A transfer is not Income or Expense (it is not an external flow and
        must never inflate either) and not a pair of adjustments (those are
        direct, immutable, and unlinked). It is its own canonical entity,
        following the existing Income/Expense "canonical record +
        synchronized projection" pattern: this row owns its projections
        via account_transactions.transfer_id (ON DELETE CASCADE), and the
        Account row still never stores a balance.

        Lifecycle/date consistency is enforced by
        ck_account_transfers_lifecycle_consistent:
        - planned: planned_date set, effective_date and posted_at NULL;
        - posted: effective_date and posted_at set; planned_date stays set
          when the transfer began as planned, and is NULL when it was
          posted immediately.
        The database cannot express "a posted transfer has exactly two
        ledger projections" or "a planned transfer has none" without
        triggers; those remain service-level atomicity invariants,
        supported by account_transaction_repository.
        create_transfer_projections' status guard and by
        uq_account_transactions_transfer_id_direction (at most one debit
        and one credit per transfer).

        The two composite foreign keys include currency, so source,
        destination, and this row's own currency can never diverge, and an
        Account referenced by any transfer cannot change currency at the
        database level (RESTRICT on delete, NO ACTION on key update).

    Fields:
        id: Unique transfer identifier.
        user_id: Owner of the transfer and of both Accounts. Denormalized,
            no FK to a users table (none exists), matching every other
            user-owned table.
        client_request_id: Client-generated create idempotency key, unique
            per user (uq_account_transfers_user_id_client_request_id).
        source_account_id: Account the money leaves.
        destination_account_id: Account the money enters. Always different
            from source_account_id.
        amount: Always positive; NUMERIC(12,2), the same precision as
            account_transactions.amount.
        currency: The shared currency of both Accounts, derived by the
            server, never client input.
        status: One of planned, posted. No server default - the service
            always sets it explicitly.
        planned_date: Original expected date. Set only when the transfer
            was created as planned; never changes, including after posting.
        effective_date: Accounting date on which the money is considered
            actually moved - the transaction_date of both ledger
            projections. Set when posted.
        description: Optional free-text note. The single canonical copy of
            the text; ledger projections keep description NULL.
        posted_at: Technical timestamp of the change to posted (not an
            accounting date).
        created_at: Record creation timestamp.
        updated_at: Record update timestamp.
    """

    __tablename__ = "account_transfers"

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_account_transfers_amount_positive"),
        CheckConstraint(
            "source_account_id <> destination_account_id",
            name="ck_account_transfers_distinct_accounts",
        ),
        CheckConstraint(
            "status IN ('planned','posted')",
            name="ck_account_transfers_status_valid",
        ),
        # posted deliberately does not constrain planned_date: it is NULL
        # for an immediately posted transfer and non-NULL for one that
        # began as planned.
        CheckConstraint(
            "(status = 'planned' AND planned_date IS NOT NULL "
            "AND effective_date IS NULL AND posted_at IS NULL) "
            "OR (status = 'posted' AND effective_date IS NOT NULL "
            "AND posted_at IS NOT NULL)",
            name="ck_account_transfers_lifecycle_consistent",
        ),
        # FK target for account_transactions.(transfer_id, user_id), which
        # makes a cross-user projection impossible at the database level.
        UniqueConstraint("id", "user_id", name="uq_account_transfers_id_user_id"),
        # Create idempotency: one transfer per client request per user.
        # Its index leads with user_id, so it also serves list-by-user
        # queries without a separate user_id index.
        UniqueConstraint(
            "user_id",
            "client_request_id",
            name="uq_account_transfers_user_id_client_request_id",
        ),
        ForeignKeyConstraint(
            ["source_account_id", "user_id", "currency"],
            ["accounts.id", "accounts.user_id", "accounts.currency"],
            name="fk_account_transfers_source_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["destination_account_id", "user_id", "currency"],
            ["accounts.id", "accounts.user_id", "accounts.currency"],
            name="fk_account_transfers_destination_account",
            ondelete="RESTRICT",
        ),
        Index("ix_account_transfers_source_account_id", "source_account_id"),
        Index(
            "ix_account_transfers_destination_account_id",
            "destination_account_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    client_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    source_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    destination_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    planned_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )

    effective_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )

    description: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )

    posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
