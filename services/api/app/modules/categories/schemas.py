from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CategoryBase(BaseModel):
    """
    Base category schema.

    What:
        Contains fields shared by category create, update, and response schemas.

    Why:
        Prevents duplication of common category fields.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=80,
        description="Human-readable category name.",
        examples=["Food"],
    )
    color: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Optional UI color for the category.",
        examples=["#22C55E"],
    )
    icon: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Optional UI icon name for the category.",
        examples=["shopping-cart"],
    )


class CategoryCreate(CategoryBase):
    """
    Schema for creating a category.

    What:
        Validates category data received from the client.

    Why:
        The client should provide only editable category fields.
        The user_id must come from authentication data.
        The is_default flag must be controlled by the backend.
    """

    model_config = ConfigDict(extra="forbid")


class CategoryUpdate(BaseModel):
    """
    Schema for updating a category.

    What:
        Validates partial category update data.

    Why:
        Allows updating only selected editable fields while rejecting
        empty update requests.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=80,
        description="Updated human-readable category name.",
        examples=["Groceries"],
    )
    color: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Updated UI color for the category.",
        examples=["#22C55E"],
    )
    icon: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Updated UI icon name for the category.",
        examples=["shopping-cart"],
    )

    @model_validator(mode="after")
    def validate_update_payload(self) -> "CategoryUpdate":
        """
        Validates that the update request contains at least one field.

        What:
            Checks that the client sent at least one editable field.

        Why:
            Prevents empty PATCH/PUT requests that do not change anything.
        """

        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for category update.")

        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Category name cannot be null.")

        return self


class CategoryResponse(CategoryBase):
    """
    Schema for returning category data.

    What:
        Defines the public API response shape for categories.

    Why:
        Keeps database models separated from API response contracts.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    is_default: bool
    created_at: datetime
    updated_at: datetime