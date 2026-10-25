"""CRUD operations for students, rooms, sessions, and attendance."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, Union
from app.db.connection import DEFAULT_DB_PATH, get_connection


@contextmanager
def _get_conn(
    target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH
) -> Generator[sqlite3.Connection, None, None]:
    """Yield an existing connection without closing it, or open and manage a new one."""
    if isinstance(target, sqlite3.Connection):
        yield target
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


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(row) if row is not None else None


def _rows_to_dicts(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(row) for row in rows]


# ==========================================
# Students Operations
# ==========================================

def insert_student(
    target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH,
    *,
    usn: str,
    name: str,
    branch: str,
) -> Dict[str, Any]:
    """Insert a new student."""
    query = "INSERT INTO students (usn, name, branch) VALUES (?, ?, ?)"
    with _get_conn(target) as conn:
        conn.execute(query, (usn.strip(), name.strip(), branch.strip()))
        if isinstance(target, sqlite3.Connection):
            conn.commit()
    return {"usn": usn.strip(), "name": name.strip(), "branch": branch.strip()}


def insert_students_bulk(
    target_or_students: Union[sqlite3.Connection, str, List[Dict[str, str]]],
    students: Optional[List[Dict[str, str]]] = None,
) -> int:
    """Insert multiple students in a single transaction."""
    if isinstance(target_or_students, list) and students is None:
        target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH
        actual_students = target_or_students
    else:
        target = target_or_students  # type: ignore[assignment]
        actual_students = students or []

    query = "INSERT INTO students (usn, name, branch) VALUES (?, ?, ?)"
    records = [
        (s["usn"].strip(), s["name"].strip(), s["branch"].strip())
        for s in actual_students
    ]
    with _get_conn(target) as conn:
        cursor = conn.cursor()
        cursor.executemany(query, records)
        if isinstance(target, sqlite3.Connection):
            conn.commit()
        return cursor.rowcount


def get_student(
    target_or_usn: Union[sqlite3.Connection, str],
    usn: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a student by USN."""
    if usn is None:
        target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH
        actual_usn = str(target_or_usn)
    else:
        target = target_or_usn
        actual_usn = usn

    query = "SELECT usn, name, branch FROM students WHERE usn = ?"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (actual_usn.strip(),))
        row = cursor.fetchone()
        return _row_to_dict(row)


def get_all_students(
    target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Retrieve all students ordered by USN."""
    query = "SELECT usn, name, branch FROM students ORDER BY usn ASC"
    with _get_conn(target) as conn:
        cursor = conn.execute(query)
        return _rows_to_dicts(cursor.fetchall())


def get_students_by_branch(
    target_or_branch: Union[sqlite3.Connection, str],
    branch: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all students in a given branch."""
    if branch is None:
        target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH
        actual_branch = str(target_or_branch)
    else:
        target = target_or_branch
        actual_branch = branch

    query = "SELECT usn, name, branch FROM students WHERE branch = ? ORDER BY usn ASC"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (actual_branch.strip(),))
        return _rows_to_dicts(cursor.fetchall())


# ==========================================
# Rooms Operations
# ==========================================

def insert_room(
    target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH,
    *,
    room_id: str,
    name: str,
) -> Dict[str, Any]:
    """Insert a new room."""
    query = "INSERT INTO rooms (room_id, name) VALUES (?, ?)"
    with _get_conn(target) as conn:
        conn.execute(query, (room_id.strip(), name.strip()))
        if isinstance(target, sqlite3.Connection):
            conn.commit()
    return {"room_id": room_id.strip(), "name": name.strip()}


def insert_rooms_bulk(
    target_or_rooms: Union[sqlite3.Connection, str, List[Dict[str, str]]],
    rooms: Optional[List[Dict[str, str]]] = None,
) -> int:
    """Insert multiple rooms in a single transaction."""
    if isinstance(target_or_rooms, list) and rooms is None:
        target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH
        actual_rooms = target_or_rooms
    else:
        target = target_or_rooms  # type: ignore[assignment]
        actual_rooms = rooms or []

    query = "INSERT INTO rooms (room_id, name) VALUES (?, ?)"
    records = [(r["room_id"].strip(), r["name"].strip()) for r in actual_rooms]
    with _get_conn(target) as conn:
        cursor = conn.cursor()
        cursor.executemany(query, records)
        if isinstance(target, sqlite3.Connection):
            conn.commit()
        return cursor.rowcount


