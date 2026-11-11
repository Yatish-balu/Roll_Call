"""N6b verification-gap tests: session-list validation, role parity and scope.

Closes the gaps identified in the N6b audit:
  * limit/offset boundary validation (422) was declared but never asserted;
  * the legacy ``/api`` mount was only compared for one role;
  * "total is computed after authorization filtering" and "pagination never
    exposes unauthorized sessions" are asserted explicitly against the
    institution-wide count.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.jwt import create_access_token
from app.db.base import Base
from app.db.models import (
    Session as DbSession,
    TeacherSubject,
    User,
)
from app.dependencies import get_db
from app.main import app

pytestmark = pytest.mark.no_auth_override

TEST_SECRET = "test-secret-key-for-n6b-listing-gaps-at-least-32-chars"


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


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_SECRET)

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=OrmSession, expire_on_commit=False)

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
                    created_at="2020-01-01T00:00:00Z",
                )
            )
        db.add(
            User(
                user_id="legacy",
                email="legacy@rollcall.edu",
                role="ADMIN",
                hashed_password=None,
                is_active=0,
                created_at="2020-01-01T00:00:00Z",
            )
        )
        # Six sessions with different ownership shapes.
        db.add(DbSession(session_id="SESS-A", date="2026-03-15", subject="Alpha", teacher_id="faculty_ds", subject_code="DIST-SYS"))
        db.add(DbSession(session_id="SESS-B", date="2026-03-16", subject="Beta", teacher_id="faculty_ml", subject_code="ML"))
        db.add(DbSession(session_id="SESS-C", date="2026-03-17", subject="Gamma", teacher_id="legacy", subject_code="ML"))
        db.add(DbSession(session_id="SESS-D", date="2026-03-18", subject="Delta", teacher_id=None, subject_code=None, coordinator_faculty_id="faculty_ds"))
        db.add(DbSession(session_id="SESS-E", date="2026-03-19", subject="Epsilon", teacher_id=None, subject_code=None))
        db.add(DbSession(session_id="SESS-F", date="2026-03-20", subject="Zeta", teacher_id="faculty_ds", subject_code="DIST-SYS"))
        db.add(TeacherSubject(user_id="faculty_ds", subject_code="DIST-SYS"))
        db.add(TeacherSubject(user_id="faculty_ml", subject_code="ML"))
        db.add(TeacherSubject(user_id="viewer_ro", subject_code="ML"))
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


def _ids(payload):
    return {item["session_id"] for item in payload["items"]}


# ---------------------------------------------------------------------------
# Pagination parameter validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=201", "offset=-1"],
)
def test_invalid_pagination_parameters_are_rejected(api, query):
    client, _ = api
    res = client.get(f"/api/v1/sessions?{query}", headers=_headers("admin_root", "ADMIN"))
    assert res.status_code == 422, res.text


def test_valid_pagination_boundaries_are_accepted(api):
    client, _ = api
    for query in ("limit=1", "limit=200", "offset=0"):
        res = client.get(f"/api/v1/sessions?{query}", headers=_headers("admin_root", "ADMIN"))
        assert res.status_code == 200, res.text


# ---------------------------------------------------------------------------
# /api and /api/v1 parity
# ---------------------------------------------------------------------------

def test_legacy_mount_matches_v1_for_admin(api):
    client, _ = api
    v1 = client.get("/api/v1/sessions?limit=200", headers=_headers("admin_root", "ADMIN"))
    legacy = client.get("/api/sessions?limit=200", headers=_headers("admin_root", "ADMIN"))
    assert v1.status_code == legacy.status_code == 200
    assert v1.json()["total"] == legacy.json()["total"]
    assert _ids(v1.json()) == _ids(legacy.json())


def test_legacy_mount_matches_v1_for_viewer(api):
    client, _ = api
    v1 = client.get("/api/v1/sessions?limit=200", headers=_headers("viewer_ro", "VIEWER"))
    legacy = client.get("/api/sessions?limit=200", headers=_headers("viewer_ro", "VIEWER"))
    assert v1.status_code == legacy.status_code == 200
    assert v1.json()["total"] == legacy.json()["total"]
    assert _ids(v1.json()) == _ids(legacy.json())


def test_legacy_mount_matches_v1_for_faculty(api):
    client, _ = api
    v1 = client.get("/api/v1/sessions?limit=200", headers=_headers("faculty_ds", "FACULTY"))
    legacy = client.get("/api/sessions?limit=200", headers=_headers("faculty_ds", "FACULTY"))
    assert v1.status_code == legacy.status_code == 200
    assert v1.json()["total"] == legacy.json()["total"]
    assert _ids(v1.json()) == _ids(legacy.json())


# ---------------------------------------------------------------------------
# Totals are computed after authorization filtering
# ---------------------------------------------------------------------------

def test_total_is_the_authorized_count_not_the_institution_count(api):
    client, _ = api
    admin = client.get("/api/v1/sessions?limit=200", headers=_headers("admin_root", "ADMIN")).json()
    assert admin["total"] == 6

    faculty = client.get("/api/v1/sessions?limit=200", headers=_headers("faculty_ds", "FACULTY")).json()
    # faculty_ds owns A and F, coordinates D and is mapped to DIST-SYS.
    assert _ids(faculty) == {"SESS-A", "SESS-D", "SESS-F"}
    assert faculty["total"] == 3
    assert faculty["total"] < admin["total"], "the scoped total must not be the institution-wide count"

    viewer = client.get("/api/v1/sessions?limit=200", headers=_headers("viewer_ro", "VIEWER")).json()
    assert _ids(viewer) == {"SESS-C"}
    assert viewer["total"] == 1


# ---------------------------------------------------------------------------
# Pagination never exposes unauthorized sessions
# ---------------------------------------------------------------------------

def test_pagination_never_exposes_unauthorized_sessions(api):
    client, _ = api
    headers = _headers("faculty_ds", "FACULTY")
    seen = set()
    for offset in range(0, 10):
        page = client.get(f"/api/v1/sessions?limit=1&offset={offset}", headers=headers)
        assert page.status_code == 200
        payload = page.json()
        assert payload["total"] == 3, payload
        items = payload["items"]
        if not items:
            break
        seen |= _ids(payload)
    assert seen == {"SESS-A", "SESS-D", "SESS-F"}
    # Nothing outside the caller's scope is ever returned.
    assert not (seen & {"SESS-B", "SESS-C", "SESS-E"})


# ---------------------------------------------------------------------------
# Filters and search cannot bypass the scope
# ---------------------------------------------------------------------------

def test_filters_and_search_cannot_bypass_the_scope(api):
    client, _ = api
    headers = _headers("faculty_ds", "FACULTY")

    # A date that only contains somebody else's session.
    res = client.get("/api/v1/sessions?date=2026-03-16", headers=headers)
    assert res.status_code == 200
    assert res.json()["items"] == []
    assert res.json()["total"] == 0

    # A search term matching somebody else's session id.
    res = client.get("/api/v1/sessions?search=SESS-B", headers=headers)
    assert res.status_code == 200
    assert res.json()["items"] == []
    assert res.json()["total"] == 0

    # A search term matching somebody else's subject.
    res = client.get("/api/v1/sessions?search=Beta", headers=headers)
    assert res.status_code == 200
    assert "SESS-B" not in _ids(res.json())

    # The caller's own records are still reachable through the filters.
    res = client.get("/api/v1/sessions?search=Alpha", headers=headers)
    assert res.status_code == 200
    assert "SESS-A" in _ids(res.json())
