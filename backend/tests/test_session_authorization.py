"""Regression tests for server-side session authorization and data isolation.

The backend is the enforcement point for session visibility: the frontend
filters defensively, but that is a UI convenience, never the security
boundary. These tests call the API directly (no frontend involved) and pin the
role-aware scoping of ``GET /api/v1/sessions`` and its detail endpoint.

Covered:
  1. ADMIN keeps institution-wide session access.
  2. FACULTY only sees sessions authorized by teacher-subject mapping / ownership.
  3. FACULTY cannot see unrelated sessions.
  4. Legacy sessions follow the existing ownership policy (mapping or coordinator).
  5. Sessions without a valid mapping stay ADMIN-only.
  6. VIEWER only receives explicitly permitted session metadata.
  7. Direct API calls cannot bypass authorization.
  8. Pagination does not expose unrelated records (or inflate ``total``).
  9. Filters (date / search) cannot bypass authorization.
 10. Subject-code matching is exact and normalized (ML != HTML, DB-SYS != ...).
 11. The legacy ``/api`` mount enforces exactly the same policy.
 12. Sibling aggregation endpoints (analytics / reports) cannot be used to
     bypass the session scope.
"""

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
    Attendance,
    Room,
    Session as DbSession,
    Student,
    TeacherSubject,
    User,
)
from app.dependencies import get_db
from app.main import app

pytestmark = pytest.mark.no_auth_override

TEST_SECRET = "test-secret-key-for-session-auth-must-be-at-least-32-chars-long"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    return create_access_token(
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


def _headers(user_id: str, role: str) -> dict:
    return {"Authorization": f"Bearer {_token(user_id, role)}"}


# ---------------------------------------------------------------------------
# Fixture: one institution with every session shape the policy must handle
# ---------------------------------------------------------------------------

@pytest.fixture
def api(monkeypatch):
    """TestClient over an in-memory database seeded with the policy fixtures."""
    # Real JWT verification is exercised (no_auth_override), so the signing
    # secret must match the one used to mint the test tokens.
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_SECRET)
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    now = _iso(datetime.now(timezone.utc))

    with factory() as db:
        for uid, role in (
            ("admin_root", "ADMIN"),
            ("faculty_ds", "FACULTY"),
            ("faculty_ml", "FACULTY"),
            ("viewer_ro", "VIEWER"),
        ):
            db.add(
                User(
                    user_id=uid,
                    email=f"{uid}@rollcall.edu",
                    role=role,
                    hashed_password=None,
                    is_active=1,
                    created_at=now,
                )
            )
        # The migration-0002 sentinel for sessions that predate ownership.
        db.add(
            User(
                user_id="legacy",
                email="legacy@rollcall.edu",
                role="ADMIN",
                hashed_password=None,
                is_active=0,
                created_at=now,
            )
        )
        db.add(Room(room_id="LH-101", name="Lecture Hall 101"))
        db.add(Student(usn="1MS21CS001", name="Alice Smith", branch="CSE"))

        # (a) explicitly owned by faculty_ds
        db.add(
            DbSession(
                session_id="SESS-OWNED",
                date="2026-03-15",
                subject="Distributed Systems",
                teacher_id="faculty_ds",
                subject_code="DIST-SYS",
            )
        )
        # (b) legacy/unowned session, subject code mapped to faculty_ml only
        db.add(
            DbSession(
                session_id="SESS-LEGACY-ML",
                date="2026-03-16",
                subject="Machine Learning",
                teacher_id="legacy",
                subject_code="ML",
            )
        )
        # (c) legacy session whose subject code nobody is mapped to
        db.add(
            DbSession(
                session_id="SESS-LEGACY-ORPHAN",
                date="2026-03-17",
                subject="Embedded Systems",
                teacher_id="legacy",
                subject_code="ES",
            )
        )
        # (d) legacy session with a coordinator and no subject code
        db.add(
            DbSession(
                session_id="SESS-COORDINATED",
                date="2026-03-18",
                subject="Computer Networks",
                teacher_id=None,
                subject_code=None,
                coordinator_faculty_id="faculty_ds",
            )
        )
        # (e) legacy session without subject code and without coordinator
        db.add(
            DbSession(
                session_id="SESS-NO-SCOPE",
                date="2026-03-19",
                subject="Compilers",
                teacher_id=None,
                subject_code=None,
            )
        )
        # (f) owned by faculty_ml - must stay invisible to faculty_ds
        db.add(
            DbSession(
                session_id="SESS-OWNED-ML",
                date="2026-03-20",
                subject="Machine Learning Lab",
                teacher_id="faculty_ml",
                subject_code="ML",
            )
        )
        # (g) subject code that must not match 'ML' by substring
        db.add(
            DbSession(
                session_id="SESS-HTML",
                date="2026-03-21",
                subject="HTML Fundamentals",
                teacher_id="legacy",
                subject_code="HTML",
            )
        )
        db.add(
            DbSession(
                session_id="SESS-DBSYS",
                date="2026-03-22",
                subject="Database Systems",
                teacher_id="legacy",
                subject_code="DB-SYS",
            )
        )

        # Teacher-subject mappings (the authorization source of truth).
        db.add(TeacherSubject(user_id="faculty_ml", subject_code="ML"))
        db.add(TeacherSubject(user_id="faculty_ml", subject_code="DB-SYS"))
        db.add(TeacherSubject(user_id="faculty_ds", subject_code="DIST-SYS"))
        db.add(TeacherSubject(user_id="viewer_ro", subject_code="ML"))

        db.add(
            Attendance(
                attendance_id="ATT-OWNED",
                session_id="SESS-OWNED",
                usn="1MS21CS001",
                room_id="LH-101",
                status="PRESENT",
                source="csv",
                confidence=1.0,
                recorded_at=now,
            )
        )
        db.commit()

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _ids(payload) -> set:
    return {item["session_id"] for item in payload["items"]}


