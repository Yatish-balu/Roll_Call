"""HTTP security headers middleware (Person 2 - Phase 1).

Applies browser/transport security headers to every HTTP response. The headers
are also expected to be set at the reverse proxy/CDN; this middleware is the
application-level safety net so a misconfigured edge cannot silently drop them.

Environment overrides
---------------------
SECURITY_HEADERS_ENABLED       "true" (default) / "false"
CONTENT_SECURITY_POLICY        Override the API Content-Security-Policy
DOCS_CONTENT_SECURITY_POLICY   Override the CSP for /docs and /redoc
REFERRER_POLICY                Default: strict-origin-when-cross-origin
PERMISSIONS_POLICY             Default: denies unused browser features
X_FRAME_OPTIONS                Default: DENY
HSTS_MAX_AGE                   Default: 31536000 (one year)
HSTS_INCLUDE_SUBDOMAINS        "true" (default) / "false"
HSTS_PRELOAD                   "false" (default) / "true"
"""

from __future__ import annotations

import os
from typing import Mapping

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Strict policy for JSON/API responses: the API never needs to render markup.
# A separate, relaxed policy is used for the interactive OpenAPI docs pages.
DEFAULT_API_CSP = (
    "default-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'none'; "
    "object-src 'none'"
)

# FastAPI's Swagger UI / ReDoc pages load assets from jsDelivr and Google Fonts.
DEFAULT_DOCS_CSP = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "connect-src 'self'"
)

DEFAULT_PERMISSIONS_POLICY = (
    "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
    "magnetometer=(), gyroscope=(), accelerometer=(), interest-cohort=()"
)

# Paths that render interactive documentation (HTML) and therefore need the
# relaxed CSP. Everything else gets the strict API policy.
_DOC_PREFIXES = ("/docs", "/redoc")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def security_headers_enabled() -> bool:
    if os.getenv("APP_ENV", "development").strip().lower() == "production":
        return True
    return _env_bool("SECURITY_HEADERS_ENABLED", True)


def content_security_policy_for(path: str) -> str:
    """Return the CSP appropriate for *path* (docs pages get a relaxed policy)."""
    override = os.getenv("CONTENT_SECURITY_POLICY", "").strip()
    if override and not path.startswith(_DOC_PREFIXES):
        return override

    if path.startswith(_DOC_PREFIXES):
        return (
            os.getenv("DOCS_CONTENT_SECURITY_POLICY", "").strip()
            or DEFAULT_DOCS_CSP
        )
    return DEFAULT_API_CSP


def _is_https(scope: Mapping[str, object]) -> bool:
    """True when the request reached the app over TLS (directly or at the edge)."""
    if scope.get("scheme") == "https":
        return True
    raw_headers = scope.get("headers") or ()
    for name, value in raw_headers:  # type: ignore[union-attr]
        if bytes(name).lower() == b"x-forwarded-proto":
            first = bytes(value).split(b",")[0].strip().lower()
            return first == b"https"
    return False


def _hsts_value() -> str:
    max_age = max(0, _env_int("HSTS_MAX_AGE", 31536000))
    value = f"max-age={max_age}"
    if _env_bool("HSTS_INCLUDE_SUBDOMAINS", True):
        value += "; includeSubDomains"
    if _env_bool("HSTS_PRELOAD", False):
        value += "; preload"
    return value


def apply_security_headers(scope: Mapping[str, object], message: Message) -> None:
    """Set the configured security headers on an outgoing ``http.response.start``."""
    if not security_headers_enabled():
        return

    headers = MutableHeaders(scope=message)  # type: ignore[arg-type]
    path = str(scope.get("path") or "/")

    # ``setdefault`` keeps a stronger value configured at the proxy/CDN.
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault(
        "Referrer-Policy",
        os.getenv("REFERRER_POLICY", "").strip() or "strict-origin-when-cross-origin",
    )
    headers.setdefault(
        "Permissions-Policy",
        os.getenv("PERMISSIONS_POLICY", "").strip() or DEFAULT_PERMISSIONS_POLICY,
    )
    headers.setdefault(
        "X-Frame-Options",
        os.getenv("X_FRAME_OPTIONS", "").strip().upper() or "DENY",
    )
    headers.setdefault("Content-Security-Policy", content_security_policy_for(path))
    headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")

    env = os.getenv("APP_ENV", "development").strip().lower()
    if env == "production" or _is_https(scope):
        headers.setdefault("Strict-Transport-Security", _hsts_value())


class SecurityHeadersMiddleware:
    """Pure ASGI middleware so headers are applied to every response, including CORS preflights."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message.get("type") == "http.response.start":
                apply_security_headers(scope, message)
            await send(message)

        await self.app(scope, receive, send_with_headers)
