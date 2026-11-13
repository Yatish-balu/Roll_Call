"""FastAPI application entrypoint for RollCall AI."""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

# Ensure backend directory is in sys.path
_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from dotenv import load_dotenv

# Load .env from project root if available, else fallback
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / ".env"
if _ENV_FILE.exists():
    load_dotenv(dotenv_path=_ENV_FILE)
else:
    load_dotenv()
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routers import (
    admin_router,
    agent_router,
    analytics_router,
    attendance_router,
    auth_router,
    me_router,
    meta_router,
    reports_router,
    rooms_router,
    sessions_router,
    students_router,
    timetable_router,
    profile_router,
    calendar_router,
    agent_stream_router,
)


load_dotenv()

logger = logging.getLogger("rollcall.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context for startup and shutdown events."""
    logger.info("RollCall AI FastAPI application starting up...")

    # Validate JWT configuration on startup
    from app.auth.jwt import DEV_FALLBACK_SECRET, validate_jwt_secret_configuration
    env = os.getenv("APP_ENV", "development").lower()
    if env == "production" and os.getenv("SECURITY_HEADERS_ENABLED", "true").strip().lower() in {
        "0", "false", "no", "off",
    }:
        raise RuntimeError(
            "Production security violation: SECURITY_HEADERS_ENABLED cannot be disabled."
        )
    secret = os.getenv("JWT_SECRET") or os.getenv("JWT_SECRET_KEY")
    if env == "production" or secret:
        if env == "production" and (secret or "").strip() == DEV_FALLBACK_SECRET:
            raise RuntimeError(
                "Production security violation: the insecure development JWT secret "
                "cannot be used in production."
            )
        validate_jwt_secret_configuration(secret, env)

    # Deliberate database connectivity check for production startup.
    # A failed Supabase connection must not be mistaken for a successful startup.
    from app.db.connection import verify_database_connectivity, get_sync_session_factory
    verify_database_connectivity()

    try:
        from app.routers.profile import _ensure_profile_table
        from app.db import crud
        session_factory = get_sync_session_factory()
        with session_factory() as session:
            _ensure_profile_table(session)
            crud.ensure_unallocated_room(session)
    except Exception as exc:
        logger.warning("Could not auto-create profile table or default room at startup: %s", exc)

    try:
        from app.agent.tools import register_all_tools
        register_all_tools()
    except Exception as exc:
        logger.warning("Could not register agent tools at startup: %s", exc)

    # Password reset only works if a reset link can be delivered. Report the
    # missing provider at startup instead of discovering it on the first reset.
    if env == "production":
        from app.security.email import get_email_provider

        if not get_email_provider().configured:
            logger.error(
                "DEPLOYMENT BLOCKER: no email provider is configured; password "
                "reset links cannot be delivered. Set SMTP_HOST (or the "
                "configured provider) before relying on self-service resets."
            )
        configured_origins = get_allowed_origins()
        if any(
            "localhost" in origin or "127.0.0.1" in origin
            for origin in configured_origins
        ):
            logger.warning(
                "Production CORS ALLOWED_ORIGINS still contains localhost/127.0.0.1 "
                "entries: %s. Configure the real frontend origin(s).",
                configured_origins,
            )

    # ------------------------------------------------------------------
    # Backend-driven academic day initialisation.
    #
    # The server prepares today's sessions from the configured timetable. The
    # browser never creates session records. The job is idempotent, so it is
    # safe to run repeatedly and under concurrency.
    # ------------------------------------------------------------------
    import asyncio

    from app.services.session_initialization import run_daily_initialization

    auto_init_enabled = (
        os.getenv("SESSION_AUTO_INIT", "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
        and "pytest" not in sys.modules
    )

    async def _session_initialisation_worker() -> None:
        try:
            await asyncio.to_thread(run_daily_initialization)
        except Exception:  # pragma: no cover - defensive guard
            logger.exception("Session initialisation worker failed")

    async def _session_initialisation_loop() -> None:
        while True:
            try:
                await _session_initialisation_worker()
            except asyncio.CancelledError:  # pragma: no cover - shutdown path
                raise
            except Exception:  # pragma: no cover - defensive guard
                logger.exception("Session initialisation loop error")
            await asyncio.sleep(1800)  # re-check every 30 minutes

    if auto_init_enabled:
        initialisation_task = asyncio.create_task(_session_initialisation_loop())
        app.state.session_initialisation_task = initialisation_task
        logger.info("Automatic session initialisation is enabled (SESSION_AUTO_INIT).")
    else:
        initialisation_task = None
        logger.info(
            "Automatic session initialisation is disabled (SESSION_AUTO_INIT=0); "
            "sessions can still be prepared through POST /api/v1/sessions/initialize."
        )
    yield
    logger.info("RollCall AI FastAPI application shutting down...")
    if initialisation_task is not None:
        initialisation_task.cancel()
        try:
            await initialisation_task
        except (asyncio.CancelledError, Exception):  # pragma: no cover - shutdown path
            pass


# ==============================================================================
# 1. FastAPI Application Setup & Metadata
# ==============================================================================

# Interactive docs and the OpenAPI schema describe the entire attack surface.
# They stay available in development but are not exposed in production.
_IS_PRODUCTION = os.getenv("APP_ENV", "development").strip().lower() == "production"

app = FastAPI(
    title="RollCall AI",
    description="Automated roll call processing, analytics, and intelligent reporting API",
    version="0.2.0",
    docs_url=None if _IS_PRODUCTION else "/docs",
    redoc_url=None if _IS_PRODUCTION else "/redoc",
    openapi_url=None if _IS_PRODUCTION else "/openapi.json",
    lifespan=lifespan,
)


# ==============================================================================
# 2. Configurable CORS Middleware (Safe: No Wildcard with Credentials)
# ==============================================================================

DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# Explicit allowlists: only the methods and headers the application uses.
DEFAULT_ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
DEFAULT_ALLOWED_HEADERS = [
    "Accept",
    "Authorization",
    "Content-Type",
    "Origin",
    "X-Request-ID",
    "X-CSRF-Token",
    "X-Requested-With",
    "X-RollCall-CSRF",
]
EXPOSED_HEADERS = ["X-Request-ID"]
CORS_MAX_AGE_SECONDS = 600


def _parse_csv_env(raw: Optional[str]) -> List[str]:
    """Split a comma-separated environment value, dropping blanks and duplicates."""
    seen: set[str] = set()
    values: List[str] = []
    for item in (raw or "").split(","):
        value = item.strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        values.append(value)
    return values


def normalize_origin(origin: str) -> Optional[str]:
    """Return a canonical scheme://host[:port] origin, or ``None`` when invalid.

    Wildcards, credentials, paths, queries and fragments are rejected: an
    allowed origin must be an exact browser origin, never a pattern.
    """
    from urllib.parse import urlsplit

    value = (origin or "").strip()
    if not value or value == "*" or "*" in value:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    if not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        return None
    host = parts.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        return None
    if (parts.scheme == "https" and port == 443) or (parts.scheme == "http" and port == 80):
        port = None
    port_suffix = f":{port}" if port else ""
    return f"{parts.scheme}://{host}{port_suffix}"


def get_allowed_origins() -> List[str]:
    """
    Retrieve allowed CORS origins from environment variable or safe localhost defaults.
    Guarantees unsafe wildcards ('*') are never combined with allow_credentials=True.
    """
    raw = os.getenv("ALLOWED_ORIGINS")
    if not raw or not raw.strip():
        return list(DEFAULT_ALLOWED_ORIGINS)

    origins: List[str] = []
    for candidate in _parse_csv_env(raw):
        normalized = normalize_origin(candidate)
        if normalized and normalized not in origins:
            origins.append(normalized)
        else:
            logger.warning(
                "Ignoring invalid CORS origin %r. Origins must be exact http(s) "
                "origins without a path, query, fragment, credentials or wildcard.",
                candidate,
            )

    if not origins:
        logger.warning(
            "ALLOWED_ORIGINS contains only wildcards or invalid entries. "
            "Falling back to safe localhost development defaults to prevent CORS vulnerability."
        )
        return list(DEFAULT_ALLOWED_ORIGINS)

    return origins


def get_allowed_methods() -> List[str]:
    """Explicit CORS method allowlist (never ``*``)."""
    configured = [m.upper() for m in _parse_csv_env(os.getenv("ALLOWED_METHODS"))]
    methods = [m for m in configured if m in DEFAULT_ALLOWED_METHODS] or list(
        DEFAULT_ALLOWED_METHODS
    )
    # OPTIONS is required for preflight and must always be present.
    if "OPTIONS" not in methods:
        methods.append("OPTIONS")
    return methods


def get_allowed_headers() -> List[str]:
    """Explicit CORS request-header allowlist (never ``*``)."""
    configured = _parse_csv_env(os.getenv("ALLOWED_HEADERS"))
    headers = configured or list(DEFAULT_ALLOWED_HEADERS)
    configured_lower = {header.lower() for header in headers}
    for required in ("X-Requested-With", "X-RollCall-CSRF"):
        if required.lower() not in configured_lower:
            headers.append(required)
    return headers


def build_cors_settings() -> dict:
    """Return the keyword arguments handed to :class:`CORSMiddleware`."""
    return {
        "allow_origins": get_allowed_origins(),
        "allow_credentials": True,
        "allow_methods": get_allowed_methods(),
        "allow_headers": get_allowed_headers(),
        "expose_headers": list(EXPOSED_HEADERS),
        "max_age": CORS_MAX_AGE_SECONDS,
    }


app.add_middleware(CORSMiddleware, **build_cors_settings())

# Added after CORS so the headers are the outermost layer: error and preflight
# responses produced by CORS still carry the browser hardening headers.
from app.security.headers import SecurityHeadersMiddleware  # noqa: E402

app.add_middleware(SecurityHeadersMiddleware)


# ==============================================================================
# 3. Global Structured Exception Handlers (Standard error format: D15 & Safe)
# ==============================================================================

def _map_error_code(status_code: int, detail: Any) -> str:
    msg = str(detail).lower()
    if status_code == 401:
        return "UNAUTHENTICATED"
    if status_code == 403:
        if "lock" in msg:
            return "LOCKED"
        return "FORBIDDEN"
    if status_code == 404:
        return "NOT_FOUND"
    if status_code == 422:
        if "quality" in msg or "photo" in msg:
            return "QUALITY_REJECTED"
        return "VALIDATION"
    if status_code == 429:
        return "RATE_LIMITED"
    return "HTTP_ERROR"


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Format Pydantic request validation errors cleanly (matching D15 format)."""
    errors = []
    for err in exc.errors():
        field = " -> ".join(str(loc) for loc in err.get("loc", []))
        errors.append({
            "field": field,
            "message": err.get("msg", "Invalid value"),
            "type": err.get("type", "value_error"),
        })
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": {
                "code": "VALIDATION",
                "message": "Input validation failed. Please check the supplied parameters.",
            },
            "status_code": 422,
            "detail": errors,
            "details": errors,
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Format standard HTTP exceptions with standard {error: {code, message}} body (D15)."""
    code = _map_error_code(exc.status_code, exc.detail)
    msg = str(exc.detail) if isinstance(exc.detail, str) else "An error occurred."
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code,
                "message": msg,
            },
            "status_code": exc.status_code,
            "detail": exc.detail,
        },
        headers=exc.headers,
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Handle business rule / value exceptions safely without stack trace leaks."""
    logger.warning("Business rule violation: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "BadRequest",
            "message": str(exc),
            "detail": str(exc),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all unhandled exception handler ensuring no internal stack trace or secret is leaked."""
    logger.exception("Unhandled server exception: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": "An unexpected internal server error occurred. Please try again later.",
        },
    )


