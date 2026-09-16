from uuid import uuid4

from app.db.database_session import SessionLocal
from app.modules.financial_settings import financial_settings_service
from app.modules.financial_settings.financial_settings_schemas import (
    UserFinancialSettingsResponse,
)


# Tests that a user's first access creates a settings row defaulting to EUR.
# This test exists to verify the lazy-bootstrap default, since there is no
# signup hook that provisions this row ahead of time.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the returned settings default to EUR.
def test_get_or_create_financial_settings_first_access_defaults_to_eur(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        # Act
        settings = financial_settings_service.get_or_create_financial_settings(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert isinstance(settings, UserFinancialSettingsResponse)
        assert settings.user_id == user_id
        assert settings.base_currency == "EUR"
        assert settings.created_at is not None
        assert settings.updated_at is not None
    finally:
        db_session.close()


# Tests that a second access for the same user returns the same settings
# without creating a duplicate row.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both calls return identical values.
def test_get_or_create_financial_settings_second_access_returns_same_settings(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        # Act
        first_settings = financial_settings_service.get_or_create_financial_settings(
            db_session=db_session,
            user_id=user_id,
        )
        second_settings = financial_settings_service.get_or_create_financial_settings(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert first_settings.user_id == second_settings.user_id
        assert first_settings.base_currency == second_settings.base_currency
        assert first_settings.created_at == second_settings.created_at
    finally:
        db_session.close()


# Tests that get_base_currency returns the plain EUR string seam that
# other modules (starting with VF-014B5C) will consume.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if get_base_currency returns "EUR".
def test_get_base_currency_returns_eur_for_new_user(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        # Act
        base_currency = financial_settings_service.get_base_currency(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert base_currency == "EUR"
    finally:
        db_session.close()


# Tests that two different users receive independent settings rows.
# This test exists to verify ownership isolation: the backend-supplied
# user_id, not any client input, scopes each settings row.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if each user's settings carry their own user_id.
def test_get_or_create_financial_settings_users_are_independent(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_a = uuid4()
    user_b = uuid4()

    try:
        # Act
        settings_a = financial_settings_service.get_or_create_financial_settings(
            db_session=db_session,
            user_id=user_a,
        )
        settings_b = financial_settings_service.get_or_create_financial_settings(
            db_session=db_session,
            user_id=user_b,
        )

        # Assert
        assert settings_a.user_id == user_a
        assert settings_b.user_id == user_b
        assert settings_a.user_id != settings_b.user_id
        assert settings_a.base_currency == "EUR"
        assert settings_b.base_currency == "EUR"
    finally:
        db_session.close()
