"""Comprehensive test suite for Phase 3B: SQLAlchemy 2.0 CRUD and Query operations."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.base import Base
from app.db.models import Student, Room, Session as DbSession, Attendance, AttendanceStatus
from app.db import crud
from tools.query_tool import query_tool, safe_sql_query, query_session_stats, query_students, query_attendance


@pytest.fixture
def sqla_session():
    """In-memory SQLite engine with SQLAlchemy Session for isolated testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_student_crud(sqla_session):
    """Test insert and retrieval of students using SQLAlchemy Session."""
    # Single insert
    res = crud.insert_student(sqla_session, usn="1MS21CS001", name="Alice", branch="CSE")
    assert res["usn"] == "1MS21CS001"

    # Get student
    stu = crud.get_student(sqla_session, "1MS21CS001")
    assert stu is not None
    assert stu["name"] == "Alice"
    assert stu["branch"] == "CSE"

    # Bulk insert
    students = [
        {"usn": "1MS21CS002", "name": "Bob", "branch": "CSE"},
        {"usn": "1MS21EC001", "name": "Charlie", "branch": "ECE"},
    ]
    inserted = crud.insert_students_bulk(sqla_session, students)
    assert inserted == 2

    all_students = crud.get_all_students(sqla_session)
    assert len(all_students) == 3

    cse_students = crud.get_students_by_branch(sqla_session, "CSE")
    assert len(cse_students) == 2


def test_room_and_session_crud(sqla_session):
    """Test room and session CRUD with SQLAlchemy Session."""
    crud.insert_room(sqla_session, room_id="LH-101", name="Lecture Hall 101")
    crud.insert_rooms_bulk(sqla_session, [{"room_id": "LH-102", "name": "Hall 102"}])
    assert len(crud.get_all_rooms(sqla_session)) == 2

    crud.insert_session(sqla_session, session_id="SESS-01", date="2026-10-25", subject="Math")
    crud.insert_sessions_bulk(sqla_session, [{"session_id": "SESS-02", "date=":"2026-10-26", "subject": "Science", "date": "2026-10-26"}])
    assert len(crud.get_all_sessions(sqla_session)) == 2
    assert crud.get_session(sqla_session, "SESS-01")["subject"] == "Math"


def test_attendance_crud_and_statuses(sqla_session):
    """Test attendance insert and retrieval across all 4 states."""
    crud.insert_student(sqla_session, usn="1MS21CS001", name="Alice", branch="CSE")
    crud.insert_room(sqla_session, room_id="LH-101", name="Lecture Hall 101")
    crud.insert_session(sqla_session, session_id="SESS-01", date="2026-10-25", subject="Math")

    # PRESENT
    crud.insert_attendance(sqla_session, session_id="SESS-01", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="manual")
    att = crud.get_attendance_record(sqla_session, "SESS-01", "1MS21CS001")
    assert att["status"] == "PRESENT"
    assert att["confidence"] == 1.0

    # Upsert to ABSENT
    crud.insert_attendance(sqla_session, session_id="SESS-01", usn="1MS21CS001", room_id="LH-101", status="ABSENT", source="manual", upsert=True)
    att_updated = crud.get_attendance_record(sqla_session, "SESS-01", "1MS21CS001")
    assert att_updated["status"] == "ABSENT"


