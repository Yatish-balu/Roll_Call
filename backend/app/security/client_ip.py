"""Trusted client-IP resolution shared by middleware and routers.

``X-Forwarded-For`` is only honoured when ``TRUST_PROXY_HEADERS`` is enabled
**and** the application is actually behind a trusted proxy. Otherwise any
client could spoof the header, poison audit logs, and evade per-IP quotas.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Request

_TRUST_VALUES = {"1", "true", "yes", "on"}


def trust_proxy_headers() -> bool:
    """Return True when the deployment explicitly trusts proxy headers."""
    return os.getenv("TRUST_PROXY_HEADERS", "").strip().lower() in _TRUST_VALUES


def get_client_ip(
    request: Optional[Request],
    *,
    default: Optional[str] = None,
    max_length: int = 45,
) -> Optional[str]:
    """Resolve the client address for logging, detection, and rate limiting.

    Args:
        request: The incoming FastAPI request (``None`` is tolerated).
        default: Value returned when no peer address is available.
        max_length: Hard cap on the returned string length.
    """
    if request is None:
        return default

    peer = request.client.host if request.client and request.client.host else None

    if trust_proxy_headers():
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first[:max_length]

    if peer:
        return peer[:max_length]
    return default
