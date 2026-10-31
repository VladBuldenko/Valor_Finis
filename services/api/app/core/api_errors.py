from typing import Dict, Mapping, Optional

from fastapi import HTTPException, status


# Stable public error codes for HTTP errors that do not come from a domain
# exception. Codes are written out explicitly: they are never derived from an
# exception class name or from a message, and a published code is never renamed
# or reused (see docs/api-contract.md, section 13).
VALIDATION_ERROR_CODE = "validation_error"
INTERNAL_SERVER_ERROR_CODE = "internal_server_error"
HTTP_ERROR_FALLBACK_CODE = "http_error"

# Fallback code by status for an HTTPException that carries no explicit code
# (Starlette's own 404/405, a plain HTTPException raised by a dependency).
HTTP_STATUS_ERROR_CODES: Dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_413_CONTENT_TOO_LARGE: "payload_too_large",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "unprocessable_content",
    status.HTTP_429_TOO_MANY_REQUESTS: "too_many_requests",
    status.HTTP_500_INTERNAL_SERVER_ERROR: INTERNAL_SERVER_ERROR_CODE,
    status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
}


# An HTTPException with an explicit, stable public error code.
# This class exists so authentication and router-level errors keep their
# existing status, detail and headers and only gain a `code`.
class ApiHTTPException(HTTPException):
    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail=detail,
            headers=dict(headers) if headers is not None else None,
        )
        self.code = code


# Returns the public code for an HTTPException.
# Parameters:
# - error: HTTPException raised by the application, FastAPI or Starlette.
# Returns:
# - The explicit code when the exception carries one, otherwise the fixed
#   code for its status, otherwise the generic http_error code.
def resolve_http_error_code(error: HTTPException) -> str:
    explicit_code = getattr(error, "code", None)

    if isinstance(explicit_code, str):
        return explicit_code

    return HTTP_STATUS_ERROR_CODES.get(error.status_code, HTTP_ERROR_FALLBACK_CODE)
