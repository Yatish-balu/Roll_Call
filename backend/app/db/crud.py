"""CRUD operations for students, rooms, sessions, and attendance.

Supports both:
1. Legacy SQLite Connection and database file paths.
2. Modern SQLAlchemy 2.0 synchronous Session objects.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Generator, List, Optional, Sequence, Set, Tuple, Union
from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.connection import DEFAULT_DB_PATH, get_connection
from app.db.models import (
    Student,
    Room,
    Session as DbSession,
    Attendance,
    User,
    TeacherSubject,
    AuditLog,
    LoginAttempt,
    PendingEdit,
    AuthSession,
    AuthRefreshToken,
)



@contextmanager
def _get_conn(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
) -> Generator[sqlite3.Connection, None, None]:
    """Yield an existing SQLite connection without closing it, or open and manage a new one."""
    if isinstance(target, sqlite3.Connection):
        yield target
    elif isinstance(target, Session):
        raise TypeError("_get_conn is only for SQLite connection/path targets, not SQLAlchemy Sessions.")
    else:
        conn = get_connection(str(target))
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _row_to_dict(row: Optional[Union[sqlite3.Row, Student, Room, DbSession, Attendance, Any]]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return dict(row)
    if isinstance(row, Student):
        return {"usn": row.usn, "name": row.name, "branch": row.branch}
    if isinstance(row, Room):
        return {"room_id": row.room_id, "name": row.name}
    if isinstance(row, DbSession):
        return {
            "session_id": row.session_id,
            "date": row.date,
            "subject": row.subject,
            "created_at": getattr(row, "created_at", None),
            "teacher_id": getattr(row, "teacher_id", None),
            "subject_code": getattr(row, "subject_code", None),
        }
    if isinstance(row, Attendance):
        return {
            "session_id": row.session_id,
            "usn": row.usn,
            "room_id": row.room_id,
            "status": row.status,
            "source": row.source,
            "confidence": row.confidence,
        }
    if isinstance(row, User):
        return {
            "user_id": row.user_id,
            "email": row.email,
            "role": row.role,
            "is_active": row.is_active,
            "created_at": row.created_at,
        }
    if isinstance(row, TeacherSubject):
        return {
            "id": row.id,
            "user_id": row.user_id,
            "subject_code": row.subject_code,
        }
    if isinstance(row, AuditLog):
        return {
            "log_id": row.log_id,
            "actor_id": row.actor_id,
            "action": row.action,
            "session_id": row.session_id,
            "usn": row.usn,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "old_value": row.old_value,
            "new_value": row.new_value,
            "reason": row.reason,
            "timestamp": row.timestamp,
        }
    if isinstance(row, LoginAttempt):
        return {
            "id": row.id,
            "user_id": row.user_id,
            "ip_address": row.ip_address,
            "success": row.success,
            "timestamp": row.timestamp,
        }
    if isinstance(row, PendingEdit):
        return {
            "edit_id": row.edit_id,
            "user_id": row.user_id,
            "session_id": row.session_id,
            "usn": row.usn,
            "old_status": row.old_status,
            "new_status": row.new_status,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
            "consumed": row.consumed,
        }
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)



def _rows_to_dicts(rows: List[Any]) -> List[Dict[str, Any]]:
    return [_row_to_dict(row) for row in rows if row is not None]  # type: ignore


# ==========================================
# Students Operations
# ==========================================

def insert_student(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    usn: str,
    name: str,
    branch: str,
) -> Dict[str, Any]:
    """Insert a new student."""
    clean_usn = usn.strip()
    clean_name = name.strip()
    clean_branch = branch.strip()

    if isinstance(target, Session):
        student = Student(usn=clean_usn, name=clean_name, branch=clean_branch)
        target.add(student)
        target.flush()
        return {"usn": clean_usn, "name": clean_name, "branch": clean_branch}

    query = "INSERT INTO students (usn, name, branch) VALUES (?, ?, ?)"
    with _get_conn(target) as conn:
        conn.execute(query, (clean_usn, clean_name, clean_branch))
        if isinstance(target, sqlite3.Connection):
            conn.commit()
    return {"usn": clean_usn, "name": clean_name, "branch": clean_branch}


def insert_students_bulk(
    target_or_students: Union[sqlite3.Connection, Session, str, List[Dict[str, str]]],
    students: Optional[List[Dict[str, str]]] = None,
) -> int:
    """Insert multiple students in a single transaction."""
    if isinstance(target_or_students, list) and students is None:
        target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
        actual_students = target_or_students
    else:
        target = target_or_students  # type: ignore[assignment]
        actual_students = students or []

    records = [
        {"usn": s["usn"].strip(), "name": s["name"].strip(), "branch": s["branch"].strip()}
        for s in actual_students
    ]

    if isinstance(target, Session):
        if not records:
            return 0
        target.bulk_insert_mappings(Student, records)
        target.flush()
        return len(records)

    tuple_records = [(r["usn"], r["name"], r["branch"]) for r in records]
    query = "INSERT INTO students (usn, name, branch) VALUES (?, ?, ?)"
    with _get_conn(target) as conn:
        cursor = conn.cursor()
        cursor.executemany(query, tuple_records)
        if isinstance(target, sqlite3.Connection):
            conn.commit()
        return cursor.rowcount


def get_student(
    target_or_usn: Union[sqlite3.Connection, Session, str],
    usn: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a student by USN."""
    if usn is None and not isinstance(target_or_usn, (sqlite3.Connection, Session)):
        target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
        actual_usn = str(target_or_usn)
    else:
        target = target_or_usn
        actual_usn = usn or ""

    clean_usn = actual_usn.strip()

    if isinstance(target, Session):
        stmt = select(Student).where(Student.usn == clean_usn)
        res = target.scalars(stmt).first()
        return _row_to_dict(res)

    query = "SELECT usn, name, branch FROM students WHERE usn = ?"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (clean_usn,))
        row = cursor.fetchone()
        return _row_to_dict(row)


def get_all_students(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Retrieve all students ordered by USN."""
    if isinstance(target, Session):
        stmt = select(Student).order_by(Student.usn.asc())
        rows = target.scalars(stmt).all()
        return _rows_to_dicts(list(rows))

    query = "SELECT usn, name, branch FROM students ORDER BY usn ASC"
    with _get_conn(target) as conn:
        cursor = conn.execute(query)
        return _rows_to_dicts(cursor.fetchall())


def get_students_by_branch(
    target_or_branch: Union[sqlite3.Connection, Session, str],
    branch: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all students in a given branch."""
    if branch is None and not isinstance(target_or_branch, (sqlite3.Connection, Session)):
        target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
        actual_branch = str(target_or_branch)
    else:
        target = target_or_branch
        actual_branch = branch or ""

    clean_branch = actual_branch.strip()

    if isinstance(target, Session):
        stmt = select(Student).where(Student.branch == clean_branch).order_by(Student.usn.asc())
        rows = target.scalars(stmt).all()
        return _rows_to_dicts(list(rows))

    query = "SELECT usn, name, branch FROM students WHERE branch = ? ORDER BY usn ASC"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (clean_branch,))
        return _rows_to_dicts(cursor.fetchall())


