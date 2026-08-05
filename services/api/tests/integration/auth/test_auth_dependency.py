from uuid import uuid4

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.core.app_config import settings


# Tests that a protected endpoint rejects
# an invalid development user identifier.
# This test exists to verify the complete HTTP authentication flow
# from request headers through the FastAPI dependency.
# Parameters:
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to set authentication mode.
# Returns:
# - None.
def test_protected_endpoint_rejects_invalid_x_user_id(
    client: TestClient,
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings,
        "auth_mode",
        "development",
    )

    # Act
    response = client.get(
        "/api/v1/categories",
        headers={
            "X-User-Id": "not-a-valid-uuid",
        },
    )

    # Assert
    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid authentication user identifier.",
    }


# Tests that Supabase mode does not accept
# the temporary development X-User-Id header.
# This test exists to prevent development authentication
# from being used when Supabase authentication is enabled.
# Parameters:
# - client: FastAPI test client.
# - monkeypatch: pytest fixture used to set authentication mode.
# Returns:
# - None.
def test_protected_endpoint_rejects_x_user_id_in_supabase_mode(
    client: TestClient,
    monkeypatch: MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(
        settings,
        "auth_mode",
        "supabase",
    )

    # Act
    response = client.get(
        "/api/v1/categories",
        headers={
            "X-User-Id": str(uuid4()),
        },
    )

    # Assert
    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authorization bearer token is required.",
    }