# ---------------------------------------------------------------------------
# 1. ADMIN keeps institution-wide access
# ---------------------------------------------------------------------------

def test_admin_lists_all_institutional_sessions(api):
    client, _ = api
    res = client.get("/api/v1/sessions", headers=_headers("admin_root", "ADMIN"))
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 8
    assert _ids(payload) == {
        "SESS-OWNED",
        "SESS-LEGACY-ML",
        "SESS-LEGACY-ORPHAN",
        "SESS-COORDINATED",
        "SESS-NO-SCOPE",
        "SESS-OWNED-ML",
        "SESS-HTML",
        "SESS-DBSYS",
    }


def test_admin_can_read_any_session_detail(api):
    client, _ = api
    headers = _headers("admin_root", "ADMIN")
    for session_id in ("SESS-NO-SCOPE", "SESS-LEGACY-ORPHAN", "SESS-HTML"):
        res = client.get(f"/api/v1/sessions/{session_id}", headers=headers)
        assert res.status_code == 200, res.text


# ---------------------------------------------------------------------------
# 2 + 3. FACULTY scoping
# ---------------------------------------------------------------------------

def test_faculty_sees_only_authorized_sessions(api):
    client, _ = api
    res = client.get("/api/v1/sessions", headers=_headers("faculty_ml", "FACULTY"))
    assert res.status_code == 200
    payload = res.json()
    visible = _ids(payload)

    # Authorized: mapped subject code (legacy session) and own session.
    assert "SESS-LEGACY-ML" in visible
    assert "SESS-DBSYS" in visible
    assert "SESS-OWNED-ML" in visible
    # Not authorized for this teacher.
    assert "SESS-OWNED" not in visible
    assert "SESS-LEGACY-ORPHAN" not in visible
    assert "SESS-COORDINATED" not in visible
    assert "SESS-NO-SCOPE" not in visible
    assert "SESS-HTML" not in visible
    assert payload["total"] == len(visible)


def test_faculty_cannot_see_unrelated_sessions(api):
    client, _ = api
    headers = _headers("faculty_ds", "FACULTY")
    res = client.get("/api/v1/sessions", headers=headers)
    assert res.status_code == 200
    visible = _ids(res.json())

    # Own session + coordinator session + own subject mapping.
    assert "SESS-OWNED" in visible
    assert "SESS-COORDINATED" in visible
    # Another teacher's session stays invisible even though faculty_ds has no
    # mapping for it.
    assert "SESS-OWNED-ML" not in visible
    assert "SESS-LEGACY-ML" not in visible
    assert "SESS-NO-SCOPE" not in visible


def test_faculty_cannot_read_unrelated_session_detail(api):
    client, _ = api
    headers = _headers("faculty_ds", "FACULTY")
    assert client.get("/api/v1/sessions/SESS-OWNED-ML", headers=headers).status_code == 403
    assert client.get("/api/v1/sessions/SESS-LEGACY-ML", headers=headers).status_code == 403
    assert client.get("/api/v1/sessions/SESS-OWNED", headers=headers).status_code == 200


