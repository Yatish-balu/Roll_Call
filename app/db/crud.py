"""CRUD operations for students, rooms, sessions, and attendance.

Supports both Supabase (PostgreSQL via SQLAlchemy) and local SQLite fallback
with identical function signatures and parameterized queries.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, Set, Union

from app.db.connection import (
    DEFAULT_DB_PATH,
    get_backend,
    get_connection,
    get_engine,
)


class _DBContext:
    """Unified wrapper around SQLite connection or SQLAlchemy connection."""

    def __init__(self, mode: str, conn: Any):
        self.mode = mode  # 'sqlite' or 'sqlalchemy'
        self.conn = conn

    def execute(self, sql: str, params: Optional[Union[Dict[str, Any], tuple, list]] = None) -> Any:
        if self.mode == "sqlalchemy":
            from sqlalchemy import text
            p = params if isinstance(params, dict) else (params or {})
            return self.conn.execute(text(sql), p)
        else:
            p = params if params is not None else ()
            return self.conn.execute(sql, p)

    def executemany(self, sql: str, param_list: List[Any]) -> Any:
        if self.mode == "sqlalchemy":
            from sqlalchemy import text
            return self.conn.execute(text(sql), param_list)
        else:
            return self.conn.executemany(sql, param_list)

    def commit(self) -> None:
        if self.mode == "sqlite":
            self.conn.commit()


@contextmanager
def _get_conn(
    target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH
) -> Generator[_DBContext, None, None]:
    """
    Yield a unified _DBContext.
    If target is an active sqlite3.Connection or SQLite target path, uses SQLite.
    If target is DEFAULT_DB_PATH and DB_BACKEND is 'supabase', uses SQLAlchemy with fallback to SQLite.
    """
    if isinstance(target, sqlite3.Connection):
        yield _DBContext("sqlite", target)
        return

    # Check if target is a custom path or memory
    if isinstance(target, str) and target != DEFAULT_DB_PATH:
        # Explicit custom SQLite path (like :memory: or tempfile)
        conn = get_connection(str(target))
        try:
            yield _DBContext("sqlite", conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return

    # Default target - check backend
    backend = get_backend()
    if backend == "supabase":
        engine = get_engine("supabase")
        if engine is not None:
            try:
                with engine.begin() as sa_conn:
                    yield _DBContext("sqlalchemy", sa_conn)
                return
            except Exception:
                # Graceful fallback to SQLite
                pass

    # SQLite fallback
    conn = get_connection(str(target))
    try:
        yield _DBContext("sqlite", conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_dict(row: Any) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


def _rows_to_dicts(rows: List[Any]) -> List[Dict[str, Any]]:
    return [_row_to_dict(r) for r in rows if r is not None]  # type: ignore[misc]


# ==========================================
# Students Operations
# ==========================================

def insert_student(
    target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH,
    *,
    usn: str,
    name: str,
    branch: str,
) -> Dict[str, Any]:
    """Insert a new student."""
    record = {"usn": usn.strip(), "name": name.strip(), "branch": branch.strip()}
    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = "INSERT INTO students (usn, name, branch) VALUES (:usn, :name, :branch)"
            ctx.execute(query, record)
        else:
            query = "INSERT INTO students (usn, name, branch) VALUES (?, ?, ?)"
            ctx.execute(query, (record["usn"], record["name"], record["branch"]))
            ctx.commit()
    return record


def insert_students_bulk(
    target_or_students: Union[sqlite3.Connection, str, List[Dict[str, str]], Any],
    students: Optional[List[Dict[str, str]]] = None,
) -> int:
    """Insert multiple students in a single transaction."""
    if isinstance(target_or_students, list) and students is None:
        target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH
        actual_students = target_or_students
    else:
        target = target_or_students
        actual_students = students or []

    records = [
        {"usn": s["usn"].strip(), "name": s["name"].strip(), "branch": s["branch"].strip()}
        for s in actual_students
    ]

    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = "INSERT INTO students (usn, name, branch) VALUES (:usn, :name, :branch)"
            res = ctx.executemany(query, records)
            return len(records)
        else:
            query = "INSERT INTO students (usn, name, branch) VALUES (?, ?, ?)"
            tuple_records = [(r["usn"], r["name"], r["branch"]) for r in records]
            cursor = ctx.conn.cursor()
            cursor.executemany(query, tuple_records)
            ctx.commit()
            return cursor.rowcount


def get_student(
    target_or_usn: Union[sqlite3.Connection, str, Any],
    usn: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a student by USN."""
    if usn is None:
        target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH
        actual_usn = str(target_or_usn)
    else:
        target = target_or_usn
        actual_usn = usn

    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = "SELECT usn, name, branch FROM students WHERE usn = :usn"
            result = ctx.execute(query, {"usn": actual_usn.strip()})
            row = result.fetchone()
        else:
            query = "SELECT usn, name, branch FROM students WHERE usn = ?"
            cursor = ctx.execute(query, (actual_usn.strip(),))
            row = cursor.fetchone()
        return _row_to_dict(row)


