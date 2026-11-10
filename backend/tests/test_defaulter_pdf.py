"""Tests for Notice Board Defaulter PDF export (Prompt N11)."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth import Role, require_roles
from app.db.base import Base
from app.db.models import Attendance, AuditLog, Session as DbSession, Student, Room, TeacherSubject, User
from app.routers.admin import export_defaulters_pdf
from app.schemas.auth import AuthenticatedUser
from tools.defaulter_pdf import generate_defaulter_pdf, _sanitize_csv_formula_injection


def test_sanitize_formula_injection():
    """Verify formula injection characters are escaped."""
    assert _sanitize_csv_formula_injection("=1+1") == "'=1+1"
    assert _sanitize_csv_formula_injection("+cmd|' /C calc'!A0") == "'+cmd|' /C calc'!A0"
    assert _sanitize_csv_formula_injection("-5") == "'-5"
    assert _sanitize_csv_formula_injection("@SUM(A1:A10)") == "'@SUM(A1:A10)"
    assert _sanitize_csv_formula_injection("Normal Name") == "Normal Name"


@pytest.fixture
def pdf_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    admin = User(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN", created_at=now)
    t1 = User(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY", created_at=now)
    db.add_all([admin, t1])

    r1 = Room(room_id="LH-101", name="Hall 101")
    db.add(r1)

    s1 = Student(usn="1MS21CS001", name="=1+1 Evil Formula", branch="CSE")
    db.add(s1)

    sess = DbSession(session_id="SESS-1", date="2026-11-10", subject="DBMS", teacher_id="faculty_t1", subject_code="DBMS", created_at=now)
    db.add(sess)

    # 1 absent out of 1 conducted -> 0%
    db.add(Attendance(attendance_id="a1", session_id="SESS-1", usn="1MS21CS001", room_id="LH-101", status="ABSENT", source="CSV", recorded_at=now))
    db.commit()

    try:
        yield db
    finally:
        db.close()


def test_defaulter_pdf_generation(pdf_db: Session):
    """Admin exports PDF: valid PDF generated, row count matches, audit row written."""
    admin = AuthenticatedUser(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN")
    response = export_defaulters_pdf(threshold=75.0, current_user=admin, db=pdf_db)

    # Valid PDF bytes
    assert response.body.startswith(b"%PDF")
    assert response.headers["Content-Type"] == "application/pdf"

    # Audit log entry written
    audit = pdf_db.execute(select(AuditLog).where(AuditLog.action == "DEFAULTER_EXPORT")).scalar_one()
    assert audit.actor_id == "admin_root"
    assert "count=1" in audit.new_value


def test_defaulter_pdf_teacher_forbidden():
    """Teacher receives 403 on export_defaulters_pdf."""
    teacher = AuthenticatedUser(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY")
    checker = require_roles(Role.ADMIN)

    with pytest.raises(HTTPException) as exc_info:
        checker(teacher)
    assert exc_info.value.status_code == 403

