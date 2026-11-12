"""Database connection management.

Supabase PostgreSQL is the only supported runtime backend. SQLite remains
available only when ``DB_BACKEND=sqlite`` is set explicitly for isolated tests
or emergency local tooling.
"""

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

# Search for .env in current directory, backend directory, or project root
_THIS_DIR = Path(__file__).resolve().parent
for _candidate_dir in [Path.cwd(), _THIS_DIR.parents[1], _THIS_DIR.parents[2]]:
    _env_candidate = _candidate_dir / ".env"
    if _env_candidate.is_file():
        load_dotenv(dotenv_path=_env_candidate)
        break
else:
    load_dotenv()

# Authoritative environment configuration (read at import time, overridable via os.environ)
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
DATABASE_URL_SYNC = os.getenv("DATABASE_URL_SYNC", "").strip()
DATABASE_URL_ASYNC = os.getenv("DATABASE_URL_ASYNC", "").strip()


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Ensure SQLite foreign key enforcement is always active for any engine.

    This listener is registered on the base ``Engine`` class, so it also fires
    for PostgreSQL connections. The PRAGMA is SQLite-specific: issuing it on a
    PostgreSQL connection raises a syntax error and aborts the transaction.
    Only touch genuine SQLite DBAPI connections.
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.close()
    except Exception:
        pass


def _is_production() -> bool:
    """Return True when the application is running in production mode."""
    return os.getenv("APP_ENV", "development").strip().lower() == "production"


def _production_write_url() -> str:
    """Resolve the authoritative write URL for production, strictly from the environment.

    In production the write connection must come from the live environment
    (the process environment or a .env loaded at startup). The import-time
    constant is deliberately NOT used here: if DATABASE_URL_SYNC is missing or
    was unset at runtime, production must fail closed rather than silently
    reuse a previously captured value.
    """
    return os.environ.get("DATABASE_URL_SYNC", "").strip()


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

    if not _production_write_url():
        raise RuntimeError(
            "Production requires DATABASE_URL_SYNC to be configured when "
            "DB_BACKEND=supabase. SQLite fallback is disabled in production."
        )

    # A read-only URL must never become the application's write connection.
    readonly = os.getenv("READONLY_DATABASE_URL", "").strip()
    if readonly and readonly == _production_write_url():
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
# Supabase/PostgreSQL is the only supported runtime backend. SQLite remains
# available only when DB_BACKEND=sqlite is set explicitly (isolated tests and
# emergency local tooling).
DB_BACKEND = os.getenv("DB_BACKEND", "supabase").strip().lower()
SUPPORTED_BACKENDS = ("supabase", "sqlite")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
READONLY_DATABASE_URL = os.getenv("READONLY_DATABASE_URL", "").strip()


def _configured_backend() -> str:
    """Return the explicitly configured backend, defaulting to Supabase."""
    return os.getenv("DB_BACKEND", DB_BACKEND).strip().lower()


def _sqlite_enabled() -> bool:
    """True only when SQLite was requested explicitly (tests/tooling)."""
    return _configured_backend() == "sqlite"


def _supabase_url() -> str:
    """Return the authoritative synchronous PostgreSQL URL, if configured."""
    return (os.getenv("DATABASE_URL_SYNC") or DATABASE_URL_SYNC or "").strip()


def get_backend() -> str:
    """Return the active backend: 'supabase' (default) or 'sqlite'.

    Supabase is the only supported runtime backend. SQLite is never selected
    implicitly: it requires an explicit ``DB_BACKEND=sqlite``.
    """
    _validate_production_config()

    backend = _configured_backend()
    if backend not in SUPPORTED_BACKENDS:
        raise RuntimeError(
            f"Unsupported DB_BACKEND={backend!r}. Use 'supabase' (default) or "
            "'sqlite' (tests/emergency tooling only)."
        )
    return backend


def get_engine(backend: Optional[str] = None, db_url: Optional[str] = None):
    """
    Get or create a SQLAlchemy engine for the configured backend.

    Supabase is authoritative: a missing ``DATABASE_URL_SYNC`` or a failed
    connection raises instead of silently falling back to SQLite.
    """
    active_backend = backend or get_backend()

    if active_backend == "supabase":
        # DATABASE_URL_SYNC is the authoritative write URL; DATABASE_URL is legacy.
        url = (db_url or _supabase_url() or os.getenv("DATABASE_URL") or DATABASE_URL).strip()
        if not url:
            raise RuntimeError(
                "Supabase is the only supported backend, but DATABASE_URL_SYNC "
                "is not configured. Set DATABASE_URL_SYNC to a "
                "postgresql+psycopg:// URL, or set DB_BACKEND=sqlite explicitly "
                "for isolated tests/tooling."
            )
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)

        # Sync psycopg driver: sslmode=require via connect_args.
        engine_kwargs = {"pool_pre_ping": True}
        if url.startswith("postgresql"):
            engine_kwargs["connect_args"] = {"sslmode": "require"}

        return create_engine(url, **engine_kwargs)

    if active_backend != "sqlite":
        raise RuntimeError(f"Unsupported database backend: {active_backend!r}")

    path = db_url or SQLITE_PATH
    if path != ":memory:" and os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    db_path_posix = path.replace(os.sep, "/") if path != ":memory:" else ":memory:"
    return create_engine(f"sqlite:///{db_path_posix}")


