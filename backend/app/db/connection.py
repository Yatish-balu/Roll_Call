"""Database connection management for SQLite and SQLAlchemy 2.0 with Supabase dual-backend support."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Generator, Optional, Union

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, QueuePool

load_dotenv()

# Authoritative environment configuration (read at import time, overridable via os.environ)
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
DATABASE_URL_SYNC = os.getenv("DATABASE_URL_SYNC", "").strip()
DATABASE_URL_ASYNC = os.getenv("DATABASE_URL_ASYNC", "").strip()


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Ensure SQLite foreign key enforcement is always active for any engine."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.close()
    except Exception:
        pass


def _is_production() -> bool:
    """Return True when the application is running in production mode."""
    return os.getenv("APP_ENV", "development").strip().lower() == "production"


def _validate_production_config() -> None:
    """
    Validate that production is configured to use Supabase PostgreSQL.

    Raises RuntimeError if production is configured for SQLite or lacks
    a write database URL. This is the single source of truth for the
    cloud-first requirement: production never falls back to SQLite.
    """
    if os.getenv("APP_ENV", "development").strip().lower() != "production":
        return

    backend = os.getenv("DB_BACKEND", DB_BACKEND).strip().lower()
    if backend != "supabase":
        raise RuntimeError(
            "Production requires DB_BACKEND=supabase. SQLite is not permitted "
            "in production (DB_BACKEND=%r, APP_ENV=%r)." % (backend, os.getenv("APP_ENV", "development"))
        )

    if not os.getenv("DATABASE_URL_SYNC", DATABASE_URL_SYNC):
        raise RuntimeError(
            "Production requires DATABASE_URL_SYNC to be configured when "
            "DB_BACKEND=supabase. SQLite fallback is disabled in production."
        )

    # A read-only URL must never become the application's write connection.
    readonly = os.getenv("READONLY_DATABASE_URL", "").strip()
    if readonly and readonly == os.getenv("DATABASE_URL_SYNC", DATABASE_URL_SYNC):
        raise RuntimeError(
            "READONLY_DATABASE_URL must not be identical to DATABASE_URL_SYNC: "
            "the read-only replica must not be used as the write connection."
        )



def _find_repo_root() -> Path:
    """Locate the RollCall AI repository root containing 'data'."""
    current = Path(__file__).resolve().parent
    for p in [current] + list(current.parents):
        if (p / "data" / "attendance.db").exists():
            return p
    for p in [current] + list(current.parents):
        if p.name == "backend" and p.parent.exists():
            return p.parent
    return current.parents[2] if len(current.parents) >= 3 else current


REPO_ROOT = _find_repo_root()


def _resolve_default_db_path() -> str:
    """Retrieve absolute, canonical path to the SQLite database."""
    raw = os.getenv("SQLITE_PATH") or os.getenv("DATABASE_PATH", "data/attendance.db")
    if raw == ":memory:":
        return ":memory:"
    if os.path.isabs(raw):
        return raw
    return str((REPO_ROOT / raw).resolve())


DEFAULT_DB_PATH = _resolve_default_db_path()
SQLITE_PATH = DEFAULT_DB_PATH
DB_BACKEND = os.getenv("DB_BACKEND", "sqlite").strip().lower()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
READONLY_DATABASE_URL = os.getenv("READONLY_DATABASE_URL", "").strip()


def get_backend() -> str:
    """Return currently active backend: 'supabase' or 'sqlite'.

    In production, DB_BACKEND=supabase and DATABASE_URL_SYNC are mandatory;
    there is no silent fallback to SQLite.
    """
    # Validate production configuration before selecting a backend.
    _validate_production_config()

    backend = os.getenv("DB_BACKEND", DB_BACKEND).strip().lower()
    has_url = bool(
        os.getenv("READONLY_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or READONLY_DATABASE_URL
        or DATABASE_URL
        or os.getenv("DATABASE_URL_SYNC")
        or DATABASE_URL_SYNC
    )
    if backend == "supabase" and not has_url:
        return "sqlite"
    return backend


def get_engine(backend: Optional[str] = None, db_url: Optional[str] = None):
    """
    Get or create SQLAlchemy engine based on configured backend.

    In production, connection failures are propagated and never silently
    fall back to SQLite. PostgreSQL (Supabase) connections require SSL.
    """
    active_backend = backend or get_backend()

    try:
        if active_backend == "supabase":
            # DATABASE_URL_SYNC is the authoritative write URL; DATABASE_URL is legacy.
            url = db_url or os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL", DATABASE_URL)
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)

            # Sync psycopg driver: sslmode=require via connect_args.
            engine_kwargs = {"pool_pre_ping": True}
            if url.startswith("postgresql"):
                engine_kwargs["connect_args"] = {"sslmode": "require"}

            return create_engine(url, **engine_kwargs)
        else:
            path = db_url or SQLITE_PATH
            if path != ":memory:" and os.path.dirname(path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
            db_path_posix = path.replace(os.sep, "/") if path != ":memory:" else ":memory:"
            return create_engine(f"sqlite:///{db_path_posix}")
    except Exception as exc:
        if _is_production():
            # Never silently fall back to SQLite in production.
            raise RuntimeError(
                f"Failed to create production database engine: {exc}"
            ) from exc
        # Development: fall back to SQLite.
        path = SQLITE_PATH
        db_path_posix = path.replace(os.sep, "/") if path != ":memory:" else ":memory:"
        return create_engine(f"sqlite:///{db_path_posix}")


# ==============================================================================
# 1. Legacy SQLite Connection Management (Unchanged for backwards compatibility)
# ==============================================================================

def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create and return an SQLite connection with Row factory and foreign keys enabled."""
    if db_path != ":memory:" and os.path.dirname(db_path):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def get_db_cursor(
    db_target: Union[str, sqlite3.Connection] = DEFAULT_DB_PATH
) -> Generator[sqlite3.Cursor, None, None]:
    """Context manager yielding a cursor and handling commit/rollback."""
    if isinstance(db_target, sqlite3.Connection):
        cursor = db_target.cursor()
        try:
            yield cursor
        finally:
            cursor.close()
    else:
        conn = get_connection(db_target)
        try:
            cursor = conn.cursor()
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# ==============================================================================
# 2. Modern SQLAlchemy 2.0 Connection Management (Explicit, no auto-connect)
# ==============================================================================

