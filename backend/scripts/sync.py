"""Database synchronization utility between Supabase PostgreSQL and local SQLite.

Usage:
  # Supabase -> SQLite (default): copies all tables safely without duplicates
  python scripts/sync.py

  # SQLite -> Supabase (--init): initial load of all records from SQLite into Supabase
  python scripts/sync.py --init
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.db.connection import (
    DEFAULT_DB_PATH,
    get_connection,
    get_engine,
)
from app.db.schema import init_db

TABLES_IN_ORDER = ["students", "rooms", "sessions", "attendance"]


def _get_sqlite_conn(sqlite_path: str):
    """Return an active SQLite connection with row factory."""
    return get_connection(sqlite_path)


def _get_supabase_engine():
    """Return an active SQLAlchemy engine for Supabase PostgreSQL."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL is not set in environment or .env file.")
    engine = get_engine("supabase", db_url=db_url)
    if engine is None:
        raise ConnectionError("Could not create SQLAlchemy engine for Supabase.")
    return engine


def sync_supabase_to_sqlite(sqlite_path: str = DEFAULT_DB_PATH) -> Dict[str, int]:
    """
    Copy all tables from Supabase PostgreSQL to local SQLite.
    Safe to rerun: uses INSERT OR REPLACE (or INSERT OR IGNORE) to prevent duplicates.
    """
    engine = _get_supabase_engine()
    sq_conn = _get_sqlite_conn(sqlite_path)
    init_db(sq_conn)

    counts: Dict[str, int] = {}
    from sqlalchemy import text

    try:
        with engine.connect() as pg_conn:
            # 1. Students
            pg_res = pg_conn.execute(text("SELECT usn, name, branch FROM students ORDER BY usn"))
            students = [dict(r._mapping) for r in pg_res]
            if students:
                sq_conn.executemany(
                    "INSERT INTO students (usn, name, branch) VALUES (?, ?, ?) "
                    "ON CONFLICT(usn) DO UPDATE SET name=excluded.name, branch=excluded.branch",
                    [(s["usn"], s["name"], s["branch"]) for s in students],
                )
            counts["students"] = len(students)

            # 2. Rooms
            pg_res = pg_conn.execute(text("SELECT room_id, name FROM rooms ORDER BY room_id"))
            rooms = [dict(r._mapping) for r in pg_res]
            if rooms:
                sq_conn.executemany(
                    "INSERT INTO rooms (room_id, name) VALUES (?, ?) "
                    "ON CONFLICT(room_id) DO UPDATE SET name=excluded.name",
                    [(r["room_id"], r["name"]) for r in rooms],
                )
            counts["rooms"] = len(rooms)

            # 3. Sessions
            pg_res = pg_conn.execute(text("SELECT session_id, date, subject FROM sessions ORDER BY session_id"))
            sessions = [dict(r._mapping) for r in pg_res]
            if sessions:
                sq_conn.executemany(
                    "INSERT INTO sessions (session_id, date, subject) VALUES (?, ?, ?) "
                    "ON CONFLICT(session_id) DO UPDATE SET date=excluded.date, subject=excluded.subject",
                    [(s["session_id"], s["date"], s["subject"]) for s in sessions],
                )
            counts["sessions"] = len(sessions)

            # 4. Attendance
            pg_res = pg_conn.execute(
                text("SELECT session_id, usn, room_id, status, source, confidence FROM attendance ORDER BY session_id, usn")
            )
            attendance = [dict(r._mapping) for r in pg_res]
            if attendance:
                sq_conn.executemany(
                    "INSERT INTO attendance (session_id, usn, room_id, status, source, confidence) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(session_id, usn) DO UPDATE SET "
                    "room_id=excluded.room_id, status=excluded.status, source=excluded.source, confidence=excluded.confidence",
                    [
                        (
                            a["session_id"],
                            a["usn"],
                            a["room_id"],
                            a["status"],
                            a["source"],
                            float(a.get("confidence", 1.0)),
                        )
                        for a in attendance
                    ],
                )
            counts["attendance"] = len(attendance)

            sq_conn.commit()
    finally:
        sq_conn.close()

    return counts


def sync_sqlite_to_supabase(sqlite_path: str = DEFAULT_DB_PATH) -> Dict[str, int]:
    """
    Initial load from local SQLite to Supabase PostgreSQL (--init flag).
    Uses ON CONFLICT DO UPDATE so it is safe to rerun without creating duplicates.
    """
    sq_conn = _get_sqlite_conn(sqlite_path)
    engine = _get_supabase_engine()
    init_db(engine)

    counts: Dict[str, int] = {}
    from sqlalchemy import text

    try:
        with engine.begin() as pg_conn:
            cursor = sq_conn.cursor()

            # 1. Students
            cursor.execute("SELECT usn, name, branch FROM students ORDER BY usn")
            students = [dict(r) for r in cursor.fetchall()]
            if students:
                pg_conn.execute(
                    text(
                        "INSERT INTO students (usn, name, branch) VALUES (:usn, :name, :branch) "
                        "ON CONFLICT (usn) DO UPDATE SET name = EXCLUDED.name, branch = EXCLUDED.branch"
                    ),
                    students,
                )
            counts["students"] = len(students)

            # 2. Rooms
            cursor.execute("SELECT room_id, name FROM rooms ORDER BY room_id")
            rooms = [dict(r) for r in cursor.fetchall()]
            if rooms:
                pg_conn.execute(
                    text(
                        "INSERT INTO rooms (room_id, name) VALUES (:room_id, :name) "
                        "ON CONFLICT (room_id) DO UPDATE SET name = EXCLUDED.name"
                    ),
                    rooms,
                )
            counts["rooms"] = len(rooms)

            # 3. Sessions
            cursor.execute("SELECT session_id, date, subject FROM sessions ORDER BY session_id")
            sessions = [dict(r) for r in cursor.fetchall()]
            if sessions:
                pg_conn.execute(
                    text(
                        "INSERT INTO sessions (session_id, date, subject) VALUES (:session_id, :date, :subject) "
                        "ON CONFLICT (session_id) DO UPDATE SET date = EXCLUDED.date, subject = EXCLUDED.subject"
                    ),
                    sessions,
                )
            counts["sessions"] = len(sessions)

            # 4. Attendance
            cursor.execute("SELECT session_id, usn, room_id, status, source, confidence FROM attendance ORDER BY session_id, usn")
            attendance = [dict(r) for r in cursor.fetchall()]
            if attendance:
                pg_conn.execute(
                    text(
                        "INSERT INTO attendance (session_id, usn, room_id, status, source, confidence) "
                        "VALUES (:session_id, :usn, :room_id, :status, :source, :confidence) "
                        "ON CONFLICT (session_id, usn) DO UPDATE SET "
                        "room_id = EXCLUDED.room_id, status = EXCLUDED.status, source = EXCLUDED.source, confidence = EXCLUDED.confidence"
                    ),
                    attendance,
                )
            counts["attendance"] = len(attendance)
    finally:
        sq_conn.close()

    return counts


def main():
    parser = argparse.ArgumentParser(description="Synchronize tables between Supabase PostgreSQL and SQLite.")
    parser.add_argument(
        "--init",
        action="store_true",
        help="Initial load: Copy all records from SQLite to Supabase PostgreSQL.",
    )
    parser.add_argument(
        "--sqlite-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to local SQLite database (default: {DEFAULT_DB_PATH})",
    )
    args = parser.parse_args()

    try:
        if args.init:
            counts = sync_sqlite_to_supabase(args.sqlite_path)
            print(f"[+] Initial load (SQLite -> Supabase) completed successfully:")
            for tbl, cnt in counts.items():
                print(f"    - {tbl}: {cnt} rows synchronized")
        else:
            counts = sync_supabase_to_sqlite(args.sqlite_path)
            print(f"[+] Sync (Supabase -> SQLite) completed successfully:")
            for tbl, cnt in counts.items():
                print(f"    - {tbl}: {cnt} rows synchronized")
    except Exception as exc:
        print(f"[-] Synchronization error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

