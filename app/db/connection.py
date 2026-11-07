"""Database connection management for SQLAlchemy with SQLite fallback."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Generator, Optional, Union
from dotenv import load_dotenv

load_dotenv()

# Environment configurations
DB_BACKEND = os.getenv("DB_BACKEND", "sqlite").strip().lower()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
READONLY_DATABASE_URL = os.getenv("READONLY_DATABASE_URL", "").strip()
SQLITE_PATH = os.getenv("SQLITE_PATH") or os.getenv("DATABASE_PATH", "data/attendance.db")
DEFAULT_DB_PATH = SQLITE_PATH

# Lazy-loaded SQLAlchemy engine and session factory
_ENGINE = None


def get_backend() -> str:
    """Return currently active backend: 'supabase' or 'sqlite'."""
    backend = os.getenv("DB_BACKEND", DB_BACKEND).strip().lower()
    has_url = bool(
        os.getenv("READONLY_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or READONLY_DATABASE_URL
        or DATABASE_URL
    )
    if backend == "supabase" and not has_url:
        # Fallback to sqlite if database url is missing
        return "sqlite"
    return backend


def get_engine(backend: Optional[str] = None, db_url: Optional[str] = None):
    """
    Get or create SQLAlchemy engine based on configured backend.
    Gracefully falls back to SQLite if Supabase connection fails or SQLAlchemy is unavailable.
    """
    global _ENGINE
    active_backend = backend or get_backend()

    try:
        from sqlalchemy import create_engine

        if active_backend == "supabase":
            url = db_url or os.getenv("DATABASE_URL", DATABASE_URL)
            # Ensure URL has correct driver prefix if postgresql is used
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            # Use pool_pre_ping for resilient Postgres connections
            return create_engine(url, pool_pre_ping=True)
        else:
            path = db_url or os.getenv("SQLITE_PATH") or DEFAULT_DB_PATH
            if path != ":memory:" and os.path.dirname(path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
            return create_engine(f"sqlite:///{path}")
    except Exception as exc:
        # Fallback to sqlite if supabase fails to initialize
        if active_backend == "supabase":
            try:
                from sqlalchemy import create_engine
                path = os.getenv("SQLITE_PATH") or DEFAULT_DB_PATH
                if path != ":memory:" and os.path.dirname(path):
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                return create_engine(f"sqlite:///{path}")
            except Exception:
                pass
        return None


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
