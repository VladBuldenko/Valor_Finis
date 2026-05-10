from pydantic import BaseModel, Field


class CategoryResponse(BaseModel):
    """
    Schema for returning category data.

    This schema defines how an expense category
    is represented in API responses.

    Fields:
    - key: internal category value used by backend
    - name: human-readable category name
    """

    key: str = Field(
        ...,
        description="Internal category key used by the backend.",
        examples=["food"],
    )

    name: str = Field(
        ...,
        description="Human-readable category name.",
        examples=["Food"],
    )