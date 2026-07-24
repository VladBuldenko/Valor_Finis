import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database_base import Base


class ReceiptModel(Base):
    """
    SQLAlchemy ORM model for the receipts table.

    What:
        Represents receipt records uploaded by users.

    Why:
        Allows the application to store receipt metadata, OCR results,
        and an optional connection to a confirmed expense.

    Fields:
        id: Unique receipt identifier.
        user_id: Owner of the receipt.
        expense_id: Optional expense created from this receipt.
        file_url: Optional public or signed URL to the uploaded receipt file.
        storage_path: Optional internal storage path for the receipt file.
        status: Processing status of the receipt.
        ocr_text: Raw OCR text extracted from the receipt.
        merchant_detected: Merchant name detected by OCR.
        total_amount_detected: Total amount detected by OCR.
        currency_detected: Currency code detected by OCR.
        purchase_date_detected: Purchase date detected by OCR.
        created_at: Record creation timestamp.
        updated_at: Record update timestamp.
    """

    __tablename__ = "receipts"

    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'processed', 'confirmed', 'failed')",
            name="ck_receipts_status_valid",
        ),
        CheckConstraint(
            "total_amount_detected IS NULL OR total_amount_detected > 0",
            name="ck_receipts_total_amount_detected_positive",
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

    expense_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("expenses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    file_url: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
    )

    storage_path: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="uploaded",
        server_default="uploaded",
        index=True,
    )

    ocr_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    merchant_detected: Mapped[Optional[str]] = mapped_column(
        String(120),
        nullable=True,
    )

    total_amount_detected: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    currency_detected: Mapped[Optional[str]] = mapped_column(
        String(3),
        nullable=True,
    )

    purchase_date_detected: Mapped[Optional[date]] = mapped_column(
        Date,
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