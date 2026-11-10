"""Tests for Calendar month heatmap and day detail endpoints (Prompt N13)."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Attendance, Session as DbSession, Student, Room, TeacherSubject, User
from app.routers.calendar import get_calendar_day, get_calendar_month
from app.schemas.auth import AuthenticatedUser


@pytest.fixture
def cal_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    admin = User(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN", created_at=now)
    t1 = User(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY", created_at=now)
    db.add_all([admin, t1])

    # t1 teaches DBMS
    ts1 = TeacherSubject(user_id="faculty_t1", subject_code="DBMS")
    db.add(ts1)

    r1 = Room(room_id="LH-101", name="Hall 101")
    db.add(r1)

    # 10 students
    students = [Student(usn=f"1MS21CS{i:03d}", name=f"Student {i}", branch="CSE") for i in range(1, 11)]
    db.add_all(students)

    # 3 sessions on 3 different days in November 2026:
    # Day 1: 2026-11-01 -> 10 present out of 10 -> 100% -> Green
    s1 = DbSession(session_id="SESS-CAL-1", date="2026-11-01", subject="DBMS", teacher_id="faculty_t1", subject_code="DBMS", created_at=now)
    # Day 2: 2026-11-02 -> 7 present, 3 absent -> 70% -> Yellow
    s2 = DbSession(session_id="SESS-CAL-2", date="2026-11-02", subject="DBMS", teacher_id="faculty_t1", subject_code="DBMS", created_at=now)
    # Day 3: 2026-11-03 -> 5 present, 5 absent -> 50% -> Red
    s3 = DbSession(session_id="SESS-CAL-3", date="2026-11-03", subject="DBMS", teacher_id="faculty_t1", subject_code="DBMS", created_at=now)
    db.add_all([s1, s2, s3])

    # Attendance
    for i in range(1, 11):
        db.add(Attendance(attendance_id=f"a1_{i}", session_id="SESS-CAL-1", usn=f"1MS21CS{i:03d}", room_id="LH-101", status="PRESENT", source="CSV", recorded_at=now))
        
        st2 = "PRESENT" if i <= 7 else "ABSENT"
        db.add(Attendance(attendance_id=f"a2_{i}", session_id="SESS-CAL-2", usn=f"1MS21CS{i:03d}", room_id="LH-101", status=st2, source="CSV", recorded_at=now))
        
        st3 = "PRESENT" if i <= 5 else "ABSENT"
        db.add(Attendance(attendance_id=f"a3_{i}", session_id="SESS-CAL-3", usn=f"1MS21CS{i:03d}", room_id="LH-101", status=st3, source="CSV", recorded_at=now))

    db.commit()

    try:
        yield db
    finally:
        db.close()


def test_calendar_three_sessions_correct_bands(cal_db: Session):
    """3 sessions on 3 days give 3 entries with the right bands (Green, Yellow, Red)."""
    admin = AuthenticatedUser(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN")
    days = get_calendar_month(month="2026-11", current_user=admin, db=cal_db)

    assert len(days) == 3
    d_map = {d["date"]: d for d in days}

    assert d_map["2026-11-01"]["percent"] == 100.0
    assert d_map["2026-11-01"]["band"] == "Green"

    assert d_map["2026-11-02"]["percent"] == 70.0
    assert d_map["2026-11-02"]["band"] == "Yellow"

    assert d_map["2026-11-03"]["percent"] == 50.0
    assert d_map["2026-11-03"]["band"] == "Red"


def test_calendar_empty_month(cal_db: Session):
    """Empty month gives empty list."""
    admin = AuthenticatedUser(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN")
    days = get_calendar_month(month="2026-12", current_user=admin, db=cal_db)
    assert days == []


def test_calendar_bad_month_format(cal_db: Session):
    """Bad month format raises 422."""
    admin = AuthenticatedUser(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN")
    with pytest.raises(HTTPException) as exc_info:
        get_calendar_month(month="INVALID-DATE", current_user=admin, db=cal_db)
    assert exc_info.value.status_code == 422


def test_calendar_teacher_other_subject_forbidden(cal_db: Session):
    """Teacher querying unassigned subject gives 403."""
    t1 = AuthenticatedUser(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY")
    with pytest.raises(HTTPException) as exc_info:
        get_calendar_month(month="2026-11", subject="PHYSICS", current_user=t1, db=cal_db)
    assert exc_info.value.status_code == 403


def test_calendar_day_detail(cal_db: Session):
    """Day detail returns sessions with computed lock flags."""
    admin = AuthenticatedUser(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN")
    sessions = get_calendar_day(date="2026-11-01", current_user=admin, db=cal_db)

    assert len(sessions) == 1
    s = sessions[0]
    assert s["session_id"] == "SESS-CAL-1"
    assert s["subject"] == "DBMS"
    assert s["editable"] is True
    assert s["locked"] is False

