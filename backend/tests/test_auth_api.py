"""Comprehensive Security & Authentication Tests for Phase 6.3.

Verifies:
1. Missing token returns 401 Unauthorized.
2. Malformed / invalid token returns 401 Unauthorized.
3. Expired token returns 401 Unauthorized.
4. Invalid cryptographic signature returns 401 Unauthorized.
5. Invalid issuer / audience returns 401 Unauthorized when configured.
6. Role-Based Access Control (RBAC):
   - ADMIN: Full access across all master data, mutating operations, and deletion.
   - FACULTY: Attendance upload, recording, reconciliation, reports, agent; forbidden from admin master-data and deletion (403).
   - VIEWER: Read-only access across master data, attendance, and analytics; forbidden from any mutations (403).
7. User identity cannot be impersonated or forged through request payload.
8. Unauthenticated requests across every router are systematically rejected (401).
"""

from __future__ import annotations

import datetime
import io
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import Role, create_access_token
from app.db.base import Base
from app.db.models import Student, Room, Session as DbSession, TeacherSubject
from app.dependencies import get_db
from app.main import app

TEST_SECRET = "test-secret-key-for-auth-tests-must-be-at-least-32-chars-long"


@pytest.fixture
def auth_db_engine():
    """Isolated in-memory SQLite database for authentication tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def unauthenticated_client(auth_db_engine):
    """
    TestClient with database override but NO auth dependency overrides.
    Executes real JWT verification for every request.
    """
    TestingSessionLocal = sessionmaker(bind=auth_db_engine, class_=Session, expire_on_commit=False)

    # Seed baseline records
    with TestingSessionLocal() as session:
        session.add(Student(usn="1MS21CS001", name="Alice Smith", branch="CSE"))
        session.add(Room(room_id="LH-101", name="Lecture Hall 101"))
        # subject_code + mapping: a session with no owner is authorized through
        # the teacher-subject mapping, not by being readable by every role.
        session.add(
            DbSession(
                session_id="SESS-001",
                date="2026-03-15",
                subject="Machine Learning",
                subject_code="ML",
            )
        )
        session.commit()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app, raise_server_exceptions=False)
    yield test_client
    app.dependency_overrides.clear()


def _grant_subject(engine, user_id: str = "user-123", subject_code: str = "ML") -> None:
    """Map a token subject to a subject code (session authorization)."""
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as db:
        exists = db.query(TeacherSubject).filter_by(user_id=user_id).first()
        if exists is None:
            db.add(TeacherSubject(user_id=user_id, subject_code=subject_code))
            db.commit()


def _seed_actor(engine, user_id: str = "user-123", role: str = "ADMIN") -> None:
    """Insert a real users row for a token subject.

    Write endpoints now emit an audit_log row whose actor_id has a foreign key
    to users.user_id, so an authenticated writer must exist locally. The role is
    also authoritative from the database, so it must match the test's token.
    """
    from app.db.models import User

    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as db:
        if db.get(User, user_id) is None:
            db.add(
                User(
                    user_id=user_id,
                    email=f"{user_id}@rollcall.edu",
                    role=role,
                    hashed_password=None,
                    is_active=1,
                    created_at=datetime.datetime.now(datetime.timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                )
            )
            db.commit()


@pytest.fixture
def make_actor(auth_db_engine):
    """Return a callback that seeds an authenticated actor with a given role."""

    def _make(user_id: str = "user-123", role: str = "ADMIN") -> None:
        _seed_actor(auth_db_engine, user_id=user_id, role=role)

    return _make


def make_token(
    user_id: str = "user-123",
    role: str = "VIEWER",
    email: str = "user@rollcall.edu",
    expires_in_minutes: int = 60,
    secret: str = TEST_SECRET,
    issuer: str | None = None,
    audience: str | None = None,
) -> str:
    """Helper to generate signed test JWT tokens."""
    payload = {
        "sub": user_id,
        "email": email,
        "app_metadata": {"role": role},
        "role": role,
    }
    if issuer:
        payload["iss"] = issuer
    if audience:
        payload["aud"] = audience

    delta = datetime.timedelta(minutes=expires_in_minutes)
    return create_access_token(payload, expires_delta=delta, secret=secret)


# ==============================================================================
# 1. Token Verification: Missing, Expired, Malformed, and Signature
# ==============================================================================

@patch.dict("os.environ", {"JWT_SECRET_KEY": TEST_SECRET})
def test_missing_token_returns_401(unauthenticated_client):
    res = unauthenticated_client.get("/api/v1/students")
    assert res.status_code == 401
    assert "Bearer token required" in res.json()["detail"]


@patch.dict("os.environ", {"JWT_SECRET_KEY": TEST_SECRET})
def test_malformed_token_returns_401(unauthenticated_client):
    headers = {"Authorization": "Bearer not-a-valid-jwt-token"}
    res = unauthenticated_client.get("/api/v1/students", headers=headers)
    assert res.status_code == 401
    assert "Invalid token" in res.json()["detail"] or "invalid" in res.json()["detail"].lower()


@patch.dict("os.environ", {"JWT_SECRET_KEY": TEST_SECRET})
def test_expired_token_returns_401(unauthenticated_client):
    expired_token = make_token(expires_in_minutes=-10)
    headers = {"Authorization": f"Bearer {expired_token}"}
    res = unauthenticated_client.get("/api/v1/students", headers=headers)
    assert res.status_code == 401
    assert "Token has expired" in res.json()["detail"]


@patch.dict("os.environ", {"JWT_SECRET_KEY": TEST_SECRET})
def test_invalid_signature_returns_401(unauthenticated_client):
    # Token signed with completely different secret
    forged_token = make_token(secret="wrong-secret-key-forged-signature-attempt-xyz")
    headers = {"Authorization": f"Bearer {forged_token}"}
    res = unauthenticated_client.get("/api/v1/students", headers=headers)
    assert res.status_code == 401
    assert "signature" in res.json()["detail"].lower()


@patch.dict("os.environ", {"JWT_SECRET_KEY": TEST_SECRET, "JWT_ISSUER": "https://trusted-supabase.co", "JWT_AUDIENCE": "authenticated"})
def test_issuer_and_audience_validation(unauthenticated_client):
    # Valid issuer and audience
    valid_token = make_token(issuer="https://trusted-supabase.co", audience="authenticated")
    headers = {"Authorization": f"Bearer {valid_token}"}
    assert unauthenticated_client.get("/api/v1/students", headers=headers).status_code == 200

    # Invalid issuer
    bad_iss_token = make_token(issuer="https://malicious-issuer.com", audience="authenticated")
    bad_iss_headers = {"Authorization": f"Bearer {bad_iss_token}"}
    res_iss = unauthenticated_client.get("/api/v1/students", headers=bad_iss_headers)
    assert res_iss.status_code == 401
    assert "issuer" in res_iss.json()["detail"].lower()

    # Invalid audience
    bad_aud_token = make_token(issuer="https://trusted-supabase.co", audience="wrong-aud")
    bad_aud_headers = {"Authorization": f"Bearer {bad_aud_token}"}
    res_aud = unauthenticated_client.get("/api/v1/students", headers=bad_aud_headers)
    assert res_aud.status_code == 401
    assert "audience" in res_aud.json()["detail"].lower()


# ==============================================================================
# 2. Role-Based Access Control (RBAC) Tests
# ==============================================================================

@patch.dict("os.environ", {"JWT_SECRET_KEY": TEST_SECRET})
def test_admin_full_access(unauthenticated_client, make_actor):
    make_actor(role="ADMIN")
    admin_token = make_token(role="ADMIN")
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Admin can list students
    assert unauthenticated_client.get("/api/v1/students", headers=headers).status_code == 200

    # Admin can create student
    create_res = unauthenticated_client.post(
        "/api/v1/students",
        json={"usn": "1MS21CS099", "name": "Admin Student", "branch": "CSE"},
        headers=headers,
    )
    assert create_res.status_code == 201

    # Admin can record attendance
    att_res = unauthenticated_client.post(
        "/api/v1/attendance/sessions/SESS-001/record",
        json={"usn": "1MS21CS099", "room_id": "LH-101", "status": "PRESENT"},
        headers=headers,
    )
    assert att_res.status_code == 201

    # Admin can delete attendance
    del_res = unauthenticated_client.delete("/api/v1/attendance/sessions/SESS-001", headers=headers)
    assert del_res.status_code == 200


@patch.dict("os.environ", {"JWT_SECRET_KEY": TEST_SECRET})
def test_faculty_permissions_and_restrictions(unauthenticated_client, make_actor, auth_db_engine):
    make_actor(role="FACULTY")
    _grant_subject(auth_db_engine)
    faculty_token = make_token(role="FACULTY")
    headers = {"Authorization": f"Bearer {faculty_token}"}

    # Faculty can read students & sessions
    assert unauthenticated_client.get("/api/v1/students", headers=headers).status_code == 200
    assert unauthenticated_client.get("/api/v1/sessions/SESS-001", headers=headers).status_code == 200

    # Faculty can record attendance
    att_res = unauthenticated_client.post(
        "/api/v1/attendance/sessions/SESS-001/record",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT"},
        headers=headers,
    )
    assert att_res.status_code == 201

    # Faculty CANNOT create new students (ADMIN only) -> 403
    create_stu_res = unauthenticated_client.post(
        "/api/v1/students",
        json={"usn": "1MS21CS999", "name": "Unauthorized", "branch": "CSE"},
        headers=headers,
    )
    assert create_stu_res.status_code == 403
    assert "Forbidden" in create_stu_res.json()["detail"]

    # Faculty CANNOT delete attendance (ADMIN only) -> 403
    del_res = unauthenticated_client.delete("/api/v1/attendance/sessions/SESS-001", headers=headers)
    assert del_res.status_code == 403
    assert "Forbidden" in del_res.json()["detail"]


@patch.dict("os.environ", {"JWT_SECRET_KEY": TEST_SECRET})
def test_viewer_read_only_restrictions(unauthenticated_client, auth_db_engine):
    _seed_actor(auth_db_engine, role="VIEWER")
    _grant_subject(auth_db_engine)
    viewer_token = make_token(role="VIEWER")
    headers = {"Authorization": f"Bearer {viewer_token}"}

    # Viewer can read master data, sessions, attendance, analytics
    assert unauthenticated_client.get("/api/v1/students", headers=headers).status_code == 200
    assert unauthenticated_client.get("/api/v1/rooms", headers=headers).status_code == 200
    assert unauthenticated_client.get("/api/v1/sessions", headers=headers).status_code == 200
    assert unauthenticated_client.get("/api/v1/attendance/sessions/SESS-001", headers=headers).status_code == 200
    assert unauthenticated_client.get("/api/v1/analytics/sessions/SESS-001/summary", headers=headers).status_code == 200

    # Viewer CANNOT record attendance -> 403
    rec_res = unauthenticated_client.post(
        "/api/v1/attendance/sessions/SESS-001/record",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT"},
        headers=headers,
    )
    assert rec_res.status_code == 403

    # Viewer CANNOT process attendance files -> 403
    csv_bytes = b"usn,status\n1MS21CS001,PRESENT\n"
    file_res = unauthenticated_client.post(
        "/api/v1/agent/process-file",
        files={"file": ("att.csv", io.BytesIO(csv_bytes), "text/csv")},
        headers=headers,
    )
    assert file_res.status_code == 403

    # Viewer CANNOT confirm attendance records -> 403
    conf_res = unauthenticated_client.post(
        "/api/v1/agent/confirm",
        json={"session_id": "SESS-001", "confirmed": True, "records": []},
        headers=headers,
    )
    assert conf_res.status_code == 403


# ==============================================================================
# 3. Payload Impersonation Defense
# ==============================================================================

@patch.dict("os.environ", {"JWT_SECRET_KEY": TEST_SECRET})
def test_cannot_impersonate_user_through_body(unauthenticated_client):
    # A VIEWER sends an ADMIN role or spoofed user_id in the JSON body
    viewer_token = make_token(user_id="viewer-uuid-123", role="VIEWER")
    headers = {"Authorization": f"Bearer {viewer_token}"}

    # Request to create a student with a spoofed admin role in payload
    payload = {
        "usn": "1MS21CS777",
        "name": "Spoofer",
        "branch": "CSE",
        "role": "ADMIN",  # Ignored by server
        "user_id": "admin-uuid-999",  # Ignored by server
    }
    res = unauthenticated_client.post("/api/v1/students", json=payload, headers=headers)
    # Server relies strictly on verified token claims (VIEWER), rejecting with 403 Forbidden
    assert res.status_code == 403
    assert "Forbidden" in res.json()["detail"]


# ==============================================================================
# 4. Comprehensive Route Protection Check (All 7 Routers Reject Missing Auth)
# ==============================================================================

@patch.dict("os.environ", {"JWT_SECRET_KEY": TEST_SECRET})
def test_all_routers_reject_unauthenticated_requests(unauthenticated_client):
    endpoints = [
        ("GET", "/api/v1/students"),
        ("GET", "/api/v1/students/1MS21CS001"),
        ("POST", "/api/v1/students"),
        ("GET", "/api/v1/rooms"),
        ("GET", "/api/v1/rooms/LH-101"),
        ("POST", "/api/v1/rooms"),
        ("GET", "/api/v1/sessions"),
        ("GET", "/api/v1/sessions/SESS-001"),
        ("POST", "/api/v1/sessions"),
        ("GET", "/api/v1/attendance/sessions/SESS-001"),
        ("GET", "/api/v1/attendance/students/1MS21CS001"),
        ("POST", "/api/v1/attendance/sessions/SESS-001/record"),
        ("DELETE", "/api/v1/attendance/sessions/SESS-001"),
        ("GET", "/api/v1/analytics/sessions/SESS-001/summary"),
        ("POST", "/api/v1/reports/export/excel"),
        ("POST", "/api/v1/reports/export/pdf"),
        ("POST", "/api/v1/agent/chat"),
        ("POST", "/api/v1/agent/process-file"),
        ("POST", "/api/v1/agent/confirm"),
        ("GET", "/api/v1/agent/status"),
    ]

    for method, path in endpoints:
        if method == "GET":
            res = unauthenticated_client.get(path)
        elif method == "POST":
            res = unauthenticated_client.post(path, json={})
        elif method == "DELETE":
            res = unauthenticated_client.delete(path)

        assert res.status_code == 401, f"Endpoint {method} {path} failed to reject unauthenticated request! Returned {res.status_code}."

