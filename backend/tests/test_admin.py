"""Tests for Admin Overview, Faculty Uploads, and Audit Log endpoints (Prompt N8)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Attendance, AuditLog, Session as DbSession, Student, Room, User
from app.routers.admin import get_admin_overview, get_faculty_uploads, get_audit_log
from app.schemas.auth import AuthenticatedUser


@pytest.fixture
def admin_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    now = datetime.now(timezone.utc)
    ts_now = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_2d = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Users: 1 admin, 2 faculty
    admin = User(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN", created_at=ts_now)
    t1 = User(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY", created_at=ts_now)
    t2 = User(user_id="faculty_t2", email="t2@rollcall.internal", role="FACULTY", created_at=ts_now)
    db.add_all([admin, t1, t2])

    # Room
    r1 = Room(room_id="LH-101", name="Hall 101")
    r2 = Room(room_id="LH-102", name="Hall 102")
    db.add_all([r1, r2])

    # Students (CSE and ECE)
    s1 = Student(usn="1MS21CS001", name="Alice", branch="CSE")
    s2 = Student(usn="1MS21CS002", name="Bob", branch="CSE")
    s3 = Student(usn="1MS21EC001", name="Charlie", branch="ECE")
    db.add_all([s1, s2, s3])

    # Sessions: t1 has 1 session 2 days ago; t2 has 0 sessions
    sess1 = DbSession(session_id="SESS-T1-1", date="2026-11-08", subject="DBMS", teacher_id="faculty_t1", subject_code="DBMS", created_at=ts_2d)
    db.add(sess1)

    # Attendance:
    # CSE: 1 present, 1 absent
    # ECE: 1 present
    # Total: 2 present, 1 absent -> 3 records, 66.7%
    a1 = Attendance(attendance_id="a1", session_id="SESS-T1-1", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="CSV", recorded_at=ts_2d)
    a2 = Attendance(attendance_id="a2", session_id="SESS-T1-1", usn="1MS21CS002", room_id="LH-101", status="ABSENT", source="CSV", recorded_at=ts_2d)
    a3 = Attendance(attendance_id="a3", session_id="SESS-T1-1", usn="1MS21EC001", room_id="LH-102", status="PRESENT", source="CSV", recorded_at=ts_2d)
    db.add_all([a1, a2, a3])

    # Audit log entries
    log1 = AuditLog(log_id=1, actor_id="admin_root", action="SESSION_CREATE", entity_type="session", entity_id="SESS-T1-1", timestamp="2026-11-08T10:00:00Z")
    log2 = AuditLog(log_id=2, actor_id="faculty_t1", action="ATTENDANCE_EDIT", entity_type="attendance", entity_id="SESS-T1-1:1MS21CS001", old_value="ABSENT", new_value="PRESENT", timestamp="2026-11-08T11:00:00Z")
    log3 = AuditLog(log_id=3, actor_id="admin_root", action="ADMIN_OVERRIDE_EVENT", entity_type="attendance", entity_id="SESS-T1-1:1MS21CS002", old_value="PRESENT", new_value="ABSENT", reason="Override", timestamp="2026-11-09T12:00:00Z")
    db.add_all([log1, log2, log3])

    db.commit()

    try:
        yield db
    finally:
        db.close()


def test_admin_overview_numbers(admin_db: Session):
    """Test overview numbers equal hand count: 3 total, 2 present, 1 absent, 66.7%."""
    admin = AuthenticatedUser(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN")
    res = get_admin_overview(current_user=admin, db=admin_db)

    assert res["total_records"] == 3
    assert res["present"] == 2
    assert res["absent"] == 1
    assert res["percentage"] == 66.7

    # Check branch wise
    b_map = {b["branch"]: b for b in res["branch_wise"]}
    assert "CSE" in b_map
    assert b_map["CSE"]["present"] == 1
    assert b_map["CSE"]["absent"] == 1
    assert b_map["CSE"]["percentage"] == 50.0

    assert "ECE" in b_map
    assert b_map["ECE"]["present"] == 1
    assert b_map["ECE"]["absent"] == 0
    assert b_map["ECE"]["percentage"] == 100.0


def test_admin_faculty_uploads(admin_db: Session):
    """Test faculty uploads: t1 has 1 session in last 7 days, t2 has 0."""
    admin = AuthenticatedUser(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN")
    res = get_faculty_uploads(current_user=admin, db=admin_db)

    assert len(res) == 2
    f_map = {f["teacher_id"]: f for f in res}

    assert "faculty_t1" in f_map
    assert f_map["faculty_t1"]["sessions_last_7_days"] == 1
    assert f_map["faculty_t1"]["sessions_this_semester"] == 1
    assert f_map["faculty_t1"]["last_upload_utc"] is not None

    # Teacher with 0 sessions is listed and shows 0
    assert "faculty_t2" in f_map
    assert f_map["faculty_t2"]["sessions_last_7_days"] == 0
    assert f_map["faculty_t2"]["sessions_this_semester"] == 0
    assert f_map["faculty_t2"]["last_upload_utc"] is None


def test_admin_audit_log_filters_and_paging(admin_db: Session):
    """Test audit log is read-only, ordered newest first, and filterable."""
    admin = AuthenticatedUser(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN")

    # All logs (page 1)
    res_all = get_audit_log(page=1, page_size=50, current_user=admin, db=admin_db)
    assert res_all["total"] == 3
    assert len(res_all["items"]) == 3
    # Newest first
    assert res_all["items"][0]["log_id"] == 3
    assert res_all["items"][1]["log_id"] == 2
    assert res_all["items"][2]["log_id"] == 1

    # Filter by event
    res_filter = get_audit_log(event="ADMIN_OVERRIDE_EVENT", page=1, page_size=50, current_user=admin, db=admin_db)
    assert res_filter["total"] == 1
    assert res_filter["items"][0]["event"] == "ADMIN_OVERRIDE_EVENT"

    # Filter by actor
    res_actor = get_audit_log(actor="faculty_t1", page=1, page_size=50, current_user=admin, db=admin_db)
    assert res_actor["total"] == 1
    assert res_actor["items"][0]["actor_id"] == "faculty_t1"


def test_teacher_forbidden_on_admin_routes(admin_db: Session):
    """Teacher receives 403 on admin routes."""
    from app.auth import require_roles, Role
    teacher = AuthenticatedUser(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY")
    checker = require_roles(Role.ADMIN)

    with pytest.raises(HTTPException) as exc_info:
        checker(teacher)
    assert exc_info.value.status_code == 403