def get_students_paginated(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    branch: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Retrieve paginated student records with optional branch filter and search query.
    Search safely matches USN, name, and branch.
    Returns (items, total_count).
    """
    limit_val = max(1, min(200, limit))
    offset_val = max(0, offset)

    if isinstance(target, Session):
        conditions = []
        if branch and branch.strip():
            conditions.append(Student.branch == branch.strip())
        if search and search.strip():
            term = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(Student.usn).like(term),
                    func.lower(Student.name).like(term),
                    func.lower(Student.branch).like(term),
                )
            )

        count_stmt = select(func.count(Student.usn))
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total = target.scalar(count_stmt) or 0

        stmt = select(Student)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(Student.usn.asc()).limit(limit_val).offset(offset_val)
        rows = target.scalars(stmt).all()
        return _rows_to_dicts(list(rows)), total

    where_clauses = []
    params: List[Any] = []
    if branch and branch.strip():
        where_clauses.append("branch = ?")
        params.append(branch.strip())
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        where_clauses.append("(LOWER(usn) LIKE ? OR LOWER(name) LIKE ? OR LOWER(branch) LIKE ?)")
        params.extend([term, term, term])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    with _get_conn(target) as conn:
        count_cursor = conn.execute(f"SELECT COUNT(*) FROM students {where_sql}", params)
        total = count_cursor.fetchone()[0]

        data_query = f"SELECT usn, name, branch FROM students {where_sql} ORDER BY usn ASC LIMIT ? OFFSET ?"
        data_params = params + [limit_val, offset_val]
        data_cursor = conn.execute(data_query, data_params)
        items = _rows_to_dicts(data_cursor.fetchall())
        return items, total


# ==========================================
# Rooms Operations
# ==========================================

def insert_room(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    room_id: str,
    name: str,
) -> Dict[str, Any]:
    """Insert a new room."""
    clean_id = room_id.strip()
    clean_name = name.strip()

    if isinstance(target, Session):
        room = Room(room_id=clean_id, name=clean_name)
        target.add(room)
        target.flush()
        return {"room_id": clean_id, "name": clean_name}

    query = "INSERT INTO rooms (room_id, name) VALUES (?, ?)"
    with _get_conn(target) as conn:
        conn.execute(query, (clean_id, clean_name))
        if isinstance(target, sqlite3.Connection):
            conn.commit()
    return {"room_id": clean_id, "name": clean_name}


def insert_rooms_bulk(
    target_or_rooms: Union[sqlite3.Connection, Session, str, List[Dict[str, str]]],
    rooms: Optional[List[Dict[str, str]]] = None,
) -> int:
    """Insert multiple rooms in a single transaction."""
    if isinstance(target_or_rooms, list) and rooms is None:
        target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
        actual_rooms = target_or_rooms
    else:
        target = target_or_rooms  # type: ignore[assignment]
        actual_rooms = rooms or []

    records = [{"room_id": r["room_id"].strip(), "name": r["name"].strip()} for r in actual_rooms]

    if isinstance(target, Session):
        if not records:
            return 0
        target.bulk_insert_mappings(Room, records)
        target.flush()
        return len(records)

    tuple_records = [(r["room_id"], r["name"]) for r in records]
    query = "INSERT INTO rooms (room_id, name) VALUES (?, ?)"
    with _get_conn(target) as conn:
        cursor = conn.cursor()
        cursor.executemany(query, tuple_records)
        if isinstance(target, sqlite3.Connection):
            conn.commit()
        return cursor.rowcount


def get_room(
    target_or_room_id: Union[sqlite3.Connection, Session, str],
    room_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a room by room_id."""
    if room_id is None and not isinstance(target_or_room_id, (sqlite3.Connection, Session)):
        target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
        actual_id = str(target_or_room_id)
    else:
        target = target_or_room_id
        actual_id = room_id or ""

    clean_id = actual_id.strip()

    if isinstance(target, Session):
        stmt = select(Room).where(Room.room_id == clean_id)
        res = target.scalars(stmt).first()
        return _row_to_dict(res)

    query = "SELECT room_id, name FROM rooms WHERE room_id = ?"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (clean_id,))
        return _row_to_dict(cursor.fetchone())


def get_all_rooms(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Retrieve all rooms ordered by room_id."""
    if isinstance(target, Session):
        stmt = select(Room).order_by(Room.room_id.asc())
        rows = target.scalars(stmt).all()
        return _rows_to_dicts(list(rows))

    query = "SELECT room_id, name FROM rooms ORDER BY room_id ASC"
    with _get_conn(target) as conn:
        cursor = conn.execute(query)
        return _rows_to_dicts(cursor.fetchall())


def get_rooms_paginated(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Retrieve paginated room records with optional search query.
    Search safely matches room_id and name.
    Returns (items, total_count).
    """
    limit_val = max(1, min(200, limit))
    offset_val = max(0, offset)

    if isinstance(target, Session):
        conditions = []
        if search and search.strip():
            term = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(Room.room_id).like(term),
                    func.lower(Room.name).like(term),
                )
            )

        count_stmt = select(func.count(Room.room_id))
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total = target.scalar(count_stmt) or 0

        stmt = select(Room)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(Room.room_id.asc()).limit(limit_val).offset(offset_val)
        rows = target.scalars(stmt).all()
        return _rows_to_dicts(list(rows)), total

    where_clauses = []
    params: List[Any] = []
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        where_clauses.append("(LOWER(room_id) LIKE ? OR LOWER(name) LIKE ?)")
        params.extend([term, term])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    with _get_conn(target) as conn:
        count_cursor = conn.execute(f"SELECT COUNT(*) FROM rooms {where_sql}", params)
        total = count_cursor.fetchone()[0]

        data_query = f"SELECT room_id, name FROM rooms {where_sql} ORDER BY room_id ASC LIMIT ? OFFSET ?"
        data_params = params + [limit_val, offset_val]
        data_cursor = conn.execute(data_query, data_params)
        items = _rows_to_dicts(data_cursor.fetchall())
        return items, total


# ==========================================
# Sessions Operations
# ==========================================