def test_attendance_bulk_upsert(sqla_session):
    """Test bulk upsert semantics with ON CONFLICT DO UPDATE."""
    crud.insert_student(sqla_session, usn="1MS21CS001", name="Alice", branch="CSE")
    crud.insert_student(sqla_session, usn="1MS21CS002", name="Bob", branch="CSE")
    crud.insert_room(sqla_session, room_id="LH-101", name="Lecture Hall 101")
    crud.insert_session(sqla_session, session_id="SESS-01", date="2026-10-25", subject="Math")

    records = [
        {"session_id": "SESS-01", "usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "source": "camera", "confidence": 0.95},
        {"session_id": "SESS-01", "usn": "1MS21CS002", "room_id": "LH-101", "status": "PENDING", "source": "camera", "confidence": 0.60},
    ]
    crud.insert_attendance_bulk(sqla_session, records)
    assert len(crud.get_attendance_by_session(sqla_session, "SESS-01")) == 2

    # Bulk upsert updating 1MS21CS002 to UNREVIEWED
    records_upsert = [
        {"session_id": "SESS-01", "usn": "1MS21CS002", "room_id": "LH-101", "status": "UNREVIEWED", "source": "review", "confidence": 0.75},
    ]
    crud.insert_attendance_bulk(sqla_session, records_upsert, upsert=True)
    rec2 = crud.get_attendance_record(sqla_session, "SESS-01", "1MS21CS002")
    assert rec2["status"] == "UNREVIEWED"
    assert rec2["confidence"] == 0.75


def test_atomic_replace_session_attendance(sqla_session):
    """Test that replace_session_attendance is completely atomic."""
    crud.insert_student(sqla_session, usn="1MS21CS001", name="Alice", branch="CSE")
    crud.insert_student(sqla_session, usn="1MS21CS002", name="Bob", branch="CSE")
    crud.insert_room(sqla_session, room_id="LH-101", name="Hall 101")
    crud.insert_session(sqla_session, session_id="SESS-01", date="2026-10-25", subject="Math")

    initial = [
        {"session_id": "SESS-01", "usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "source": "init"},
    ]
    crud.replace_session_attendance(sqla_session, "SESS-01", initial)
    assert len(crud.get_attendance_by_session(sqla_session, "SESS-01")) == 1

    # Atomic replace with 2 records
    new_batch = [
        {"session_id": "SESS-01", "usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT", "source": "new"},
        {"session_id": "SESS-01", "usn": "1MS21CS002", "room_id": "LH-101", "status": "PRESENT", "source": "new"},
    ]
    crud.replace_session_attendance(sqla_session, "SESS-01", new_batch)
    assert len(crud.get_attendance_by_session(sqla_session, "SESS-01")) == 2
    assert crud.get_attendance_record(sqla_session, "SESS-01", "1MS21CS001")["status"] == "ABSENT"


def test_atomic_replace_rollback_on_failure(sqla_session):
    """Test that failure during replacement rolls back and preserves existing records."""
    crud.insert_student(sqla_session, usn="1MS21CS001", name="Alice", branch="CSE")
    crud.insert_room(sqla_session, room_id="LH-101", name="Hall 101")
    crud.insert_session(sqla_session, session_id="SESS-01", date="2026-10-25", subject="Math")

    initial = [
        {"session_id": "SESS-01", "usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "source": "init"},
    ]
    crud.replace_session_attendance(sqla_session, "SESS-01", initial)

    # Attempt replace with an invalid record (violates status check constraint)
    bad_batch = [
        {"usn": "1MS21CS001", "room_id": "LH-101", "status": "INVALID_STATUS", "source": "bad"},
    ]
    with pytest.raises(ValueError):
        crud.replace_session_attendance(sqla_session, "SESS-01", bad_batch)

    # Verify original record was preserved (not deleted)
    recs = crud.get_attendance_by_session(sqla_session, "SESS-01")
    assert len(recs) == 1
    assert recs[0]["status"] == "PRESENT"


def test_reconcile_preserves_pending_and_unreviewed(sqla_session):
    """Test that reconciliation marks missing sheets as PENDING and ambiguous as UNREVIEWED, never ABSENT."""
    roster = [
        {"usn": "1MS21CS001", "room_id": "LH-101"},
        {"usn": "1MS21CS002", "room_id": "LH-101"},
        {"usn": "1MS21CS003", "room_id": "LH-102"},
    ]
    uploaded = [
        {"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "confidence": 0.95},
        {"usn": "1MS21CS002", "room_id": "LH-101", "status": "AMBIGUOUS", "confidence": 0.50},
    ]

    # LH-102 is missing sheet
    reconciled = crud.reconcile_session_roster(
        sqla_session,
        session_id="SESS-01",
        roster=roster,
        uploaded_records=uploaded,
        missing_room_ids={"LH-102"},
    )
    rec_by_usn = {r["usn"]: r for r in reconciled}
    assert rec_by_usn["1MS21CS001"]["status"] == "PRESENT"
    assert rec_by_usn["1MS21CS002"]["status"] == "UNREVIEWED"
    assert rec_by_usn["1MS21CS003"]["status"] == "PENDING"
    # Neither was converted to ABSENT
    assert all(r["status"] != "ABSENT" for r in [rec_by_usn["1MS21CS002"], rec_by_usn["1MS21CS003"]])


def test_query_tool_sqlalchemy_integration(sqla_session):
    """Test query_tool execution with SQLAlchemy Session."""
    crud.insert_student(sqla_session, usn="1MS21CS001", name="Alice", branch="CSE")
    crud.insert_student(sqla_session, usn="1MS21CS002", name="Bob", branch="CSE")
    crud.insert_room(sqla_session, room_id="LH-101", name="Hall 101")
    crud.insert_session(sqla_session, session_id="SESS-01", date="2026-10-25", subject="Math")

    records = [
        {"session_id": "SESS-01", "usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "source": "camera"},
        {"session_id": "SESS-01", "usn": "1MS21CS002", "room_id": "LH-101", "status": "ABSENT", "source": "manual"},
    ]
    crud.insert_attendance_bulk(sqla_session, records)

    # 1. query_students
    res_stu = query_students(branch="CSE", db_target=sqla_session)
    assert res_stu.found is True
    assert res_stu.total_count == 2

    # 2. query_attendance
    res_att = query_attendance(session_id="SESS-01", db_target=sqla_session)
    assert res_att.found is True
    assert res_att.total_count == 2

    # 3. query_session_stats (rate = 1 / (1 + 1) * 100 = 50.0%)
    res_stats = query_session_stats(session_id="SESS-01", db_target=sqla_session)
    assert res_stats.found is True
    assert res_stats.data[0]["confirmed_percentage"] == 50.0

    # 4. safe_sql_query with session
    res_sql = safe_sql_query("SELECT usn, name FROM students WHERE branch = :branch", {"branch": "CSE"}, db_target=sqla_session)
    assert res_sql.found is True
    assert res_sql.total_count == 2

    # 5. reject mutations in safe_sql_query
    with pytest.raises(ValueError, match="Only SELECT or WITH"):
        safe_sql_query("DELETE FROM students", db_target=sqla_session)
