"""Standard error body for all API responses (N3, D15).

Every error returned by the backend uses this shape:

    {"error": {"code": "<CODE>", "message": "<human message>"}}

Codes:
    UNAUTHENTICATED 401   Missing or invalid authentication token
    FORBIDDEN         403   Role or subject-scope does not permit the action
    LOCKED            403   Session is outside the edit window
    NOT_FOUND         404   Resource does not exist
    VALIDATION        422   Bad input (status, missing reason, etc.)
    QUALITY_REJECTED  422   Upload failed the quality gate
    RATE_LIMITED      429   Too many requests
"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """Raised by route handlers to produce a standard error response."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message}}


# Standard codes
UNAUTHENTICATED = "UNAUTHENTICATED"
FORBIDDEN = "FORBIDDEN"
LOCKED = "LOCKED"
NOT_FOUND = "NOT_FOUND"
VALIDATION = "VALIDATION"
QUALITY_REJECTED = "QUALITY_REJECTED"
RATE_LIMITED = "RATE_LIMITED"

# Code -> HTTP status mapping
CODE_STATUS: dict[str, int] = {
    UNAUTHENTICATED: 401,
    FORBIDDEN: 403,
    LOCKED: 403,
    NOT_FOUND: 404,
    VALIDATION: 422,
    QUALITY_REJECTED: 422,
    RATE_LIMITED: 429,
}


def error_response(code: str, message: str, status_code: int | None = None) -> dict[str, Any]:
    """Build a standard error body dict."""
    if status_code is None:
        status_code = CODE_STATUS.get(code, 400)
    return {"error": {"code": code, "message": message}}


__all__ = [
    "ApiError",
    "error_response",
    "UNAUTHENTICATED",
    "FORBIDDEN",
    "LOCKED",
    "NOT_FOUND",
    "VALIDATION",
    "QUALITY_REJECTED",
    "RATE_LIMITED",
    "CODE_STATUS",
]
