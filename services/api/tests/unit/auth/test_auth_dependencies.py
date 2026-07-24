from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from pytest import MonkeyPatch

from app.core.app_config import settings
from app.modules.auth import auth_dependencies
from app.modules.auth.auth_schemas import CurrentUser


# Tests that a valid Authorization header returns the bearer token.
# This test exists to verify token extraction before JWT validation.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the extracted token is correct.
def test_extract_bearer_token_returns_token() -> None:
    # Arrange
    token = "valid.jwt.token"

    # Act
    extracted_token = auth_dependencies.extract_bearer_token(
        authorization=f"Bearer {token}",
    )

    # Assert
    assert extracted_token == token


# Tests that an invalid Authorization header is rejected.
# This test exists to verify that only Bearer authentication scheme is accepted.
# Parameters:
# - None.
# Returns:
# - None. The test passes if HTTP 401 is raised.
def test_extract_bearer_token_rejects_invalid_authorization_header() -> None:
    # Act
    with pytest.raises(HTTPException) as error:
        auth_dependencies.extract_bearer_token(
            authorization="Token invalid.jwt.token",
        )

    # Assert
    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert error.value.detail == "Invalid Authorization header."


# Tests that an empty bearer token is rejected.
# This test exists to verify that Authorization header must contain a token value.
# Parameters:
# - None.
# Returns:
# - None. The test passes if HTTP 401 is raised.
def test_extract_bearer_token_rejects_missing_token() -> None:
    # Act
    with pytest.raises(HTTPException) as error:
        auth_dependencies.extract_bearer_token(
            authorization="Bearer ",
        )

    # Assert
    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert error.value.detail == "Missing bearer token."


# Tests that development mode allows X-User-Id authentication.
# This test exists to keep local development and existing integration tests supported.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None. The test passes if CurrentUser is returned from X-User-Id.
def test_get_current_user_allows_x_user_id_in_development(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    user_id = uuid4()

    monkeypatch.setattr(
        settings,
        "auth_mode",
        "development",
    )

    # Act
    current_user = auth_dependencies.get_current_user(
        x_user_id=user_id,
    )

    # Assert
    assert isinstance(current_user, CurrentUser)
    assert current_user.id == user_id


# Tests that development mode rejects requests without authentication credentials.
# This test exists to verify missing auth handling when neither Authorization nor X-User-Id is provided.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None. The test passes if HTTP 401 is raised.
def test_get_current_user_rejects_missing_credentials_in_development(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings,
        "auth_mode",
        "development",
    )

    # Act
    with pytest.raises(HTTPException) as error:
        auth_dependencies.get_current_user()

    # Assert
    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert error.value.detail == "Missing authentication credentials."


# Tests that production mode rejects X-User-Id fallback when Authorization is missing.
# This test exists to verify that production authentication requires a bearer token.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None. The test passes if HTTP 401 is raised.
def test_get_current_user_requires_bearer_token_in_production(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    user_id = uuid4()

    monkeypatch.setattr(
        settings,
        "auth_mode",
        "production",
    )

    # Act
    with pytest.raises(HTTPException) as error:
        auth_dependencies.get_current_user(
            x_user_id=user_id,
        )

    # Assert
    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert error.value.detail == "Authorization bearer token is required."


# Tests that Authorization bearer token is used when provided.
# This test exists to verify that JWT authentication has priority over X-User-Id fallback.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None. The test passes if CurrentUser is returned from the bearer token flow.
def test_get_current_user_uses_authorization_bearer_token(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    user_id = uuid4()
    other_user_id = uuid4()

    def fake_get_current_user_from_supabase_token(token: str) -> CurrentUser:
        assert token == "valid.jwt.token"
        return CurrentUser(id=user_id)

    monkeypatch.setattr(
        auth_dependencies,
        "get_current_user_from_supabase_token",
        fake_get_current_user_from_supabase_token,
    )

    # Act
    current_user = auth_dependencies.get_current_user(
        authorization="Bearer valid.jwt.token",
        x_user_id=other_user_id,
    )

    # Assert
    assert current_user.id == user_id
    assert current_user.id != other_user_id


# Tests that Supabase user payload is converted to CurrentUser.
# This test exists to verify that the Supabase user id becomes the internal current user id.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None. The test passes if CurrentUser contains the Supabase user id.
def test_get_current_user_from_supabase_token_returns_current_user(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    user_id = uuid4()

    def fake_get_supabase_user_payload(token: str) -> dict[str, str]:
        assert token == "valid.jwt.token"
        return {"id": str(user_id)}

    monkeypatch.setattr(
        auth_dependencies,
        "get_supabase_user_payload",
        fake_get_supabase_user_payload,
    )

    # Act
    current_user = auth_dependencies.get_current_user_from_supabase_token(
        token="valid.jwt.token",
    )

    # Assert
    assert isinstance(current_user, CurrentUser)
    assert current_user.id == user_id


# Tests that Supabase user payload without id is rejected.
# This test exists to verify that authentication cannot continue without a valid user id.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None. The test passes if HTTP 401 is raised.
def test_get_current_user_from_supabase_token_rejects_payload_without_user_id(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    def fake_get_supabase_user_payload(token: str) -> dict[str, str]:
        return {}

    monkeypatch.setattr(
        auth_dependencies,
        "get_supabase_user_payload",
        fake_get_supabase_user_payload,
    )

    # Act
    with pytest.raises(HTTPException) as error:
        auth_dependencies.get_current_user_from_supabase_token(
            token="valid.jwt.token",
        )

    # Assert
    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert error.value.detail == "Invalid authentication user payload."


# Tests that Supabase user payload with invalid UUID is rejected.
# This test exists to verify that internal CurrentUser always receives a valid UUID.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None. The test passes if HTTP 401 is raised.
def test_get_current_user_from_supabase_token_rejects_invalid_user_id(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    def fake_get_supabase_user_payload(token: str) -> dict[str, str]:
        return {"id": "not-a-valid-uuid"}

    monkeypatch.setattr(
        auth_dependencies,
        "get_supabase_user_payload",
        fake_get_supabase_user_payload,
    )

    # Act
    with pytest.raises(HTTPException) as error:
        auth_dependencies.get_current_user_from_supabase_token(
            token="valid.jwt.token",
        )

    # Assert
    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert error.value.detail == "Invalid authentication user identifier."


# Tests that missing Supabase settings are rejected.
# This test exists to verify configuration validation before Supabase Auth calls.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None. The test passes if HTTP 500 is raised.
def test_get_supabase_auth_settings_rejects_missing_settings(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings,
        "supabase_url",
        None,
    )
    monkeypatch.setattr(
        settings,
        "supabase_publishable_key",
        None,
    )

    # Act
    with pytest.raises(HTTPException) as error:
        auth_dependencies.get_supabase_auth_settings()

    # Assert
    assert error.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert error.value.detail == "Supabase authentication is not configured."


# Tests that Supabase settings are returned when configured.
# This test exists to verify that configured Supabase values are normalized before use.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None. The test passes if settings are returned correctly.
def test_get_supabase_auth_settings_returns_configured_settings(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings,
        "supabase_url",
        "https://example.supabase.co/",
    )
    monkeypatch.setattr(
        settings,
        "supabase_publishable_key",
        "publishable-key",
    )

    # Act
    supabase_url, supabase_publishable_key = (
        auth_dependencies.get_supabase_auth_settings()
    )

    # Assert
    assert supabase_url == "https://example.supabase.co"
    assert supabase_publishable_key == "publishable-key"