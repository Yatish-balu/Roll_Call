"""Database connection management for SQLite and SQLAlchemy 2.0."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Generator, Optional, Union

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, QueuePool


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
    raw = os.getenv("DATABASE_PATH", "data/attendance.db")
    if raw == ":memory:":
        return ":memory:"
    if os.path.isabs(raw):
        return raw
    return str((REPO_ROOT / raw).resolve())


DEFAULT_DB_PATH = _resolve_default_db_path()


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
    """
    db_path_posix = DEFAULT_DB_PATH.replace(os.sep, "/") if DEFAULT_DB_PATH != ":memory:" else ":memory:"
    target_url = url or os.getenv("DATABASE_URL_SYNC") or f"sqlite:///{db_path_posix}"

    if target_url.startswith("sqlite"):
        # SQLite engines: avoid PostgreSQL pool options
        engine_kwargs = {
            "echo": echo,
            **kwargs,
        }
    else:
        # PostgreSQL / Supabase connection pooling configuration
        engine_kwargs = {
            "echo": echo,
            "pool_pre_ping": True,
            "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
            "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
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
    """
    target_url = url or os.getenv("DATABASE_URL_ASYNC") or f"sqlite+aiosqlite:///{DEFAULT_DB_PATH}"

    if "sqlite" in target_url:
        engine_kwargs = {
            "echo": echo,
            **kwargs,
        }
    else:
        # PostgreSQL / Supabase async connection pooling configuration
        engine_kwargs = {
            "echo": echo,
            "pool_pre_ping": True,
            "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
            "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
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
