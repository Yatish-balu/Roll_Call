"""Tests for query_tool: safe read-only database inspections and analytics."""

import sqlite3
import pytest
from app.db.schema import init_db
from app.db.crud import insert_student, insert_room, insert_session, insert_attendance
from tools.query_tool import (
    query_tool,
    query_attendance,
    query_session_stats,
    query_absentees,
    query_students,
    safe_sql_query,
    validate_read_only_sql,
    NO_DATA_MESSAGE,
    QueryResult,
)


@pytest.fixture
def populated_db():
    """Create and seed an in-memory database with test data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    # Insert students
    insert_student(conn, usn="1MS21CS001", name="Alice Smith", branch="CSE")
    insert_student(conn, usn="1MS21CS002", name="Bob Jones", branch="CSE")
    insert_student(conn, usn="1MS21IS001", name="Charlie Brown", branch="ISE")
    insert_student(conn, usn="1MS21EC001", name="David Miller", branch="ECE")

    # Insert rooms
    insert_room(conn, room_id="LH-101", name="Lecture Hall 101")
    insert_room(conn, room_id="LH-102", name="Lecture Hall 102")

    # Insert sessions
    insert_session(conn, session_id="SESS-01", date="2026-10-24", subject="Algorithms")
    insert_session(conn, session_id="SESS-EMPTY", date="2026-10-25", subject="Empty Session")

    # Insert attendance
    insert_attendance(conn, session_id="SESS-01", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="csv", confidence=1.0)
    insert_attendance(conn, session_id="SESS-01", usn="1MS21CS002", room_id="LH-101", status="ABSENT", source="csv", confidence=1.0)
    insert_attendance(conn, session_id="SESS-01", usn="1MS21IS001", room_id="LH-102", status="PENDING", source="csv", confidence=0.7)
    insert_attendance(conn, session_id="SESS-01", usn="1MS21EC001", room_id="LH-102", status="UNREVIEWED", source="csv", confidence=0.6)

    return conn


def test_query_attendance_all(populated_db):
    res = query_attendance(db_target=populated_db)
    assert res.found is True
    assert res.total_count == 4
    assert len(res.data) == 4


def test_query_attendance_filters(populated_db):
    # Filter by room
    res_room = query_attendance(room_id="LH-101", db_target=populated_db)
    assert res_room.total_count == 2
    assert all(r["room_id"] == "LH-101" for r in res_room.data)

    # Filter by status
    res_absent = query_attendance(status="ABSENT", db_target=populated_db)
    assert res_absent.total_count == 1
    assert res_absent.data[0]["usn"] == "1MS21CS002"

    # Filter by branch
    res_branch = query_attendance(branch="ISE", db_target=populated_db)
    assert res_branch.total_count == 1
    assert res_branch.data[0]["usn"] == "1MS21IS001"


def test_query_session_stats_correct_percentage(populated_db):
    res = query_session_stats("SESS-01", db_target=populated_db)
    assert res.found is True
    stats = res.data[0]
    assert stats["present"] == 1
    assert stats["absent"] == 1
    assert stats["pending"] == 1
    assert stats["unreviewed"] == 1
    assert stats["total"] == 4
    # Confirmed is present + absent = 2. Confirmed percentage = 1 / 2 * 100 = 50.0%
    assert stats["confirmed"] == 2
    assert stats["confirmed_percentage"] == 50.0


def test_query_session_stats_missing_session_returns_no_data(populated_db):
    res = query_session_stats("NON_EXISTENT_SESSION", db_target=populated_db)
    assert res.found is False
    assert res.message == NO_DATA_MESSAGE
    assert res.data == []


def test_query_session_stats_empty_session_returns_no_data(populated_db):
    res = query_session_stats("SESS-EMPTY", db_target=populated_db)
    assert res.found is False
    assert res.message == NO_DATA_MESSAGE


def test_query_absentees(populated_db):
    res = query_absentees(session_id="SESS-01", db_target=populated_db)
    assert res.found is True
    assert res.total_count == 1
    assert res.data[0]["usn"] == "1MS21CS002"
    assert res.data[0]["student_name"] == "Bob Jones"


def test_query_students(populated_db):
    res = query_students(branch="CSE", db_target=populated_db)
    assert res.found is True
    assert res.total_count == 2
    usns = {s["usn"] for s in res.data}
    assert usns == {"1MS21CS001", "1MS21CS002"}


def test_safe_sql_query_allowed(populated_db):
    sql = "SELECT usn, name FROM students WHERE branch = ? ORDER BY usn ASC"
    res = safe_sql_query(sql, params=("CSE",), db_target=populated_db)
    assert res.found is True
    assert res.total_count == 2
    assert res.data[0]["usn"] == "1MS21CS001"


def test_safe_sql_blocks_mutations():
    # Non-SELECT mutations
    with pytest.raises(ValueError):
        validate_read_only_sql("DELETE FROM students WHERE usn = '1MS21CS001'")

    with pytest.raises(ValueError):
        validate_read_only_sql("DROP TABLE attendance")

    with pytest.raises(ValueError):
        validate_read_only_sql("INSERT INTO rooms VALUES ('LH-999', 'Forbidden')")

    with pytest.raises(ValueError):
        validate_read_only_sql("UPDATE attendance SET status = 'PRESENT'")

    # Mutation keyword inside a query starting with SELECT
    with pytest.raises(ValueError, match="Disallowed keyword"):
        validate_read_only_sql("SELECT * FROM students WHERE usn IN (DELETE FROM students)")


def test_safe_sql_blocks_multi_statements():
    with pytest.raises(ValueError, match="Multiple SQL statements"):
        validate_read_only_sql("SELECT * FROM students; DROP TABLE students;")


def test_safe_sql_blocks_unauthorized_tables():
    with pytest.raises(ValueError, match="Access to table 'sqlite_master' is not permitted"):
        validate_read_only_sql("SELECT name FROM sqlite_master")


def test_query_tool_dispatcher(populated_db):
    # Dispatch attendance
    res1 = query_tool("attendance", session_id="SESS-01", db_target=populated_db)
    assert res1.found is True
    assert res1.total_count == 4

    # Dispatch stats
    res2 = query_tool("session_stats", session_id="SESS-01", db_target=populated_db)
    assert res2.found is True

    # Dispatch absentees
    res3 = query_tool("absentees", session_id="SESS-01", db_target=populated_db)
    assert res3.found is True

    # Unknown type
    res4 = query_tool("unknown_operation", db_target=populated_db)
    assert res4.found is False
    assert "Unsupported query_type" in res4.message
