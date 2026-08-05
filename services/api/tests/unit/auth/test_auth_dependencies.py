from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError
from urllib.request import Request
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from pytest import MonkeyPatch
from email.message import Message

from app.core.app_config import settings
from app.modules.auth import auth_dependencies
from app.modules.auth.auth_schemas import CurrentUser

# Creates a mocked urlopen response with the provided body.
# This helper exists to simulate Supabase HTTP responses
# without making real network requests.
# Parameters:
# - response_body: raw response body returned by Supabase.
# Returns:
# - MagicMock configured as a context manager response.
def create_urlopen_response(
    response_body: bytes,
) -> MagicMock:
    response = MagicMock()
    response.read.return_value = response_body
    response.__enter__.return_value = response
    response.__exit__.return_value = False

    return response


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
# This test exists to verify that only the Bearer authentication scheme
# is accepted.
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
# This test exists to verify that the Authorization header
# must contain a token value.
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
# This test exists to keep local development
# and existing integration tests supported.
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
        x_user_id=str(user_id),
    )

    # Assert
    assert isinstance(current_user, CurrentUser)
    assert current_user.id == user_id


# Tests that development mode rejects an invalid X-User-Id.
# This test exists to return an authentication error
# instead of accepting a malformed user identifier.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None. The test passes if HTTP 401 is raised.
def test_get_current_user_rejects_invalid_x_user_id_in_development(
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
        auth_dependencies.get_current_user(
            x_user_id="not-a-valid-uuid",
        )

    # Assert
    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert error.value.detail == "Invalid authentication user identifier."


# Tests that development mode rejects requests
# without authentication credentials.
# This test exists to verify missing auth handling when neither
# Authorization nor X-User-Id is provided.
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


# Tests that Supabase mode rejects the X-User-Id fallback
# when Authorization is missing.
# This test exists to verify that production authentication
# requires a bearer token.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None. The test passes if HTTP 401 is raised.
def test_get_current_user_requires_bearer_token_in_supabase_mode(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    user_id = uuid4()

    monkeypatch.setattr(
        settings,
        "auth_mode",
        "supabase",
    )

    # Act
    with pytest.raises(HTTPException) as error:
        auth_dependencies.get_current_user(
            x_user_id=str(user_id),
        )

    # Assert
    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert error.value.detail == "Authorization bearer token is required."


# Tests that the Authorization bearer token is used when provided.
# This test exists to verify that JWT authentication
# has priority over the X-User-Id development fallback.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None. The test passes if CurrentUser is returned
#   from the bearer token flow.
def test_get_current_user_uses_authorization_bearer_token(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    user_id = uuid4()
    other_user_id = uuid4()

    monkeypatch.setattr(
        settings,
        "auth_mode",
        "development",
    )

    def fake_get_current_user_from_supabase_token(
        token: str,
    ) -> CurrentUser:
        assert token == "valid.jwt.token"

        return CurrentUser(
            id=user_id,
        )

    monkeypatch.setattr(
        auth_dependencies,
        "get_current_user_from_supabase_token",
        fake_get_current_user_from_supabase_token,
    )

    # Act
    current_user = auth_dependencies.get_current_user(
        authorization="Bearer valid.jwt.token",
        x_user_id=str(other_user_id),
    )

    # Assert
    assert current_user.id == user_id
    assert current_user.id != other_user_id


# Tests that a Supabase user payload is converted to CurrentUser.
# This test exists to verify that the Supabase user id
# becomes the internal current user id.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None. The test passes if CurrentUser contains
#   the Supabase user identifier.
def test_get_current_user_from_supabase_token_returns_current_user(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    user_id = uuid4()

    def fake_get_supabase_user_payload(
        token: str,
    ) -> dict[str, str]:
        assert token == "valid.jwt.token"

        return {
            "id": str(user_id),
        }

    monkeypatch.setattr(
        auth_dependencies,
        "get_supabase_user_payload",
        fake_get_supabase_user_payload,
    )

    # Act
    current_user = (
        auth_dependencies.get_current_user_from_supabase_token(
            token="valid.jwt.token",
        )
    )

    # Assert
    assert isinstance(current_user, CurrentUser)
    assert current_user.id == user_id


# Tests that a Supabase user payload without id is rejected.
# This test exists to verify that authentication cannot continue
# without a valid user identifier.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None. The test passes if HTTP 401 is raised.
def test_get_current_user_from_supabase_token_rejects_payload_without_user_id(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    def fake_get_supabase_user_payload(
        token: str,
    ) -> dict[str, str]:
        assert token == "valid.jwt.token"

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


# Tests that a Supabase user payload with an invalid UUID is rejected.
# This test exists to verify that internal CurrentUser
# always receives a valid UUID.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None. The test passes if HTTP 401 is raised.
def test_get_current_user_from_supabase_token_rejects_invalid_user_id(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    def fake_get_supabase_user_payload(
        token: str,
    ) -> dict[str, str]:
        assert token == "valid.jwt.token"

        return {
            "id": "not-a-valid-uuid",
        }

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
# This test exists to verify configuration validation
# before Supabase Auth calls.
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


# Tests that configured Supabase settings are returned.
# This test exists to verify that Supabase configuration values
# are normalized before use.
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

    # Tests that a valid Supabase response returns the user payload.
# This test exists to verify request construction
# and successful Supabase response parsing.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None.
def test_get_supabase_user_payload_returns_user_payload(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    user_id = uuid4()

    monkeypatch.setattr(
        settings,
        "supabase_url",
        "https://example.supabase.co",
    )
    monkeypatch.setattr(
        settings,
        "supabase_publishable_key",
        "publishable-key",
    )

    response = create_urlopen_response(
        response_body=(
            f'{{"id": "{user_id}", "email": "user@example.com"}}'
        ).encode("utf-8"),
    )

    def fake_urlopen(
        request: Request,
        timeout: int,
    ) -> MagicMock:
        assert request.full_url == (
            "https://example.supabase.co/auth/v1/user"
        )
        assert request.get_method() == "GET"
        assert timeout == 5

        headers = {
            name.lower(): value
            for name, value in request.header_items()
        }

        assert headers["apikey"] == "publishable-key"
        assert headers["authorization"] == (
            "Bearer valid.jwt.token"
        )

        return response

    monkeypatch.setattr(
        auth_dependencies,
        "urlopen",
        fake_urlopen,
    )

    # Act
    payload = auth_dependencies.get_supabase_user_payload(
        token="valid.jwt.token",
    )

    # Assert
    assert payload == {
        "id": str(user_id),
        "email": "user@example.com",
    }

    # Tests that rejected Supabase tokens are mapped to HTTP 401.
# This test exists to handle invalid, expired,
# or unauthorized authentication tokens consistently.
# Parameters:
# - supabase_status_code: HTTP status returned by Supabase.
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None.
@pytest.mark.parametrize(
    "supabase_status_code",
    [
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    ],
)
def test_get_supabase_user_payload_rejects_invalid_token(
    supabase_status_code: int,
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings,
        "supabase_url",
        "https://example.supabase.co",
    )
    monkeypatch.setattr(
        settings,
        "supabase_publishable_key",
        "publishable-key",
    )

    def fake_urlopen(
        request: Request,
        timeout: int,
    ) -> MagicMock:
        raise HTTPError(
            url=request.full_url,
            code=supabase_status_code,
            msg="Authentication failed",
            hdrs=Message(),
            fp=None,
        )

    monkeypatch.setattr(
        auth_dependencies,
        "urlopen",
        fake_urlopen,
    )

    # Act
    with pytest.raises(HTTPException) as error:
        auth_dependencies.get_supabase_user_payload(
            token="invalid.jwt.token",
        )

    # Assert
    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert error.value.detail == (
        "Invalid or expired authentication token."
    )

    # Tests that unexpected Supabase HTTP errors are mapped to HTTP 503.
# This test exists to distinguish authentication failures
# from temporary Supabase service failures.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None.
def test_get_supabase_user_payload_maps_http_error_to_service_unavailable(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings,
        "supabase_url",
        "https://example.supabase.co",
    )
    monkeypatch.setattr(
        settings,
        "supabase_publishable_key",
        "publishable-key",
    )

    def fake_urlopen(
        request: Request,
        timeout: int,
    ) -> MagicMock:
        raise HTTPError(
            url=request.full_url,
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            msg="Internal server error",
            hdrs=Message(),
            fp=None,
        )

    monkeypatch.setattr(
        auth_dependencies,
        "urlopen",
        fake_urlopen,
    )

    # Act
    with pytest.raises(HTTPException) as error:
        auth_dependencies.get_supabase_user_payload(
            token="valid.jwt.token",
        )

    # Assert
    assert error.value.status_code == (
        status.HTTP_503_SERVICE_UNAVAILABLE
    )
    assert error.value.detail == (
        "Supabase authentication service is unavailable."
    )

    # Tests that network failures are mapped to HTTP 503.
# This test exists to return a controlled response
# when Supabase Auth cannot be reached.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None.
def test_get_supabase_user_payload_maps_network_error_to_service_unavailable(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings,
        "supabase_url",
        "https://example.supabase.co",
    )
    monkeypatch.setattr(
        settings,
        "supabase_publishable_key",
        "publishable-key",
    )

    def fake_urlopen(
        request: Request,
        timeout: int,
    ) -> MagicMock:
        raise URLError(
            reason="Connection refused",
        )

    monkeypatch.setattr(
        auth_dependencies,
        "urlopen",
        fake_urlopen,
    )

    # Act
    with pytest.raises(HTTPException) as error:
        auth_dependencies.get_supabase_user_payload(
            token="valid.jwt.token",
        )

    # Assert
    assert error.value.status_code == (
        status.HTTP_503_SERVICE_UNAVAILABLE
    )
    assert error.value.detail == (
        "Supabase authentication service is unavailable."
    )

    # Tests that an invalid Supabase JSON response is rejected.
# This test exists to prevent malformed external responses
# from entering the authentication flow.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None.
def test_get_supabase_user_payload_rejects_invalid_json(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings,
        "supabase_url",
        "https://example.supabase.co",
    )
    monkeypatch.setattr(
        settings,
        "supabase_publishable_key",
        "publishable-key",
    )

    response = create_urlopen_response(
        response_body=b"not-valid-json",
    )

    monkeypatch.setattr(
        auth_dependencies,
        "urlopen",
        lambda request, timeout: response,
    )

    # Act
    with pytest.raises(HTTPException) as error:
        auth_dependencies.get_supabase_user_payload(
            token="valid.jwt.token",
        )

    # Assert
    assert error.value.status_code == (
        status.HTTP_503_SERVICE_UNAVAILABLE
    )
    assert error.value.detail == (
        "Invalid Supabase authentication response."
    )

    # Tests that a non-object Supabase JSON response is rejected.
# This test exists to ensure authentication always receives
# a dictionary with user attributes.
# Parameters:
# - monkeypatch: pytest monkeypatch fixture.
# Returns:
# - None.
def test_get_supabase_user_payload_rejects_non_object_json(
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings,
        "supabase_url",
        "https://example.supabase.co",
    )
    monkeypatch.setattr(
        settings,
        "supabase_publishable_key",
        "publishable-key",
    )

    response = create_urlopen_response(
        response_body=b'["unexpected", "list"]',
    )

    monkeypatch.setattr(
        auth_dependencies,
        "urlopen",
        lambda request, timeout: response,
    )

    # Act
    with pytest.raises(HTTPException) as error:
        auth_dependencies.get_supabase_user_payload(
            token="valid.jwt.token",
        )

    # Assert
    assert error.value.status_code == (
        status.HTTP_503_SERVICE_UNAVAILABLE
    )
    assert error.value.detail == (
        "Invalid Supabase authentication response."
    )