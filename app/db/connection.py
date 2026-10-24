"""Database connection management for SQLite."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Generator, Union

DEFAULT_DB_PATH = os.getenv("DATABASE_PATH", "data/attendance.db")


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
