"""Tests for the Safe Attendance Edit service and T-EDIT verification matrix."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Attendance, Session as DbSession, Student, Room, User, AuditLog
from app.services.attendance_edit import update_attendance


@pytest.fixture
def test_db():
    """Create an isolated in-memory SQLite database with schema and immutability triggers."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    
    # Add audit log triggers for immutability
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS prevent_audit_log_update
            BEFORE UPDATE ON audit_log
            BEGIN
                SELECT RAISE(ABORT, 'audit_log is append-only: UPDATE is strictly prohibited');
            END;
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS prevent_audit_log_delete
            BEFORE DELETE ON audit_log
            BEGIN
                SELECT RAISE(ABORT, 'audit_log is append-only: DELETE is strictly prohibited');
            END;
        """))
    
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    # Seed baseline fixtures
    now = datetime.now(timezone.utc)
    ts_now = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Users
    admin = User(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN", created_at=ts_now)
    t1 = User(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY", created_at=ts_now)
    t2 = User(user_id="faculty_t2", email="t2@rollcall.internal", role="FACULTY", created_at=ts_now)
    legacy_user = User(user_id="legacy", email="legacy@rollcall.internal", role="ADMIN", is_active=0, created_at=ts_now)
    db.add_all([admin, t1, t2, legacy_user])
    
    # Room
    room = Room(room_id="LH-101", name="Lecture Hall 101")
    db.add(room)
    
    # Students
    s1 = Student(usn="1MS21CS001", name="Alice Smith", branch="CSE")
    s2 = Student(usn="1MS21CS002", name="Bob Jones", branch="CSE")
    db.add_all([s1, s2])
    
    # Sessions:
    # 1. t1 session, 2 hours old
    ts_2h = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sess_t1_2h = DbSession(session_id="SESS-T1-2H", date="2026-11-10", subject="Math", teacher_id="faculty_t1", subject_code="MATH-1", created_at=ts_2h)
    
    # 2. t1 session, 25 hours old
    ts_25h = (now - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sess_t1_25h = DbSession(session_id="SESS-T1-25H", date="2026-11-09", subject="Math", teacher_id="faculty_t1", subject_code="MATH-1", created_at=ts_25h)
    
    # 3. t2 session, 2 hours old
    sess_t2_2h = DbSession(session_id="SESS-T2-2H", date="2026-11-10", subject="Physics", teacher_id="faculty_t2", subject_code="PHY-1", created_at=ts_2h)
    
    # 4. legacy session (teacher_id='legacy', 30 days old)
    ts_30d = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sess_legacy = DbSession(session_id="SESS-LEGACY", date="2026-10-10", subject="History", teacher_id="legacy", subject_code="HIST-1", created_at=ts_30d)
    
    db.add_all([sess_t1_2h, sess_t1_25h, sess_t2_2h, sess_legacy])
    
    # Attendance marks
    att1 = Attendance(attendance_id="att-1", session_id="SESS-T1-2H", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="CSV", recorded_at=ts_2h)
    att2 = Attendance(attendance_id="att-2", session_id="SESS-T1-25H", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="CSV", recorded_at=ts_25h)
    att3 = Attendance(attendance_id="att-3", session_id="SESS-T2-2H", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="CSV", recorded_at=ts_2h)
    att4 = Attendance(attendance_id="att-4", session_id="SESS-LEGACY", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="CSV", recorded_at=ts_30d)
    db.add_all([att1, att2, att3, att4])
    
    db.commit()
    
    try:
        yield db
    finally:
        db.close()


def test_t_edit_teacher_own_session_2h(test_db: Session):
    """Row 1: Teacher edits own session, 2 hours old -> Done. 1 audit row ATTENDANCE_EDIT."""
    user = {"user_id": "faculty_t1", "role": "FACULTY"}
    res = update_attendance(user, "SESS-T1-2H", "1MS21CS001", "ABSENT", db=test_db)
    
    assert res["success"] is True
    assert res["old_status"] == "PRESENT"
    assert res["new_status"] == "ABSENT"
    assert res["event"] == "ATTENDANCE_EDIT"
    
    # Verify in DB
    att = test_db.execute(select(Attendance).where(Attendance.session_id == "SESS-T1-2H", Attendance.usn == "1MS21CS001")).scalar_one()
    assert att.status == "ABSENT"
    
    # Verify audit row
    audit = test_db.execute(select(AuditLog).where(AuditLog.session_id == "SESS-T1-2H")).scalar_one()
    assert audit.actor_id == "faculty_t1"
    assert audit.action == "ATTENDANCE_EDIT"
    assert audit.old_value == "PRESENT"
    assert audit.new_value == "ABSENT"


def test_t_edit_teacher_own_session_25h_locked(test_db: Session):
    """Row 2: Teacher edits own session, 25 hours old -> 403 LOCKED. Status unchanged. No edit audit row."""
    user = {"user_id": "faculty_t1", "role": "FACULTY"}
    with pytest.raises(HTTPException) as exc_info:
        update_attendance(user, "SESS-T1-25H", "1MS21CS001", "ABSENT", db=test_db)
    
    assert exc_info.value.status_code == 403
    assert "locked" in exc_info.value.detail.lower()
    
    # Status unchanged
    att = test_db.execute(select(Attendance).where(Attendance.session_id == "SESS-T1-25H", Attendance.usn == "1MS21CS001")).scalar_one()
    assert att.status == "PRESENT"
    
    # No edit audit row
    audits = test_db.execute(select(AuditLog).where(AuditLog.session_id == "SESS-T1-25H")).scalars().all()
    assert len(audits) == 0


def test_t_edit_teacher_another_teacher_session(test_db: Session):
    """Row 3: Teacher edits another teacher's session -> 403. Nothing changed."""
    user = {"user_id": "faculty_t1", "role": "FACULTY"}
    with pytest.raises(HTTPException) as exc_info:
        update_attendance(user, "SESS-T2-2H", "1MS21CS001", "ABSENT", db=test_db)
    
    assert exc_info.value.status_code == 403
    assert "not assigned" in exc_info.value.detail.lower()
    
    att = test_db.execute(select(Attendance).where(Attendance.session_id == "SESS-T2-2H", Attendance.usn == "1MS21CS001")).scalar_one()
    assert att.status == "PRESENT"


