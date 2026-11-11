"""Request correlation identifiers.

Every request gets a correlation id that is attached to the request state, to
the response (``X-Request-ID``) and to every structured security event, so an
operator can correlate an application request with the security events it
produced. The id is not a secret and carries no credential material.
"""

from __future__ import annotations

import contextvars
import uuid

_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "rollcall_request_id", default=""
)


def set_request_id(request_id: str) -> contextvars.Token:
    """Bind a request id to the current context and return the reset token."""
    return _REQUEST_ID.set(request_id or "")


def get_request_id() -> str:
    """Return the correlation id of the current request (may be empty)."""
    return _REQUEST_ID.get()


def clear_request_id(token: contextvars.Token) -> None:
    """Restore the previous correlation id."""
    try:
        _REQUEST_ID.reset(token)
    except ValueError:  # pragma: no cover - token from another context
        _REQUEST_ID.set("")


def new_request_id() -> str:
    """Generate a new correlation id."""
    return uuid.uuid4().hex