def create_sync_engine(
    url: Optional[str] = None,
    *,
    echo: bool = False,
    **kwargs: Any,
) -> Engine:
    """
    Explicitly create a synchronous SQLAlchemy Engine.
    Differentiates SQLite configurations (e.g. testing) from PostgreSQL production configurations.
    Does not connect on initialization.

    DATABASE_URL_SYNC is the authoritative write connection for the FastAPI
    application. In production it must point at Supabase PostgreSQL with SSL.
    """
    db_path_posix = DEFAULT_DB_PATH.replace(os.sep, "/") if DEFAULT_DB_PATH != ":memory:" else ":memory:"
    target_url = url or os.getenv("DATABASE_URL_SYNC", DATABASE_URL_SYNC) or f"sqlite:///{db_path_posix}"

    # Production: authoritative write URL is required; no SQLite fallback.
    if _is_production():
        if not os.getenv("DATABASE_URL_SYNC", DATABASE_URL_SYNC):
            raise RuntimeError(
                "Production requires DATABASE_URL_SYNC to be configured. "
                "SQLite fallback is disabled in production."
            )

    if target_url.startswith("sqlite"):
        engine_kwargs = {
            "echo": echo,
            **kwargs,
        }
    else:
        # PostgreSQL (Supabase) production configuration.
        # psycopg driver uses sslmode=require via connect_args.
        engine_kwargs = {
            "echo": echo,
            "pool_pre_ping": True,
            "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
            "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
            "connect_args": {"sslmode": "require"},
            **kwargs,
        }
    return create_engine(target_url, **engine_kwargs)


def create_async_engine_instance(
    url: Optional[str] = None,
    *,
    echo: bool = False,
    **kwargs: Any,
) -> AsyncEngine:
    """
    Explicitly create an asynchronous SQLAlchemy Engine for FastAPI.
    Differentiates SQLite/aiosqlite testing from PostgreSQL production configurations.
    Does not connect on initialization.

    NOTE: This factory is exported for completeness but is not currently wired
    into the FastAPI request path. All API routes use synchronous sessions via
    get_sync_session_factory() / create_sync_engine(). Phase 3 (async wiring)
    is intentionally deferred.
    """
    target_url = url or os.getenv("DATABASE_URL_ASYNC", DATABASE_URL_ASYNC) or f"sqlite+aiosqlite:///{DEFAULT_DB_PATH}"

    if "sqlite" in target_url:
        engine_kwargs = {
            "echo": echo,
            **kwargs,
        }
    else:
        # PostgreSQL (Supabase) production configuration.
        # asyncpg driver uses ssl=require via connect_args (driver-specific,
        # not the same as psycopg's sslmode).
        engine_kwargs = {
            "echo": echo,
            "pool_pre_ping": True,
            "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
            "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
            "connect_args": {"ssl": "require"},
            **kwargs,
        }
    return create_async_engine(target_url, **engine_kwargs)


def get_sync_session_factory(engine: Optional[Engine] = None) -> sessionmaker[Session]:
    """Return a synchronous sessionmaker bound to the given or default engine."""
    eng = engine or create_sync_engine()
    return sessionmaker(bind=eng, class_=Session, expire_on_commit=False)


def get_async_session_factory(async_engine: Optional[AsyncEngine] = None) -> async_sessionmaker[AsyncSession]:
    """Return an asynchronous sessionmaker bound to the given or default async engine."""
    eng = async_engine or create_async_engine_instance()
    return async_sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)


def verify_database_connectivity() -> None:
    """
    Deliberate database connectivity check for production startup.

    Ensures a failed Supabase connection cannot be mistaken for a successful
    startup. In production, this validates that DATABASE_URL_SYNC is configured,
    the backend is supabase, and a real connection can be established.
    In non-production environments this is a no-op (SQLite is created lazily).
    """
    if not _is_production():
        return

    # Validate configuration (raises if misconfigured).
    _validate_production_config()

    # Attempt an actual connection so failures are visible at startup.
    engine = create_sync_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise RuntimeError(
            "Production database connectivity check failed: "
            f"Supabase is unreachable ({exc})"
        ) from exc
