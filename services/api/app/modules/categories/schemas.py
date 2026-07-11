from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CategoryBase(BaseModel):
    """
    Base schema containing fields shared by category operations.

    What:
        Defines common category fields.

    Why:
        Prevents duplication between create and response schemas.
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

    is_default: bool = Field(
        default=False,
        description="Shows whether this category is a default system category.",
    )


class CategoryCreate(CategoryBase):
    """
    Schema for creating a new category.

    What:
        Validates incoming category data before it reaches service and repository layers.

    Why:
        Keeps invalid client input away from business and database logic.
        The user_id is not accepted from the client because it must come
        from authentication data.
    """

    model_config = ConfigDict(extra="forbid")


class CategoryResponse(CategoryBase):
    """
    Schema for returning category data.

    What:
        Defines the public API response shape for categories.

    Why:
        Keeps the database model separated from the API contract.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime