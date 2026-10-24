"""Database schema definitions and initialization."""

from __future__ import annotations

import sqlite3
from typing import Union
from app.db.connection import DEFAULT_DB_PATH, get_connection

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
    status TEXT NOT NULL CHECK(status IN ('PRESENT', 'ABSENT', 'PENDING', 'UNREVIEWED')),
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


def init_db(db_target: Union[str, sqlite3.Connection] = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Initialize database tables and indexes."""
    if isinstance(db_target, sqlite3.Connection):
        db_target.executescript(SCHEMA_SQL)
        db_target.commit()
        return db_target

    conn = get_connection(db_target)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        return conn
    except Exception:
        conn.close()
        raise
