import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, Date, DateTime, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


class IncomeModel(Base):
    """
    SQLAlchemy ORM model for the income table.

    What:
        Represents money received by the user: salary, freelance payment,
        refund, gift, or other. VF-017C scope only - no account_id (see
        income_schemas.py for why), no category, no recurrence.

    Why:
        Income is Expense's mirror-image domain: a rich, dated monetary
        event with the same historical FX-snapshot needs, reusing the
        exact same FX architecture (app.modules.fx, financial_settings)
        Expense already established in VF-014B5C - not a new FX
        implementation.

    Fields:
        id: Unique income identifier.
        user_id: Owner of the income record.
        amount: Original amount received, in `currency`. Never revalued.
        currency: Original currency code, e.g. EUR or USD.
        received_at: Date the money was actually received.
        source: Closed set - salary, freelance, refund, gift, other.
        description: Optional user note.
        base_amount: `amount` converted to the user's base currency, using
            the historical rate in effect on received_at. Backend-derived
            only; never client-supplied.
        base_currency: The base currency `base_amount` is denominated in.
        fx_rate: units of base_currency per 1 unit of `currency`, at
            fx_rate_date. base_amount = amount * fx_rate.
        fx_rate_date: the actual published rate date used - may differ
            from received_at (weekends/holidays), never later than it.
        fx_source: 'identity' | 'ecb' | 'nbu'.
        created_at: Record creation timestamp.
        updated_at: Record update timestamp.

    Note (VF-017D): this table still has no account_id column, even
    though Income can now be linked to an Account. Income is the
    canonical record; its link to an Account is represented entirely by
    an AccountTransaction row (kind="income") whose income_id points back
    here - see account_transaction_models.py. Storing account_id on both
    sides would create two independently-writable copies of the same
    fact, exactly the "two sources of business truth" this design
    deliberately avoids. The public API still exposes a read-only,
    derived account_id on IncomeResponse - see income_service.py's
    _build_income_response and account_transaction_repository.py's
    get_income_projection/get_income_account_links_for_user.
    """

    __tablename__ = "income"

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_income_amount_positive"),
        CheckConstraint(
            "source IN ('salary','freelance','refund','gift','other')",
            name="ck_income_source_valid",
        ),
        CheckConstraint(
            "base_amount IS NULL OR base_amount > 0",
            name="ck_income_base_amount_positive",
        ),
        CheckConstraint(
            "fx_rate IS NULL OR fx_rate > 0",
            name="ck_income_fx_rate_positive",
        ),
        CheckConstraint(
            "(base_amount IS NULL AND base_currency IS NULL AND fx_rate IS NULL "
            "AND fx_rate_date IS NULL AND fx_source IS NULL) "
            "OR (base_amount IS NOT NULL AND base_currency IS NOT NULL AND fx_rate IS NOT NULL "
            "AND fx_rate_date IS NOT NULL AND fx_source IS NOT NULL)",
            name="ck_income_fx_snapshot_all_or_none",
        ),
        # Composite-unique FK target (VF-017D): lets account_transactions
        # carry a (income_id, user_id) -> income(id, user_id) foreign key,
        # so a cross-user Income<->Account link is impossible to construct
        # at the database level, not only the service level.
        UniqueConstraint("id", "user_id", name="uq_income_id_user_id"),
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

    received_at: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    description: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
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
