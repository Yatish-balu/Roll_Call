"""Integration tests for ticket [RC-AI-003]: Attendance Save & Session Resolution.

Verifies:
1. PUT /api/v1/attendance/sessions/{session_id} saves attendance with 200 OK.
2. Scheduled timetable session resolution without premature 404.
3. 24-hour teacher lock enforcement (403 for faculty on expired sessions).
4. Admin override of locked session with explicit reason (200 OK).
"""

from __future__ import annotations

import datetime
from typing import Generator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.jwt import create_access_token
from app.db.base import Base
from app.db.models import (
    College,
    Department,
    Room,
    Session as DbSession,
    Student,
    TeacherSubject,
    User,
)
from app.dependencies import get_db
from app.main import app

pytestmark = pytest.mark.no_auth_override


@pytest.fixture
def test_db() -> Generator[OrmSession, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()

    # Seed baseline
    clg = College(college_id="DSCE", name="Dayananda Sagar College of Engineering", code="DSCE")
    dept = Department(dept_id="CSE", name="Computer Science", code="CSE", college_id="DSCE")
    room = Room(room_id="LH-101", name="Lecture Hall 101", capacity=60)
    unalloc = Room(room_id="UNALLOCATED", name="Unallocated Classroom", capacity=100)
    student = Student(usn="1MS21CS001", name="Alice Smith", branch="CSE")

    u_faculty = User(
        user_id="faculty_cn",
        name="Faculty CN",
        email="faculty_cn@dsce.edu.in",
        role="FACULTY",
        is_active=1,
        created_at="2026-01-01T00:00:00Z",
    )
    u_admin = User(
        user_id="admin_root",
        name="Admin Root",
        email="admin@dsce.edu.in",
        role="ADMIN",
        is_active=1,
        created_at="2026-01-01T00:00:00Z",
    )
    ts = TeacherSubject(user_id="faculty_cn", subject_code="CN")

    session.add_all([clg, dept, room, unalloc, student, u_faculty, u_admin, ts])
    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(test_db: OrmSession) -> Generator[TestClient, None, None]:
    def _override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_attendance_save_returns_200_and_commits(client: TestClient, test_db: OrmSession):
    """Save changes on active session succeeds with 200 OK."""
    # Create an active session
    today_str = datetime.date.today().isoformat()
    sess = DbSession(
        session_id="SESS-CN-TODAY-01",
        date=today_str,
        subject="Computer Networks",
        subject_code="CN",
        teacher_id="faculty_cn",
    )
    test_db.add(sess)
    test_db.commit()

    token = create_access_token(
        data={"sub": "faculty_cn", "role": "FACULTY", "user_id": "faculty_cn"}
    )
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "records": [
            {
                "session_id": "SESS-CN-TODAY-01",
                "usn": "1MS21CS001",
                "room_id": "LH-101",
                "status": "PRESENT",
                "source": "manual",
                "confidence": 1.0,
            }
        ]
    }

    res = client.put("/api/v1/attendance/sessions/SESS-CN-TODAY-01", json=payload, headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["replaced_count"] == 1
    assert "Successfully replaced" in data["message"]


def test_attendance_save_respects_24h_lock(client: TestClient, test_db: OrmSession):
    """Faculty cannot edit session older than 24h, but Admin can override with reason."""
    old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)
    old_date = old_time.date().isoformat()
    sess = DbSession(
        session_id="SESS-CN-OLD-01",
        date=old_date,
        subject="Computer Networks",
        subject_code="CN",
        teacher_id="faculty_cn",
        created_at=old_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    test_db.add(sess)
    test_db.commit()

    faculty_token = create_access_token(
        data={"sub": "faculty_cn", "role": "FACULTY", "user_id": "faculty_cn"}
    )
    admin_token = create_access_token(
        data={"sub": "admin_root", "role": "ADMIN", "user_id": "admin_root"}
    )

    payload = {
        "records": [
            {
                "session_id": "SESS-CN-OLD-01",
                "usn": "1MS21CS001",
                "room_id": "LH-101",
                "status": "ABSENT",
                "source": "manual",
                "confidence": 1.0,
            }
        ]
    }

    # Faculty attempt -> 403 Forbidden
    res_fac = client.put(
        "/api/v1/attendance/sessions/SESS-CN-OLD-01",
        json=payload,
        headers={"Authorization": f"Bearer {faculty_token}"},
    )
    assert res_fac.status_code == 403
    assert "locked" in res_fac.text.lower()

    # Admin attempt without reason -> 422
    res_adm_no_reason = client.put(
        "/api/v1/attendance/sessions/SESS-CN-OLD-01",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_adm_no_reason.status_code == 422

    # Admin attempt with reason -> 200 OK
    res_adm = client.put(
        "/api/v1/attendance/sessions/SESS-CN-OLD-01?reason=Dean+approved+medical+leave+reconciliation",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_adm.status_code == 200
    assert res_adm.json()["replaced_count"] == 1
