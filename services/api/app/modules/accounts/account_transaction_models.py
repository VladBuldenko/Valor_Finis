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


class AccountTransactionModel(Base):
    """
    SQLAlchemy ORM model for the account_transactions table.

    What:
        Ledger of balance-affecting events for an Account. VF-017B shipped
        two direct kinds: opening_balance (recorded once, at account
        creation, to represent a real pre-existing balance) and adjustment
        (a direct manual correction/reconciliation entry). VF-017D added a
        third, source-backed kind: income - a synchronized projection of
        an Income row (see income_id below). VF-017E adds a fourth,
        source-backed kind: expense - a synchronized projection of an
        Expense row (see expense_id below), symmetric to income but always
        a debit. transfer remains deferred - see the "Why" note below.

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

        Direct rows (opening_balance, adjustment) are immutable: there is
        no PATCH/DELETE endpoint, and corrections are made with
        compensating adjustment entries, never edits - identical
        philosophy to GoalTransaction. Income-backed rows (kind="income")
        and expense-backed rows (kind="expense") are the deliberate
        exceptions VF-017B's own docstring already anticipated: each is a
        synchronized projection of its source Income/Expense row, and may
        be created/updated/deleted ONLY through income_service/
        expenses_service respectively, atomically with the source row
        itself - never through a public AccountTransaction endpoint,
        which still exposes no PATCH/DELETE at all. See
        account_transaction_repository.py's create_income_projection/
        update_income_projection/delete_income_projection and their exact
        expense-projection counterparts (create_expense_projection/
        update_expense_projection/delete_expense_projection) -
        narrowly-scoped primitives that exist specifically so no code
        path can accidentally make a direct opening_balance/adjustment
        row (or the wrong source's projection) mutable by reusing a
        generic update function.

        income_id: nullable, UNIQUE (at most one projection per Income),
        FK to income(id) ON DELETE CASCADE - deliberately the opposite
        choice from account_id's RESTRICT. account_id/goal_id's RESTRICT
        protects a record's OWN deletion when it has dependent history;
        here the relationship is inverted - Income is canonical and owns
        its projection (VF-017D), so the projection must vanish with its
        source, never block it. The (income_id, user_id) composite FK
        below additionally guarantees a projection can never reference an
        Income belonging to a different user, at the database level, not
        only the service level.

        expense_id: nullable, UNIQUE (at most one projection per
        Expense), FK to expenses(id) ON DELETE CASCADE (VF-017E) -
        exactly symmetric to income_id, for the identical
        canonical-owns-its-projection reason. Receipt's own, entirely
        independent expense_id -> expenses.id ON DELETE SET NULL FK is
        unaffected by this: both FK actions fire from the same Expense
        DELETE statement with no ordering conflict, since they target two
        different child tables. The (expense_id, user_id) composite FK
        below guarantees a projection can never reference an Expense
        belonging to a different user, at the database level.

        A single row can never be both an income projection and an
        expense projection at once - ck_account_transactions_
        source_linkage_valid (below) enforces this by construction, since
        kind is a single scalar value and its three branches (income,
        expense, direct) are mutually exclusive.

    Fields:
        id: Unique transaction identifier.
        account_id: Account this transaction belongs to. RESTRICT on
            delete, not CASCADE, so an Account's financial history cannot
            silently disappear if the Account row is deleted.
        user_id: Owner of the account. Denormalized, no FK to a users
            table (none exists), matching the Supabase-owned-identity
            pattern used on every other user-owned table (see
            goal_transactions.user_id). VF-017D additionally uses it, via
            composite foreign keys below, as the mechanism that makes a
            cross-user Income<->Account link database-impossible.
        kind: One of opening_balance, adjustment (VF-017B), income
            (VF-017D), expense (VF-017E). Enforced at the database level
            via CHECK, not only application validation. opening_balance
            is reserved for account creation, income for Income linkage,
            and expense for Expense linkage - the public API must never
            let a client create any of the three directly (see
            account_transaction_schemas.AccountTransactionCreate).
        direction: One of credit (increases balance), debit (decreases
            balance). Every income-backed row is a credit and every
            expense-backed row is a debit - both enforced by
            ck_account_transactions_source_linkage_valid below.
        amount: Always positive; direction is carried by the direction
            column, never by sign. For an income-backed row, always
            synchronized to equal the source Income's own amount; for an
            expense-backed row, always synchronized to equal the source
            Expense's own amount (never Expense.base_amount - the ledger
            reflects real cash movement in the Account's own currency,
            not base-currency analytics).
        transaction_date: The date this event actually happened (may
            differ from created_at, the same distinction expense_date has
            from an Expense's created_at). For an income-backed row,
            always synchronized to equal the source Income's received_at;
            for an expense-backed row, always synchronized to equal the
            source Expense's own expense_date.
        description: Optional free-text note. Always NULL for an
            income-backed or expense-backed row - the source record's own
            description/title/source remain the single canonical copy of
            that text; the ledger row identifies its source via
            income_id/expense_id instead of duplicating mutable text that
            would need its own synchronization (see income_service.py /
            expenses_service.py).
        income_id: If this row is an Income projection, the source
            Income's id. NULL for direct opening_balance/adjustment rows
            and for expense-backed rows.
        expense_id: If this row is an Expense projection, the source
            Expense's id (VF-017E). NULL for direct opening_balance/
            adjustment rows and for income-backed rows.
        created_at: Record creation timestamp. For an income- or
            expense-backed row, this is the projection's own creation
            time and is never reset when the row is later synchronized
            (an amount/date sync or an Account move updates the existing
            row in place) or moved between Accounts.
    """

    __tablename__ = "account_transactions"

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_account_transactions_amount_positive"),
        CheckConstraint(
            "kind IN ('opening_balance','adjustment','income','expense')",
            name="ck_account_transactions_kind_valid",
        ),
        CheckConstraint(
            "direction IN ('credit','debit')",
            name="ck_account_transactions_direction_valid",
        ),
        # Combined source-linkage CHECK (VF-017E, replaces VF-017D's
        # income-only version): the three branches are mutually exclusive
        # by construction, since kind is a single scalar value - a row
        # can satisfy at most one, which is what makes "both income_id
        # and expense_id populated" and every other invalid combination
        # structurally impossible, not merely application-validated.
        CheckConstraint(
            "(kind = 'income' AND income_id IS NOT NULL AND expense_id IS NULL "
            "AND direction = 'credit') "
            "OR (kind = 'expense' AND expense_id IS NOT NULL AND income_id IS NULL "
            "AND direction = 'debit') "
            "OR (kind IN ('opening_balance','adjustment') "
            "AND income_id IS NULL AND expense_id IS NULL)",
            name="ck_account_transactions_source_linkage_valid",
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
        UniqueConstraint("income_id", name="uq_account_transactions_income_id"),
        UniqueConstraint("expense_id", name="uq_account_transactions_expense_id"),
        # Composite ownership FKs (VF-017D income, VF-017E expense):
        # account_id/income_id/expense_id must each agree with THIS row's
        # own user_id, not merely reference a valid id - this is what
        # makes a cross-user Income/Expense<->Account link impossible at
        # the database level. The existing plain account_id -> accounts.id
        # FK (below, on the column itself) remains as additional
        # defense-in-depth rather than being replaced.
        ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            name="fk_account_transactions_account_id_user_id",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["income_id", "user_id"],
            ["income.id", "income.user_id"],
            name="fk_account_transactions_income_id_user_id",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["expense_id", "user_id"],
            ["expenses.id", "expenses.user_id"],
            name="fk_account_transactions_expense_id_user_id",
            ondelete="CASCADE",
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

    income_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    expense_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
