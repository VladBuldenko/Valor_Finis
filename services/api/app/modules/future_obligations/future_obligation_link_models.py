import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base

# Constraint names, shared with the repository (which maps a violation to a domain
# error) and the migration.
UNIQUE_EXPENSE_CONSTRAINT = "uq_future_obligation_links_expense_id"
UNIQUE_OCCURRENCE_CONSTRAINT = "uq_future_obligation_links_obligation_id_due_date"


class FutureObligationExpenseLinkModel(Base):
    """
    SQLAlchemy ORM model for the future_obligation_expense_links table.

    What:
        One row says: "this recorded Expense corresponds to this scheduled bill
        occurrence". An occurrence is identified by (obligation_id, due_date); it is
        never stored on its own, so no row exists for an occurrence that has no
        Expense.

    Why:
        It is relationship metadata the user chose by hand. It is NOT a monetary
        transaction: it creates no Expense, posts nothing to an Account, changes no
        balance, Goal or analytics figure, and does not mean a bank payment was
        verified. Keeping the relation in its own table leaves both the Expense and
        the obligation exactly as they were.

    Fields:
        id: Unique identifier.
        user_id: Owner. Both foreign keys include it, so a link can never join
            records of two different users, whatever the application does.
        obligation_id: The obligation. ON DELETE RESTRICT: link history is never
            erased silently (obligations are archived, not deleted).
        due_date: The occurrence's due date, a real date of the obligation's
            schedule at the time of linking.
        expense_id: The linked Expense. ON DELETE RESTRICT: a linked Expense must be
            unlinked before it is deleted.
        created_at: When the link was made.

    Constraints: one link per Expense and one link per occurrence, so nothing is
    counted twice and nothing is silently reassigned.
    """

    __tablename__ = "future_obligation_expense_links"

    __table_args__ = (
        ForeignKeyConstraint(
            ["obligation_id", "user_id"],
            ["future_obligations.id", "future_obligations.user_id"],
            name="fk_future_obligation_links_obligation_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["expense_id", "user_id"],
            ["expenses.id", "expenses.user_id"],
            name="fk_future_obligation_links_expense_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("expense_id", name=UNIQUE_EXPENSE_CONSTRAINT),
        UniqueConstraint("obligation_id", "due_date", name=UNIQUE_OCCURRENCE_CONSTRAINT),
        CheckConstraint(
            "due_date BETWEEN DATE '2000-01-01' AND DATE '2100-12-31'",
            name="ck_future_obligation_links_due_date_range",
        ),
        # The overview reads a user's links in a date window.
        Index("ix_future_obligation_links_user_id_due_date", "user_id", "due_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    obligation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    expense_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