def test_t_edit_admin_session_25h_with_reason(test_db: Session):
    """Row 4: Admin edits session 25 hours old with reason -> Done. Audit row ADMIN_OVERRIDE_EVENT with admin id, reason, time."""
    admin = {"user_id": "admin_root", "role": "ADMIN"}
    res = update_attendance(admin, "SESS-T1-25H", "1MS21CS001", "ABSENT", reason="Student was representing college in sports", db=test_db)
    
    assert res["success"] is True
    assert res["event"] == "ADMIN_OVERRIDE_EVENT"
    
    # Verify DB
    att = test_db.execute(select(Attendance).where(Attendance.session_id == "SESS-T1-25H", Attendance.usn == "1MS21CS001")).scalar_one()
    assert att.status == "ABSENT"
    
    audit = test_db.execute(select(AuditLog).where(AuditLog.session_id == "SESS-T1-25H")).scalar_one()
    assert audit.actor_id == "admin_root"
    assert audit.action == "ADMIN_OVERRIDE_EVENT"
    assert audit.reason == "Student was representing college in sports"


def test_t_edit_admin_session_25h_without_reason(test_db: Session):
    """Row 5: Admin edits session 25 hours old without reason -> 422. Nothing changed."""
    admin = {"user_id": "admin_root", "role": "ADMIN"}
    with pytest.raises(HTTPException) as exc_info:
        update_attendance(admin, "SESS-T1-25H", "1MS21CS001", "ABSENT", reason="", db=test_db)
    
    assert exc_info.value.status_code == 422
    assert "reason" in exc_info.value.detail.lower()
    
    att = test_db.execute(select(Attendance).where(Attendance.session_id == "SESS-T1-25H", Attendance.usn == "1MS21CS001")).scalar_one()
    assert att.status == "PRESENT"