def insert_session(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    session_id: str,
    date: str,
    subject: str,
    teacher_id: Optional[str] = None,
    subject_code: Optional[str] = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert a new session. N4: optionally stamps teacher, subject code and creation time."""
    clean_id = session_id.strip()
    clean_date = date.strip()
    clean_sub = subject.strip()
    clean_teacher = teacher_id.strip() if teacher_id else None
    clean_code = subject_code.strip().upper() if subject_code else None
    clean_created = created_at or _utcnow_iso()

    record = {
        "session_id": clean_id,
        "date": clean_date,
        "subject": clean_sub,
        "teacher_id": clean_teacher,
        "subject_code": clean_code,
        "created_at": clean_created,
    }

    if isinstance(target, Session):
        sess = DbSession(**record)
        target.add(sess)
        target.flush()
        return record

    query = (
        "INSERT INTO sessions (session_id, date, subject, teacher_id, subject_code, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    )
    with _get_conn(target) as conn:
        conn.execute(query, (clean_id, clean_date, clean_sub, clean_teacher, clean_code, clean_created))
        if isinstance(target, sqlite3.Connection):
            conn.commit()
    return record


def insert_sessions_bulk(
    target_or_sessions: Union[sqlite3.Connection, Session, str, List[Dict[str, str]]],
    sessions: Optional[List[Dict[str, str]]] = None,
) -> int:
    """Insert multiple sessions in a single transaction."""
    if isinstance(target_or_sessions, list) and sessions is None:
        target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
        actual_sessions = target_or_sessions
    else:
        target = target_or_sessions  # type: ignore[assignment]
        actual_sessions = sessions or []

    records = [
        {"session_id": s["session_id"].strip(), "date": s["date"].strip(), "subject": s["subject"].strip()}
        for s in actual_sessions
    ]

    if isinstance(target, Session):
        if not records:
            return 0
        target.bulk_insert_mappings(DbSession, records)
        target.flush()
        return len(records)

    tuple_records = [(r["session_id"], r["date"], r["subject"]) for r in records]
    query = "INSERT INTO sessions (session_id, date, subject) VALUES (?, ?, ?)"
    with _get_conn(target) as conn:
        cursor = conn.cursor()
        cursor.executemany(query, tuple_records)
        if isinstance(target, sqlite3.Connection):
            conn.commit()
        return cursor.rowcount


def get_session(
    target_or_session_id: Union[sqlite3.Connection, Session, str],
    session_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a session by session_id."""
    if session_id is None and not isinstance(target_or_session_id, (sqlite3.Connection, Session)):
        target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
        actual_id = str(target_or_session_id)
    else:
        target = target_or_session_id
        actual_id = session_id or ""

    clean_id = actual_id.strip()

    if isinstance(target, Session):
        stmt = select(DbSession).where(DbSession.session_id == clean_id)
        res = target.scalars(stmt).first()
        return _row_to_dict(res)

    query = "SELECT session_id, date, subject, created_at, teacher_id, subject_code FROM sessions WHERE session_id = ?"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (clean_id,))
        return _row_to_dict(cursor.fetchone())


def get_all_sessions(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Retrieve all sessions ordered by date descending."""
    if isinstance(target, Session):
        stmt = select(DbSession).order_by(DbSession.date.desc(), DbSession.session_id.asc())
        rows = target.scalars(stmt).all()
        return _rows_to_dicts(list(rows))

    query = "SELECT session_id, date, subject, created_at, teacher_id, subject_code FROM sessions ORDER BY date DESC, session_id ASC"
    with _get_conn(target) as conn:
        cursor = conn.execute(query)
        return _rows_to_dicts(cursor.fetchall())


def get_sessions_by_date(
    target_or_date: Union[sqlite3.Connection, Session, str],
    date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve sessions for a specific date."""
    if date is None and not isinstance(target_or_date, (sqlite3.Connection, Session)):
        target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
        actual_date = str(target_or_date)
    else:
        target = target_or_date
        actual_date = date or ""

    clean_date = actual_date.strip()

    if isinstance(target, Session):
        stmt = select(DbSession).where(DbSession.date == clean_date).order_by(DbSession.session_id.asc())
        rows = target.scalars(stmt).all()
        return _rows_to_dicts(list(rows))

    query = "SELECT session_id, date, subject, created_at, teacher_id, subject_code FROM sessions WHERE date = ? ORDER BY session_id ASC"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (clean_date,))
        return _rows_to_dicts(cursor.fetchall())


