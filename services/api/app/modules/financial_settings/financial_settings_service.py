from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.financial_settings import financial_settings_repository
from app.modules.financial_settings.financial_settings_schemas import (
    UserFinancialSettingsResponse,
)


# Returns a user's financial settings, creating the default-EUR row on
# first access.
# This function exists as the internal domain seam VF-014B5C's Expense FX
# resolution will consume, and to keep response mapping outside the
# repository layer.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier that owns the settings row.
#   Always sourced from authenticated identity, never request payload data.
# Returns:
# - UserFinancialSettingsResponse for the user's settings.
def get_or_create_financial_settings(
    db_session: Session,
    user_id: UUID,
) -> UserFinancialSettingsResponse:
    settings_model = financial_settings_repository.get_or_create_financial_settings(
        db_session=db_session,
        user_id=user_id,
    )

    return UserFinancialSettingsResponse.model_validate(settings_model)


# Returns a user's base currency, creating their default-EUR settings row
# on first access.
# This function exists as the single, narrow seam other modules (starting
# with VF-014B5C) should call when they only need the currency code, not
# the full settings object.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier that owns the settings row.
# Returns:
# - The user's base currency code, e.g. "EUR".
def get_base_currency(
    db_session: Session,
    user_id: UUID,
) -> str:
    settings = get_or_create_financial_settings(
        db_session=db_session,
        user_id=user_id,
    )

    return settings.base_currency
