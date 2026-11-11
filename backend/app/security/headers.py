"""HTTP security response headers.

The API returns JSON, but responses still reach browsers (error pages, the
development OpenAPI UI, download endpoints). These headers close the
browser-side attack surface that application-layer authorization cannot:

* ``X-Content-Type-Options: nosniff`` - no MIME sniffing of user uploads.
* ``X-Frame-Options: DENY`` + ``frame-ancestors 'none'`` - no clickjacking.
* ``Referrer-Policy: no-referrer`` - no URL/query leakage to third parties.
* ``Permissions-Policy`` - no camera/microphone/geolocation/payment access.
* ``Content-Security-Policy`` - a restrictive default for API responses.
* ``Strict-Transport-Security`` - only over HTTPS (or in production, where a
  proxy terminates TLS), so plain-HTTP development is never pinned.

The middleware never overwrites a header a route deliberately set.
"""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# API responses render no markup, so nothing is allowed by default.
API_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'none'; object-src 'none'"
)

# The development OpenAPI UI needs its bundled assets; production disables the
# UI entirely (docs_url=None), so this policy is never served there.
DOCS_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)

DOCS_PATHS = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})

PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), payment=(), usb=()"
)


def _is_https(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return forwarded == "https" or request.url.scheme == "https"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach browser security headers to every response."""

    def __init__(self, app, *, hsts: bool | None = None) -> None:
        super().__init__(app)
        self._is_production = os.getenv("APP_ENV", "development").strip().lower() == "production"
        self._hsts = self._is_production if hsts is None else hsts

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        headers = response.headers

        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        headers.setdefault(
            "Content-Security-Policy",
            DOCS_CONTENT_SECURITY_POLICY
            if request.url.path in DOCS_PATHS
            else API_CONTENT_SECURITY_POLICY,
        )

        # HSTS is only meaningful over TLS. Behind a trusted proxy the scheme is
        # read from X-Forwarded-Proto; in production the deployment is TLS-only.
        if self._hsts or _is_https(request):
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )

        return response