def get_sessions_paginated(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    date: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Retrieve paginated session records with optional date filter and search query.
    Search safely matches session_id and subject.
    Returns (items, total_count).
    """
    limit_val = max(1, min(200, limit))
    offset_val = max(0, offset)

    if isinstance(target, Session):
        conditions = []
        if date and date.strip():
            conditions.append(DbSession.date == date.strip())
        if search and search.strip():
            term = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(DbSession.session_id).like(term),
                    func.lower(DbSession.subject).like(term),
                )
            )

        count_stmt = select(func.count(DbSession.session_id))
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total = target.scalar(count_stmt) or 0

        stmt = select(DbSession)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(DbSession.date.desc(), DbSession.session_id.asc()).limit(limit_val).offset(offset_val)
        rows = target.scalars(stmt).all()
        return _rows_to_dicts(list(rows)), total

    where_clauses = []
    params: List[Any] = []
    if date and date.strip():
        where_clauses.append("date = ?")
        params.append(date.strip())
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        where_clauses.append("(LOWER(session_id) LIKE ? OR LOWER(subject) LIKE ?)")
        params.extend([term, term])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    with _get_conn(target) as conn:
        count_cursor = conn.execute(f"SELECT COUNT(*) FROM sessions {where_sql}", params)
        total = count_cursor.fetchone()[0]

        data_query = f"SELECT session_id, date, subject, created_at, teacher_id, subject_code FROM sessions {where_sql} ORDER BY date DESC, session_id ASC LIMIT ? OFFSET ?"
        data_params = params + [limit_val, offset_val]
        data_cursor = conn.execute(data_query, data_params)
        items = _rows_to_dicts(data_cursor.fetchall())
        return items, total


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
    """
    Normalize status string to uppercase and validate against allowed states.
    Supports common aliases (e.g. 'present', 'p', 'absent', 'a', 'pending', 'unreviewed').
    Neither PENDING nor UNREVIEWED is ever defaulted to ABSENT.
    """
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
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    session_id: str,
    usn: str,
    room_id: str,
    status: str,
    source: str,
    confidence: float = 1.0,
    upsert: bool = False,
    allocation_id: Optional[str] = None,
    attendance_id: Optional[str] = None,
    recorded_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert or optionally upsert an attendance record."""
    clean_status = normalize_attendance_status(status)
    clean_allocation_id = allocation_id.strip() if allocation_id else None
    clean_attendance_id = attendance_id.strip() if attendance_id else str(uuid4())
    clean_recorded_at = recorded_at or _utcnow_iso()
    record = {
        "attendance_id": clean_attendance_id,
        "session_id": session_id.strip(),
        "allocation_id": clean_allocation_id,
        "usn": usn.strip(),
        "room_id": room_id.strip(),
        "status": clean_status,
        "source": source.strip(),
        "confidence": float(confidence),
        "recorded_at": clean_recorded_at,
    }

    if isinstance(target, Session):
        bind = target.get_bind()
        dialect_name = bind.dialect.name if bind else "sqlite"

        if upsert:
            if dialect_name == "postgresql":
                stmt = pg_insert(Attendance).values(record)
                if clean_allocation_id:
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["allocation_id", "usn"],
                        set_={
                            "room_id": stmt.excluded.room_id,
                            "status": stmt.excluded.status,
                            "source": stmt.excluded.source,
                            "confidence": stmt.excluded.confidence,
                            "recorded_at": stmt.excluded.recorded_at,
                        },
                    )
                else:
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["session_id", "usn"],
                        where=Attendance.allocation_id.is_(None),
                        set_={
                            "room_id": stmt.excluded.room_id,
                            "status": stmt.excluded.status,
                            "source": stmt.excluded.source,
                            "confidence": stmt.excluded.confidence,
                            "recorded_at": stmt.excluded.recorded_at,
                        },
                    )
                target.execute(stmt)
            else:
                # SQLite: UPDATE-first upsert pattern
                # Try to update existing row matching (session_id, usn) with allocation_id IS NULL
                # or (allocation_id, usn) when allocation_id is present
                if clean_allocation_id:
                    target.execute(
                        update(Attendance).where(
                            Attendance.allocation_id == clean_allocation_id,
                            Attendance.usn == record["usn"],
                        ).values(
                            room_id=record["room_id"],
                            status=record["status"],
                            source=record["source"],
                            confidence=record["confidence"],
                            recorded_at=record["recorded_at"],
                        )
                    )
                    existing = target.execute(
                        select(Attendance).where(
                            Attendance.allocation_id == clean_allocation_id,
                            Attendance.usn == record["usn"],
                        )
                    ).first()
                else:
                    target.execute(
                        update(Attendance).where(
                            Attendance.session_id == record["session_id"],
                            Attendance.usn == record["usn"],
                            Attendance.allocation_id.is_(None),
                        ).values(
                            room_id=record["room_id"],
                            status=record["status"],
                            source=record["source"],
                            confidence=record["confidence"],
                            recorded_at=record["recorded_at"],
                        )
                    )
                    existing = target.execute(
                        select(Attendance).where(
                            Attendance.session_id == record["session_id"],
                            Attendance.usn == record["usn"],
                            Attendance.allocation_id.is_(None),
                        )
                    ).first()
                if not existing:
                    att = Attendance(**record)
                    target.add(att)
        else:
            att = Attendance(**record)
            target.add(att)

        target.flush()
        return record

    # Raw sqlite3.Connection path
    query = """
    INSERT INTO attendance (attendance_id, session_id, allocation_id, usn, room_id, status, source, confidence, recorded_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    if upsert and isinstance(target, sqlite3.Connection):
        # SQLite: UPDATE first, then INSERT if no row matched
        if clean_allocation_id:
            target.execute(
                "UPDATE attendance SET room_id=?, status=?, source=?, confidence=?, recorded_at=? WHERE allocation_id=? AND usn=?",
                (
                    record["room_id"],
                    record["status"],
                    record["source"],
                    record["confidence"],
                    record["recorded_at"],
                    clean_allocation_id,
                    record["usn"],
                ),
            )
            cur = target.execute(
                "SELECT 1 FROM attendance WHERE allocation_id=? AND usn=? LIMIT 1",
                (clean_allocation_id, record["usn"]),
            )
        else:
            target.execute(
                "UPDATE attendance SET room_id=?, status=?, source=?, confidence=?, recorded_at=? WHERE session_id=? AND usn=? AND allocation_id IS NULL",
                (
                    record["room_id"],
                    record["status"],
                    record["source"],
                    record["confidence"],
                    record["recorded_at"],
                    record["session_id"],
                    record["usn"],
                ),
            )
            cur = target.execute(
                "SELECT 1 FROM attendance WHERE session_id=? AND usn=? AND allocation_id IS NULL LIMIT 1",
                (record["session_id"], record["usn"]),
            )
        if cur.fetchone() is None:
            target.execute(
                query,
                (
                    record["attendance_id"],
                    record["session_id"],
                    record["allocation_id"],
                    record["usn"],
                    record["room_id"],
                    record["status"],
                    record["source"],
                    record["confidence"],
                    record["recorded_at"],
                ),
            )
        target.commit()
    else:
        with _get_conn(target) as conn:
            conn.execute(
                query,
                (
                    record["attendance_id"],
                    record["session_id"],
                    record["allocation_id"],
                    record["usn"],
                    record["room_id"],
                    record["status"],
                    record["source"],
                    record["confidence"],
                    record["recorded_at"],
                ),
            )
            if isinstance(target, sqlite3.Connection):
                conn.commit()

    return record


def insert_attendance_bulk(
    target_or_records: Union[sqlite3.Connection, Session, str, List[Dict[str, Any]]],
    records: Optional[List[Dict[str, Any]]] = None,
    upsert: bool = False,
) -> int:
    """Insert multiple attendance records."""
    if isinstance(target_or_records, list) and records is None:
        target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
        actual_records = target_or_records
    else:
        target = target_or_records  # type: ignore[assignment]
        actual_records = records or []

    formatted_records = [
        {
            "attendance_id": str(uuid4()),
            "session_id": r["session_id"].strip(),
            "allocation_id": r.get("allocation_id"),
            "usn": r["usn"].strip(),
            "room_id": r["room_id"].strip(),
            "status": normalize_attendance_status(r["status"]),
            "source": r["source"].strip(),
            "confidence": float(r.get("confidence", 1.0)),
            "recorded_at": _utcnow_iso(),
        }
        for r in actual_records
    ]

    if not formatted_records:
        return 0

    if isinstance(target, Session):
        bind = target.get_bind()
        dialect_name = bind.dialect.name if bind else "sqlite"

        if upsert:
            if dialect_name == "postgresql":
                stmt = pg_insert(Attendance).values(formatted_records)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["session_id", "usn"],
                    set_={
                        "room_id": stmt.excluded.room_id,
                        "status": stmt.excluded.status,
                        "source": stmt.excluded.source,
                        "confidence": stmt.excluded.confidence,
                    },
                )
            else:
                # SQLite: UPDATE-first upsert per record (no UNIQUE constraint
                # on (session_id, usn) - only partial indexes, so ON CONFLICT
                # cannot be used reliably here)
                for rec in formatted_records:
                    alloc_id = rec.get("allocation_id")
                    if alloc_id:
                        target.execute(
                            update(Attendance).where(
                                Attendance.allocation_id == alloc_id,
                                Attendance.usn == rec["usn"],
                            ).values(
                                room_id=rec["room_id"],
                                status=rec["status"],
                                source=rec["source"],
                                confidence=rec["confidence"],
                                recorded_at=rec["recorded_at"],
                            )
                        )
                        existing = target.execute(
                            select(Attendance).where(
                                Attendance.allocation_id == alloc_id,
                                Attendance.usn == rec["usn"],
                            )
                        ).first()
                    else:
                        target.execute(
                            update(Attendance).where(
                                Attendance.session_id == rec["session_id"],
                                Attendance.usn == rec["usn"],
                                Attendance.allocation_id.is_(None),
                            ).values(
                                room_id=rec["room_id"],
                                status=rec["status"],
                                source=rec["source"],
                                confidence=rec["confidence"],
                                recorded_at=rec["recorded_at"],
                            )
                        )
                        existing = target.execute(
                            select(Attendance).where(
                                Attendance.session_id == rec["session_id"],
                                Attendance.usn == rec["usn"],
                                Attendance.allocation_id.is_(None),
                            )
                        ).first()
                    if not existing:
                        target.add(Attendance(**rec))
            target.flush()
            return len(formatted_records)
        else:
            target.bulk_insert_mappings(Attendance, formatted_records)
            target.flush()
            return len(formatted_records)

    formatted_records = [
        {
            "attendance_id": str(uuid4()),
            "session_id": r["session_id"].strip(),
            "allocation_id": r.get("allocation_id"),
            "usn": r["usn"].strip(),
            "room_id": r["room_id"].strip(),
            "status": normalize_attendance_status(r["status"]),
            "source": r["source"].strip(),
            "confidence": float(r.get("confidence", 1.0)),
            "recorded_at": _utcnow_iso(),
        }
        for r in actual_records
    ]

    if not formatted_records:
        return 0

    if isinstance(target, Session):
        bind = target.get_bind()
        dialect_name = bind.dialect.name if bind else "sqlite"

        if upsert:
            if dialect_name == "postgresql":
                stmt = pg_insert(Attendance).values(formatted_records)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["session_id", "usn"],
                    set_={
                        "room_id": stmt.excluded.room_id,
                        "status": stmt.excluded.status,
                        "source": stmt.excluded.source,
                        "confidence": stmt.excluded.confidence,
                        "recorded_at": stmt.excluded.recorded_at,
                    },
                    where=Attendance.allocation_id.is_(None),
                )
            else:
                # SQLite: delete existing then insert (no partial index ON CONFLICT support)
                for r in formatted_records:
                    target.execute(
                        delete(Attendance).where(
                            Attendance.session_id == r["session_id"],
                            Attendance.usn == r["usn"],
                            Attendance.allocation_id.is_(None),
                        )
                    )
                target.bulk_insert_mappings(Attendance, formatted_records)
                target.flush()
                return len(formatted_records)
        else:
            target.bulk_insert_mappings(Attendance, formatted_records)
            target.flush()
            return len(formatted_records)

    # Raw SQLite path - no ON CONFLICT support for partial indexes
    with _get_conn(target) as conn:
        if upsert:
            # For upsert in raw SQLite, we delete existing then insert
            for r in formatted_records:
                existing = conn.execute(
                    "SELECT attendance_id FROM attendance WHERE session_id = ? AND usn = ? AND allocation_id IS NULL",
                    (r["session_id"], r["usn"])
                ).fetchone()
                if existing:
                    conn.execute(
                        "DELETE FROM attendance WHERE session_id = ? AND usn = ? AND allocation_id IS NULL",
                        (r["session_id"], r["usn"])
                    )

        query = """
        INSERT INTO attendance (attendance_id, session_id, allocation_id, usn, room_id, status, source, confidence, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor = conn.cursor()
        insert_rows = [
            (r["attendance_id"], r["session_id"], r["allocation_id"], r["usn"], r["room_id"],
             r["status"], r["source"], r["confidence"], r["recorded_at"])
            for r in formatted_records
        ]
        cursor.executemany(query, insert_rows)
        if isinstance(target, sqlite3.Connection):
            conn.commit()
        return cursor.rowcount


def delete_session_attendance(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    session_id: str = "",
) -> int:
    """Delete all attendance records for a specific session without affecting other sessions."""
    clean_id = session_id.strip()

    if isinstance(target, Session):
        stmt = delete(Attendance).where(Attendance.session_id == clean_id)
        res = target.execute(stmt)
        target.flush()
        return res.rowcount or 0

    query = "DELETE FROM attendance WHERE session_id = ?"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (clean_id,))
        if isinstance(target, sqlite3.Connection):
            conn.commit()
        return cursor.rowcount


