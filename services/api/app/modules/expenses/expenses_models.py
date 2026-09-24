import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


class ExpenseModel(Base):
    """
    SQLAlchemy ORM model for the expenses table.

    What:
        Represents expense records stored in PostgreSQL.

    Why:
        Allows the application to persist user expenses in a real database
        instead of using temporary in-memory lists.

    Fields:
        id: Unique expense identifier.
        user_id: Owner of the expense.
        category_id: Optional category connected to the expense.
        title: Short expense name.
        amount: Original transaction amount, in `currency`. Never revalued.
        currency: Original transaction currency code, e.g. EUR or USD.
        expense_date: Date when the expense happened.
        description: Optional user note.
        source: Origin of the expense, for example manual or receipt.
        base_amount: `amount` converted to the user's base currency, using
            the historical rate in effect on expense_date (VF-014B5C).
            Backend-derived only; never client-supplied. Nullable only to
            truthfully represent a legacy foreign expense created before
            VF-014B5C, whose snapshot has not been resolved yet.
        base_currency: The base currency `base_amount` is denominated in.
        fx_rate: units of base_currency per 1 unit of `currency`, at
            fx_rate_date. base_amount = amount * fx_rate.
        fx_rate_date: the actual published rate date used - may differ
            from expense_date (weekends/holidays), never later than it.
        fx_source: 'identity' | 'ecb' | 'nbu'.
        created_at: Record creation timestamp.
        updated_at: Record update timestamp.

    Note (VF-017E): this table still has no account_id column, even
    though an Expense can now be linked to an Account. Expense is the
    canonical record; its link to an Account is represented entirely by
    an AccountTransaction row (kind="expense") whose expense_id points
    back here - mirroring Income's own VF-017D design exactly. Storing
    account_id on both sides would create two independently-writable
    copies of the same fact, the "two sources of business truth" this
    design deliberately avoids. The public API still exposes a
    read-only, derived account_id on ExpenseResponse - see
    expenses_service.py's _build_expense_response and
    account_transaction_repository.py's get_expense_projection/
    get_expense_account_links_for_user.
    """

    __tablename__ = "expenses"

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
        CheckConstraint(
            "base_amount IS NULL OR base_amount > 0",
            name="ck_expenses_base_amount_positive",
        ),
        CheckConstraint(
            "fx_rate IS NULL OR fx_rate > 0",
            name="ck_expenses_fx_rate_positive",
        ),
        CheckConstraint(
            "(base_amount IS NULL AND base_currency IS NULL AND fx_rate IS NULL "
            "AND fx_rate_date IS NULL AND fx_source IS NULL) "
            "OR (base_amount IS NOT NULL AND base_currency IS NOT NULL AND fx_rate IS NOT NULL "
            "AND fx_rate_date IS NOT NULL AND fx_source IS NOT NULL)",
            name="ck_expenses_fx_snapshot_all_or_none",
        ),
        # Composite-unique FK target (VF-017E): lets account_transactions
        # carry a (expense_id, user_id) -> expenses(id, user_id) foreign
        # key, so a cross-user Expense<->Account link is impossible to
        # construct at the database level, not only the service level.
        UniqueConstraint("id", "user_id", name="uq_expenses_id_user_id"),
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

    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="EUR",
        server_default="EUR",
    )

    expense_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    description: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )

    source: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="manual",
        server_default="manual",
    )

    base_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    base_currency: Mapped[Optional[str]] = mapped_column(
        String(3),
        nullable=True,
    )

    fx_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 8),
        nullable=True,
    )

    fx_rate_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )

    fx_source: Mapped[Optional[str]] = mapped_column(
        String(30),
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