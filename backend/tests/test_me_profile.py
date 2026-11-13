"""Profile Settings persistence tests for /api/v1/me/profile (N4).

Verifies that profile edits issued by the Profile Settings UI are committed to
the database and remain visible to subsequent GET /api/v1/auth/me requests -
including from a *fresh* session, i.e. across page reloads and re-logins.

Real JWT verification is used (no mock admin user), mirroring the isolated
fixture in test_person1_security.py.
"""

from __future__ import annotations

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import User, UserProfile
from app.dependencies import get_db
from app.main import app

TEST_SECRET = "me-profile-test-secret-key-at-least-32-chars"  # gitleaks:allow - dummy signing key for tests, never a deployed credential

# Real JWT verification (no mock admin user) for every test in this module.
pytestmark = pytest.mark.no_auth_override


@pytest.fixture
def api(monkeypatch):
    """App client bound to an isolated in-memory SQLite database."""
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_SECRET)
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine, class_=OrmSession, expire_on_commit=False)
    # The authentication router opens its own session factory; point it at the
    # isolated test database so the test never touches another database.
    monkeypatch.setattr("app.db.connection.get_sync_session_factory", lambda eng=None: factory)
    monkeypatch.setattr("app.routers.auth.get_sync_session_factory", lambda: factory)

    now = "2026-01-01T00:00:00Z"
    with factory() as db:
        db.add(User(user_id="faculty_ds", email="faculty.ds@rollcall.edu", name=None,
                    role="FACULTY", hashed_password=None, is_active=1, created_at=now))
        db.add(User(user_id="faculty_ml", email="faculty.ml@rollcall.edu", name="Machine Learning",
                    role="FACULTY", hashed_password=None, is_active=1, created_at=now))
        db.commit()

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client, factory
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        engine.dispose()


def _headers(user_id: str, role: str = "FACULTY") -> dict:
    """Authorization header for a signed test token."""
    import time

    ts = int(time.time())
    token = pyjwt.encode(
        {
            "sub": user_id,
            "email": f"{user_id}@rollcall.edu",
            "role": role,
            "iat": ts,
            "exp": ts + 3600,
        },
        TEST_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_profile_update_persists_across_me_requests(api):
    """PATCH commits to the database; later GET /auth/me returns the update."""
    client, factory = api

    # Before: the display name falls back to the email prefix.
    before = client.get("/api/v1/auth/me", headers=_headers("faculty_ds"))
    assert before.status_code == 200
    assert before.json()["name"] == "faculty.ds"

    # Profile Settings UI payload (camelCase contract).
    res = client.patch(
        "/api/v1/me/profile",
        headers=_headers("faculty_ds"),
        json={
            "fullName": "Data Systems Faculty",
            "email": "data.systems@rollcall.edu",
            "mobile": "9876543210",
            "branch": "CSE",
            "designation": "Associate Professor",
            "experienceYears": 7,
            "qualifications": "Ph.D. Database Systems",
            "specialization": "Distributed Systems",
            "expertise": ["Distributed Systems", "Cloud"],
            "masteredSubjects": ["DIST-SYS", "DB-SYS"],
            "photoUrl": "data:image/png;base64,abc123",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["fullName"] == "Data Systems Faculty"
    assert body["email"] == "data.systems@rollcall.edu"
    assert body["experienceYears"] == 7
    assert body["expertise"] == ["Distributed Systems", "Cloud"]
    assert body["facultyId"] == "faculty_ds"
    assert body["updatedAt"]

    # The update must be visible to subsequent /me requests (new sessions).
    me = client.get("/api/v1/auth/me", headers=_headers("faculty_ds"))
    assert me.status_code == 200
    assert me.json()["name"] == "Data Systems Faculty"
    assert me.json()["email"] == "data.systems@rollcall.edu"

    again = client.get("/api/v1/me/profile", headers=_headers("faculty_ds"))
    assert again.status_code == 200
    assert again.json() == body

    # Persistence across a completely fresh session (page reload / re-login).
    with factory() as db:
        row = db.get(UserProfile, "faculty_ds")
        assert row is not None
        assert row.designation == "Associate Professor"
        assert row.experience_years == 7
        user = db.get(User, "faculty_ds")
        assert user.name == "Data Systems Faculty"
        assert user.email == "data.systems@rollcall.edu"


def test_put_full_replace_resets_absent_fields(api):
    """PUT replaces the whole profile; fields omitted are cleared."""
    client, _factory = api
    first = client.put(
        "/api/v1/me/profile",
        headers=_headers("faculty_ml"),
        json={
            "fullName": "Full Replace",
            "designation": "Professor",
            "experienceYears": 10,
            "expertise": ["AI"],
        },
    )
    assert first.status_code == 200
    assert first.json()["designation"] == "Professor"

    second = client.put(
        "/api/v1/me/profile",
        headers=_headers("faculty_ml"),
        json={"fullName": "Full Replace"},
    )
    assert second.status_code == 200
    body = second.json()
    assert body["designation"] == ""
    assert body["experienceYears"] is None
    assert body["expertise"] == []


def test_duplicate_email_returns_409(api):
    """Another account's email must be rejected, not silently saved."""
    client, factory = api
    res = client.patch(
        "/api/v1/me/profile",
        headers=_headers("faculty_ds"),
        json={"email": "faculty.ml@rollcall.edu"},
    )
    assert res.status_code == 409
    with factory() as db:
        assert db.get(User, "faculty_ds").email == "faculty.ds@rollcall.edu"


def test_invalid_email_returns_422(api):
    client, _factory = api
    res = client.patch(
        "/api/v1/me/profile",
        headers=_headers("faculty_ds"),
        json={"email": "not-an-email"},
    )
    assert res.status_code == 422


def test_profile_requires_authentication(api):
    client, _factory = api
    res = client.get("/api/v1/me/profile")
    assert res.status_code in (401, 403)