def replace_session_attendance(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    session_id: str = "",
    records: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """
    Atomically re-upload/replace all attendance records for a session.
    Cleans up old records for this session only and inserts new records without affecting other sessions.
    Validates input before any writes. If an error occurs, the entire operation is rolled back.
    """
    clean_id = session_id.strip()
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
            "attendance_id": str(uuid4()),
            "session_id": clean_id,
            "usn": usn,
            "room_id": room_id,
            "status": status,
            "source": source,
            "confidence": confidence,
            "recorded_at": _utcnow_iso(),
        })

    if isinstance(target, Session):
        # Transaction safety: execute within nested transaction if one exists, or rely on caller session
        # Use a SAVEPOINT if in an outer transaction so partial failure rolls back cleanly
        savepoint = target.begin_nested()
        try:
            target.execute(delete(Attendance).where(Attendance.session_id == clean_id))
            if validated_records:
                target.bulk_insert_mappings(Attendance, validated_records)
            target.flush()
            savepoint.commit()
            return len(validated_records)
        except Exception:
            savepoint.rollback()
            raise

    with _get_conn(target) as conn:
        conn.execute("DELETE FROM attendance WHERE session_id = ?", (clean_id,))
        query = """
        INSERT INTO attendance (attendance_id, session_id, usn, room_id, status, source, confidence, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor = conn.cursor()
        insert_rows = [
            (v["attendance_id"], v["session_id"], v["usn"], v["room_id"], v["status"], v["source"], v["confidence"], v["recorded_at"])
            for v in validated_records
        ]
        cursor.executemany(query, insert_rows)
        if isinstance(target, sqlite3.Connection):
            conn.commit()
        return len(validated_records)


def reconcile_session_roster(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    session_id: str,
    roster: List[Dict[str, str]],
    uploaded_records: List[Dict[str, Any]],
    missing_room_ids: Optional[Set[str]] = None,
    confidence_threshold: float = 0.7,
    persist: bool = False,
) -> List[Dict[str, Any]]:
    """
    Reconcile student roster against uploaded attendance sheet records for a session:
    - Missing sheets (rooms in missing_room_ids or unrecorded students) leave status as PENDING.
    - Ambiguous entries (explicit 'UNREVIEWED'/'ambiguous' status or confidence < threshold) leave status as UNREVIEWED.
    - Confirmed entries are marked PRESENT or ABSENT.
    - Neither PENDING nor UNREVIEWED is ever defaulted or miscounted as ABSENT.
    """
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
    target_or_session_id: Union[sqlite3.Connection, Session, str],
    session_id_or_usn: str,
    usn: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve attendance record for a specific student in a specific session."""
    if usn is None and not isinstance(target_or_session_id, (sqlite3.Connection, Session)):
        target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
        actual_session_id = str(target_or_session_id)
        actual_usn = session_id_or_usn
    else:
        target = target_or_session_id
        actual_session_id = session_id_or_usn
        actual_usn = usn or ""

    clean_sess = actual_session_id.strip()
    clean_usn = actual_usn.strip()

    if isinstance(target, Session):
        stmt = select(Attendance).where(
            Attendance.session_id == clean_sess,
            Attendance.usn == clean_usn,
        )
        res = target.scalars(stmt).first()
        return _row_to_dict(res)

    query = """
    SELECT session_id, usn, room_id, status, source, confidence
    FROM attendance
    WHERE session_id = ? AND usn = ?
    """
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (clean_sess, clean_usn))
        return _row_to_dict(cursor.fetchone())


