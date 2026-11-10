"""Tests for Student Lookup, Ledger, and T-BAND color classification (Prompt N12)."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Attendance, Session as DbSession, Student, Room, TeacherSubject, User
from app.health import health_band
from app.routers.students import get_student_ledger, lookup_students
from app.schemas.auth import AuthenticatedUser


def test_t_band_all_rows():
    """Verify exact health band mapping from table T-BAND."""
    # 100.0 -> Green
    assert health_band(100.0) == "Green"
    # 85.1 -> Green
    assert health_band(85.1) == "Green"
    # 85.0 -> Yellow (boundary test)
    assert health_band(85.0) == "Yellow"
    # 70.0 -> Yellow (boundary test)
    assert health_band(70.0) == "Yellow"
    # 69.9 -> Red
    assert health_band(69.9) == "Red"
    # 0.0 -> Red
    assert health_band(0.0) == "Red"


@pytest.fixture
def lookup_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Users
    admin = User(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN", created_at=now)
    t1 = User(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY", created_at=now)
    t2 = User(user_id="faculty_t2", email="t2@rollcall.internal", role="FACULTY", created_at=now)
    db.add_all([admin, t1, t2])

    # Mappings: t1 teaches DBMS, t2 teaches MATH
    ts1 = TeacherSubject(user_id="faculty_t1", subject_code="DBMS")
    ts2 = TeacherSubject(user_id="faculty_t2", subject_code="MATH")
    db.add_all([ts1, ts2])

    room = Room(room_id="LH-101", name="Hall 101")
    db.add(room)

    # Students
    s1 = Student(usn="1MS21CS001", name="Alice Wonderland", branch="CSE")
    s2 = Student(usn="1MS21CS002", name="Bob Builder", branch="CSE")
    s3 = Student(usn="1MS21EC001", name="Charlie Brown", branch="ECE")
    db.add_all([s1, s2, s3])

    # Sessions in date order
    sess1 = DbSession(session_id="SESS-01", date="2026-11-01", subject="DBMS", teacher_id="faculty_t1", subject_code="DBMS", created_at=now)
    sess2 = DbSession(session_id="SESS-02", date="2026-11-03", subject="MATH", teacher_id="faculty_t2", subject_code="MATH", created_at=now)
    sess3 = DbSession(session_id="SESS-03", date="2026-11-05", subject="DBMS", teacher_id="faculty_t1", subject_code="DBMS", created_at=now)
    db.add_all([sess1, sess2, sess3])

    # Attendance for Alice:
    # 2026-11-01 (DBMS): PRESENT
    # 2026-11-03 (MATH): ABSENT
    # 2026-11-05 (DBMS): PRESENT
    db.add(Attendance(attendance_id="a1", session_id="SESS-01", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="CSV", recorded_at=now))
    db.add(Attendance(attendance_id="a2", session_id="SESS-02", usn="1MS21CS001", room_id="LH-101", status="ABSENT", source="CSV", recorded_at=now))
    db.add(Attendance(attendance_id="a3", session_id="SESS-03", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="CSV", recorded_at=now))

    db.commit()

    try:
        yield db
    finally:
        db.close()


def test_lookup_by_usn_and_name(lookup_db: Session):
    """Search by USN part and name part."""
    admin = AuthenticatedUser(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN")

    # Search by USN part
    res1 = lookup_students(q="CS001", current_user=admin, db=lookup_db)
    assert len(res1) == 1
    assert res1[0]["usn"] == "1MS21CS001"

    # Search by name part
    res2 = lookup_students(q="Builder", current_user=admin, db=lookup_db)
    assert len(res2) == 1
    assert res2[0]["usn"] == "1MS21CS002"

    # Unknown search gives empty list
    res3 = lookup_students(q="NONEXISTENT999", current_user=admin, db=lookup_db)
    assert len(res3) == 0


def test_lookup_sql_injection_defense(lookup_db: Session):
    """SQL injection string `' OR 1=1--` returns nothing and changes nothing."""
    admin = AuthenticatedUser(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN")
    res = lookup_students(q="' OR 1=1--", current_user=admin, db=lookup_db)
    assert len(res) == 0


def test_ledger_admin_sees_all_chronological(lookup_db: Session):
    """Admin ledger sees all subjects, ordered by date."""
    admin = AuthenticatedUser(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN")
    ledger = get_student_ledger(usn="1MS21CS001", current_user=admin, db=lookup_db)

    assert ledger["usn"] == "1MS21CS001"
    assert ledger["total_sessions"] == 3
    assert ledger["attended_sessions"] == 2
    assert ledger["percent"] == 66.7
    assert ledger["band"] == "Red"

    # Chronological check
    assert ledger["sessions"][0]["date"] == "2026-11-01"
    assert ledger["sessions"][1]["date"] == "2026-11-03"
    assert ledger["sessions"][2]["date"] == "2026-11-05"


def test_ledger_teacher_scoped_to_assigned_subject(lookup_db: Session):
    """Teacher t1 (DBMS only) sees only DBMS sessions in student ledger."""
    t1 = AuthenticatedUser(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY")
    ledger = get_student_ledger(usn="1MS21CS001", current_user=t1, db=lookup_db)

    # t1 only sees 2 DBMS sessions (both PRESENT), MATH session is omitted
    assert ledger["total_sessions"] == 2
    assert ledger["attended_sessions"] == 2
    assert ledger["percent"] == 100.0
    assert ledger["band"] == "Green"

    subjects = [s["subject"] for s in ledger["sessions"]]
    assert "DBMS" in subjects
    assert "MATH" not in subjects

