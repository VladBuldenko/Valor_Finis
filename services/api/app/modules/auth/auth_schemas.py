from uuid import UUID

from pydantic import BaseModel


class CurrentUser(BaseModel):
    """
    Schema for the currently authenticated user.

    What:
        Represents the user resolved from authentication data.

    Why:
        Keeps authentication data structured and reusable across routers.

    Attributes:
        id: Unique user identifier.
    """

    id: UUID