def get_existing_attendance_usns(
    target_or_session_id: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    session_id_or_usns: Union[str, Sequence[str]] = "",
    usns: Optional[Sequence[str]] = None,
) -> List[str]:
    """
    Retrieve list of student USNs that already have attendance records for a specific session in a single batch query.
    Preserves duplicate detection and avoids N+1 queries.
    """
    if usns is None and not isinstance(target_or_session_id, (sqlite3.Connection, Session)):
        target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
        actual_session_id = str(target_or_session_id)
        actual_usns = list(session_id_or_usns) if isinstance(session_id_or_usns, (list, set, tuple)) else []
    else:
        target = target_or_session_id
        actual_session_id = str(session_id_or_usns)
        actual_usns = list(usns) if usns else []

    clean_sess = actual_session_id.strip()
    clean_usns = [str(u).strip().upper() for u in actual_usns if str(u).strip()]
    if not clean_usns or not clean_sess:
        return []

    if isinstance(target, Session):
        stmt = (
            select(Attendance.usn)
            .where(
                Attendance.session_id == clean_sess,
                Attendance.usn.in_(clean_usns),
            )
            .order_by(Attendance.usn.asc())
        )
        return list(target.scalars(stmt).all())

    placeholders = ",".join("?" for _ in clean_usns)
    query = f"""
    SELECT usn
    FROM attendance
    WHERE session_id = ? AND usn IN ({placeholders})
    ORDER BY usn ASC
    """
    with _get_conn(target) as conn:
        cursor = conn.execute(query, [clean_sess] + clean_usns)
        return [row[0] if isinstance(row, tuple) else row["usn"] for row in cursor.fetchall()]


def get_attendance_by_session(
    target_or_session_id: Union[sqlite3.Connection, Session, str],
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all attendance records for a given session."""
    if session_id is None and not isinstance(target_or_session_id, (sqlite3.Connection, Session)):
        target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
        actual_id = str(target_or_session_id)
    else:
        target = target_or_session_id
        actual_id = session_id or ""

    clean_id = actual_id.strip()

    if isinstance(target, Session):
        stmt = select(Attendance).where(Attendance.session_id == clean_id).order_by(Attendance.usn.asc())
        rows = target.scalars(stmt).all()
        return _rows_to_dicts(list(rows))

    query = """
    SELECT session_id, usn, room_id, status, source, confidence
    FROM attendance
    WHERE session_id = ?
    ORDER BY usn ASC
    """
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (clean_id,))
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
    target_or_usn: Union[sqlite3.Connection, Session, str],
    usn: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all attendance records for a specific student."""
    if usn is None and not isinstance(target_or_usn, (sqlite3.Connection, Session)):
        target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
        actual_usn = str(target_or_usn)
    else:
        target = target_or_usn
        actual_usn = usn or ""

    clean_usn = actual_usn.strip()

    if isinstance(target, Session):
        stmt = select(Attendance).where(Attendance.usn == clean_usn).order_by(Attendance.session_id.asc())
        rows = target.scalars(stmt).all()
        return _rows_to_dicts(list(rows))

    query = """
    SELECT session_id, usn, room_id, status, source, confidence
    FROM attendance
    WHERE usn = ?
    ORDER BY session_id ASC
    """
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (clean_usn,))
        return _rows_to_dicts(cursor.fetchall())