def test_t_edit_admin_session_2h(test_db: Session):
    """Row 6: Admin edits session 2 hours old -> Done. Audit row ATTENDANCE_EDIT (not override)."""
    admin = {"user_id": "admin_root", "role": "ADMIN"}
    res = update_attendance(admin, "SESS-T1-2H", "1MS21CS001", "ABSENT", db=test_db)
    
    assert res["success"] is True
    assert res["event"] == "ATTENDANCE_EDIT"
    
    audit = test_db.execute(select(AuditLog).where(AuditLog.session_id == "SESS-T1-2H")).scalar_one()
    assert audit.action == "ATTENDANCE_EDIT"


def test_t_edit_teacher_legacy_session(test_db: Session):
    """Row 7: Teacher edits a legacy session -> 403. Nothing changed."""
    user = {"user_id": "faculty_t1", "role": "FACULTY"}
    with pytest.raises(HTTPException) as exc_info:
        update_attendance(user, "SESS-LEGACY", "1MS21CS001", "ABSENT", db=test_db)
    
    assert exc_info.value.status_code == 403
    assert "legacy" in exc_info.value.detail.lower()


def test_t_edit_usn_not_in_session(test_db: Session):
    """Row 8: USN not in that session -> 404. Nothing changed."""
    user = {"user_id": "faculty_t1", "role": "FACULTY"}
    with pytest.raises(HTTPException) as exc_info:
        update_attendance(user, "SESS-T1-2H", "1MS21CS999", "ABSENT", db=test_db)
    
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


def test_t_edit_status_invalid_maybe(test_db: Session):
    """Row 9: Status 'Maybe' -> 422. Nothing changed."""
    user = {"user_id": "faculty_t1", "role": "FACULTY"}
    with pytest.raises(HTTPException) as exc_info:
        update_attendance(user, "SESS-T1-2H", "1MS21CS001", "Maybe", db=test_db)
    
    assert exc_info.value.status_code == 422
    assert "invalid" in exc_info.value.detail.lower()


def test_t_edit_audit_write_failure_rollback(test_db: Session, monkeypatch):
    """Row 10: Audit write forced to fail -> Whole change rolled back. Status unchanged."""
    user = {"user_id": "faculty_t1", "role": "FACULTY"}
    
    # Intercept AuditLog initialization or db.add to simulate failure during audit row creation
    original_add = test_db.add
    def failing_add(instance):
        if isinstance(instance, AuditLog):
            raise RuntimeError("Forced audit log write failure for rollback test")
        original_add(instance)
    
    monkeypatch.setattr(test_db, "add", failing_add)
    
    with pytest.raises(RuntimeError) as exc_info:
        update_attendance(user, "SESS-T1-2H", "1MS21CS001", "ABSENT", db=test_db)
    
    assert "Forced audit log write failure" in str(exc_info.value)
    
    # Check that status was rolled back and remained PRESENT
    att = test_db.execute(select(Attendance).where(Attendance.session_id == "SESS-T1-2H", Attendance.usn == "1MS21CS001")).scalar_one()
    assert att.status == "PRESENT"


def test_t_edit_direct_sql_tamper_rejected_by_trigger(test_db: Session):
    """Row 11: Direct SQL UPDATE or DELETE on an audit row -> Rejected by the database trigger."""
    admin = {"user_id": "admin_root", "role": "ADMIN"}
    res = update_attendance(admin, "SESS-T1-2H", "1MS21CS001", "ABSENT", db=test_db)
    log_id = res["audit_log_id"]
    
    # Try direct UPDATE
    with pytest.raises(Exception) as exc_u:
        test_db.execute(text(f"UPDATE audit_log SET new_value = 'TAMPERED' WHERE log_id = {log_id}"))
        test_db.commit()
    assert "strictly prohibited" in str(exc_u.value).lower()
    test_db.rollback()
    
    # Try direct DELETE
    with pytest.raises(Exception) as exc_d:
        test_db.execute(text(f"DELETE FROM audit_log WHERE log_id = {log_id}"))
        test_db.commit()
    assert "strictly prohibited" in str(exc_d.value).lower()
    test_db.rollback()
