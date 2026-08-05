import json
from typing import Annotated, Any, Optional, Union, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from fastapi import Header, HTTPException, status

from app.core.app_config import settings
from app.modules.auth.auth_schemas import CurrentUser


# Extracts a bearer token from the Authorization header.
# This function exists to keep Authorization header parsing isolated
# from the main current-user dependency.
# Parameters:
# - authorization: raw Authorization header value.
# Returns:
# - Bearer token string.
# Raises:
# - HTTPException 401 when the Authorization header is invalid.
def extract_bearer_token(authorization: str) -> str:
    auth_scheme = "Bearer "

    if not authorization.startswith(auth_scheme):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header.",
        )

    token = authorization.removeprefix(auth_scheme).strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )

    return token


# Returns configured Supabase authentication settings.
# This function exists to keep configuration validation in one place.
# Parameters:
# - None.
# Returns:
# - Tuple with Supabase URL and publishable key.
# Raises:
# - HTTPException 500 when Supabase authentication settings are missing.
def get_supabase_auth_settings() -> tuple[str, str]:
    supabase_url = settings.supabase_url
    supabase_publishable_key = settings.supabase_publishable_key

    if not supabase_url or not supabase_publishable_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase authentication is not configured.",
        )

    return (
        supabase_url.rstrip("/"),
        supabase_publishable_key,
    )


# Validates a Supabase JWT access token and returns the Supabase user payload.
# This function exists to isolate communication with Supabase Auth.
# Parameters:
# - token: Supabase JWT access token.
# Returns:
# - Dictionary with Supabase user data.
# Raises:
# - HTTPException 401 when the token is invalid or expired.
# - HTTPException 503 when Supabase Auth cannot be reached.
def get_supabase_user_payload(token: str) -> dict[str, Any]:
    supabase_url, supabase_publishable_key = get_supabase_auth_settings()

    request = Request(
        url=f"{supabase_url}/auth/v1/user",
        method="GET",
        headers={
            "apikey": supabase_publishable_key,
            "Authorization": f"Bearer {token}",
        },
    )

    try:
        with urlopen(request, timeout=5) as response:
            response_body = response.read()
    except HTTPError as error:
        if error.code in {
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        }:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication token.",
            ) from error

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase authentication service is unavailable.",
        ) from error
    except URLError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase authentication service is unavailable.",
        ) from error

    try:
        payload = json.loads(
            response_body.decode("utf-8"),
        )
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid Supabase authentication response.",
        ) from error

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid Supabase authentication response.",
        )

    return cast(dict[str, Any], payload)


# Resolves the current user from a Supabase JWT token.
# This function exists to validate production authentication data
# and convert Supabase user data into the internal CurrentUser schema.
# Parameters:
# - token: Supabase JWT access token.
# Returns:
# - CurrentUser object resolved from the JWT token.
# Raises:
# - HTTPException 401 when the token does not resolve to a valid user.
def get_current_user_from_supabase_token(
    token: str,
) -> CurrentUser:
    user_payload = get_supabase_user_payload(
        token=token,
    )

    user_id = user_payload.get("id")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication user payload.",
        )

    try:
        return CurrentUser(
            id=UUID(str(user_id)),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication user identifier.",
        ) from error


# Resolves the current user from the temporary development header.
# This function exists to keep development authentication parsing
# separate from production Supabase authentication.
# Parameters:
# - x_user_id: raw or already parsed user identifier.
# Returns:
# - CurrentUser object resolved from the development header.
# Raises:
# - HTTPException 401 when the user identifier is invalid.
def get_current_user_from_development_header(
    x_user_id: Union[str, UUID],
) -> CurrentUser:
    try:
        return CurrentUser(
            id=UUID(str(x_user_id)),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication user identifier.",
        ) from error


# Resolves the current user from request authentication data.
# This dependency exists to support Supabase JWT authentication in production
# while keeping the temporary X-User-Id header available only in development.
# Parameters:
# - authorization: optional Authorization header with Bearer token.
# - x_user_id: temporary user identifier passed through the X-User-Id header.
# Returns:
# - CurrentUser object with the resolved user id.
# Raises:
# - HTTPException 401 when authentication data is missing or invalid.
def get_current_user(
    authorization: Annotated[
        Optional[str],
        Header(alias="Authorization"),
    ] = None,
    x_user_id: Annotated[
        Optional[str],
        Header(alias="X-User-Id"),
    ] = None,
) -> CurrentUser:
    if authorization is not None:
        token = extract_bearer_token(
            authorization=authorization,
        )

        return get_current_user_from_supabase_token(
            token=token,
        )

    if settings.auth_mode == "development":
        if x_user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication credentials.",
            )

        return get_current_user_from_development_header(
            x_user_id=x_user_id,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authorization bearer token is required.",
    )