from datetime import date as Date, datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ReceiptStatus = Literal[
    "uploaded",
    "processing",
    "processed",
    "confirmed",
    "failed",
]


class ReceiptCreate(BaseModel):
    """
    Schema for creating a receipt.

    What:
        Validates receipt metadata received from the client.

    Why:
        Keeps uploaded receipt data structured before OCR processing starts.
        The user_id must come from authentication data.
        The status must be controlled by the backend.
    """

    model_config = ConfigDict(extra="forbid")

    file_url: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional public or signed URL to the uploaded receipt file.",
        examples=["https://example.com/receipts/receipt-1.jpg"],
    )
    storage_path: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional internal storage path for the receipt file.",
        examples=["receipts/user-id/receipt-1.jpg"],
    )

    @model_validator(mode="after")
    def validate_create_payload(self) -> "ReceiptCreate":
        """
        Validates that receipt create request contains a file reference.

        What:
            Checks that at least one file reference is provided.

        Why:
            Prevents creating empty receipt records without an uploaded file.
        """

        if self.file_url is None and self.storage_path is None:
            raise ValueError("Either file_url or storage_path must be provided.")

        return self


class ReceiptUpdate(BaseModel):
    """
    Schema for updating a receipt.

    What:
        Validates partial receipt update data.

    Why:
        Allows the backend to update OCR fields, status, or expense linkage
        while rejecting empty update requests.
    """

    model_config = ConfigDict(extra="forbid")

    expense_id: Optional[UUID] = Field(
        default=None,
        description="Optional expense created from this receipt.",
    )
    file_url: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Updated public or signed URL to the receipt file.",
    )
    storage_path: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Updated internal storage path for the receipt file.",
    )
    status: Optional[ReceiptStatus] = Field(
        default=None,
        description="Updated receipt processing status.",
        examples=["processed"],
    )
    ocr_text: Optional[str] = Field(
        default=None,
        description="Raw OCR text extracted from the receipt.",
    )
    merchant_detected: Optional[str] = Field(
        default=None,
        max_length=120,
        description="Merchant name detected by OCR.",
        examples=["Lidl"],
    )
    total_amount_detected: Optional[Decimal] = Field(
        default=None,
        gt=0,
        description="Total amount detected by OCR.",
        examples=["24.99"],
    )
    currency_detected: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="Currency code detected by OCR.",
        examples=["EUR"],
    )
    purchase_date_detected: Optional[Date] = Field(
        default=None,
        description="Purchase date detected by OCR.",
        examples=["2026-07-25"],
    )

    @field_validator("currency_detected")
    @classmethod
    def normalize_currency_detected(cls, value: Optional[str]) -> Optional[str]:
        """
        Normalizes detected currency code.

        What:
            Converts currency code to uppercase.

        Why:
            Keeps API responses and database values consistent.
        """

        if value is None:
            return value

        return value.strip().upper()
    
    @field_validator("file_url", "storage_path")
    @classmethod
    def normalize_file_reference(cls, value: Optional[str]) -> Optional[str]:
        """
        Normalizes receipt file reference fields.

        What:
            Strips whitespace from file reference values.

        Why:
            Prevents empty strings from being accepted as valid file references.
        """

        if value is None:
            return value

        normalized_value = value.strip()

        if not normalized_value:
            return None

        return normalized_value

    @model_validator(mode="after")
    def validate_update_payload(self) -> "ReceiptUpdate":
        """
        Validates that the update request contains at least one field.

        What:
            Checks that the client sent at least one editable field.

        Why:
            Prevents empty PATCH requests that do not change anything.
        """

        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for receipt update.")

        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("Receipt status cannot be null.")

        return self


class ReceiptResponse(BaseModel):
    """
    Schema for returning receipt data.

    What:
        Defines the public API response shape for receipts.

    Why:
        Keeps database models separated from API response contracts.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    expense_id: Optional[UUID]
    file_url: Optional[str]
    storage_path: Optional[str]
    status: ReceiptStatus
    ocr_text: Optional[str]
    merchant_detected: Optional[str]
    total_amount_detected: Optional[Decimal]
    currency_detected: Optional[str]
    purchase_date_detected: Optional[Date]
    created_at: datetime
    updated_at: datetime