# ---------------------------------------------------------------------------
# 4 + 5. Legacy session policy
# ---------------------------------------------------------------------------

def test_legacy_session_visible_through_subject_mapping(api):
    client, _ = api
    res = client.get("/api/v1/sessions/SESS-LEGACY-ML", headers=_headers("faculty_ml", "FACULTY"))
    assert res.status_code == 200
    assert res.json()["session_id"] == "SESS-LEGACY-ML"


def test_legacy_session_visible_through_coordinator(api):
    client, _ = api
    res = client.get("/api/v1/sessions/SESS-COORDINATED", headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 200


def test_legacy_session_without_mapping_stays_admin_only(api):
    client, _ = api
    for role_user in (("faculty_ds", "FACULTY"), ("faculty_ml", "FACULTY"), ("viewer_ro", "VIEWER")):
        res = client.get(
            "/api/v1/sessions/SESS-LEGACY-ORPHAN", headers=_headers(*role_user)
        )
        assert res.status_code == 403, (role_user, res.text)


def test_session_without_subject_code_or_coordinator_is_admin_only(api):
    client, _ = api
    for role_user in (("faculty_ds", "FACULTY"), ("faculty_ml", "FACULTY"), ("viewer_ro", "VIEWER")):
        res = client.get("/api/v1/sessions/SESS-NO-SCOPE", headers=_headers(*role_user))
        assert res.status_code == 403, (role_user, res.text)


def test_reading_legacy_session_does_not_assign_ownership(api):
    """Authorizing by subject mapping must never mutate the session owner."""
    client, factory = api
    res = client.get("/api/v1/sessions/SESS-LEGACY-ML", headers=_headers("faculty_ml", "FACULTY"))
    assert res.status_code == 200
    with factory() as db:
        session = db.get(DbSession, "SESS-LEGACY-ML")
        assert session.teacher_id == "legacy"
        assert session.coordinator_faculty_id is None


# ---------------------------------------------------------------------------
# 6. VIEWER scope
# ---------------------------------------------------------------------------

def test_viewer_receives_only_permitted_sessions(api):
    client, _ = api
    res = client.get("/api/v1/sessions", headers=_headers("viewer_ro", "VIEWER"))
    assert res.status_code == 200
    payload = res.json()
    visible = _ids(payload)
    # The viewer is mapped to ML, so exactly the ML-mapped legacy session and
    # the viewer must not receive institution-wide metadata.
    assert visible == {"SESS-LEGACY-ML"}
    assert payload["total"] == 1


def test_viewer_cannot_read_unmapped_session(api):
    client, _ = api
    headers = _headers("viewer_ro", "VIEWER")
    assert client.get("/api/v1/sessions/SESS-OWNED", headers=headers).status_code == 403
    assert client.get("/api/v1/sessions/SESS-NO-SCOPE", headers=headers).status_code == 403
    assert client.get("/api/v1/sessions/SESS-COORDINATED", headers=headers).status_code == 403


# ---------------------------------------------------------------------------
# 7 + 8 + 9. Direct API calls, pagination and filters cannot bypass the scope
# ---------------------------------------------------------------------------

def test_direct_api_call_cannot_bypass_authorization(api):
    """The detail endpoint enforces the same scope as the list endpoint."""
    client, _ = api
    headers = _headers("faculty_ds", "FACULTY")
    for session_id in ("SESS-OWNED-ML", "SESS-LEGACY-ML", "SESS-NO-SCOPE", "SESS-HTML"):
        res = client.get(f"/api/v1/sessions/{session_id}", headers=headers)
        assert res.status_code == 403, (session_id, res.text)


def test_pagination_does_not_expose_unrelated_records(api):
    client, _ = api
    headers = _headers("faculty_ml", "FACULTY")

    # A large page must still only contain permitted sessions.
    res = client.get("/api/v1/sessions?limit=200&offset=0", headers=headers)
    assert res.status_code == 200
    payload = res.json()
    visible = _ids(payload)
    assert "SESS-OWNED" not in visible
    assert "SESS-NO-SCOPE" not in visible
    assert payload["total"] == len(visible) == 3

    # Paging through the scoped set must not leak other records either.
    seen = set()
    for offset in range(0, 10):
        page = client.get(f"/api/v1/sessions?limit=1&offset={offset}", headers=headers)
        assert page.status_code == 200
        items = page.json()["items"]
        if not items:
            break
        seen |= _ids(page.json())
    assert seen == visible
    assert "SESS-OWNED" not in seen


def test_filters_cannot_bypass_authorization(api):
    client, _ = api
    headers = _headers("faculty_ds", "FACULTY")

    # date filter targeting somebody else's session
    res = client.get("/api/v1/sessions?date=2026-03-20", headers=headers)
    assert res.status_code == 200
    assert res.json()["items"] == []
    assert res.json()["total"] == 0

    # search term matching somebody else's session id
    res = client.get("/api/v1/sessions?search=SESS-OWNED-ML", headers=headers)
    assert res.status_code == 200
    assert res.json()["items"] == []
    assert res.json()["total"] == 0

    # search term matching somebody else's subject
    res = client.get("/api/v1/sessions?search=Machine", headers=headers)
    assert res.status_code == 200
    assert "SESS-OWNED-ML" not in _ids(res.json())

    # ... while the caller's own records are still reachable through filters
    res = client.get("/api/v1/sessions?search=SESS-OWNED", headers=headers)
    assert res.status_code == 200
    assert "SESS-OWNED" in _ids(res.json())


def test_legacy_api_mount_enforces_the_same_policy(api):
    """The legacy /api mount must not be a bypass of the /api/v1 policy."""
    client, _ = api
    headers = _headers("faculty_ds", "FACULTY")

    res = client.get("/api/sessions", headers=headers)
    assert res.status_code == 200
    assert "SESS-OWNED-ML" not in _ids(res.json())

    res = client.get("/api/sessions/SESS-OWNED-ML", headers=headers)
    assert res.status_code == 403


def test_unauthenticated_session_listing_is_rejected(api):
    client, _ = api
    assert client.get("/api/v1/sessions").status_code == 401
    assert client.get("/api/sessions").status_code == 401


# ---------------------------------------------------------------------------
# 10. Exact, normalized subject-code matching
# ---------------------------------------------------------------------------

def test_subject_code_matching_is_exact_and_normalized(api):
    client, _ = api
    headers = _headers("faculty_ml", "FACULTY")

    # 'ML' must not match 'HTML' by substring.
    res = client.get("/api/v1/sessions", headers=headers)
    visible = _ids(res.json())
    assert "SESS-HTML" not in visible
    assert "SESS-LEGACY-ML" in visible

    # 'DB-SYS' is mapped to faculty_ml and therefore visible ...
    assert "SESS-DBSYS" in visible
    # ... while a code that merely contains 'ML' is not.
    assert "SESS-HTML" not in visible

    # Detail endpoint applies the same exact matching.
    assert client.get("/api/v1/sessions/SESS-HTML", headers=headers).status_code == 403
    assert client.get("/api/v1/sessions/SESS-DBSYS", headers=headers).status_code == 200


def test_subject_code_matching_normalizes_case_and_whitespace(api):
    """Stored codes are compared after normalization (trim + upper)."""
    client, factory = api
    with factory() as db:
        db.add(
            DbSession(
                session_id="SESS-LOWERCASE",
                date="2026-03-23",
                subject="Lowercase Code",
                teacher_id="legacy",
                subject_code="  ml  ",
            )
        )
        db.commit()

    headers = _headers("faculty_ml", "FACULTY")
    res = client.get("/api/v1/sessions/SESS-LOWERCASE", headers=headers)
    assert res.status_code == 200, res.text


# ---------------------------------------------------------------------------
# 12. Sibling endpoints cannot be used to bypass the session scope
# ---------------------------------------------------------------------------

def test_analytics_endpoints_respect_the_session_scope(api):
    client, _ = api
    headers = _headers("faculty_ds", "FACULTY")

    # Session summary for a session outside the scope is rejected.
    res = client.get("/api/v1/analytics/sessions/SESS-OWNED-ML/summary", headers=headers)
    assert res.status_code == 403

    # Institution-wide overview only aggregates visible sessions: faculty_ds
    # sees SESS-OWNED (which holds the only attendance row), nothing else.
    res = client.get("/api/v1/analytics/overview", headers=headers)
    assert res.status_code == 200
    assert res.json()["overall"]["total"] == 1


def test_report_export_respects_the_session_scope(api):
    client, _ = api
    headers = _headers("faculty_ds", "FACULTY")

    res = client.post(
        "/api/v1/reports/export/excel",
        json={"session_id": "SESS-OWNED-ML", "include_branch_summary": False},
        headers=headers,
    )
    assert res.status_code == 403
