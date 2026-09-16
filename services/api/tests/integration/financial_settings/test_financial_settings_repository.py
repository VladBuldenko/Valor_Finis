import threading
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.db.database_session import SessionLocal
from app.modules.financial_settings import financial_settings_repository
from app.modules.financial_settings.financial_settings_models import (
    UserFinancialSettingsModel,
)


# Tests (A) that a user's first access creates exactly one settings row.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if exactly one row exists after the call.
def test_get_or_create_financial_settings_first_access_creates_one_row(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        # Act
        financial_settings_repository.get_or_create_financial_settings(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        rows = (
            db_session.query(UserFinancialSettingsModel)
            .filter(UserFinancialSettingsModel.user_id == user_id)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].base_currency == "EUR"
    finally:
        db_session.close()


# Tests (B) that repeated access for the same user never creates a second row.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if exactly one row exists after three calls.
def test_get_or_create_financial_settings_repeated_access_remains_one_row(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        # Act
        for _ in range(3):
            financial_settings_repository.get_or_create_financial_settings(
                db_session=db_session,
                user_id=user_id,
            )

        # Assert
        rows = (
            db_session.query(UserFinancialSettingsModel)
            .filter(UserFinancialSettingsModel.user_id == user_id)
            .all()
        )
        assert len(rows) == 1
    finally:
        db_session.close()


# Tests (C) that two different users each receive their own row.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if two independent rows exist, one per user.
def test_get_or_create_financial_settings_two_users_get_independent_rows(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_a = uuid4()
    user_b = uuid4()

    try:
        # Act
        financial_settings_repository.get_or_create_financial_settings(
            db_session=db_session,
            user_id=user_a,
        )
        financial_settings_repository.get_or_create_financial_settings(
            db_session=db_session,
            user_id=user_b,
        )

        # Assert
        assert (
            db_session.query(UserFinancialSettingsModel)
            .filter(UserFinancialSettingsModel.user_id == user_a)
            .count()
            == 1
        )
        assert (
            db_session.query(UserFinancialSettingsModel)
            .filter(UserFinancialSettingsModel.user_id == user_b)
            .count()
            == 1
        )
    finally:
        db_session.close()


# Tests (D) that an explicitly pre-existing row (with a value the lazy
# bootstrap would never itself write) is respected, not overwritten.
# This test exists to prove ON CONFLICT DO NOTHING truly does nothing to
# an existing row, rather than resetting it back to the EUR default.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the pre-seeded value survives the call.
def test_get_or_create_financial_settings_respects_existing_row(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        db_session.add(
            UserFinancialSettingsModel(user_id=user_id, base_currency="USD"),
        )
        db_session.commit()

        # Act
        settings_model = financial_settings_repository.get_or_create_financial_settings(
            db_session=db_session,
            user_id=user_id,
        )

        # Assert
        assert settings_model.base_currency == "USD"
        assert (
            db_session.query(UserFinancialSettingsModel)
            .filter(UserFinancialSettingsModel.user_id == user_id)
            .count()
            == 1
        )
    finally:
        db_session.close()


# Tests (E) that two genuinely concurrent first-access requests for the
# same user - each on its own thread and its own database session/
# connection - do not raise and still leave exactly one row.
# This test exists to verify the race-safety claim directly rather than
# only simulating it with sequential calls, using real concurrent
# PostgreSQL connections.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if both threads succeed and one row remains.
def test_get_or_create_financial_settings_concurrent_first_access_is_race_safe(
    clean_database: None,
) -> None:
    # Arrange
    user_id = uuid4()
    errors: list[Exception] = []

    def bootstrap_in_own_session() -> None:
        thread_session = SessionLocal()
        try:
            financial_settings_repository.get_or_create_financial_settings(
                db_session=thread_session,
                user_id=user_id,
            )
        except Exception as error:  # noqa: BLE001 - captured for the main thread to assert on
            errors.append(error)
        finally:
            thread_session.close()

    threads = [
        threading.Thread(target=bootstrap_in_own_session),
        threading.Thread(target=bootstrap_in_own_session),
    ]

    # Act
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Assert
    assert errors == []

    verification_session = SessionLocal()
    try:
        rows = (
            verification_session.query(UserFinancialSettingsModel)
            .filter(UserFinancialSettingsModel.user_id == user_id)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].base_currency == "EUR"
    finally:
        verification_session.close()


# Tests that the database primary key itself prevents a duplicate settings
# row for the same user, independent of the ON CONFLICT DO NOTHING
# bootstrap logic.
# This test exists as the required minimum DB-level guarantee: even a
# direct insert bypassing get_or_create_financial_settings cannot create
# a second row for one user_id.
# Parameters:
# - clean_database: Fixture that cleans database tables before and after the test.
# Returns:
# - None. The test passes if the duplicate raw insert raises IntegrityError.
def test_user_financial_settings_primary_key_rejects_duplicate_user_id(
    clean_database: None,
) -> None:
    # Arrange
    db_session = SessionLocal()
    user_id = uuid4()

    try:
        db_session.add(
            UserFinancialSettingsModel(user_id=user_id, base_currency="EUR"),
        )
        db_session.commit()

        db_session.add(
            UserFinancialSettingsModel(user_id=user_id, base_currency="USD"),
        )

        # Act / Assert
        try:
            db_session.commit()
            assert False, "expected IntegrityError for duplicate user_id"
        except IntegrityError:
            db_session.rollback()
    finally:
        db_session.close()
