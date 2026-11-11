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
    subject TEXT NOT NULL,
    created_at TEXT,
    teacher_id TEXT,
    subject_code TEXT
);

CREATE TABLE IF NOT EXISTS attendance (
    attendance_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    allocation_id TEXT,
    usn TEXT NOT NULL,
    room_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PRESENT', 'ABSENT', 'PENDING', 'UNREVIEWED', 'P', 'A')),
    source TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY (usn) REFERENCES students(usn) ON DELETE CASCADE,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_allocation_usn ON attendance (allocation_id, usn) WHERE allocation_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_legacy_session_usn ON attendance (session_id, usn) WHERE allocation_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_attendance_session ON attendance(session_id);
CREATE INDEX IF NOT EXISTS idx_attendance_usn ON attendance(usn);
CREATE INDEX IF NOT EXISTS idx_attendance_room ON attendance(room_id);
CREATE INDEX IF NOT EXISTS idx_attendance_allocation ON attendance(allocation_id);

-- Audit infrastructure (mirrors migration 0002). Required so that every
-- attendance write path - including the raw SQLite/legacy UI path - can
-- record an append-only audit entry for the change it performs.
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    hashed_password TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id TEXT NOT NULL,
    actor_role TEXT,
    action TEXT NOT NULL,
    session_id TEXT,
    usn TEXT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    reason TEXT,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (actor_id) REFERENCES users(user_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor_ts ON audit_log (actor_id, timestamp);

-- Append-only protection for the audit log (mirrors migration 0002).
CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: updates forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: deletions forbidden');
END;
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
