"""FastAPI application entrypoint for RollCall AI."""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

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
    agent_router,
    analytics_router,
    attendance_router,
    reports_router,
    rooms_router,
    sessions_router,
    students_router,
)

load_dotenv()

logger = logging.getLogger("rollcall.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context for startup and shutdown events."""
    logger.info("RollCall AI FastAPI application starting up...")
    yield
    logger.info("RollCall AI FastAPI application shutting down...")


# ==============================================================================
# 1. FastAPI Application Setup & Metadata
# ==============================================================================

app = FastAPI(
    title="RollCall AI",
    description="Automated roll call processing, analytics, and intelligent reporting API",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
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


def get_allowed_origins() -> List[str]:
    """
    Retrieve allowed CORS origins from environment variable or safe localhost defaults.
    Guarantees unsafe wildcards ('*') are never combined with allow_credentials=True.
    """
    raw = os.getenv("ALLOWED_ORIGINS")
    if not raw or not raw.strip():
        return list(DEFAULT_ALLOWED_ORIGINS)

    origins = [origin.strip() for origin in raw.split(",") if origin.strip() and origin.strip() != "*"]
    if not origins:
        logger.warning(
            "ALLOWED_ORIGINS contains only wildcards or blank entries. "
            "Falling back to safe localhost development defaults to prevent CORS vulnerability."
        )
        return list(DEFAULT_ALLOWED_ORIGINS)

    return origins


allowed_origins = get_allowed_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
# 4. Core Health & Root Endpoints (Preserved for backwards compatibility)
# ==============================================================================

@app.get("/", tags=["General"])
def read_root():
    return {"message": "Welcome to RollCall AI API"}


@app.get("/health", tags=["General"])
def health_check():
    return {
        "status": "healthy",
        "environment": os.getenv("APP_ENV", "development"),
        "version": app.version,
    }


# ==============================================================================
# 5. API Routers Registration (Dual Mount: /api/v1 and Playbook Contract /api)
# ==============================================================================

# API v1 Routers
app.include_router(students_router, prefix="/api/v1")
app.include_router(rooms_router, prefix="/api/v1")
app.include_router(sessions_router, prefix="/api/v1")
app.include_router(attendance_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")

# Unversioned /api/ Routers (matching RollCall Playbook API Contract)
app.include_router(students_router, prefix="/api")
app.include_router(rooms_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(attendance_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(reports_router, prefix="/api")
app.include_router(agent_router, prefix="/api")


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
