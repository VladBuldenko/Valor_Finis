import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


class AccountModel(Base):
    """
    SQLAlchemy ORM model for the accounts table.

    What:
        Represents a real-world place a user's money is held: a checking
        account, a savings account, or cash. VF-017B scope only - credit
        cards, debt/liability accounts, and investment accounts are
        explicitly out of scope.

    Why:
        Accounts exist to answer "where is this money", distinct from a
        Budget (a spending limit, never a cash source) and a Goal (an
        aspirational target, not yet connected to any cash source).

    Fields:
        id: Unique account identifier.
        user_id: Owner of the account.
        name: Human-readable account name. Not unique - a user may
            legitimately have multiple similarly named accounts (e.g. two
            "Cash" wallets).
        type: One of checking, savings, cash.
        currency: Currency code such as EUR or USD.
        status: One of active, archived. An archived account keeps its
            full history readable but cannot receive new direct
            transactions (see account_service.create_account_transaction).
        created_at: Record creation timestamp.
        updated_at: Record update timestamp.

    Note: this model has no persisted balance column. An Account's balance
    exists only as the sum of its account_transactions ledger rows
    (credit adds, debit subtracts); it is never stored on the Account row
    itself. Unlike Goal, an Account's ledger-derived balance MAY be
    negative - an Account is a descriptive financial record, not a
    payment-authorization system, so there is no insufficient-funds check
    anywhere in this domain. See account_transaction_repository.py for the
    ledger-balance calculation, and account_schemas.AccountResponse for the
    public, ledger-derived current_balance field.
    """

    __tablename__ = "accounts"

    __table_args__ = (
        CheckConstraint(
            "type IN ('checking','savings','cash')",
            name="ck_accounts_type_valid",
        ),
        CheckConstraint(
            "status IN ('active','archived')",
            name="ck_accounts_status_valid",
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
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="EUR",
        server_default="EUR",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
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
