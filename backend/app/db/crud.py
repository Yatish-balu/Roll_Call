"""CRUD operations for students, rooms, sessions, and attendance.

Supports both:
1. Legacy SQLite Connection and database file paths.
2. Modern SQLAlchemy 2.0 synchronous Session objects.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, Sequence, Set, Tuple, Union

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.connection import DEFAULT_DB_PATH, get_connection
from app.db.models import Student, Room, Session as DbSession, Attendance


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
        return {"session_id": row.session_id, "date": row.date, "subject": row.subject}
    if isinstance(row, Attendance):
        return {
            "session_id": row.session_id,
            "usn": row.usn,
            "room_id": row.room_id,
            "status": row.status,
            "source": row.source,
            "confidence": row.confidence,
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
) -> Dict[str, Any]:
    """Insert a new session."""
    clean_id = session_id.strip()
    clean_date = date.strip()
    clean_sub = subject.strip()

    if isinstance(target, Session):
        sess = DbSession(session_id=clean_id, date=clean_date, subject=clean_sub)
        target.add(sess)
        target.flush()
        return {"session_id": clean_id, "date": clean_date, "subject": clean_sub}

    query = "INSERT INTO sessions (session_id, date, subject) VALUES (?, ?, ?)"
    with _get_conn(target) as conn:
        conn.execute(query, (clean_id, clean_date, clean_sub))
        if isinstance(target, sqlite3.Connection):
            conn.commit()
    return {"session_id": clean_id, "date": clean_date, "subject": clean_sub}


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

    query = "SELECT session_id, date, subject FROM sessions WHERE session_id = ?"
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

    query = "SELECT session_id, date, subject FROM sessions ORDER BY date DESC, session_id ASC"
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

    query = "SELECT session_id, date, subject FROM sessions WHERE date = ? ORDER BY session_id ASC"
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

        data_query = f"SELECT session_id, date, subject FROM sessions {where_sql} ORDER BY date DESC, session_id ASC LIMIT ? OFFSET ?"
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

    if isinstance(target, Session):
        bind = target.get_bind()
        dialect_name = bind.dialect.name if bind else "sqlite"

        if upsert:
            if dialect_name == "postgresql":
                stmt = pg_insert(Attendance).values(record)
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
                stmt = sqlite_insert(Attendance).values(record)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["session_id", "usn"],
                    set_={
                        "room_id": stmt.excluded.room_id,
                        "status": stmt.excluded.status,
                        "source": stmt.excluded.source,
                        "confidence": stmt.excluded.confidence,
                    },
                )
            target.execute(stmt)
        else:
            att = Attendance(**record)
            target.add(att)

        target.flush()
        return record

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

    with _get_conn(target) as conn:
        conn.execute(
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
            "session_id": r["session_id"].strip(),
            "usn": r["usn"].strip(),
            "room_id": r["room_id"].strip(),
            "status": normalize_attendance_status(r["status"]),
            "source": r["source"].strip(),
            "confidence": float(r.get("confidence", 1.0)),
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
                stmt = sqlite_insert(Attendance).values(formatted_records)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["session_id", "usn"],
                    set_={
                        "room_id": stmt.excluded.room_id,
                        "status": stmt.excluded.status,
                        "source": stmt.excluded.source,
                        "confidence": stmt.excluded.confidence,
                    },
                )
            res = target.execute(stmt)
            target.flush()
            return len(formatted_records)
        else:
            target.bulk_insert_mappings(Attendance, formatted_records)
            target.flush()
            return len(formatted_records)

    tuple_records = [
        (r["session_id"], r["usn"], r["room_id"], r["status"], r["source"], r["confidence"])
        for r in formatted_records
    ]

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

    with _get_conn(target) as conn:
        cursor = conn.cursor()
        cursor.executemany(query, tuple_records)
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
            "session_id": clean_id,
            "usn": usn,
            "room_id": room_id,
            "status": status,
            "source": source,
            "confidence": confidence,
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
        INSERT INTO attendance (session_id, usn, room_id, status, source, confidence)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        cursor = conn.cursor()
        insert_rows = [
            (v["session_id"], v["usn"], v["room_id"], v["status"], v["source"], v["confidence"])
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
