import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
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


class GoalTransactionModel(Base):
    """
    SQLAlchemy ORM model for the goal_transactions table.

    What:
        Append-only ledger of balance-affecting events for a Goal:
        opening_balance (migration-created historical balance),
        contribution (money added), and withdrawal (money removed).

    Why:
        VF-016 replaces goals.current_amount (formerly a freely
        client-editable field) with a derived balance backed by
        transaction history, so overfunding/withdrawals/history become
        representable without an independently-editable source of truth.
        This table is THE authoritative source of a Goal's balance: the
        Goal row itself has no balance column at all (removed in VF-016G,
        after VF-016B introduced this ledger with a lossless backfill of
        pre-existing balances, and VF-016C-D switched all reads/writes over
        to it). A Goal's balance is always computed here, at read time,
        from opening_balance + contribution - withdrawal - never cached or
        stored anywhere on the Goal row.

    Fields:
        id: Unique transaction identifier.
        goal_id: Goal this transaction belongs to. RESTRICT on delete, not
            CASCADE, so a Goal's financial history cannot silently
            disappear if the Goal row is deleted.
        user_id: Owner of the goal. Denormalized: there is no users table
            to reference, matching the Supabase-owned-identity pattern used
            on every other user-owned table (see budget_versions.user_id).
            Since VF-020B2 the composite FK (goal_id, user_id) ->
            goals(id, user_id) requires it to equal the goal's owner.
        type: One of opening_balance, contribution, withdrawal. Enforced
            at the database level via CHECK, not only application
            validation. opening_balance is reserved for migration/system
            backfill - public APIs must never let a client create one.
        amount: Always positive; direction is carried by type, not sign.
        description: Optional free-text note.
        created_at: Record creation timestamp. For backfilled
            opening_balance rows this is set to the source Goal's own
            created_at (not migration execution time), since the opening
            balance represents pre-existing state, not a new event.
        currency: Currency of the amount - always the owning Goal's
            currency, copied by the service from the locked Goal row and
            never accepted from the client (VF-020B3). NOT NULL since
            VF-020B4, which first filled the remaining NULLs of older
            history from the owning goal; the (goal_id, user_id, currency)
            foreign key keeps it equal to the goal's currency.
        effective_date: Business date of the transaction (VF-020A P13).
            Every row created since VF-020B3 has one (request value, or the
            server date when omitted). NULL only for history created before
            VF-020B3 - it is never derived from created_at.
        client_request_id: Optional client-generated idempotency key for
            the create request (VF-020B3). Unique per user through
            uq_goal_transactions_user_id_client_request_id; NULL for rows
            created without a key (older clients, history). PostgreSQL
            treats NULLs as distinct, so any number of key-less rows is
            allowed.

    Note: the three columns above were added by the VF-020B2 expand
    migration (1e921a4a4412) and are mapped since VF-020B3. The VF-020B4
    contract migration made currency NOT NULL and added the
    (goal_id, user_id, currency) foreign key. effective_date (NULL for
    older history) and client_request_id (optional key) stay nullable.
    """

    __tablename__ = "goal_transactions"

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_goal_transactions_amount_positive"),
        CheckConstraint(
            "type IN ('opening_balance','contribution','withdrawal')",
            name="ck_goal_transactions_type_valid",
        ),
        Index(
            "ix_goal_transactions_goal_id_created_at",
            "goal_id",
            "created_at",
        ),
        # Composite ownership FK (VF-020B2): the row's user_id must equal
        # its goal's user_id at the database level. The single-column
        # goal_id FK below is kept as additional defense.
        ForeignKeyConstraint(
            ["goal_id", "user_id"],
            ["goals.id", "goals.user_id"],
            name="fk_goal_transactions_goal_id_user_id",
            ondelete="RESTRICT",
        ),
        # Final integrity foreign key (VF-020B4): the transaction's goal,
        # owner and currency must all match the goal row. The two foreign
        # keys above stay as layered defenses.
        ForeignKeyConstraint(
            ["goal_id", "user_id", "currency"],
            ["goals.id", "goals.user_id", "goals.currency"],
            name="fk_goal_transactions_goal_id_user_id_currency",
            ondelete="RESTRICT",
        ),
        # Create idempotency key (VF-020B2 constraint, used since VF-020B3):
        # a key identifies at most one transaction per user, across all of
        # the user's goals.
        UniqueConstraint(
            "user_id",
            "client_request_id",
            name="uq_goal_transactions_user_id_client_request_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("goals.id", ondelete="RESTRICT"),
        nullable=False,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    description: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    effective_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )

    client_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
