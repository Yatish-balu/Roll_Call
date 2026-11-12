"""Tests for profile, teacher-subject unassignment, and calendar ics export endpoints."""

import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
import app.db.models as models
from app.dependencies import get_db
from app.main import app

pytestmark = pytest.mark.no_auth_override


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine, monkeypatch):
    test_secret = "test-secret-key-at-least-32-chars-long-abc"
    monkeypatch.setenv("JWT_SECRET", test_secret)
    monkeypatch.setenv("JWT_SECRET_KEY", test_secret)
    factory = sessionmaker(bind=engine, class_=OrmSession, expire_on_commit=False)
    monkeypatch.setattr("app.db.connection.get_sync_session_factory", lambda eng=None: factory)
    monkeypatch.setattr("app.routers.auth.get_sync_session_factory", lambda: factory)

    with factory() as db:
        db.add(models.User(
            user_id="faculty_cn",
            name="Dr. Rajesh Raman",
            email="faculty.cn@rollcall.internal",
            role="FACULTY",
            is_active=1,
            created_at="2026-01-01T00:00:00Z",
        ))
        db.add(models.User(
            user_id="admin_root",
            name="Administrator",
            email="admin@rollcall.internal",
            role="ADMIN",
            is_active=1,
            created_at="2026-01-01T00:00:00Z",
        ))
        db.add(models.FacultySubject(
            user_id="faculty_cn",
            subject_code="CN",
            dept_id="CSE",
        ))
        db.add(models.Session(
            session_id="SESS-TEST-001",
            date="2026-11-15",
            subject="CN",
            subject_code="CN",
            teacher_id="faculty_cn",
        ))
        db.commit()

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


def _auth_header(user_id: str, role: str) -> dict:
    import jwt
    from datetime import datetime, timedelta, timezone

    secret = "test-secret-key-at-least-32-chars-long-abc"
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": user_id,
            "email": f"{user_id}@rollcall.internal",
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=2)).timestamp()),
        },
        secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_get_profile_default(client):
    headers = _auth_header("faculty_cn", "FACULTY")
    res = client.get("/api/v1/profile", headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["facultyId"] == "faculty_cn"
    assert data["fullName"] == "Dr. Rajesh Raman"
    assert "CN" in data["masteredSubjects"]


def test_put_and_get_profile_persistence(client):
    headers = _auth_header("faculty_cn", "FACULTY")
    payload = {
        "fullName": "Prof. Rajesh Raman",
        "mobile": "9876543210",
        "email": "rajesh.raman@dsce.edu.in",
        "branch": "CyberSecurity",
        "facultyId": "faculty_cn",
        "designation": "Professor",
        "experienceYears": 12,
        "qualifications": "Ph.D. Computer Networks",
        "specialization": "Network Forensics & Security",
        "expertise": ["Network Security", "Cryptography"],
        "masteredSubjects": ["CN", "NET-SEC"],
        "photoUrl": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    }
    put_res = client.put("/api/v1/profile", json=payload, headers=headers)
    assert put_res.status_code == 200, put_res.text
    saved = put_res.json()
    assert saved["designation"] == "Professor"
    assert saved["experienceYears"] == 12
    assert "Network Security" in saved["expertise"]

    # Verify subsequent GET returns the persisted data
    get_res = client.get("/api/v1/profile", headers=headers)
    assert get_res.status_code == 200
    retrieved = get_res.json()
    assert retrieved["fullName"] == "Prof. Rajesh Raman"
    assert retrieved["mobile"] == "9876543210"
    assert retrieved["branch"] == "CyberSecurity"
    assert retrieved["specialization"] == "Network Forensics & Security"
    assert retrieved["expertise"] == ["Network Security", "Cryptography"]


def test_admin_remove_teacher_subject(client):
    admin_headers = _auth_header("admin_root", "ADMIN")
    res = client.delete(
        "/api/v1/admin/teacher-subjects?user_id=faculty_cn&subject_code=CN",
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["success"] is True

    # Attempting to delete again should return 404
    res2 = client.delete(
        "/api/v1/admin/teacher-subjects?user_id=faculty_cn&subject_code=CN",
        headers=admin_headers,
    )
    assert res2.status_code == 404


def test_export_calendar_ics(client):
    headers = _auth_header("faculty_cn", "FACULTY")
    res = client.get("/api/v1/calendar/export.ics", headers=headers)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/calendar")
    content = res.text
    assert "BEGIN:VCALENDAR" in content
    assert "BEGIN:VEVENT" in content
    assert "SUMMARY:CN - RollCall Session" in content
    assert "END:VCALENDAR" in content
