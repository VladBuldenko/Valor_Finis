import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


class AccountTransactionModel(Base):
    """
    SQLAlchemy ORM model for the account_transactions table.

    What:
        Ledger of balance-affecting events for an Account. VF-017B ships
        exactly two kinds: opening_balance (recorded once, at account
        creation, to represent a real pre-existing balance) and adjustment
        (a direct manual correction/reconciliation entry). income, expense,
        and transfer kinds are intentionally NOT part of this slice - see
        the "Why" note below.

    Why:
        This table is THE authoritative source of an Account's balance:
        the Account row itself has no balance column at all (matching the
        VF-016G Goal architecture). An Account's balance is always
        computed here, at read time, from
        SUM(CASE direction WHEN 'credit' THEN amount WHEN 'debit' THEN
        -amount END) - never cached or stored anywhere on the Account row.

        Unlike GoalTransaction, direction is a separate column from kind
        rather than being implied by kind (contribution=credit,
        withdrawal=debit). This is deliberate, not an arbitrary
        divergence: a future income/expense/transfer kind will need to
        carry the same direction concept a plain adjustment does, and
        keeping direction orthogonal to kind now means adding those future
        kinds is a pure CHECK-constraint extension, not a restructuring of
        this column.

        Also unlike GoalTransaction, an Account's ledger balance MAY be
        negative - an Account is a descriptive financial record, not a
        payment-authorization system. There is no insufficient-funds
        validation anywhere in this domain (see account_service.py).

        Every row here is immutable in this slice: there is no PATCH/DELETE
        endpoint, and corrections are made with compensating adjustment
        entries, never edits - identical philosophy to GoalTransaction.
        A future slice that links income/expense source rows to this table
        will introduce a different, explicitly-scoped correction model for
        those specific rows only (they will be synchronized projections of
        their mutable source row) - opening_balance and adjustment rows
        stay immutable forever regardless of that future change.

    Fields:
        id: Unique transaction identifier.
        account_id: Account this transaction belongs to. RESTRICT on
            delete, not CASCADE, so an Account's financial history cannot
            silently disappear if the Account row is deleted.
        user_id: Owner of the account. Denormalized, no FK, matching the
            Supabase-owned-identity pattern used on every other user-owned
            table (see goal_transactions.user_id).
        kind: One of opening_balance, adjustment (VF-017B). Enforced at
            the database level via CHECK, not only application validation.
            opening_balance is reserved for account creation - the public
            API must never let a client create one directly (see
            account_transaction_schemas.AccountTransactionCreate).
        direction: One of credit (increases balance), debit (decreases
            balance).
        amount: Always positive; direction is carried by the direction
            column, never by sign.
        transaction_date: The date this event actually happened (may
            differ from created_at, the same distinction expense_date has
            from an Expense's created_at).
        description: Optional free-text note.
        created_at: Record creation timestamp.
    """

    __tablename__ = "account_transactions"

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_account_transactions_amount_positive"),
        CheckConstraint(
            "kind IN ('opening_balance','adjustment')",
            name="ck_account_transactions_kind_valid",
        ),
        CheckConstraint(
            "direction IN ('credit','debit')",
            name="ck_account_transactions_direction_valid",
        ),
        Index(
            "ix_account_transactions_account_id_transaction_date",
            "account_id",
            "transaction_date",
        ),
        Index(
            "uq_account_transactions_one_opening_balance_per_account",
            "account_id",
            unique=True,
            postgresql_where="kind = 'opening_balance'",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    direction: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    transaction_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    description: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