def get_room(
    target_or_room_id: Union[sqlite3.Connection, str],
    room_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a room by room_id."""
    if room_id is None:
        target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH
        actual_id = str(target_or_room_id)
    else:
        target = target_or_room_id
        actual_id = room_id

    query = "SELECT room_id, name FROM rooms WHERE room_id = ?"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (actual_id.strip(),))
        return _row_to_dict(cursor.fetchone())


def get_all_rooms(
    target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Retrieve all rooms ordered by room_id."""
    query = "SELECT room_id, name FROM rooms ORDER BY room_id ASC"
    with _get_conn(target) as conn:
        cursor = conn.execute(query)
        return _rows_to_dicts(cursor.fetchall())


# ==========================================
# Sessions Operations
# ==========================================

def insert_session(
    target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH,
    *,
    session_id: str,
    date: str,
    subject: str,
) -> Dict[str, Any]:
    """Insert a new session."""
    query = "INSERT INTO sessions (session_id, date, subject) VALUES (?, ?, ?)"
    with _get_conn(target) as conn:
        conn.execute(query, (session_id.strip(), date.strip(), subject.strip()))
        if isinstance(target, sqlite3.Connection):
            conn.commit()
    return {"session_id": session_id.strip(), "date": date.strip(), "subject": subject.strip()}


def insert_sessions_bulk(
    target_or_sessions: Union[sqlite3.Connection, str, List[Dict[str, str]]],
    sessions: Optional[List[Dict[str, str]]] = None,
) -> int:
    """Insert multiple sessions in a single transaction."""
    if isinstance(target_or_sessions, list) and sessions is None:
        target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH
        actual_sessions = target_or_sessions
    else:
        target = target_or_sessions  # type: ignore[assignment]
        actual_sessions = sessions or []

    query = "INSERT INTO sessions (session_id, date, subject) VALUES (?, ?, ?)"
    records = [
        (s["session_id"].strip(), s["date"].strip(), s["subject"].strip())
        for s in actual_sessions
    ]
    with _get_conn(target) as conn:
        cursor = conn.cursor()
        cursor.executemany(query, records)
        if isinstance(target, sqlite3.Connection):
            conn.commit()
        return cursor.rowcount


def get_session(
    target_or_session_id: Union[sqlite3.Connection, str],
    session_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a session by session_id."""
    if session_id is None:
        target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH
        actual_id = str(target_or_session_id)
    else:
        target = target_or_session_id
        actual_id = session_id

    query = "SELECT session_id, date, subject FROM sessions WHERE session_id = ?"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (actual_id.strip(),))
        return _row_to_dict(cursor.fetchone())


def get_all_sessions(
    target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Retrieve all sessions ordered by date descending."""
    query = "SELECT session_id, date, subject FROM sessions ORDER BY date DESC, session_id ASC"
    with _get_conn(target) as conn:
        cursor = conn.execute(query)
        return _rows_to_dicts(cursor.fetchall())


def get_sessions_by_date(
    target_or_date: Union[sqlite3.Connection, str],
    date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve sessions for a specific date."""
    if date is None:
        target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH
        actual_date = str(target_or_date)
    else:
        target = target_or_date
        actual_date = date

    query = "SELECT session_id, date, subject FROM sessions WHERE date = ? ORDER BY session_id ASC"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (actual_date.strip(),))
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
    target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH,
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

    record = {
        "session_id": session_id.strip(),
        "usn": usn.strip(),
        "room_id": room_id.strip(),
        "status": clean_status,
        "source": source.strip(),
        "confidence": float(confidence),
    }

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
    target_or_records: Union[sqlite3.Connection, str, List[Dict[str, Any]]],
    records: Optional[List[Dict[str, Any]]] = None,
    upsert: bool = False,
) -> int:
    """Insert multiple attendance records."""
    if isinstance(target_or_records, list) and records is None:
        target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH
        actual_records = target_or_records
    else:
        target = target_or_records  # type: ignore[assignment]
        actual_records = records or []

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

    formatted_records = [
        (
            r["session_id"].strip(),
            r["usn"].strip(),
            r["room_id"].strip(),
            normalize_attendance_status(r["status"]),
            r["source"].strip(),
            float(r.get("confidence", 1.0)),
        )
        for r in actual_records
    ]

    with _get_conn(target) as conn:
        cursor = conn.cursor()
        cursor.executemany(query, formatted_records)
        if isinstance(target, sqlite3.Connection):
            conn.commit()
        return cursor.rowcount


def delete_session_attendance(
    target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH,
    session_id: str = "",
) -> int:
    """Delete all attendance records for a specific session without affecting other sessions."""
    query = "DELETE FROM attendance WHERE session_id = ?"
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (session_id.strip(),))
        if isinstance(target, sqlite3.Connection):
            conn.commit()
        return cursor.rowcount


def replace_session_attendance(
    target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH,
    session_id: str = "",
    records: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """
    Atomically re-upload/replace all attendance records for a session.
    Cleans up old records for this session only and inserts new records without affecting other sessions.
    """
    new_records = records or []
    formatted_records = [
        (
            session_id.strip(),
            r["usn"].strip(),
            r["room_id"].strip(),
            normalize_attendance_status(r["status"]),
            r["source"].strip(),
            float(r.get("confidence", 1.0)),
        )
        for r in new_records
    ]

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

        # Normalize missing room_id and status to sensible defaults so database writes stay consistent.
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

    with _get_conn(target) as conn:
        conn.execute("DELETE FROM attendance WHERE session_id = ?", (session_id.strip(),))
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
    target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH,
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
            # Missing sheet or missing entry -> PENDING
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
    target_or_session_id: Union[sqlite3.Connection, str],
    session_id_or_usn: str,
    usn: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve attendance record for a specific student in a specific session."""
    if usn is None:
        target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH
        actual_session_id = str(target_or_session_id)
        actual_usn = session_id_or_usn
    else:
        target = target_or_session_id
        actual_session_id = session_id_or_usn
        actual_usn = usn

    query = """
    SELECT session_id, usn, room_id, status, source, confidence
    FROM attendance
    WHERE session_id = ? AND usn = ?
    """
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (actual_session_id.strip(), actual_usn.strip()))
        return _row_to_dict(cursor.fetchone())


def get_attendance_by_session(
    target_or_session_id: Union[sqlite3.Connection, str],
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all attendance records for a given session."""
    if session_id is None:
        target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH
        actual_id = str(target_or_session_id)
    else:
        target = target_or_session_id
        actual_id = session_id

    query = """
    SELECT session_id, usn, room_id, status, source, confidence
    FROM attendance
    WHERE session_id = ?
    ORDER BY usn ASC
    """
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (actual_id.strip(),))
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
    target_or_usn: Union[sqlite3.Connection, str],
    usn: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all attendance records for a specific student."""
    if usn is None:
        target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH
        actual_usn = str(target_or_usn)
    else:
        target = target_or_usn
        actual_usn = usn

    query = """
    SELECT session_id, usn, room_id, status, source, confidence
    FROM attendance
    WHERE usn = ?
    ORDER BY session_id ASC
    """
    with _get_conn(target) as conn:
        cursor = conn.execute(query, (actual_usn.strip(),))
        return _rows_to_dicts(cursor.fetchall())


def get_session_attendance_details(
    target_or_session_id: Union[sqlite3.Connection, str],
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve joined detailed attendance data for a session."""
    if session_id is None:
        target: Union[sqlite3.Connection, str] = DEFAULT_DB_PATH
        actual_id = str(target_or_session_id)
    else:
        target = target_or_session_id
        actual_id = session_id

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
        cursor = conn.execute(query, (actual_id.strip(),))
        return _rows_to_dicts(cursor.fetchall())
