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
from weakref import WeakKeyDictionary

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy import insert as sa_insert
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.connection import DEFAULT_DB_PATH, get_connection
from app.security.audit_chain import (
    DEFAULT_CHAIN_ID,
    compute_row_hash,
    get_chain_secret,
    get_genesis_hash,
)
from app.db.models import (
    Student,
    Room,
    Session as DbSession,
    Attendance,
    User,
    FacultySubject,
    TeacherSubject,
    Subject,
    Department,
    AuditLog,
    AuditChainHead,
    LoginAttempt,
    PendingEdit,
    SessionAllocation,
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
        d = dict(row)
        if "edit_id" in d and "pending_id" not in d:
            d["pending_id"] = d["edit_id"]
        if "consumed" in d and "used" not in d:
            d["used"] = d["consumed"]
        if "action" in d and "event" not in d:
            d["event"] = d["action"]
        if "timestamp" in d and "at_utc" not in d:
            d["at_utc"] = d["timestamp"]
        return d
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
            "coordinator_faculty_id": getattr(row, "coordinator_faculty_id", None),
            "lifecycle_status": getattr(row, "lifecycle_status", None),
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
            "name": getattr(row, "name", None),
            "email": row.email,
            "role": row.role,
            "is_active": row.is_active,
            "created_at": row.created_at,
        }
    if isinstance(row, (TeacherSubject, FacultySubject)):
        return {
            "id": row.id,
            "user_id": row.user_id,
            "subject_code": row.subject_code,
            "dept_id": getattr(row, "dept_id", None),
            "semester": getattr(row, "semester", None),
        }
    if isinstance(row, AuditLog):
        return {
            "log_id": row.log_id,
            "actor_id": row.actor_id,
            "action": row.action,
            "event": row.action,
            "session_id": row.session_id,
            "usn": row.usn,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "old_value": row.old_value,
            "new_value": row.new_value,
            "reason": row.reason,
            "timestamp": row.timestamp,
            "at_utc": row.timestamp,
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
            "pending_id": row.edit_id,
            "user_id": row.user_id,
            "session_id": row.session_id,
            "usn": row.usn,
            "old_status": row.old_status,
            "new_status": row.new_status,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
            "consumed": row.consumed,
            "used": row.consumed,
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
    scope_condition: Optional[Any] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Retrieve paginated student records with optional branch filter and search query.
    Search safely matches USN, name, and branch.
    ``scope_condition`` is an optional SQLAlchemy predicate applied to the
    authorization scope; it is applied to the COUNT and the page query so that
    pagination, counts and search can never widen the caller's scope.
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
        if scope_condition is not None:
            conditions.append(scope_condition)

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
    if scope_condition is not None:
        # Fail closed: a scoped listing must never silently fall back to an
        # unscoped query on a raw connection.
        raise ValueError(
            "Scoped student listing requires a SQLAlchemy Session target."
        )
    if branch and branch.strip():
        where_clauses.append("branch = ?")
        params.append(branch.strip())
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        where_clauses.append("(LOWER(usn) LIKE ? OR LOWER(name) LIKE ? OR LOWER(branch) LIKE ?)")
        params.extend([term, term, term])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    with _get_conn(target) as conn:
        count_cursor = conn.execute(f"SELECT COUNT(*) FROM students {where_sql}", params)  # nosec B608
        total = count_cursor.fetchone()[0]

        data_query = f"SELECT usn, name, branch FROM students {where_sql} ORDER BY usn ASC LIMIT ? OFFSET ?"  # nosec B608 - fixed literals, bound values
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
        count_cursor = conn.execute(f"SELECT COUNT(*) FROM rooms {where_sql}", params)  # nosec B608 - fixed literals, bound values
        total = count_cursor.fetchone()[0]

        data_query = f"SELECT room_id, name FROM rooms {where_sql} ORDER BY room_id ASC LIMIT ? OFFSET ?"  # nosec B608 - fixed literals, bound values
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


# ---------------------------------------------------------------------------
# Session column helpers
#
# The raw SQLite code path has to cope with both the migrated schema (Alembic
# 0009 adds sessions.coordinator_faculty_id) and the legacy bootstrap schema
# created by app.db.schema.init_db, which does not have that column yet.
# ---------------------------------------------------------------------------

SESSION_OPTIONAL_COLUMNS = (
    "created_at",
    "teacher_id",
    "subject_code",
    "coordinator_faculty_id",
)


def _session_table_columns(conn: sqlite3.Connection) -> Set[str]:
    """Return the column names the sessions table actually has."""
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    except Exception:
        return set()


def _session_select_columns(available: Set[str]) -> List[str]:
    """Build the sessions SELECT list for the columns that exist."""
    if not available:
        # Table missing or unreadable: keep the historical column list.
        return ["session_id", "date", "subject", "created_at", "teacher_id", "subject_code"]
    columns = ["session_id", "date", "subject"]
    columns.extend(col for col in SESSION_OPTIONAL_COLUMNS if col in available)
    return columns


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

    with _get_conn(target) as conn:
        available = _session_table_columns(conn)
        select_columns = ", ".join(_session_select_columns(available))
        cursor = conn.execute(
            f"SELECT {select_columns} FROM sessions WHERE session_id = ?", (clean_id,)  # nosec B608 - columns from a fixed allowlist, value bound
        )
        return _row_to_dict(cursor.fetchone())


def get_all_sessions(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Retrieve all sessions ordered by date descending."""
    if isinstance(target, Session):
        stmt = select(DbSession).order_by(DbSession.date.desc(), DbSession.session_id.asc())
        rows = target.scalars(stmt).all()
        return _rows_to_dicts(list(rows))

    with _get_conn(target) as conn:
        available = _session_table_columns(conn)
        select_columns = ", ".join(_session_select_columns(available))
        cursor = conn.execute(
            f"SELECT {select_columns} FROM sessions ORDER BY date DESC, session_id ASC"  # nosec B608 - columns from a fixed allowlist
        )
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

    with _get_conn(target) as conn:
        available = _session_table_columns(conn)
        select_columns = ", ".join(_session_select_columns(available))
        cursor = conn.execute(
            f"SELECT {select_columns} FROM sessions WHERE date = ? ORDER BY session_id ASC",  # nosec B608 - allowlisted columns, value bound
            (clean_date,),
        )
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
        available = _session_table_columns(conn)
        select_columns = ", ".join(_session_select_columns(available))
        count_cursor = conn.execute(f"SELECT COUNT(*) FROM sessions {where_sql}", params)  # nosec B608 - fixed literals, bound values
        total = count_cursor.fetchone()[0]

        data_query = (
            f"SELECT {select_columns} FROM sessions {where_sql} "  # nosec B608 - allowlisted columns, bound values
            "ORDER BY date DESC, session_id ASC LIMIT ? OFFSET ?"
        )
        data_params = params + [limit_val, offset_val]
        data_cursor = conn.execute(data_query, data_params)
        items = _rows_to_dicts(data_cursor.fetchall())
        return items, total


# ---------------------------------------------------------------------------
# Session visibility scoping
# ---------------------------------------------------------------------------

# Owner values that mean "no real owner". Migration 0002 backfills the literal
# sentinel 'legacy' for sessions that predate teacher ownership.
LEGACY_SESSION_OWNER_SENTINELS = ("", "legacy")


def normalize_subject_code(raw: Optional[str]) -> str:
    """Normalize a subject code for EXACT equality comparisons.

    ' ml ' and 'ML' are the same code; 'HTML' is a different code than 'ML'.
    Never compare raw subject codes with substring matching.
    """
    if raw is None:
        return ""
    return str(raw).strip().upper()


def _session_scope_condition_orm(user_id: str, subject_codes: List[str]):
    """SQLAlchemy predicate restricting sessions to one caller's scope.

    The policy itself lives in ``app.auth.session_scope`` so that the session
    endpoints, the attendance endpoints and the AI query tools all enforce the
    exact same rule.
    """
    from app.auth.session_scope import session_scope_condition

    return session_scope_condition(user_id, subject_codes)


def get_sessions_paginated_scoped(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    date: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    scope_user_id: Optional[str] = None,
    scope_subject_codes: Optional[Sequence[str]] = None,
    unrestricted: bool = False,
) -> Tuple[List[Dict[str, Any]], int]:
    """Paginated session listing restricted to the caller's visibility scope.

    The scope is applied inside the SQL statement, before COUNT, LIMIT and
    OFFSET, so pagination, date filters and search terms can never widen the
    result set (or the reported total) beyond what the caller may see.

    Visibility rules:
      * ``unrestricted=True`` (ADMIN): every session.
      * a session owned by a real teacher: visible to that teacher only.
      * an unowned / legacy session: visible to its coordinator, or to a
        teacher mapped to the session's subject code (exact, normalized match).
    """
    limit_val = max(1, min(200, limit))
    offset_val = max(0, offset)

    clean_uid = (scope_user_id or "").strip()
    clean_codes = sorted(
        {
            normalize_subject_code(code)
            for code in (scope_subject_codes or [])
            if normalize_subject_code(code)
        }
    )

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
        if not unrestricted:
            conditions.append(_session_scope_condition_orm(clean_uid, clean_codes))

        count_stmt = select(func.count(DbSession.session_id))
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total = target.scalar(count_stmt) or 0

        stmt = select(DbSession)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = (
            stmt.order_by(DbSession.date.desc(), DbSession.session_id.asc())
            .limit(limit_val)
            .offset(offset_val)
        )
        rows = target.scalars(stmt).all()
        return _rows_to_dicts(list(rows)), total

    where_clauses: List[str] = []
    params: List[Any] = []
    if date and date.strip():
        where_clauses.append("date = ?")
        params.append(date.strip())
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        where_clauses.append("(LOWER(session_id) LIKE ? OR LOWER(subject) LIKE ?)")
        params.extend([term, term])

    with _get_conn(target) as conn:
        available = _session_table_columns(conn)
        select_columns = ", ".join(_session_select_columns(available))

        if not unrestricted:
            scope_parts: List[str] = []
            scope_params: List[Any] = []
            inner_parts: List[str] = []
            inner_params: List[Any] = []
            if "teacher_id" in available:
                scope_parts.append("teacher_id = ?")
                scope_params.append(clean_uid)
            if clean_uid and "coordinator_faculty_id" in available:
                inner_parts.append("coordinator_faculty_id = ?")
                inner_params.append(clean_uid)
            if clean_codes and "subject_code" in available:
                placeholders = ",".join("?" for _ in clean_codes)
                inner_parts.append(f"UPPER(subject_code) IN ({placeholders})")
                inner_params.extend(clean_codes)
            if inner_parts:
                owner_guard = (
                    "COALESCE(teacher_id, '') IN ('', 'legacy')"
                    if "teacher_id" in available
                    else "1 = 1"
                )
                scope_parts.append(
                    f"({owner_guard} AND (" + " OR ".join(inner_parts) + "))"
                )
                scope_params.extend(inner_params)
            if scope_parts:
                where_clauses.append("(" + " OR ".join(scope_parts) + ")")
                params.extend(scope_params)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        count_cursor = conn.execute(f"SELECT COUNT(*) FROM sessions {where_sql}", params)  # nosec B608 - fixed literals, bound values
        total = count_cursor.fetchone()[0]

        data_query = (
            f"SELECT {select_columns} FROM sessions {where_sql} "  # nosec B608 - allowlisted columns, bound values
            "ORDER BY date DESC, session_id ASC LIMIT ? OFFSET ?"
        )
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
                    # Uniqueness for allocation rows lives in the *partial* index
                    # idx_attendance_allocation_usn, so the conflict target must
                    # carry the matching predicate via index_where.
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["allocation_id", "usn"],
                        index_where=Attendance.allocation_id.is_not(None),
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
                        index_where=Attendance.allocation_id.is_(None),
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
    """Insert multiple attendance records, optionally updating existing rows.

    Upsert is UPDATE-first on both dialects so an existing row keeps its
    surrogate ``attendance_id``; a DELETE+INSERT would also cascade-delete any
    ``pending_edits`` rows that reference that attendance_id.

    Uniqueness is enforced by two *partial* unique indexes
    (``idx_attendance_legacy_session_usn`` for legacy rows and
    ``idx_attendance_allocation_usn`` for allocation rows), so a PostgreSQL
    ``ON CONFLICT`` target must carry the matching predicate via ``index_where``.
    """
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
            "allocation_id": (r.get("allocation_id") or None),
            "usn": r["usn"].strip(),
            "room_id": r["room_id"].strip(),
            "status": normalize_attendance_status(r["status"]),
            "source": r["source"].strip(),
            "confidence": float(r.get("confidence", 1.0)),
            "recorded_at": r.get("recorded_at") or _utcnow_iso(),
        }
        for r in actual_records
    ]

    if not formatted_records:
        return 0

    if isinstance(target, Session):
        bind = target.get_bind()
        dialect_name = bind.dialect.name if bind else "sqlite"

        if not upsert:
            target.bulk_insert_mappings(Attendance, formatted_records)
            target.flush()
            return len(formatted_records)

        if dialect_name == "postgresql":
            # The two partial unique indexes are disjoint: split by scope so each
            # ON CONFLICT target names the index that actually applies.
            legacy_records = [r for r in formatted_records if not r["allocation_id"]]
            allocation_records = [r for r in formatted_records if r["allocation_id"]]

            updated_columns = ("room_id", "status", "source", "confidence", "recorded_at")

            if legacy_records:
                stmt = pg_insert(Attendance).values(legacy_records)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["session_id", "usn"],
                    index_where=Attendance.allocation_id.is_(None),
                    set_={col: getattr(stmt.excluded, col) for col in updated_columns},
                )
                target.execute(stmt)

            # Allocation-scoped rows may target different allocations, so they
            # are upserted one statement per record.
            for rec in allocation_records:
                stmt = pg_insert(Attendance).values(**rec)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["allocation_id", "usn"],
                    index_where=Attendance.allocation_id.is_not(None),
                    set_={col: getattr(stmt.excluded, col) for col in updated_columns},
                )
                target.execute(stmt)

            target.flush()
            return len(formatted_records)

        # SQLite: UPDATE-first upsert per record (a partial index cannot be used
        # as an ON CONFLICT target portably).
        for rec in formatted_records:
            alloc_id = rec.get("allocation_id")
            if alloc_id:
                match = (
                    Attendance.allocation_id == alloc_id,
                    Attendance.usn == rec["usn"],
                )
            else:
                match = (
                    Attendance.session_id == rec["session_id"],
                    Attendance.usn == rec["usn"],
                    Attendance.allocation_id.is_(None),
                )
            target.execute(
                update(Attendance).where(*match).values(
                    room_id=rec["room_id"],
                    status=rec["status"],
                    source=rec["source"],
                    confidence=rec["confidence"],
                    recorded_at=rec["recorded_at"],
                )
            )
            existing = target.execute(select(Attendance.attendance_id).where(*match)).first()
            if existing is None:
                target.add(Attendance(**rec))
        target.flush()
        return len(formatted_records)

    # Raw sqlite3.Connection path.
    query = """
    INSERT INTO attendance (attendance_id, session_id, allocation_id, usn, room_id, status, source, confidence, recorded_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with _get_conn(target) as conn:
        if upsert:
            # UPDATE-first: deleting first would discard the existing surrogate
            # attendance_id and cascade-delete dependent pending_edits.
            for r in formatted_records:
                if r["allocation_id"]:
                    conn.execute(
                        "UPDATE attendance SET room_id=?, status=?, source=?, confidence=?, recorded_at=? "
                        "WHERE allocation_id=? AND usn=?",
                        (
                            r["room_id"], r["status"], r["source"], r["confidence"], r["recorded_at"],
                            r["allocation_id"], r["usn"],
                        ),
                    )
                    existing = conn.execute(
                        "SELECT 1 FROM attendance WHERE allocation_id=? AND usn=? LIMIT 1",
                        (r["allocation_id"], r["usn"]),
                    ).fetchone()
                else:
                    conn.execute(
                        "UPDATE attendance SET room_id=?, status=?, source=?, confidence=?, recorded_at=? "
                        "WHERE session_id=? AND usn=? AND allocation_id IS NULL",
                        (
                            r["room_id"], r["status"], r["source"], r["confidence"], r["recorded_at"],
                            r["session_id"], r["usn"],
                        ),
                    )
                    existing = conn.execute(
                        "SELECT 1 FROM attendance WHERE session_id=? AND usn=? AND allocation_id IS NULL LIMIT 1",
                        (r["session_id"], r["usn"]),
                    ).fetchone()
                if existing is None:
                    conn.execute(
                        query,
                        (r["attendance_id"], r["session_id"], r["allocation_id"], r["usn"],
                         r["room_id"], r["status"], r["source"], r["confidence"], r["recorded_at"]),
                    )
            if isinstance(target, sqlite3.Connection):
                conn.commit()
            return len(formatted_records)

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
    """Delete all attendance records for a specific session without affecting other sessions.

    Raises ``ValueError`` when students still have unconsumed staged edits: the
    RESTRICT foreign key would otherwise abort the delete at the database.
    """
    clean_id = session_id.strip()
    staged = get_usns_with_pending_edits(target, clean_id)
    if staged:
        raise ValueError(
            "Cannot delete attendance for session "
            f"'{clean_id}': {len(staged)} student(s) have unconsumed pending edits "
            f"({', '.join(staged[:5])}{'…' if len(staged) > 5 else ''}). "
            "Confirm or discard the staged edits first."
        )

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


def resolve_session_room_id(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    session_id: str = "",
    usn: Optional[str] = None,
) -> Optional[str]:
    """Resolve a room that genuinely belongs to a session.

    Order of preference (never a hardcoded default):
      1. the room already recorded for this student's attendance row,
      2. the session's single allocation room (ambiguous if several),
      3. the single room already present on the session's attendance rows.
    Returns ``None`` when the session has no unambiguous room, so the caller can
    reject the request instead of inventing one.
    """
    clean_id = session_id.strip()
    if not clean_id:
        return None

    def _pick(values: Sequence[Optional[str]]) -> Optional[str]:
        uniq = {str(v).strip() for v in values if v and str(v).strip()}
        return uniq.pop() if len(uniq) == 1 else None

    if isinstance(target, Session):
        if usn:
            existing = target.scalars(
                select(Attendance.room_id).where(
                    Attendance.session_id == clean_id, Attendance.usn == usn.strip().upper()
                )
            ).all()
            picked = _pick(existing)
            if picked:
                return picked
        allocation_rooms = target.scalars(
            select(SessionAllocation.room_id).where(
                SessionAllocation.session_id == clean_id
            )
        ).all()
        picked = _pick(allocation_rooms)
        if picked:
            return picked
        return _pick(
            target.scalars(
                select(Attendance.room_id).where(Attendance.session_id == clean_id)
            ).all()
        )

    with _get_conn(target) as conn:
        if usn:
            rows = conn.execute(
                "SELECT room_id FROM attendance WHERE session_id = ? AND usn = ?",
                (clean_id, usn.strip().upper()),
            ).fetchall()
            picked = _pick([r[0] for r in rows])
            if picked:
                return picked
        rows = conn.execute(
            "SELECT room_id FROM session_allocations WHERE session_id = ?", (clean_id,)
        ).fetchall()
        picked = _pick([r[0] for r in rows])
        if picked:
            return picked
        rows = conn.execute(
            "SELECT room_id FROM attendance WHERE session_id = ?", (clean_id,)
        ).fetchall()
        return _pick([r[0] for r in rows])


def get_usns_with_pending_edits(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    session_id: str = "",
) -> List[str]:
    """USNs in a session that still have unconsumed staged attendance edits.

    ``pending_edits.attendance_id`` is ON DELETE RESTRICT, so deleting such an
    attendance row fails at the database. Callers use this to reject the whole
    operation up front with a clear message instead of losing staged work.
    """
    clean_id = session_id.strip()
    if not clean_id:
        return []

    if isinstance(target, Session):
        stmt = (
            select(PendingEdit.usn)
            .join(Attendance, PendingEdit.attendance_id == Attendance.attendance_id)
            .where(Attendance.session_id == clean_id, PendingEdit.consumed == 0)
            .distinct()
        )
        return sorted({str(u) for u in target.scalars(stmt).all() if u})

    with _get_conn(target) as conn:
        rows = conn.execute(
            "SELECT DISTINCT pe.usn FROM pending_edits pe "
            "JOIN attendance a ON a.attendance_id = pe.attendance_id "
            "WHERE a.session_id = ? AND pe.consumed = 0",
            (clean_id,),
        ).fetchall()
        return sorted({str(r[0]) for r in rows if r[0]})


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
            room_id = str(r.get("room_id") or "").strip()
            status = normalize_attendance_status(str(r.get("status", "UNREVIEWED")))
            source = str(r.get("source", "UI_CONFIRMED")).strip()
            confidence = float(r.get("confidence", 1.0))
        except Exception as exc:
            raise ValueError(f"Invalid attendance record: {exc}")

        if not usn:
            raise ValueError("Invalid attendance record: usn is empty.")

        if not room_id:
            # No invented default: use the room the session actually has.
            room_id = resolve_session_room_id(target, clean_id, usn) or ""
        if not room_id:
            raise ValueError(
                f"Invalid attendance record for '{usn}': room_id is required because "
                f"session '{clean_id}' has no unambiguous room on record. "
                "Supply room_id explicitly."
            )
        if not status:
            status = "UNREVIEWED"
        if not source:
            source = "UI_CONFIRMED"

        validated_records.append({
            "attendance_id": str(uuid4()),
            "session_id": clean_id,
            "allocation_id": (
                str(r.get("allocation_id")).strip() if r.get("allocation_id") else None
            ),
            "usn": usn,
            "room_id": room_id,
            "status": status,
            "source": source,
            "confidence": confidence,
            "recorded_at": _utcnow_iso(),
        })

    def _match_clause(rec: Dict[str, Any]):
        if rec["allocation_id"]:
            return (Attendance.allocation_id == rec["allocation_id"], Attendance.usn == rec["usn"])
        return (
            Attendance.session_id == clean_id,
            Attendance.usn == rec["usn"],
            Attendance.allocation_id.is_(None),
        )

    if isinstance(target, Session):
        # Transaction safety: execute within nested transaction if one exists, or rely on caller session
        # Use a SAVEPOINT if in an outer transaction so partial failure rolls back cleanly
        savepoint = target.begin_nested()
        try:
            # UPDATE-first so an existing row keeps its surrogate attendance_id;
            # pending_edits.attendance_id is ON DELETE CASCADE and must survive a
            # re-upload of the same session roster.
            kept_ids: Set[str] = set()
            for rec in validated_records:
                existing = target.execute(select(Attendance).where(*_match_clause(rec))).scalars().first()
                if existing is not None:
                    existing.room_id = rec["room_id"]
                    existing.status = rec["status"]
                    existing.source = rec["source"]
                    existing.confidence = rec["confidence"]
                    existing.recorded_at = rec["recorded_at"]
                    kept_ids.add(existing.attendance_id)
                else:
                    target.add(Attendance(**rec))
                    kept_ids.add(rec["attendance_id"])

            # Only rows no longer present in the payload are removed.
            stale_stmt = select(Attendance.attendance_id).where(Attendance.session_id == clean_id)
            if kept_ids:
                stale_stmt = stale_stmt.where(Attendance.attendance_id.notin_(kept_ids))
            stale_ids = [row[0] for row in target.execute(stale_stmt).all()]
            if stale_ids:
                blocked = target.scalars(
                    select(PendingEdit.usn)
                    .where(
                        PendingEdit.attendance_id.in_(stale_ids),
                        PendingEdit.consumed == 0,
                    )
                    .distinct()
                ).all()
                if blocked:
                    raise ValueError(
                        "Cannot drop attendance for staged students "
                        f"({', '.join(sorted({str(b) for b in blocked}))}): "
                        "they have unconsumed pending edits. Confirm or discard "
                        "the staged edits first."
                    )
                target.execute(delete(Attendance).where(Attendance.attendance_id.in_(stale_ids)))

            target.flush()
            # The SAVEPOINT is intentionally NOT released here.
            # Releasing it (savepoint.commit()) implicitly commits the outer
            # transaction in SQLAlchemy 2.0, which would make the replacement
            # survive a later failure - for example an audit insert that fails
            # after this call. Leaving it open keeps the replacement, the audit
            # row and the final commit inside one transaction, so the caller's
            # commit() persists all of it and its rollback() discards all of it.
            return len(validated_records)
        except Exception:
            savepoint.rollback()
            raise

    with _get_conn(target) as conn:
        kept_ids: List[str] = []
        for v in validated_records:
            if v["allocation_id"]:
                conn.execute(
                    "UPDATE attendance SET room_id=?, status=?, source=?, confidence=?, recorded_at=? "
                    "WHERE allocation_id=? AND usn=?",
                    (v["room_id"], v["status"], v["source"], v["confidence"], v["recorded_at"],
                     v["allocation_id"], v["usn"]),
                )
                row = conn.execute(
                    "SELECT attendance_id FROM attendance WHERE allocation_id=? AND usn=? LIMIT 1",
                    (v["allocation_id"], v["usn"]),
                ).fetchone()
            else:
                conn.execute(
                    "UPDATE attendance SET room_id=?, status=?, source=?, confidence=?, recorded_at=? "
                    "WHERE session_id=? AND usn=? AND allocation_id IS NULL",
                    (v["room_id"], v["status"], v["source"], v["confidence"], v["recorded_at"],
                     clean_id, v["usn"]),
                )
                row = conn.execute(
                    "SELECT attendance_id FROM attendance WHERE session_id=? AND usn=? AND allocation_id IS NULL LIMIT 1",
                    (clean_id, v["usn"]),
                ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO attendance (attendance_id, session_id, allocation_id, usn, room_id, status, source, confidence, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (v["attendance_id"], v["session_id"], v["allocation_id"], v["usn"],
                     v["room_id"], v["status"], v["source"], v["confidence"], v["recorded_at"]),
                )
                kept_ids.append(v["attendance_id"])
            else:
                kept_ids.append(row[0])

        if kept_ids:
            placeholders = ",".join("?" for _ in kept_ids)
            conn.execute(
                f"DELETE FROM attendance WHERE session_id = ? AND attendance_id NOT IN ({placeholders})",  # nosec B608 - placeholders are generated '?' markers
                (clean_id, *kept_ids),
            )
        else:
            conn.execute("DELETE FROM attendance WHERE session_id = ?", (clean_id,))
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
    unresolved_rooms: List[str] = []
    for item in roster:
        usn = item["usn"].strip().upper()
        # Prefer the caller's room, then the room the session/student actually has.
        room_id = str(item.get("room_id") or "").strip()
        if not room_id:
            room_id = resolve_session_room_id(target, session_id, usn) or ""
        if not room_id:
            unresolved_rooms.append(usn)

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
        if unresolved_rooms:
            raise ValueError(
                "Cannot persist reconciliation: no room is known for "
                f"{len(unresolved_rooms)} student(s) ({', '.join(unresolved_rooms[:5])}"
                f"{'…' if len(unresolved_rooms) > 5 else ''}). "
                "Supply room_id in the roster or allocation data."
            )
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
    """  # nosec B608 - placeholders are generated '?' markers; values are bound
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


def is_teacher_assigned_to_subject(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    user_id: str = "",
    subject_code: str = "",
) -> bool:
    """True when ``user_id`` is mapped to ``subject_code`` in faculty_subjects."""
    clean_user = (user_id or "").strip()
    clean_code = (subject_code or "").strip().upper()
    if not clean_user or not clean_code:
        return False

    if isinstance(target, Session):
        stmt = select(FacultySubject.id).where(
            FacultySubject.user_id == clean_user,
            func.upper(FacultySubject.subject_code) == clean_code,
        )
        return target.execute(stmt).first() is not None

    with _get_conn(target) as conn:
        try:
            row = conn.execute(
                "SELECT 1 FROM faculty_subjects WHERE user_id = ? AND UPPER(subject_code) = ? LIMIT 1",
                (clean_user, clean_code),
            ).fetchone()
            if row is not None:
                return True
        except Exception:
            pass
        try:
            row = conn.execute(
                "SELECT 1 FROM teacher_subjects WHERE user_id = ? AND UPPER(subject_code) = ? LIMIT 1",
                (clean_user, clean_code),
            ).fetchone()
            return row is not None
        except Exception:
            return False


def get_attendance_by_student(
    target_or_usn: Union[sqlite3.Connection, Session, str],
    usn: Optional[str] = None,
    *,
    session_ids: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all attendance records for a specific student.

    ``session_ids`` optionally restricts the result to the sessions the caller
    is authorized to see; it is applied before the records are returned so that
    a student history can never expose records from an invisible session.
    """
    if usn is None and not isinstance(target_or_usn, (sqlite3.Connection, Session)):
        target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH
        actual_usn = str(target_or_usn)
    else:
        target = target_or_usn
        actual_usn = usn or ""

    clean_usn = actual_usn.strip()
    allowed_sessions = None
    if session_ids is not None:
        allowed_sessions = {str(s) for s in session_ids}

    if isinstance(target, Session):
        stmt = select(Attendance).where(Attendance.usn == clean_usn)
        if allowed_sessions is not None:
            stmt = stmt.where(Attendance.session_id.in_(allowed_sessions))
        stmt = stmt.order_by(Attendance.session_id.asc())
        rows = target.scalars(stmt).all()
        return _rows_to_dicts(list(rows))

    query = """
    SELECT session_id, usn, room_id, status, source, confidence
    FROM attendance
    WHERE usn = ?
    """
    params: List[Any] = [clean_usn]
    if allowed_sessions is not None:
        if not allowed_sessions:
            return []
        placeholders = ",".join("?" for _ in allowed_sessions)
        query += f" AND session_id IN ({placeholders})"
        params.extend(sorted(allowed_sessions))
    query += " ORDER BY session_id ASC"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, tuple(params))
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
    dept_id: Optional[str] = None,
    semester: Optional[int] = None,
) -> Dict[str, Any]:
    """Assign a subject code to a teacher in faculty_subjects."""
    clean_uid = user_id.strip()
    clean_code = subject_code.strip().upper()
    clean_dept = dept_id.strip() if dept_id else None

    if isinstance(target, Session):
        fs = FacultySubject(
            user_id=clean_uid,
            subject_code=clean_code,
            dept_id=clean_dept,
            semester=semester,
        )
        target.add(fs)
        target.flush()
        return _row_to_dict(fs)  # type: ignore

    query = "INSERT INTO faculty_subjects (user_id, subject_code, dept_id, semester) VALUES (?, ?, ?, ?)"
    with _get_conn(target) as conn:
        try:
            cursor = conn.execute(query, (clean_uid, clean_code, clean_dept, semester))
            new_id = cursor.lastrowid
        except Exception:
            # Fallback for unmigrated temporary test fixtures that only have teacher_subjects
            cursor = conn.execute(
                "INSERT INTO teacher_subjects (user_id, subject_code) VALUES (?, ?)",
                (clean_uid, clean_code),
            )
            new_id = cursor.lastrowid
    return {"id": new_id, "user_id": clean_uid, "subject_code": clean_code, "dept_id": clean_dept, "semester": semester}


def get_teacher_subjects(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    user_id: str,
) -> List[str]:
    """List all subject codes assigned to a given teacher exclusively from faculty_subjects."""
    clean_uid = user_id.strip()
    if isinstance(target, Session):
        stmt = select(FacultySubject.subject_code).where(FacultySubject.user_id == clean_uid)
        codes = set(target.execute(stmt).scalars().all())
        return sorted(codes)

    codes = set()
    with _get_conn(target) as conn:
        try:
            cursor = conn.execute("SELECT subject_code FROM faculty_subjects WHERE user_id = ?", (clean_uid,))
            for r in cursor.fetchall():
                codes.add(r["subject_code"] if isinstance(r, sqlite3.Row) else r[0])
        except Exception:
            pass
        if not codes:
            try:
                cursor2 = conn.execute("SELECT subject_code FROM teacher_subjects WHERE user_id = ?", (clean_uid,))
                for r in cursor2.fetchall():
                    codes.add(r["subject_code"] if isinstance(r, sqlite3.Row) else r[0])
            except Exception:
                pass
    return sorted(codes)


def list_teacher_subject_mappings(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    user_id: Optional[str] = None,
    subject_code: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List teacher-subject mappings from faculty_subjects exclusively.
    Admin-facing helper for the teacher-subject management endpoint (N4).
    """
    clean_uid = user_id.strip() if user_id else None
    clean_code = subject_code.strip().upper() if subject_code else None

    if isinstance(target, Session):
        stmt = select(FacultySubject)
        if clean_uid:
            stmt = stmt.where(FacultySubject.user_id == clean_uid)
        if clean_code:
            stmt = stmt.where(FacultySubject.subject_code == clean_code)
        stmt = stmt.order_by(FacultySubject.user_id.asc(), FacultySubject.subject_code.asc())
        rows = target.execute(stmt).scalars().all()
        return [
            {
                "id": r.id,
                "user_id": r.user_id,
                "subject_code": r.subject_code,
                "dept_id": getattr(r, "dept_id", None),
                "semester": getattr(r, "semester", None),
            }
            for r in rows
        ]

    query = "SELECT id, user_id, subject_code, dept_id, semester FROM faculty_subjects WHERE 1=1"
    params: List[Any] = []
    if clean_uid:
        query += " AND user_id = ?"
        params.append(clean_uid)
    if clean_code:
        query += " AND subject_code = ?"
        params.append(clean_code)
    query += " ORDER BY user_id ASC, subject_code ASC"
    result: List[Dict[str, Any]] = []
    with _get_conn(target) as conn:
        try:
            cursor = conn.execute(query, tuple(params))
            for r in cursor.fetchall():
                result.append(_row_to_dict(r))
        except Exception:
            # Fallback for unmigrated temporary test fixtures
            try:
                fb_q = "SELECT id, user_id, subject_code FROM teacher_subjects WHERE 1=1"
                cursor = conn.execute(fb_q, tuple(params))
                for r in cursor.fetchall():
                    result.append(_row_to_dict(r))
            except Exception:
                pass
    return result


_AUDIT_ROLE_SUPPORT_CACHE: "WeakKeyDictionary[Any, bool]" = WeakKeyDictionary()


def _audit_log_supports_actor_role(target: Union[sqlite3.Connection, Session]) -> bool:
    """True when the audit_log table has the ``actor_role`` column (migration 0014).

    The check keeps the audit path working on databases that have not been
    migrated yet: the role is simply omitted instead of failing the write.

    The column list is read on the *caller's own* connection. Using an
    inspector here would check out a second connection from the engine, and
    returning it to the pool rolls back the caller's pending transaction
    (which would silently discard the attendance change being audited).
    """
    if isinstance(target, Session):
        bind = target.get_bind()
        if bind is None:
            return False
        cached = _AUDIT_ROLE_SUPPORT_CACHE.get(bind)
        if cached is not None:
            return cached
        try:
            if bind.dialect.name == "sqlite":
                rows = target.execute(text("PRAGMA table_info(audit_log)")).fetchall()
                columns = {row[1] for row in rows}
            else:
                rows = target.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'audit_log' AND table_schema = current_schema()"
                    )
                ).fetchall()
                columns = {row[0] for row in rows}
        except Exception:
            return False
        supported = "actor_role" in columns
        try:
            _AUDIT_ROLE_SUPPORT_CACHE[bind] = supported
        except TypeError:  # pragma: no cover - non-weakrefable bind
            pass
        return supported

    try:
        columns = {
            row[1] for row in target.execute("PRAGMA table_info(audit_log)").fetchall()
        }
        return "actor_role" in columns
    except Exception:
        return False


def _audit_log_supports_chain(target: Union[sqlite3.Connection, Session]) -> bool:
    """True when the audit_log table has the hash-chain columns."""
    try:
        if isinstance(target, Session):
            bind = target.get_bind()
            if bind is None:
                return False
            if bind.dialect.name == "sqlite":
                rows = target.execute(text("PRAGMA table_info(audit_log)")).fetchall()
                columns = {row[1] for row in rows}
            else:
                rows = target.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'audit_log' AND table_schema = current_schema()"
                    )
                ).fetchall()
                columns = {row[0] for row in rows}
        else:
            columns = {
                row[1] for row in target.execute("PRAGMA table_info(audit_log)").fetchall()
            }
        return {"chain_id", "prev_hash", "row_hash"}.issubset(columns)
    except Exception:
        return False


def _audit_chain_lock_and_read_head(
    target: Union[sqlite3.Connection, Session], chain_id: str
) -> Optional[str]:
    """Lock the chain head and return the current tip hash.

    The upsert-with-no-op-update locks the head row (PostgreSQL row lock,
    SQLite write lock) so that two concurrent writers cannot read the same tip
    and fork the chain. The lock is released when the caller's transaction
    commits or rolls back.
    """
    lock_sql = text(
        "INSERT INTO audit_chain_head (chain_id, last_hash, last_log_id, updated_at) "
        "VALUES (:chain_id, NULL, NULL, NULL) "
        "ON CONFLICT(chain_id) DO UPDATE SET last_hash = audit_chain_head.last_hash"
    )
    if isinstance(target, Session):
        target.execute(lock_sql, {"chain_id": chain_id})
        head = target.execute(
            select(AuditChainHead).where(AuditChainHead.chain_id == chain_id)
        ).scalars().first()
        return head.last_hash if head is not None else None

    target.execute(lock_sql, {"chain_id": chain_id})
    row = target.execute(
        "SELECT last_hash FROM audit_chain_head WHERE chain_id = ?", (chain_id,)
    ).fetchone()
    if row is None:
        return None
    return row[0] if not isinstance(row, dict) else row.get("last_hash")


def _audit_chain_prev_hash(target: Union[sqlite3.Connection, Session], chain_id: str) -> str:
    """Lock the chain head and return the predecessor hash for the next record."""
    last_hash = _audit_chain_lock_and_read_head(target, chain_id)
    return str(last_hash) if last_hash else get_genesis_hash()


def _audit_chain_advance_head(
    target: Union[sqlite3.Connection, Session],
    chain_id: str,
    row_hash: str,
    log_id: Optional[int],
    timestamp: str,
) -> None:
    """Advance the chain head inside the caller's transaction."""
    if isinstance(target, Session):
        head = target.get(AuditChainHead, chain_id)
        if head is None:
            head = AuditChainHead(chain_id=chain_id)
            target.add(head)
        head.last_hash = row_hash
        head.last_log_id = log_id
        head.updated_at = timestamp
        target.flush()
        return

    with _get_conn(target) as conn:
        conn.execute(
            "INSERT INTO audit_chain_head (chain_id, last_hash, last_log_id, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(chain_id) DO UPDATE SET last_hash = excluded.last_hash, "
            "last_log_id = excluded.last_log_id, updated_at = excluded.updated_at",
            (chain_id, row_hash, log_id, timestamp),
        )


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
    actor_role: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an append-only audit log entry.

    When the audit hash chain is provisioned (``AUDIT_CHAIN_HMAC_SECRET``), the
    record is linked to its predecessor with an HMAC-SHA256 hash. The link and
    the record are written in the **same transaction**, so an audit entry can
    never exist without its chain link.
    """
    clean_actor = actor_id.strip()
    clean_act = action.strip().upper()
    ts = timestamp or _utcnow_iso()
    clean_role = actor_role.strip().upper() if actor_role else None

    if isinstance(target, Session):
        supports_role = _audit_log_supports_actor_role(target)
        supports_chain = _audit_log_supports_chain(target)
        values: Dict[str, Any] = {
            "actor_id": clean_actor,
            "action": clean_act,
            "session_id": session_id.strip() if session_id else None,
            "usn": usn.strip().upper() if usn else None,
            "entity_type": entity_type.strip(),
            "entity_id": entity_id.strip(),
            "old_value": old_value,
            "new_value": new_value,
            "reason": reason.strip() if reason else None,
            "timestamp": ts,
        }
        if supports_role:
            values["actor_role"] = clean_role

        prev_hash: Optional[str] = None
        row_hash: Optional[str] = None
        chain_id: Optional[str] = None
        if supports_chain:
            secret = get_chain_secret()
            if secret is not None:
                chain_id = DEFAULT_CHAIN_ID
                prev_hash = _audit_chain_prev_hash(target, chain_id)
                values["chain_id"] = chain_id
                values["prev_hash"] = prev_hash
                values["row_hash"] = compute_row_hash(
                    {**values, "chain_id": chain_id, "prev_hash": prev_hash}, secret
                )

        # Core insert with an explicit column set: the ORM entity would always
        # include actor_role, which would break databases not yet migrated.
        insert_result = target.execute(sa_insert(AuditLog.__table__).values(**values))
        target.flush()
        log_id = None
        try:
            log_id = insert_result.inserted_primary_key[0]
        except Exception:
            pass

        if chain_id is not None and row_hash is None:
            row_hash = values.get("row_hash")
        if chain_id is not None and row_hash:
            _audit_chain_advance_head(target, chain_id, str(row_hash), log_id, ts)

        result = {
            "log_id": log_id,
            "actor_id": clean_actor,
            "actor_role": clean_role if supports_role else None,
            "action": clean_act,
            "session_id": session_id,
            "usn": usn,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "old_value": old_value,
            "new_value": new_value,
            "reason": reason,
            "timestamp": ts,
            "chain_id": chain_id,
            "prev_hash": prev_hash,
            "row_hash": row_hash,
        }
        return result

    with _get_conn(target) as conn:
        supports_role = _audit_log_supports_actor_role(conn)
        if supports_role:
            query = """
            INSERT INTO audit_log (
                actor_id, actor_role, action, session_id, usn, entity_type, entity_id,
                old_value, new_value, reason, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                clean_actor,
                clean_role,
                clean_act,
                session_id.strip() if session_id else None,
                usn.strip().upper() if usn else None,
                entity_type.strip(),
                entity_id.strip(),
                old_value,
                new_value,
                reason.strip() if reason else None,
                ts,
            )
        else:
            query = """
            INSERT INTO audit_log (
                actor_id, action, session_id, usn, entity_type, entity_id,
                old_value, new_value, reason, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = (
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
            )
        cursor = conn.execute(query, params)
        log_id = cursor.lastrowid
    return {
        "log_id": log_id,
        "actor_id": clean_actor,
        "actor_role": clean_role if supports_role else None,
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


def list_audit_entries(
    target: Union[sqlite3.Connection, Session, str] = DEFAULT_DB_PATH,
    *,
    actor_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    action: Optional[str] = None,
    session_id: Optional[str] = None,
    usn: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """List append-only audit entries, newest first.

    Only the audit columns are returned: the log never contains credentials or
    unrelated sensitive data. ``actor_role`` is nullable because records
    written before migration 0014 have no role column.
    """
    limit_val = max(1, min(200, limit))
    offset_val = max(0, offset)

    supports_role = _audit_log_supports_actor_role(target)

    filters: List[Any] = []
    if actor_id and actor_id.strip():
        filters.append(AuditLog.actor_id == actor_id.strip())
    if actor_role and actor_role.strip() and supports_role:
        filters.append(func.upper(AuditLog.actor_role) == actor_role.strip().upper())
    if action and action.strip():
        filters.append(AuditLog.action == action.strip().upper())
    if session_id and session_id.strip():
        filters.append(AuditLog.session_id == session_id.strip())
    if usn and usn.strip():
        filters.append(AuditLog.usn == usn.strip().upper())
    if start_date and start_date.strip():
        filters.append(AuditLog.timestamp >= f"{start_date.strip()}T00:00:00Z")
    if end_date and end_date.strip():
        filters.append(AuditLog.timestamp <= f"{end_date.strip()}T23:59:59Z")

    if isinstance(target, Session):
        table = AuditLog.__table__
        columns = [
            table.c.log_id,
            table.c.actor_id,
            table.c.action,
            table.c.session_id,
            table.c.usn,
            table.c.entity_type,
            table.c.entity_id,
            table.c.old_value,
            table.c.new_value,
            table.c.reason,
            table.c.timestamp,
        ]
        if supports_role:
            columns.insert(2, table.c.actor_role)

        count_stmt = select(func.count(table.c.log_id))
        if filters:
            count_stmt = count_stmt.where(and_(*filters))
        total = target.scalar(count_stmt) or 0

        stmt = select(*columns)
        if filters:
            stmt = stmt.where(and_(*filters))
        stmt = (
            stmt.order_by(table.c.timestamp.desc(), table.c.log_id.desc())
            .limit(limit_val)
            .offset(offset_val)
        )
        rows = target.execute(stmt).mappings().all()
        return [_audit_row_to_dict(row) for row in rows], total

    where_clauses: List[str] = []
    params: List[Any] = []
    if actor_id and actor_id.strip():
        where_clauses.append("actor_id = ?")
        params.append(actor_id.strip())
    if actor_role and actor_role.strip() and supports_role:
        where_clauses.append("UPPER(actor_role) = ?")
        params.append(actor_role.strip().upper())
    if action and action.strip():
        where_clauses.append("action = ?")
        params.append(action.strip().upper())
    if session_id and session_id.strip():
        where_clauses.append("session_id = ?")
        params.append(session_id.strip())
    if usn and usn.strip():
        where_clauses.append("usn = ?")
        params.append(usn.strip().upper())
    if start_date and start_date.strip():
        where_clauses.append("timestamp >= ?")
        params.append(f"{start_date.strip()}T00:00:00Z")
    if end_date and end_date.strip():
        where_clauses.append("timestamp <= ?")
        params.append(f"{end_date.strip()}T23:59:59Z")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    select_columns = (
        "log_id, actor_id, actor_role, action, session_id, usn, entity_type, "
        "entity_id, old_value, new_value, reason, timestamp"
        if supports_role
        else (
            "log_id, actor_id, action, session_id, usn, entity_type, "
            "entity_id, old_value, new_value, reason, timestamp"
        )
    )
    with _get_conn(target) as conn:
        count_cursor = conn.execute(f"SELECT COUNT(*) FROM audit_log {where_sql}", params)  # nosec B608 - fixed literals, bound values
        total = count_cursor.fetchone()[0]
        data_query = (
            f"SELECT {select_columns} FROM audit_log {where_sql} "  # nosec B608 - select_columns is a constant string
            "ORDER BY timestamp DESC, log_id DESC LIMIT ? OFFSET ?"
        )
        data_params = params + [limit_val, offset_val]
        data_cursor = conn.execute(data_query, data_params)
        return [_audit_row_to_dict(r) for r in data_cursor.fetchall()], total


def _audit_row_to_dict(row: Any) -> Dict[str, Any]:
    """Normalize an audit row into the public read contract."""
    if row is None:
        return {}
    if isinstance(row, dict):
        data = dict(row)
    elif isinstance(row, sqlite3.Row):
        data = dict(row)
    elif isinstance(row, AuditLog):
        data = {
            "log_id": row.log_id,
            "actor_id": row.actor_id,
            "actor_role": row.actor_role,
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
    elif hasattr(row, "keys"):
        # SQLAlchemy RowMapping and other mapping-like rows.
        data = {key: row[key] for key in row.keys()}
    else:
        data = {
            "log_id": row[0],
            "actor_id": row[1],
            "actor_role": row[2],
            "action": row[3],
            "session_id": row[4],
            "usn": row[5],
            "entity_type": row[6],
            "entity_id": row[7],
            "old_value": row[8],
            "new_value": row[9],
            "reason": row[10],
            "timestamp": row[11],
        }
    return {
        "id": data.get("log_id"),
        "log_id": data.get("log_id"),
        "actor_id": data.get("actor_id"),
        "actor_role": data.get("actor_role"),
        "event_type": data.get("action"),
        "action": data.get("action"),
        "event": data.get("action"),
        "session_id": data.get("session_id"),
        "usn": data.get("usn"),
        "entity_type": data.get("entity_type"),
        "entity_id": data.get("entity_id"),
        "old_status": data.get("old_value"),
        "new_status": data.get("new_value"),
        "old_value": data.get("old_value"),
        "new_value": data.get("new_value"),
        "reason": data.get("reason"),
        "timestamp": data.get("timestamp"),
        "at_utc": data.get("timestamp"),
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
        "pending_id": edit_id,
        "user_id": clean_uid,
        "session_id": clean_sid,
        "usn": clean_usn,
        "old_status": clean_old,
        "new_status": clean_new,
        "created_at": now_ts,
        "expires_at": exp_ts,
        "consumed": 0,
        "used": 0,
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
        # Authorization mirrors the shared session policy: the owner, the
        # coordinator, or a teacher mapped to the session's subject code.
        subj_code = sess.subject_code or sess.subject
        teacher_assigned = (sess.teacher_id == clean_uid)
        if not teacher_assigned and sess.coordinator_faculty_id == clean_uid:
            teacher_assigned = True
        if not teacher_assigned and subj_code:
            stmt = select(FacultySubject).where(
                FacultySubject.user_id == clean_uid,
                FacultySubject.subject_code == subj_code,
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

    # Step 8: Insert audit log entry in the same transaction.
    # Uses the shared append-only audit helper so the actor role is recorded
    # and databases without migration 0014 keep working.
    audit = create_audit_entry(
        session,
        actor_id=clean_uid,
        actor_role=role,
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

    return {
        "edit_id": clean_eid,
        "session_id": edit.session_id,
        "usn": edit.usn,
        "old_status": edit.old_status,
        "new_status": edit.new_status,
        "consumed": 1,
        "audit_log_id": audit.get("log_id"),
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


