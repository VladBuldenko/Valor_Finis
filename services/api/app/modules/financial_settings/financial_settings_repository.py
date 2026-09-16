from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.modules.financial_settings.financial_settings_models import (
    DEFAULT_BASE_CURRENCY,
    UserFinancialSettingsModel,
)


# Returns a user's financial settings, creating the default-EUR row on
# first access.
# This function exists to make "get me this user's settings" and "create
# them if this is the first time" one atomic, race-safe operation, since
# there is no signup hook in this backend (Supabase owns identity) to
# provision this row ahead of time.
# Parameters:
# - db_session: active SQLAlchemy database session.
# - user_id: authenticated user identifier that owns the settings row.
# - commit: whether the repository should commit the transaction
#   immediately. Must be False when this bootstrap runs inside a larger
#   caller-owned transaction (e.g. expense creation nested inside receipt
#   confirmation) so it never prematurely commits the caller's other
#   pending writes - the caller commits everything together instead.
#   Race safety does not depend on this commit: ON CONFLICT DO NOTHING is
#   enforced by PostgreSQL against the unique user_id constraint (via row
#   locking against any concurrent in-flight insert) regardless of when,
#   or whether, this particular transaction is committed.
# Returns:
# - UserFinancialSettingsModel instance, either just-created or pre-existing.
def get_or_create_financial_settings(
    db_session: Session,
    user_id: UUID,
    commit: bool = True,
) -> UserFinancialSettingsModel:
    # Target-less ON CONFLICT DO NOTHING, matching the same race-safe
    # first-use bootstrap pattern already established for default
    # categories (categories/repository.py:ensure_default_categories):
    # two concurrent first-access requests for the same user_id can both
    # attempt this insert without either raising IntegrityError - the
    # loser's insert is simply skipped, and the follow-up select below
    # returns the single row that actually landed.
    db_session.execute(
        pg_insert(UserFinancialSettingsModel)
        .values(
            user_id=user_id,
            base_currency=DEFAULT_BASE_CURRENCY,
        )
        .on_conflict_do_nothing()
    )

    if commit:
        db_session.commit()
    else:
        db_session.flush()

    return (
        db_session.query(UserFinancialSettingsModel)
        .filter(UserFinancialSettingsModel.user_id == user_id)
        .first()
    )
