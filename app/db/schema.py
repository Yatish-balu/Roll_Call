"""Database schema definitions and initialization."""

from __future__ import annotations

import sqlite3
from typing import Any, Optional, Union
from app.db.connection import (
    DEFAULT_DB_PATH,
    get_backend,
    get_connection,
    get_engine,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS students (
    usn TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    branch TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rooms (
    room_id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    subject TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attendance (
    session_id TEXT NOT NULL,
    usn TEXT NOT NULL,
    room_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PRESENT', 'ABSENT', 'PENDING', 'UNREVIEWED', 'P', 'A')),
    source TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (session_id, usn),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY (usn) REFERENCES students(usn) ON DELETE CASCADE,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_attendance_session ON attendance(session_id);
CREATE INDEX IF NOT EXISTS idx_attendance_usn ON attendance(usn);
CREATE INDEX IF NOT EXISTS idx_attendance_room ON attendance(room_id);
"""

POSTGRES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS students (
    usn VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    branch VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS rooms (
    room_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR(100) PRIMARY KEY,
    date VARCHAR(50) NOT NULL,
    subject VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS attendance (
    session_id VARCHAR(100) NOT NULL,
    usn VARCHAR(50) NOT NULL,
    room_id VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('PRESENT', 'ABSENT', 'PENDING', 'UNREVIEWED', 'P', 'A')),
    source VARCHAR(100) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    PRIMARY KEY (session_id, usn),
    CONSTRAINT fk_attendance_session FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
    CONSTRAINT fk_attendance_student FOREIGN KEY (usn) REFERENCES students(usn) ON DELETE CASCADE,
    CONSTRAINT fk_attendance_room FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_attendance_session_id ON attendance(session_id);
CREATE INDEX IF NOT EXISTS idx_attendance_room_id ON attendance(room_id);
CREATE INDEX IF NOT EXISTS idx_attendance_usn ON attendance(usn);
"""


def init_db(db_target: Union[str, sqlite3.Connection, Any] = DEFAULT_DB_PATH) -> Any:
    """Initialize database tables and indexes for SQLite or Supabase Postgres."""
    # If explicitly passed an SQLite connection
    if isinstance(db_target, sqlite3.Connection):
        db_target.executescript(SCHEMA_SQL)
        db_target.commit()
        return db_target

    # If SQLAlchemy Engine is passed
    if hasattr(db_target, "connect") and hasattr(db_target, "begin"):
        try:
            from sqlalchemy import text
            with db_target.begin() as conn:
                statements = [s.strip() for s in POSTGRES_SCHEMA_SQL.split(";") if s.strip()]
                for stmt in statements:
                    conn.execute(text(stmt))
            return db_target
        except Exception:
            raise

    # Check backend
    backend = get_backend()
    if backend == "supabase" and (db_target == DEFAULT_DB_PATH or db_target is None):
        engine = get_engine(backend="supabase")
        if engine is not None:
            try:
                from sqlalchemy import text
                with engine.begin() as conn:
                    # Execute individual statements
                    statements = [s.strip() for s in POSTGRES_SCHEMA_SQL.split(";") if s.strip()]
                    for stmt in statements:
                        conn.execute(text(stmt))
                return engine
            except Exception:
                # Fallback to sqlite if supabase connection fails
                pass

    conn = get_connection(str(db_target))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        return conn
    except Exception:
        conn.close()
        raise