def get_all_students(
    target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Retrieve all students ordered by USN."""
    query = "SELECT usn, name, branch FROM students ORDER BY usn ASC"
    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            result = ctx.execute(query)
            return _rows_to_dicts(result.fetchall())
        else:
            cursor = ctx.execute(query)
            return _rows_to_dicts(cursor.fetchall())


def get_students_by_branch(
    target_or_branch: Union[sqlite3.Connection, str, Any],
    branch: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all students in a given branch."""
    if branch is None:
        target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH
        actual_branch = str(target_or_branch)
    else:
        target = target_or_branch
        actual_branch = branch

    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = "SELECT usn, name, branch FROM students WHERE branch = :branch ORDER BY usn ASC"
            result = ctx.execute(query, {"branch": actual_branch.strip()})
            return _rows_to_dicts(result.fetchall())
        else:
            query = "SELECT usn, name, branch FROM students WHERE branch = ? ORDER BY usn ASC"
            cursor = ctx.execute(query, (actual_branch.strip(),))
            return _rows_to_dicts(cursor.fetchall())


# ==========================================
# Rooms Operations
# ==========================================

def insert_room(
    target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH,
    *,
    room_id: str,
    name: str,
) -> Dict[str, Any]:
    """Insert a new room."""
    record = {"room_id": room_id.strip(), "name": name.strip()}
    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = "INSERT INTO rooms (room_id, name) VALUES (:room_id, :name)"
            ctx.execute(query, record)
        else:
            query = "INSERT INTO rooms (room_id, name) VALUES (?, ?)"
            ctx.execute(query, (record["room_id"], record["name"]))
            ctx.commit()
    return record


def insert_rooms_bulk(
    target_or_rooms: Union[sqlite3.Connection, str, List[Dict[str, str]], Any],
    rooms: Optional[List[Dict[str, str]]] = None,
) -> int:
    """Insert multiple rooms in a single transaction."""
    if isinstance(target_or_rooms, list) and rooms is None:
        target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH
        actual_rooms = target_or_rooms
    else:
        target = target_or_rooms
        actual_rooms = rooms or []

    records = [{"room_id": r["room_id"].strip(), "name": r["name"].strip()} for r in actual_rooms]
    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = "INSERT INTO rooms (room_id, name) VALUES (:room_id, :name)"
            ctx.executemany(query, records)
            return len(records)
        else:
            query = "INSERT INTO rooms (room_id, name) VALUES (?, ?)"
            tuple_records = [(r["room_id"], r["name"]) for r in records]
            cursor = ctx.conn.cursor()
            cursor.executemany(query, tuple_records)
            ctx.commit()
            return cursor.rowcount


def get_room(
    target_or_room_id: Union[sqlite3.Connection, str, Any],
    room_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a room by room_id."""
    if room_id is None:
        target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH
        actual_id = str(target_or_room_id)
    else:
        target = target_or_room_id
        actual_id = room_id

    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = "SELECT room_id, name FROM rooms WHERE room_id = :room_id"
            result = ctx.execute(query, {"room_id": actual_id.strip()})
            return _row_to_dict(result.fetchone())
        else:
            query = "SELECT room_id, name FROM rooms WHERE room_id = ?"
            cursor = ctx.execute(query, (actual_id.strip(),))
            return _row_to_dict(cursor.fetchone())


def get_all_rooms(
    target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Retrieve all rooms ordered by room_id."""
    query = "SELECT room_id, name FROM rooms ORDER BY room_id ASC"
    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            result = ctx.execute(query)
            return _rows_to_dicts(result.fetchall())
        else:
            cursor = ctx.execute(query)
            return _rows_to_dicts(cursor.fetchall())


# ==========================================
# Sessions Operations
# ==========================================

def insert_session(
    target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH,
    *,
    session_id: str,
    date: str,
    subject: str,
) -> Dict[str, Any]:
    """Insert a new session."""
    record = {"session_id": session_id.strip(), "date": date.strip(), "subject": subject.strip()}
    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = "INSERT INTO sessions (session_id, date, subject) VALUES (:session_id, :date, :subject)"
            ctx.execute(query, record)
        else:
            query = "INSERT INTO sessions (session_id, date, subject) VALUES (?, ?, ?)"
            ctx.execute(query, (record["session_id"], record["date"], record["subject"]))
            ctx.commit()
    return record


def insert_sessions_bulk(
    target_or_sessions: Union[sqlite3.Connection, str, List[Dict[str, str]], Any],
    sessions: Optional[List[Dict[str, str]]] = None,
) -> int:
    """Insert multiple sessions in a single transaction."""
    if isinstance(target_or_sessions, list) and sessions is None:
        target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH
        actual_sessions = target_or_sessions
    else:
        target = target_or_sessions
        actual_sessions = sessions or []

    records = [
        {"session_id": s["session_id"].strip(), "date": s["date"].strip(), "subject": s["subject"].strip()}
        for s in actual_sessions
    ]
    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = "INSERT INTO sessions (session_id, date, subject) VALUES (:session_id, :date, :subject)"
            ctx.executemany(query, records)
            return len(records)
        else:
            query = "INSERT INTO sessions (session_id, date, subject) VALUES (?, ?, ?)"
            tuple_records = [(s["session_id"], s["date"], s["subject"]) for s in records]
            cursor = ctx.conn.cursor()
            cursor.executemany(query, tuple_records)
            ctx.commit()
            return cursor.rowcount


def get_session(
    target_or_session_id: Union[sqlite3.Connection, str, Any],
    session_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a session by session_id."""
    if session_id is None:
        target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH
        actual_id = str(target_or_session_id)
    else:
        target = target_or_session_id
        actual_id = session_id

    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = "SELECT session_id, date, subject FROM sessions WHERE session_id = :session_id"
            result = ctx.execute(query, {"session_id": actual_id.strip()})
            return _row_to_dict(result.fetchone())
        else:
            query = "SELECT session_id, date, subject FROM sessions WHERE session_id = ?"
            cursor = ctx.execute(query, (actual_id.strip(),))
            return _row_to_dict(cursor.fetchone())


def get_all_sessions(
    target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Retrieve all sessions ordered by date descending."""
    query = "SELECT session_id, date, subject FROM sessions ORDER BY date DESC, session_id ASC"
    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            result = ctx.execute(query)
            return _rows_to_dicts(result.fetchall())
        else:
            cursor = ctx.execute(query)
            return _rows_to_dicts(cursor.fetchall())


def get_sessions_by_date(
    target_or_date: Union[sqlite3.Connection, str, Any],
    date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve sessions for a specific date."""
    if date is None:
        target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH
        actual_date = str(target_or_date)
    else:
        target = target_or_date
        actual_date = date

    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = "SELECT session_id, date, subject FROM sessions WHERE date = :date ORDER BY session_id ASC"
            result = ctx.execute(query, {"date": actual_date.strip()})
            return _rows_to_dicts(result.fetchall())
        else:
            query = "SELECT session_id, date, subject FROM sessions WHERE date = ? ORDER BY session_id ASC"
            cursor = ctx.execute(query, (actual_date.strip(),))
            return _rows_to_dicts(cursor.fetchall())


# ==========================================
# Attendance Operations
# ==========================================

VALID_ATTENDANCE_STATUSES = {"PRESENT", "ABSENT", "PENDING", "UNREVIEWED"}

STATUS_ALIASES = {
    "present": "PRESENT",
    "p": "PRESENT",
    "1": "PRESENT",
    "yes": "PRESENT",
    "true": "PRESENT",
    "absent": "ABSENT",
    "a": "ABSENT",
    "0": "ABSENT",
    "no": "ABSENT",
    "false": "ABSENT",
    "pending": "PENDING",
    "unreviewed": "UNREVIEWED",
    "ambiguous": "UNREVIEWED",
}


def normalize_attendance_status(status: Any) -> str:
    """Normalize status string to uppercase and validate against allowed states."""
    if status is None or not str(status).strip():
        raise ValueError("Attendance status cannot be empty or blank.")
    clean = str(status).strip().lower()
    normalized = STATUS_ALIASES.get(clean, str(status).strip().upper())
    if normalized not in VALID_ATTENDANCE_STATUSES:
        raise ValueError(
            f"Invalid attendance status '{status}'. Must be one of: {sorted(VALID_ATTENDANCE_STATUSES)}"
        )
    return normalized


def insert_attendance(
    target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH,
    *,
    session_id: str,
    usn: str,
    room_id: str,
    status: str,
    source: str,
    confidence: float = 1.0,
    upsert: bool = False,
) -> Dict[str, Any]:
    """Insert or optionally upsert an attendance record."""
    clean_status = normalize_attendance_status(status)
    record = {
        "session_id": session_id.strip(),
        "usn": usn.strip(),
        "room_id": room_id.strip(),
        "status": clean_status,
        "source": source.strip(),
        "confidence": float(confidence),
    }

    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            if upsert:
                query = """
                INSERT INTO attendance (session_id, usn, room_id, status, source, confidence)
                VALUES (:session_id, :usn, :room_id, :status, :source, :confidence)
                ON CONFLICT(session_id, usn) DO UPDATE SET
                    room_id = EXCLUDED.room_id,
                    status = EXCLUDED.status,
                    source = EXCLUDED.source,
                    confidence = EXCLUDED.confidence
                """
            else:
                query = """
                INSERT INTO attendance (session_id, usn, room_id, status, source, confidence)
                VALUES (:session_id, :usn, :room_id, :status, :source, :confidence)
                """
            ctx.execute(query, record)
        else:
            if upsert:
                query = """
                INSERT INTO attendance (session_id, usn, room_id, status, source, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, usn) DO UPDATE SET
                    room_id = excluded.room_id,
                    status = excluded.status,
                    source = excluded.source,
                    confidence = excluded.confidence
                """
            else:
                query = """
                INSERT INTO attendance (session_id, usn, room_id, status, source, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                """
            ctx.execute(
                query,
                (
                    record["session_id"],
                    record["usn"],
                    record["room_id"],
                    record["status"],
                    record["source"],
                    record["confidence"],
                ),
            )
            ctx.commit()

    return record


def insert_attendance_bulk(
    target_or_records: Union[sqlite3.Connection, str, List[Dict[str, Any]], Any],
    records: Optional[List[Dict[str, Any]]] = None,
    upsert: bool = False,
) -> int:
    """Insert multiple attendance records."""
    if isinstance(target_or_records, list) and records is None:
        target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH
        actual_records = target_or_records
    else:
        target = target_or_records
        actual_records = records or []

    formatted_records = [
        {
            "session_id": r["session_id"].strip(),
            "usn": r["usn"].strip(),
            "room_id": r["room_id"].strip(),
            "status": normalize_attendance_status(r["status"]),
            "source": r["source"].strip(),
            "confidence": float(r.get("confidence", 1.0)),
        }
        for r in actual_records
    ]

    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            if upsert:
                query = """
                INSERT INTO attendance (session_id, usn, room_id, status, source, confidence)
                VALUES (:session_id, :usn, :room_id, :status, :source, :confidence)
                ON CONFLICT(session_id, usn) DO UPDATE SET
                    room_id = EXCLUDED.room_id,
                    status = EXCLUDED.status,
                    source = EXCLUDED.source,
                    confidence = EXCLUDED.confidence
                """
            else:
                query = """
                INSERT INTO attendance (session_id, usn, room_id, status, source, confidence)
                VALUES (:session_id, :usn, :room_id, :status, :source, :confidence)
                """
            ctx.executemany(query, formatted_records)
            return len(formatted_records)
        else:
            if upsert:
                query = """
                INSERT INTO attendance (session_id, usn, room_id, status, source, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, usn) DO UPDATE SET
                    room_id = excluded.room_id,
                    status = excluded.status,
                    source = excluded.source,
                    confidence = excluded.confidence
                """
            else:
                query = """
                INSERT INTO attendance (session_id, usn, room_id, status, source, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                """
            tuple_records = [
                (
                    r["session_id"],
                    r["usn"],
                    r["room_id"],
                    r["status"],
                    r["source"],
                    r["confidence"],
                )
                for r in formatted_records
            ]
            cursor = ctx.conn.cursor()
            cursor.executemany(query, tuple_records)
            ctx.commit()
            return cursor.rowcount


def delete_session_attendance(
    target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH,
    session_id: str = "",
) -> int:
    """Delete all attendance records for a specific session without affecting other sessions."""
    clean_id = session_id.strip()
    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = "DELETE FROM attendance WHERE session_id = :session_id"
            result = ctx.execute(query, {"session_id": clean_id})
            return result.rowcount if hasattr(result, "rowcount") else 0
        else:
            query = "DELETE FROM attendance WHERE session_id = ?"
            cursor = ctx.execute(query, (clean_id,))
            ctx.commit()
            return cursor.rowcount


def replace_session_attendance(
    target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH,
    session_id: str = "",
    records: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """
    Atomically re-upload/replace all attendance records for a session.
    Cleans up old records for this session only and inserts new records without affecting other sessions.
    """
    new_records = records or []
    validated_records = []
    for r in new_records:
        if not isinstance(r, dict):
            raise ValueError("Each attendance record must be a mapping with string keys.")
        try:
            usn = str(r.get("usn", "")).strip().upper()
            room_id = str(r.get("room_id", "LH-101")).strip()
            status = normalize_attendance_status(str(r.get("status", "UNREVIEWED")))
            source = str(r.get("source", "UI_CONFIRMED")).strip()
            confidence = float(r.get("confidence", 1.0))
        except Exception as exc:
            raise ValueError(f"Invalid attendance record: {exc}")

        if not usn:
            raise ValueError("Invalid attendance record: usn is empty.")

        if not room_id:
            room_id = "LH-101"
        if not status:
            status = "UNREVIEWED"
        if not source:
            source = "UI_CONFIRMED"

        validated_records.append({
            "session_id": session_id.strip(),
            "usn": usn,
            "room_id": room_id,
            "status": status,
            "source": source,
            "confidence": confidence,
        })

    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            ctx.execute("DELETE FROM attendance WHERE session_id = :session_id", {"session_id": session_id.strip()})
            query = """
            INSERT INTO attendance (session_id, usn, room_id, status, source, confidence)
            VALUES (:session_id, :usn, :room_id, :status, :source, :confidence)
            """
            ctx.executemany(query, validated_records)
            return len(validated_records)
        else:
            ctx.execute("DELETE FROM attendance WHERE session_id = ?", (session_id.strip(),))
            query = """
            INSERT INTO attendance (session_id, usn, room_id, status, source, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """
            cursor = ctx.conn.cursor()
            insert_rows = [
                (v["session_id"], v["usn"], v["room_id"], v["status"], v["source"], v["confidence"])
                for v in validated_records
            ]
            cursor.executemany(query, insert_rows)
            ctx.commit()
            return len(validated_records)


def reconcile_session_roster(
    target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH,
    *,
    session_id: str,
    roster: List[Dict[str, str]],
    uploaded_records: List[Dict[str, Any]],
    missing_room_ids: Optional[Set[str]] = None,
    confidence_threshold: float = 0.7,
    persist: bool = False,
) -> List[Dict[str, Any]]:
    """Reconcile student roster against uploaded attendance sheet records for a session."""
    missing_rooms = set(missing_room_ids or [])
    uploaded_by_usn = {
        r["usn"].strip().upper(): r for r in uploaded_records if r.get("usn")
    }

    reconciled: List[Dict[str, Any]] = []
    for item in roster:
        usn = item["usn"].strip().upper()
        room_id = item.get("room_id", "LH-101").strip()

        if room_id in missing_rooms or usn not in uploaded_by_usn:
            status = "PENDING"
            source = "roster_reconciliation"
            conf = 1.0
        else:
            rec = uploaded_by_usn[usn]
            raw_status = str(rec.get("status", "")).strip().upper()
            conf = float(rec.get("confidence", 1.0))
            source = str(rec.get("source", "upload")).strip()
            room_id = str(rec.get("room_id", room_id)).strip()

            if raw_status in ("UNREVIEWED", "AMBIGUOUS", "?") or conf < confidence_threshold:
                status = "UNREVIEWED"
            elif raw_status in ("PRESENT", "P", "1", "YES", "TRUE"):
                status = "PRESENT"
            elif raw_status in ("ABSENT", "A", "0", "NO", "FALSE"):
                status = "ABSENT"
            elif raw_status == "PENDING":
                status = "PENDING"
            else:
                status = "UNREVIEWED"

        reconciled.append({
            "session_id": session_id.strip(),
            "usn": usn,
            "room_id": room_id,
            "status": status,
            "source": source,
            "confidence": conf,
        })

    if persist:
        replace_session_attendance(target, session_id, reconciled)

    return reconciled


def get_attendance_record(
    target_or_session_id: Union[sqlite3.Connection, str, Any],
    session_id_or_usn: str,
    usn: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve attendance record for a specific student in a specific session."""
    if usn is None:
        target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH
        actual_session_id = str(target_or_session_id)
        actual_usn = session_id_or_usn
    else:
        target = target_or_session_id
        actual_session_id = session_id_or_usn
        actual_usn = usn

    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = """
            SELECT session_id, usn, room_id, status, source, confidence
            FROM attendance
            WHERE session_id = :session_id AND usn = :usn
            """
            result = ctx.execute(query, {"session_id": actual_session_id.strip(), "usn": actual_usn.strip()})
            return _row_to_dict(result.fetchone())
        else:
            query = """
            SELECT session_id, usn, room_id, status, source, confidence
            FROM attendance
            WHERE session_id = ? AND usn = ?
            """
            cursor = ctx.execute(query, (actual_session_id.strip(), actual_usn.strip()))
            return _row_to_dict(cursor.fetchone())


def get_attendance_by_session(
    target_or_session_id: Union[sqlite3.Connection, str, Any],
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all attendance records for a given session."""
    if session_id is None:
        target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH
        actual_id = str(target_or_session_id)
    else:
        target = target_or_session_id
        actual_id = session_id

    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = """
            SELECT session_id, usn, room_id, status, source, confidence
            FROM attendance
            WHERE session_id = :session_id
            ORDER BY usn ASC
            """
            result = ctx.execute(query, {"session_id": actual_id.strip()})
            return _rows_to_dicts(result.fetchall())
        else:
            query = """
            SELECT session_id, usn, room_id, status, source, confidence
            FROM attendance
            WHERE session_id = ?
            ORDER BY usn ASC
            """
            cursor = ctx.execute(query, (actual_id.strip(),))
            rows = cursor.fetchall()
            if isinstance(rows, list) and rows and isinstance(rows[0], sqlite3.Row):
                return _rows_to_dicts(rows)
            return [
                {
                    "session_id": r[0],
                    "usn": r[1],
                    "room_id": r[2],
                    "status": r[3],
                    "source": r[4],
                    "confidence": r[5],
                }
                for r in rows
            ]


def get_attendance_by_student(
    target_or_usn: Union[sqlite3.Connection, str, Any],
    usn: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all attendance records for a specific student."""
    if usn is None:
        target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH
        actual_usn = str(target_or_usn)
    else:
        target = target_or_usn
        actual_usn = usn

    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = """
            SELECT session_id, usn, room_id, status, source, confidence
            FROM attendance
            WHERE usn = :usn
            ORDER BY session_id ASC
            """
            result = ctx.execute(query, {"usn": actual_usn.strip()})
            return _rows_to_dicts(result.fetchall())
        else:
            query = """
            SELECT session_id, usn, room_id, status, source, confidence
            FROM attendance
            WHERE usn = ?
            ORDER BY session_id ASC
            """
            cursor = ctx.execute(query, (actual_usn.strip(),))
            return _rows_to_dicts(cursor.fetchall())


def get_session_attendance_details(
    target_or_session_id: Union[sqlite3.Connection, str, Any],
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve joined detailed attendance data for a session."""
    if session_id is None:
        target: Union[sqlite3.Connection, str, Any] = DEFAULT_DB_PATH
        actual_id = str(target_or_session_id)
    else:
        target = target_or_session_id
        actual_id = session_id

    with _get_conn(target) as ctx:
        if ctx.mode == "sqlalchemy":
            query = """
            SELECT
                a.session_id,
                sess.date AS session_date,
                sess.subject,
                a.usn,
                stu.name AS student_name,
                stu.branch,
                a.room_id,
                rm.name AS room_name,
                a.status,
                a.source,
                a.confidence
            FROM attendance a
            JOIN sessions sess ON a.session_id = sess.session_id
            JOIN students stu ON a.usn = stu.usn
            JOIN rooms rm ON a.room_id = rm.room_id
            WHERE a.session_id = :session_id
            ORDER BY stu.name ASC
            """
            result = ctx.execute(query, {"session_id": actual_id.strip()})
            return _rows_to_dicts(result.fetchall())
        else:
            query = """
            SELECT
                a.session_id,
                sess.date AS session_date,
                sess.subject,
                a.usn,
                stu.name AS student_name,
                stu.branch,
                a.room_id,
                rm.name AS room_name,
                a.status,
                a.source,
                a.confidence
            FROM attendance a
            JOIN sessions sess ON a.session_id = sess.session_id
            JOIN students stu ON a.usn = stu.usn
            JOIN rooms rm ON a.room_id = rm.room_id
            WHERE a.session_id = ?
            ORDER BY stu.name ASC
            """
            cursor = ctx.execute(query, (actual_id.strip(),))
            return _rows_to_dicts(cursor.fetchall())
