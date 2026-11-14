"""Integration tests for Class Delegation (Proxy/Exchange) and Extra Class creation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.jwt import create_access_token
from app.db.base import Base
from app.db.models import (
    AcademicYear,
    Attendance,
    College,
    Department,
    Room,
    Semester,
    Session as DbSession,
    Student,
    TeacherSubject,
    User,
)
from app.dependencies import get_db
from app.main import app

pytestmark = pytest.mark.no_auth_override

TEST_SECRET = "test-secret-key-for-delegation-tests-must-be-32-chars-long"


def _headers(user_id: str, role: str = "FACULTY") -> dict:
    now = datetime.now(timezone.utc)
    token = create_access_token(
        {
            "sub": user_id,
            "email": f"{user_id}@rollcall.edu",
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        expires_delta=timedelta(hours=1),
        secret=TEST_SECRET,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_SECRET)
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with factory() as db:
        for uid, role in (
            ("admin_root", "ADMIN"),
            ("faculty_ds", "FACULTY"),
            ("faculty_ml", "FACULTY"),
        ):
            db.add(
                User(
                    user_id=uid,
                    email=f"{uid}@rollcall.edu",
                    role=role,
                    hashed_password=None,
                    is_active=1,
                    created_at=now_str,
                )
            )
        db.add(College(college_id="DSCE", name="Dayananda Sagar College", code="DSCE"))
        db.add(
            AcademicYear(
                year_id="AY-2026",
                college_id="DSCE",
                year_label="2026-27",
                start_date="2026-08-01",
                end_date="2027-06-30",
                is_active=1,
            )
        )
        db.add(Room(room_id="CDS10-105", name="Room CDS10-105"))
        db.add(Department(dept_id="CSE-CY", college_id="DSCE", name="Cyber Security", code="CY"))
        db.add(
            Semester(
                semester_id="SEM-5",
                year_id="AY-2026",
                semester_label="Semester 5",
                semester_number=5,
                start_date="2026-08-01",
                end_date="2026-12-31",
                is_active=1,
            )
        )
        db.add(Student(usn="1DS24CY001", name="Alice", branch="CSE", dept_id="CSE-CY", semester_id="SEM-5"))
        db.add(TeacherSubject(user_id="faculty_ds", subject_code="DIST-SYS"))
        db.add(TeacherSubject(user_id="faculty_ml", subject_code="ML"))
        db.commit()

    def _override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    test_client = TestClient(app, raise_server_exceptions=False)
    yield test_client
    app.dependency_overrides.pop(get_db, None)


def test_colleagues_list(client):
    headers = _headers("faculty_ds", "FACULTY")
    resp = client.get("/api/v1/sessions/colleagues", headers=headers)
    assert resp.status_code == 200, resp.text
    colleagues = resp.json()
    assert isinstance(colleagues, list)
    uids = [c["user_id"] for c in colleagues]
    assert "faculty_ds" not in uids
    assert "faculty_ml" in uids


def test_extra_session_creation(client):
    headers = _headers("faculty_ds", "FACULTY")
    payload = {
        "subject_code": "DIST-SYS",
        "subject_name": "Distributed Systems",
        "date": "2026-11-20",
        "start_time": "14:00",
        "end_time": "15:00",
        "room_id": "CDS10-105",
        "dept_id": "CSE-CY",
        "semester_number": 5,
        "class_type": "EXTRA",
    }
    resp = client.post("/api/v1/sessions/extra", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "EXTRA-DIST-SYS" in data["session_id"]
    assert data["date"] == "2026-11-20"
    assert data["students_enrolled"] >= 1

    # Ensure it appears in session listing
    list_resp = client.get("/api/v1/sessions?date=2026-11-20", headers=headers)
    assert list_resp.status_code == 200
    session_ids = [s["session_id"] for s in list_resp.json()["items"]]
    assert data["session_id"] in session_ids


def test_class_delegation_flow(client):
    # 1. faculty_ds creates an extra session
    headers_ds = _headers("faculty_ds", "FACULTY")
    headers_ml = _headers("faculty_ml", "FACULTY")

    sess_payload = {
        "subject_code": "DIST-SYS",
        "subject_name": "Distributed Systems",
        "date": "2026-11-21",
        "start_time": "10:00",
        "end_time": "11:00",
        "room_id": "CDS10-105",
        "dept_id": "CSE-CY",
        "semester_number": 5,
    }
    create_resp = client.post("/api/v1/sessions/extra", json=sess_payload, headers=headers_ds)
    assert create_resp.status_code == 201, create_resp.text
    session_id = create_resp.json()["session_id"]

    # Before delegation, faculty_ml cannot see this session
    ml_list_before = client.get(f"/api/v1/sessions?date=2026-11-21", headers=headers_ml)
    assert session_id not in [s["session_id"] for s in ml_list_before.json()["items"]]

    # 2. faculty_ds delegates the session to faculty_ml
    del_payload = {
        "session_id": session_id,
        "substitute_faculty_id": "faculty_ml",
        "delegation_type": "PROXY",
        "reason": "On Medical Leave",
    }
    del_resp = client.post("/api/v1/sessions/delegations", json=del_payload, headers=headers_ds)
    assert del_resp.status_code == 201, del_resp.text
    del_data = del_resp.json()
    assert del_data["status"] == "ACTIVE"
    delegation_id = del_data["delegation_id"]

    # 3. Now faculty_ml CAN see the session and it has proxy annotation!
    ml_list_after = client.get(f"/api/v1/sessions?date=2026-11-21", headers=headers_ml)
    assert ml_list_after.status_code == 200
    matched_sessions = [s for s in ml_list_after.json()["items"] if s["session_id"] == session_id]
    assert len(matched_sessions) == 1
    assert matched_sessions[0]["is_delegated"] is True
    assert matched_sessions[0]["delegation"]["from_user_id"] == "faculty_ds"
    assert matched_sessions[0]["delegation"]["is_proxy_for_me"] is True

    # 4. Check /delegations/my
    my_del_resp = client.get("/api/v1/sessions/delegations/my", headers=headers_ml)
    assert my_del_resp.status_code == 200
    received = my_del_resp.json()["received"]
    assert any(d["delegation_id"] == delegation_id for d in received)

    # 5. Cancel delegation
    cancel_resp = client.delete(f"/api/v1/sessions/delegations/{delegation_id}", headers=headers_ds)
    assert cancel_resp.status_code == 200
