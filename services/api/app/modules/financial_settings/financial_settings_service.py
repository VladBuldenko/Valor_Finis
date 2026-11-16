from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.financial_settings import financial_settings_repository
from app.modules.financial_settings.financial_settings_models import DEFAULT_BASE_CURRENCY
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
# - commit: whether the repository should commit the transaction
#   immediately. Pass False when a caller (e.g. expenses_service) is
#   composing this bootstrap into a larger transaction it will commit
#   itself.
# Returns:
# - UserFinancialSettingsResponse for the user's settings.
def get_or_create_financial_settings(
    db_session: Session,
    user_id: UUID,
    commit: bool = True,
) -> UserFinancialSettingsResponse:
    settings_model = financial_settings_repository.get_or_create_financial_settings(
        db_session=db_session,
        user_id=user_id,
        commit=commit,
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
# - commit: whether the underlying bootstrap should commit immediately.
#   Pass False when composing into a larger caller-owned transaction.
# Returns:
# - The user's base currency code, e.g. "EUR".
def get_base_currency(
    db_session: Session,
    user_id: UUID,
    commit: bool = True,
) -> str:
    settings = get_or_create_financial_settings(
        db_session=db_session,
        user_id=user_id,
        commit=commit,
    )

    return settings.base_currency


# Returns a user's base currency without writing anything.
# This function exists for read-only endpoints (VF-GOALS-PLANNING-002A):
# get_base_currency bootstraps the default-EUR settings row on first access,
# which is a write. A user with no settings row yet has, by definition, the
# default base currency - exactly what the bootstrap would store.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier that owns the settings row.
# Returns:
# - The user's base currency code, or the default when no row exists yet.
def get_base_currency_read_only(
    db_session: Session,
    user_id: UUID,
) -> str:
    settings_model = financial_settings_repository.get_financial_settings(
        db_session=db_session,
        user_id=user_id,
    )

    if settings_model is None:
        return DEFAULT_BASE_CURRENCY

    return settings_model.base_currency