def get_session_attendance_details(
    target_or_session_id: Union[sqlite3.Connection, Session, str],
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve joined detailed attendance data for a session."""
    if session_id is None and not isinstance(target_or_session_id, (sqlite3.Connection, Session)):
        target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
        actual_id = str(target_or_session_id)
    else:
        target = target_or_session_id
        actual_id = session_id or ""

    clean_id = actual_id.strip()

    if isinstance(target, Session):
        stmt = (
            select(
                Attendance.session_id,
                DbSession.date.label("session_date"),
                DbSession.subject,
                Attendance.usn,
                Student.name.label("student_name"),
                Student.branch,
                Attendance.room_id,
                Room.name.label("room_name"),
                Attendance.status,
                Attendance.source,
                Attendance.confidence,
            )
            .join(DbSession, Attendance.session_id == DbSession.session_id)
            .join(Student, Attendance.usn == Student.usn)
            .join(Room, Attendance.room_id == Room.room_id)
            .where(Attendance.session_id == clean_id)
            .order_by(Student.name.asc())
        )
        res = target.execute(stmt)
        return [dict(r._mapping) for r in res.all()]

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
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (clean_id,))
        return _rows_to_dicts(cursor.fetchall())


# ==========================================
# RBAC and N1 Extensions (Users, Teachers, Audits, Edits)
# ==========================================

def _utcnow_iso() -> str:
    """Return current UTC time in fixed standard ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_user(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    user_id: str,
    email: str,
    role: str,
    hashed_password: Optional[str] = None,
    is_active: int = 1,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new user record."""
    clean_uid = user_id.strip()
    clean_email = email.strip().lower()
    clean_role = role.strip().upper()
    ts = created_at or _utcnow_iso()

    if isinstance(target, Session):
        user = User(
            user_id=clean_uid,
            email=clean_email,
            role=clean_role,
            hashed_password=hashed_password,
            is_active=is_active,
            created_at=ts,
        )
        target.add(user)
        target.flush()
        return _row_to_dict(user)  # type: ignore

    query = """
    INSERT INTO users (user_id, email, role, hashed_password, is_active, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """
    with _get_conn(target) as conn:
        conn.execute(query, (clean_uid, clean_email, clean_role, hashed_password, is_active, ts))
    return {
        "user_id": clean_uid,
        "email": clean_email,
        "role": clean_role,
        "hashed_password": hashed_password,
        "is_active": is_active,
        "created_at": ts,
    }


def get_user(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    user_id: str,
) -> Optional[Dict[str, Any]]:
    """Fetch user by primary key user_id."""
    clean_uid = user_id.strip()
    if isinstance(target, Session):
        user = target.get(User, clean_uid)
        return _row_to_dict(user)

    query = "SELECT user_id, email, role, hashed_password, is_active, created_at FROM users WHERE user_id = ?"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (clean_uid,))
        row = cursor.fetchone()
        return _row_to_dict(row)


def assign_teacher_subject(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    user_id: str,
    subject_code: str,
) -> Dict[str, Any]:
    """Assign a subject code to a teacher."""
    clean_uid = user_id.strip()
    clean_code = subject_code.strip().upper()

    if isinstance(target, Session):
        ts = TeacherSubject(user_id=clean_uid, subject_code=clean_code)
        target.add(ts)
        target.flush()
        return _row_to_dict(ts)  # type: ignore

    query = "INSERT INTO teacher_subjects (user_id, subject_code) VALUES (?, ?)"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (clean_uid, clean_code))
        new_id = cursor.lastrowid
    return {"id": new_id, "user_id": clean_uid, "subject_code": clean_code}


def get_teacher_subjects(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    user_id: str,
) -> List[str]:
    """List all subject codes assigned to a given teacher."""
    clean_uid = user_id.strip()
    if isinstance(target, Session):
        stmt = select(TeacherSubject.subject_code).where(TeacherSubject.user_id == clean_uid)
        res = target.execute(stmt)
        return [row[0] for row in res.all()]

    query = "SELECT subject_code FROM teacher_subjects WHERE user_id = ? ORDER BY subject_code ASC"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (clean_uid,))
        return [r["subject_code"] if isinstance(r, sqlite3.Row) else r[0] for r in cursor.fetchall()]


def list_teacher_subject_mappings(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    user_id: Optional[str] = None,
    subject_code: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List teacher-subject mappings, optionally filtered by user and/or subject code.
    Admin-facing helper for the teacher-subject management endpoint (N4).
    """
    clean_uid = user_id.strip() if user_id else None
    clean_code = subject_code.strip().upper() if subject_code else None

    if isinstance(target, Session):
        stmt = select(TeacherSubject)
        if clean_uid:
            stmt = stmt.where(TeacherSubject.user_id == clean_uid)
        if clean_code:
            stmt = stmt.where(TeacherSubject.subject_code == clean_code)
        stmt = stmt.order_by(TeacherSubject.user_id.asc(), TeacherSubject.subject_code.asc())
        rows = target.execute(stmt).scalars().all()
        return [
            {"id": r.id, "user_id": r.user_id, "subject_code": r.subject_code}
            for r in rows
        ]

    query = "SELECT id, user_id, subject_code FROM teacher_subjects WHERE 1=1"
    params: List[Any] = []
    if clean_uid:
        query += " AND user_id = ?"
        params.append(clean_uid)
    if clean_code:
        query += " AND subject_code = ?"
        params.append(clean_code)
    query += " ORDER BY user_id ASC, subject_code ASC"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, tuple(params))
        return [
            {"id": r["id"], "user_id": r["user_id"], "subject_code": r["subject_code"]}
            if isinstance(r, sqlite3.Row)
            else {"id": r[0], "user_id": r[1], "subject_code": r[2]}
            for r in cursor.fetchall()
        ]


def create_audit_entry(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    session_id: Optional[str] = None,
    usn: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    reason: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an append-only audit log entry."""
    clean_actor = actor_id.strip()
    clean_act = action.strip().upper()
    ts = timestamp or _utcnow_iso()

    if isinstance(target, Session):
        log = AuditLog(
            actor_id=clean_actor,
            action=clean_act,
            session_id=session_id.strip() if session_id else None,
            usn=usn.strip().upper() if usn else None,
            entity_type=entity_type.strip(),
            entity_id=entity_id.strip(),
            old_value=old_value,
            new_value=new_value,
            reason=reason.strip() if reason else None,
            timestamp=ts,
        )
        target.add(log)
        target.flush()
        return _row_to_dict(log)  # type: ignore

    query = """
    INSERT INTO audit_log (
        actor_id, action, session_id, usn, entity_type, entity_id,
        old_value, new_value, reason, timestamp
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with _get_conn(target) as conn:
        cursor = conn.execute(
            query,
            (
                clean_actor,
                clean_act,
                session_id.strip() if session_id else None,
                usn.strip().upper() if usn else None,
                entity_type.strip(),
                entity_id.strip(),
                old_value,
                new_value,
                reason.strip() if reason else None,
                ts,
            ),
        )
        log_id = cursor.lastrowid
    return {
        "log_id": log_id,
        "actor_id": clean_actor,
        "action": clean_act,
        "session_id": session_id,
        "usn": usn,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "old_value": old_value,
        "new_value": new_value,
        "reason": reason,
        "timestamp": ts,
    }


def record_login_attempt(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    success: int = 1,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Record an authentication attempt."""
    ts = timestamp or _utcnow_iso()
    clean_uid = user_id.strip() if user_id else None
    clean_ip = ip_address.strip() if ip_address else None

    if isinstance(target, Session):
        attempt = LoginAttempt(
            user_id=clean_uid,
            ip_address=clean_ip,
            success=1 if success else 0,
            timestamp=ts,
        )
        target.add(attempt)
        target.flush()
        return _row_to_dict(attempt)  # type: ignore

    query = "INSERT INTO login_attempts (user_id, ip_address, success, timestamp) VALUES (?, ?, ?, ?)"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (clean_uid, clean_ip, 1 if success else 0, ts))
        aid = cursor.lastrowid
    return {"id": aid, "user_id": clean_uid, "ip_address": clean_ip, "success": success, "timestamp": ts}


def create_pending_edit(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    user_id: str,
    session_id: str,
    usn: str,
    old_status: str,
    new_status: str,
    ttl_minutes: int = 5,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a pending attendance edit record with 5-minute expiry."""
    clean_uid = user_id.strip()
    clean_sid = session_id.strip()
    clean_usn = usn.strip().upper()
    clean_old = old_status.strip().upper()
    clean_new = new_status.strip().upper()

    now_dt = datetime.now(timezone.utc)
    now_ts = created_at or now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    exp_dt = now_dt + timedelta(minutes=ttl_minutes)
    exp_ts = exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    edit_id = str(uuid4())

    if isinstance(target, Session):
        pe = PendingEdit(
            edit_id=edit_id,
            user_id=clean_uid,
            session_id=clean_sid,
            usn=clean_usn,
            old_status=clean_old,
            new_status=clean_new,
            created_at=now_ts,
            expires_at=exp_ts,
            consumed=0,
        )
        target.add(pe)
        target.flush()
        return _row_to_dict(pe)  # type: ignore

    query = """
    INSERT INTO pending_edits (
        edit_id, user_id, session_id, usn, old_status, new_status,
        created_at, expires_at, consumed
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
    """
    with _get_conn(target) as conn:
        conn.execute(query, (edit_id, clean_uid, clean_sid, clean_usn, clean_old, clean_new, now_ts, exp_ts))
    return {
        "edit_id": edit_id,
        "user_id": clean_uid,
        "session_id": clean_sid,
        "usn": clean_usn,
        "old_status": clean_old,
        "new_status": clean_new,
        "created_at": now_ts,
        "expires_at": exp_ts,
        "consumed": 0,
    }


def consume_pending_edit_atomic(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    edit_id: str,
    user_id: str,
    now_iso: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Atomically consume a pending edit if ownership matches, not expired, and not consumed.
    Returns the edit dict if successfully claimed, or None if expired/already consumed/not owned.
    """
    clean_eid = edit_id.strip()
    clean_uid = user_id.strip()
    now_ts = now_iso or _utcnow_iso()

    if isinstance(target, Session):
        stmt = (
            update(PendingEdit)
            .where(
                PendingEdit.edit_id == clean_eid,
                PendingEdit.user_id == clean_uid,
                PendingEdit.consumed == 0,
                PendingEdit.expires_at > now_ts,
            )
            .values(consumed=1)
        )
        res = target.execute(stmt)
        if res.rowcount == 0:
            return None
        target.flush()
        pe = target.get(PendingEdit, clean_eid)
        return _row_to_dict(pe)

    query = """
    UPDATE pending_edits
    SET consumed = 1
    WHERE edit_id = ? AND user_id = ? AND consumed = 0 AND expires_at > ?
    """
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (clean_eid, clean_uid, now_ts))
        if cursor.rowcount == 0:
            return None
        cursor = conn.execute("SELECT * FROM pending_edits WHERE edit_id = ?", (clean_eid,))
        return _row_to_dict(cursor.fetchone())


def apply_attendance_edit_atomic(
    session: Session,
    *,
    edit_id: str,
    user_id: str,
    authenticated_role: str,
    reason: Optional[str] = None,
    now_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute full attendance edit confirmation in a single atomic transaction.

    Verifications performed:
    1. Authenticated user ownership of pending edit.
    2. Pending edit has not expired.
    3. Pending edit has not already been consumed.
    4. Teacher assignment / ADMIN permission for session subject.
    5. Session and Student entities still exist.
    6. Current attendance status strictly equals the proposal's old_status (compare-and-set).
    7. Atomically applies new status and marks edit consumed.
    8. Inserts AuditLog record.
    If any step fails, the entire transaction rolls back.
    """
    clean_eid = edit_id.strip()
    clean_uid = user_id.strip()
    role = authenticated_role.strip().upper()
    now_ts = now_iso or _utcnow_iso()

    # Step 1-3: Fetch and validate pending edit
    edit = session.get(PendingEdit, clean_eid)
    if edit is None or edit.user_id != clean_uid:
        raise PermissionError(f"Pending edit '{clean_eid}' does not belong to user '{clean_uid}'.")
    if edit.consumed != 0:
        raise ValueError(f"Pending edit '{clean_eid}' has already been consumed.")
    if edit.expires_at <= now_ts:
        raise ValueError(f"Pending edit '{clean_eid}' expired at {edit.expires_at}.")

    # Step 4: Validate role and subject assignment
    sess = session.get(DbSession, edit.session_id)
    if sess is None:
        raise ValueError(f"Session '{edit.session_id}' no longer exists.")

    if role == "ADMIN":
        pass  # College-wide edit privilege
    elif role == "FACULTY":
        # Check teacher assigned subjects
        subj_code = sess.subject_code or sess.subject
        teacher_assigned = (sess.teacher_id == clean_uid)
        if not teacher_assigned and subj_code:
            stmt = select(TeacherSubject).where(
                TeacherSubject.user_id == clean_uid,
                TeacherSubject.subject_code == subj_code,
            )
            teacher_assigned = session.execute(stmt).first() is not None

        if not teacher_assigned:
            raise PermissionError(
                f"Faculty '{clean_uid}' is not assigned to session '{sess.session_id}' or subject '{subj_code}'."
            )
    else:
        raise PermissionError(f"Role '{role}' is not authorized to edit attendance.")

    # Step 5: Verify student exists
    student = session.get(Student, edit.usn)
    if student is None:
        raise ValueError(f"Student '{edit.usn}' no longer exists.")

    # Step 6: Atomic compare-and-set update on attendance
    att_update = (
        update(Attendance)
        .where(
            Attendance.session_id == edit.session_id,
            Attendance.usn == edit.usn,
            Attendance.status == edit.old_status,
        )
        .values(status=edit.new_status)
    )
    res_att = session.execute(att_update)
    if res_att.rowcount == 0:
        raise ValueError(
            f"Stale edit rejected: attendance status for USN '{edit.usn}' in session '{edit.session_id}' "
            f"has changed since the proposal was created (expected '{edit.old_status}')."
        )

    # Step 7: Mark pending edit consumed
    edit_consume = (
        update(PendingEdit)
        .where(
            PendingEdit.edit_id == clean_eid,
            PendingEdit.consumed == 0,
        )
        .values(consumed=1)
    )
    res_edit = session.execute(edit_consume)
    if res_edit.rowcount == 0:
        raise ValueError(f"Pending edit '{clean_eid}' was concurrently consumed.")

    # Step 8: Insert audit log entry in the same transaction
    audit = AuditLog(
        actor_id=clean_uid,
        action="ATTENDANCE_EDIT",
        session_id=edit.session_id,
        usn=edit.usn,
        entity_type="attendance",
        entity_id=f"{edit.session_id}:{edit.usn}",
        old_value=edit.old_status,
        new_value=edit.new_status,
        reason=reason.strip() if reason else None,
        timestamp=now_ts,
    )
    session.add(audit)
    session.flush()

    return {
        "edit_id": clean_eid,
        "session_id": edit.session_id,
        "usn": edit.usn,
        "old_status": edit.old_status,
        "new_status": edit.new_status,
        "consumed": 1,
        "audit_log_id": audit.log_id,
        "timestamp": now_ts,
    }


def revoke_all_user_sessions(
    session: Session,
    user_id: str,
) -> int:
    """
    Revoke all active authentication session families and refresh tokens for a user.
    Called on account deactivation, password reset, or explicit security revocation.
    """
    clean_uid = user_id.strip()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    subquery = select(AuthSession.session_id).where(AuthSession.user_id == clean_uid)
    stmt_tokens = (
        update(AuthRefreshToken)
        .where(
            AuthRefreshToken.session_id.in_(subquery),
            AuthRefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now_iso)
    )
    session.execute(stmt_tokens)

    stmt_sessions = (
        update(AuthSession)
        .where(
            AuthSession.user_id == clean_uid,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now_iso)
    )
    res = session.execute(stmt_sessions)
    session.flush()
    return res.rowcount