# ==============================================================================
# 3b. Security Middleware: request correlation ids + access-denial events
# ==============================================================================

from app.security.context import clear_request_id, get_request_id, new_request_id, set_request_id
from app.security.detection import detector
from app.security.events import log_security_event


def _client_ip(request: Request) -> Optional[str]:
    """Best-effort client address (never a credential)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client and request.client.host:
        return request.client.host
    return None


@app.middleware("http")
async def security_context_middleware(request: Request, call_next):
    """Attach a correlation id and report denied access as a security event.

    The correlation id is echoed back as ``X-Request-ID`` so an operator can
    tie an application request to the security events it produced. Denied
    requests are counted by the detector; a single denial never blocks a user.
    """
    incoming = request.headers.get("x-request-id", "").strip()
    request_id = incoming[:64] if incoming else new_request_id()
    token = set_request_id(request_id)
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    finally:
        clear_request_id(token)

    response.headers["X-Request-ID"] = request_id

    if response.status_code in (401, 403):
        detector.record_access_denied(
            ip_address=_client_ip(request),
            path=request.url.path,
            status_code=response.status_code,
            request_id=request_id,
        )
        log_security_event(
            "access_denied",
            severity="warning" if response.status_code == 403 else "info",
            outcome="failure",
            ip_address=_client_ip(request),
            request_id=request_id,
            path=request.url.path,
            method=request.method,
            details={"status_code": response.status_code},
        )
    return response


# ==============================================================================
# 4. Core Health & Root Endpoints (Preserved for backwards compatibility)
# ==============================================================================

@app.get("/", tags=["General"])
def read_root():
    return {"message": "Welcome to RollCall AI API"}


@app.get("/health", tags=["General"])
def health_check():
    # No environment/debug detail: the endpoint is unauthenticated.
    return {
        "status": "healthy",
        "version": app.version,
    }


@app.get("/models", tags=["General"])
@app.get("/v1/models", tags=["General"])
@app.get("/api/v1/models", tags=["General"])
@app.get("/api/models", tags=["General"])
def list_models():
    """Return list of models supported by the RollCall AI backend in OpenAI-compatible format."""
    return {
        "object": "list",
        "data": [
            {
                "id": "gemini-3.5-flash-lite",
                "object": "model",
                "created": 1700000000,
                "owned_by": "rollcall-ai",
            },
            {
                "id": "gemini-2.5-flash",
                "object": "model",
                "created": 1700000000,
                "owned_by": "rollcall-ai",
            },
            {
                "id": "rollcall-ai-agent",
                "object": "model",
                "created": 1700000000,
                "owned_by": "rollcall-ai",
            },
        ],
    }


# ==============================================================================
# 5. API Routers Registration (Dual Mount: /api/v1 and Playbook Contract /api)
# ==============================================================================

# API v1 Routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(me_router, prefix="/api/v1")
app.include_router(meta_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(students_router, prefix="/api/v1")
app.include_router(rooms_router, prefix="/api/v1")
app.include_router(sessions_router, prefix="/api/v1")
app.include_router(timetable_router, prefix="/api/v1")
app.include_router(attendance_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(agent_stream_router, prefix="/api/v1")
app.include_router(profile_router, prefix="/api/v1")
app.include_router(calendar_router, prefix="/api/v1")

# Unversioned /api/ Routers (matching RollCall Playbook API Contract)
app.include_router(auth_router, prefix="/api")
app.include_router(me_router, prefix="/api")
app.include_router(meta_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(students_router, prefix="/api")
app.include_router(rooms_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(timetable_router, prefix="/api")
app.include_router(attendance_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(reports_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(agent_stream_router, prefix="/api")
app.include_router(profile_router, prefix="/api")
app.include_router(calendar_router, prefix="/api")



# ==============================================================================
# 6. Streamlit UI Launcher (Preserved for existing workflow)
# ==============================================================================

def run_streamlit_ui():
    """Optional launcher for the Streamlit UI entrypoint used by Phase 3."""
    import subprocess
    import sys
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", "app/ui.py", "--server.port=8501", "--server.headless=true"],
        cwd=_BACKEND_DIR,
    )


if __name__ == "__main__":
    run_streamlit_ui()
