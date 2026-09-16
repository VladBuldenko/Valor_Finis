from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserFinancialSettingsResponse(BaseModel):
    """
    Schema for a user's financial settings.

    What:
        Represents the authoritative financial-domain settings owned by
        one user.

    Why:
        Keeps the database model separated from any future public API
        contract. No router exposes this in VF-014B5B - this exists so
        the service layer follows the same Response-schema convention as
        every other module, ready for B5C's internal consumption.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    base_currency: str = Field(
        ...,
        description="The user's base currency for normalized financial data.",
        examples=["EUR"],
    )
    created_at: datetime
    updated_at: datetime
