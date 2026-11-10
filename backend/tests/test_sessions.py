"""Tests for Session endpoints and lock metadata (Prompt N6b)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Attendance, Session as DbSession, Student, Room, User
from app.routers.sessions import get_session_attendance, list_sessions
from app.schemas.auth import AuthenticatedUser


@pytest.fixture
def session_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    now = datetime.now(timezone.utc)
    ts_now = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_2h = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_25h = (now - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Users
    admin = User(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN", created_at=ts_now)
    t1 = User(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY", created_at=ts_now)
    t2 = User(user_id="faculty_t2", email="t2@rollcall.internal", role="FACULTY", created_at=ts_now)
    legacy = User(user_id="legacy", email="legacy@rollcall.internal", role="ADMIN", is_active=0, created_at=ts_now)
    db.add_all([admin, t1, t2, legacy])

    # Room
    room = Room(room_id="LH-101", name="Lecture Hall 1")
    db.add(room)

    # Student
    student = Student(usn="1MS21CS001", name="Alice Smith", branch="CSE")
    db.add(student)

    # Sessions
    s_t1_new = DbSession(session_id="SESS-T1-NEW", date="2026-11-10", subject="CS101", teacher_id="faculty_t1", subject_code="CS101", created_at=ts_2h)
    s_t1_old = DbSession(session_id="SESS-T1-OLD", date="2026-11-09", subject="CS101", teacher_id="faculty_t1", subject_code="CS101", created_at=ts_25h)
    s_t2 = DbSession(session_id="SESS-T2-NEW", date="2026-11-10", subject="EC101", teacher_id="faculty_t2", subject_code="EC101", created_at=ts_2h)
    s_legacy = DbSession(session_id="SESS-LEGACY", date="2026-10-01", subject="ME101", teacher_id="legacy", subject_code="ME101", created_at=ts_25h)
    db.add_all([s_t1_new, s_t1_old, s_t2, s_legacy])

    # Attendance
    att1 = Attendance(attendance_id="a1", session_id="SESS-T1-NEW", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="CSV", recorded_at=ts_2h)
    att2 = Attendance(attendance_id="a2", session_id="SESS-T1-OLD", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="CSV", recorded_at=ts_25h)
    att3 = Attendance(attendance_id="a3", session_id="SESS-T2-NEW", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="CSV", recorded_at=ts_2h)
    att4 = Attendance(attendance_id="a4", session_id="SESS-LEGACY", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="CSV", recorded_at=ts_25h)
    db.add_all([att1, att2, att3, att4])

    db.commit()

    try:
        yield db
    finally:
        db.close()


def test_teacher_sees_only_own_sessions(session_db: Session):
    """Test 1: Teacher sees only own sessions."""
    t1_user = AuthenticatedUser(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY")
    res = list_sessions(limit=50, offset=0, current_user=t1_user, db=session_db)
    
    session_ids = [s["session_id"] for s in res["items"]]
    assert "SESS-T1-NEW" in session_ids
    assert "SESS-T1-OLD" in session_ids
    assert "SESS-T2-NEW" not in session_ids
    assert "SESS-LEGACY" not in session_ids


def test_lock_attributes_for_teacher_and_admin(session_db: Session):
    """Test 2: 25h old session shows locked true for teacher and editable true for admin."""
    t1_user = AuthenticatedUser(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY")
    admin_user = AuthenticatedUser(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN")

    # Teacher view of 25h old session
    t1_view = get_session_attendance("SESS-T1-OLD", current_user=t1_user, db=session_db)
    assert t1_view["session"]["locked"] is True
    assert t1_view["session"]["editable"] is False
    assert len(t1_view["records"]) == 1
    assert t1_view["records"][0]["usn"] == "1MS21CS001"

    # Admin view of 25h old session
    admin_view = get_session_attendance("SESS-T1-OLD", current_user=admin_user, db=session_db)
    assert admin_view["session"]["locked"] is False
    assert admin_view["session"]["editable"] is True


def test_other_teacher_session_forbidden(session_db: Session):
    """Test 3: Other teacher's session gives 403."""
    t1_user = AuthenticatedUser(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY")
    with pytest.raises(HTTPException) as exc_info:
        get_session_attendance("SESS-T2-NEW", current_user=t1_user, db=session_db)
    
    assert exc_info.value.status_code == 403


def test_legacy_session_locked_for_teacher(session_db: Session):
    """Test 4: Legacy session locked for teacher (or forbidden if not mapped)."""
    t1_user = AuthenticatedUser(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY")
    with pytest.raises(HTTPException) as exc_info:
        get_session_attendance("SESS-LEGACY", current_user=t1_user, db=session_db)
    
    assert exc_info.value.status_code == 403

