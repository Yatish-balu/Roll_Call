"""Database package initialization and unified exports."""

from app.db.connection import DEFAULT_DB_PATH, get_connection, get_db_cursor
from app.db.schema import SCHEMA_SQL, init_db
from app.db.crud import (
    # Students
    insert_student,
    insert_students_bulk,
    get_student,
    get_all_students,
    get_students_by_branch,
    # Rooms
    insert_room,
    insert_rooms_bulk,
    get_room,
    get_all_rooms,
    # Sessions
    insert_session,
    insert_sessions_bulk,
    get_session,
    get_all_sessions,
    get_sessions_by_date,
    # Attendance
    VALID_ATTENDANCE_STATUSES,
    normalize_attendance_status,
    insert_attendance,
    insert_attendance_bulk,
    delete_session_attendance,
    replace_session_attendance,
    reconcile_session_roster,
    get_attendance_record,
    get_attendance_by_session,
    get_attendance_by_student,
    get_session_attendance_details,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "get_connection",
    "get_db_cursor",
    "SCHEMA_SQL",
    "init_db",
    "insert_student",
    "insert_students_bulk",
    "get_student",
    "get_all_students",
    "get_students_by_branch",
    "insert_room",
    "insert_rooms_bulk",
    "get_room",
    "get_all_rooms",
    "insert_session",
    "insert_sessions_bulk",
    "get_session",
    "get_all_sessions",
    "get_sessions_by_date",
    "VALID_ATTENDANCE_STATUSES",
    "normalize_attendance_status",
    "insert_attendance",
    "insert_attendance_bulk",
    "delete_session_attendance",
    "replace_session_attendance",
    "reconcile_session_roster",
    "get_attendance_record",
    "get_attendance_by_session",
    "get_attendance_by_student",
    "get_session_attendance_details",
]