# ==============================================================================
# 1. Legacy SQLite Connection Management (Unchanged for backwards compatibility)
# ==============================================================================

def get_connection(
    db_path: str = DEFAULT_DB_PATH, *, allow_sqlite: bool = False
) -> sqlite3.Connection:
    """Create and return an SQLite connection with Row factory and foreign keys enabled.

    In Supabase-only mode (the default) this raises unless ``allow_sqlite`` is
    explicitly set by a test or local tooling helper.
    """
    if not allow_sqlite and not _sqlite_enabled():
        raise RuntimeError(
            "Raw SQLite access is disabled because DB_BACKEND=supabase. Use the "
            "SQLAlchemy session/engine APIs instead. Set DB_BACKEND=sqlite only "
            "for isolated tests or emergency local tooling."
        )
    if db_path != ":memory:" and os.path.dirname(db_path):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def get_db_cursor(
    db_target: Union[str, sqlite3.Connection] = DEFAULT_DB_PATH,
    *,
    allow_sqlite: bool = False,
) -> Generator[sqlite3.Cursor, None, None]:
    """Context manager yielding a cursor and handling commit/rollback."""
    if isinstance(db_target, sqlite3.Connection):
        cursor = db_target.cursor()
        try:
            yield cursor
        finally:
            cursor.close()
    else:
        conn = get_connection(db_target, allow_sqlite=allow_sqlite)
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
    Does not connect on initialization.

    DATABASE_URL_SYNC is the authoritative write connection and is required for
    the default Supabase backend. SQLite is used only when DB_BACKEND=sqlite is
    set explicitly (isolated tests/tooling) or a SQLite ``url`` is passed.
    """
    db_path_posix = DEFAULT_DB_PATH.replace(os.sep, "/") if DEFAULT_DB_PATH != ":memory:" else ":memory:"

    # Determine the effective backend
    effective_backend = _configured_backend()

    if url is not None:
        target_url = url
    elif effective_backend == "sqlite":
        # SQLite explicitly requested (e.g. testing or emergency tooling)
        target_url = f"sqlite:///{db_path_posix}"
    else:
        # Supabase/PostgreSQL is the default and only runtime backend.
        target_url = _supabase_url()
        if not target_url:
            raise RuntimeError(
                "Supabase is the only supported backend, but DATABASE_URL_SYNC "
                "is not configured. Set DATABASE_URL_SYNC to a "
                "postgresql+psycopg:// URL, or set DB_BACKEND=sqlite explicitly "
                "for isolated tests/tooling."
            )

    # Production: authoritative write URL is required; no SQLite fallback.
    if _is_production():
        if not _production_write_url():
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
    if url is not None:
        target_url = url
    elif _configured_backend() == "sqlite":
        target_url = f"sqlite+aiosqlite:///{DEFAULT_DB_PATH}"
    else:
        target_url = (os.getenv("DATABASE_URL_ASYNC") or DATABASE_URL_ASYNC or "").strip()
        if not target_url:
            raise RuntimeError(
                "DATABASE_URL_ASYNC is not configured. Supabase is the only "
                "supported backend; set DATABASE_URL_ASYNC to a "
                "postgresql+asyncpg:// URL, or set DB_BACKEND=sqlite explicitly."
            )

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
    Deliberate database connectivity check for application startup.

    Supabase is the only supported runtime backend, so a missing URL or an
    unreachable database is a hard startup failure rather than a silent
    fallback. When ``DB_BACKEND=sqlite`` is explicitly set (tests/emergency
    tooling) the check is a no-op because SQLite is created lazily.
    """
    backend = get_backend()

    if backend == "sqlite":
        return

    # Attempt an actual connection so failures are visible at startup.
    engine = create_sync_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise RuntimeError(
            "Supabase database connectivity check failed: the database is "
            f"unreachable or the credentials are invalid ({exc}).\n"
            "Check DATABASE_URL_SYNC in .env:\n"
            "  - confirm the Supabase project is running (not paused);\n"
            "  - reset the database password if needed (Supabase Dashboard -> "
            "Project Settings -> Database -> Reset database password);\n"
            "  - percent-encode special characters in the password;\n"
            "  - ensure no stale DATABASE_URL_SYNC environment variable is "
            "overriding .env."
        ) from exc
    finally:
        engine.dispose()
