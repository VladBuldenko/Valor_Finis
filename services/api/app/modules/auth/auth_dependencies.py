from typing import Annotated, Optional
from uuid import UUID

from fastapi import Header, HTTPException, status

from app.modules.auth.auth_schemas import CurrentUser


# Resolves the current user from the temporary X-User-Id header.
# This dependency exists as a temporary bridge before Supabase JWT authentication.
# Parameters:
# - x_user_id: user identifier passed through the X-User-Id request header.
# Returns:
# - CurrentUser object with the resolved user id.
# Raises:
# - HTTPException 401 when the X-User-Id header is missing.
def get_current_user(
    x_user_id: Annotated[
        Optional[UUID],
        Header(alias="X-User-Id"),
    ] = None,
) -> CurrentUser:
    if x_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-User-Id header.",
        )

    return CurrentUser(id=x_user_id)