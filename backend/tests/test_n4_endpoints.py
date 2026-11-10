"""Tests for Wave 1 Prompt N4: teacher-subject mapping, session-create scoping, and meta config.

Covers the T-RBAC rows from docs/TESTS.md:
- GET /api/meta/config        -> 401 unauthenticated, 200 teacher, 200 admin
- GET /api/me/subjects        -> 401 unauthenticated, 200 teacher (own codes only)
- POST /api/admin/teacher-subjects -> 401, 403 teacher, 201 admin (+404/409/422)
- POST /api/sessions (assigned subject)    -> 201 teacher / 201 admin
- POST /api/sessions (unassigned subject)   -> 403 teacher / 201 admin
- Audit rows for SESSION_CREATE and TEACHER_SUBJECT_ASSIGN
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.db.base import Base
from app.db.models import AuditLog, TeacherSubject, User
from app.dependencies import get_db
from app.main import app
from app.schemas.auth import AuthenticatedUser, Role

# Unique IDs that do not exist in any real database (defensive isolation).
ADMIN_ID = "n4-admin-user"
FACULTY_TOM = "n4-faculty-tom"
FACULTY_SARA = "n4-faculty-sara"
FACULTY_OFF = "n4-faculty-off"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def test_db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)

    TestingSessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with TestingSessionLocal() as db:
        db.add_all(
            [
                User(
                    user_id=ADMIN_ID,
                    email="n4-admin@rollcall.test",
                    role="ADMIN",
                    hashed_password=None,
                    is_active=1,
                    created_at=_utcnow_iso(),
                ),
                User(
                    user_id=FACULTY_TOM,
                    email="n4-tom@rollcall.test",
                    role="FACULTY",
                    hashed_password=None,
                    is_active=1,
                    created_at=_utcnow_iso(),
                ),
                User(
                    user_id=FACULTY_SARA,
                    email="n4-sara@rollcall.test",
                    role="FACULTY",
                    hashed_password=None,
                    is_active=1,
                    created_at=_utcnow_iso(),
                ),
                User(
                    user_id=FACULTY_OFF,
                    email="n4-off@rollcall.test",
                    role="FACULTY",
                    hashed_password=None,
                    is_active=0,
                    created_at=_utcnow_iso(),
                ),
                TeacherSubject(user_id=FACULTY_TOM, subject_code="ML"),
                TeacherSubject(user_id=FACULTY_TOM, subject_code="CN"),
            ]
        )
        db.commit()

    yield engine
    engine.dispose()


@pytest.fixture
def as_user():
    """Override the authenticated user for the current test. None restores strict auth."""
    def _set(user: AuthenticatedUser | None) -> None:
        if user is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = lambda: user

    yield _set
    app.dependency_overrides.pop(get_current_user, None)


def _user(user_id: str, role: Role) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        email=f"{user_id}@rollcall.test",
        role=role,
        claims={"sub": user_id, "role": role.value},
    )


@pytest.fixture
def client(test_db_engine, as_user):
    TestingSessionLocal = sessionmaker(bind=test_db_engine, class_=Session, expire_on_commit=False)

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    # Default to a logged-in teacher for convenience; individual tests override.
    as_user(_user(FACULTY_TOM, Role.FACULTY))
    test_client = TestClient(app, raise_server_exceptions=False)
    yield test_client
    app.dependency_overrides.pop(get_db, None)


# ==============================================================================
# 1. GET /api/meta/config
# ==============================================================================

def test_meta_config_rejects_unauthenticated(client, as_user):
    as_user(None)
    res = client.get("/api/v1/meta/config")
    assert res.status_code == 401
    body = res.json()
    assert body["error"]["code"] in ("UNAUTHENTICATED", "UNAUTHORIZED")


def test_meta_config_teacher_and_admin(client, as_user):
    res = client.get("/api/v1/meta/config")
    assert res.status_code == 200
    data = res.json()
    assert data["edit_lock_hours"] == 24
    assert data["defaulter_threshold_percent"] == 75.0
    assert data["defaulter_required_percent"] == 75.0
    assert data["attendance_bands"]["green_above_percent"] == 85.0
    assert data["attendance_bands"]["yellow_from_percent"] == 70.0
    assert data["upload_limits"]["image_max_bytes"] == 10 * 1024 * 1024
    assert data["upload_limits"]["csv_max_bytes"] == 5 * 1024 * 1024
    assert data["chat_confirm_expiry_minutes"] == 5
    assert data["admin_override_allowed"] is True
    assert set(data["subject_codes"]) == {"ML", "CN"}

    as_user(_user(ADMIN_ID, Role.ADMIN))
    res2 = client.get("/api/meta/config")  # unversioned mount
    assert res2.status_code == 200
    assert res2.json()["edit_lock_hours"] == 24


def test_meta_config_env_override(client, as_user, monkeypatch):
    monkeypatch.setenv("EDIT_LOCK_HOURS", "48")
    monkeypatch.setenv("DEFAULTER_THRESHOLD_PERCENT", "80.5")
    res = client.get("/api/v1/meta/config")
    assert res.status_code == 200
    data = res.json()
    assert data["edit_lock_hours"] == 48
    assert data["defaulter_threshold_percent"] == 80.5


# ==============================================================================
# 2. GET /api/me/subjects
# ==============================================================================

def test_me_subjects_rejects_unauthenticated(client, as_user):
    as_user(None)
    res = client.get("/api/v1/me/subjects")
    assert res.status_code == 401


def test_me_subjects_returns_own_codes_only(client, as_user):
    res = client.get("/api/v1/me/subjects")
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == FACULTY_TOM
    assert data["role"] == "FACULTY"
    assert sorted(data["subject_codes"]) == ["CN", "ML"]

    as_user(_user(FACULTY_SARA, Role.FACULTY))
    res2 = client.get("/api/v1/me/subjects")
    assert res2.status_code == 200
    assert res2.json()["subject_codes"] == []
    assert res2.json()["user_id"] == FACULTY_SARA


def test_me_subjects_admin_mount(client, as_user):
    as_user(_user(ADMIN_ID, Role.ADMIN))
    res = client.get("/api/me/subjects")  # unversioned mount
    assert res.status_code == 200
    assert res.json()["subject_codes"] == []


# ==============================================================================
# 3. POST /api/admin/teacher-subjects
# ==============================================================================

def test_admin_teacher_subjects_rejects_unauthenticated(client, as_user):
    as_user(None)
    res = client.post("/api/v1/admin/teacher-subjects", json={"user_id": FACULTY_SARA, "subject_code": "ML"})
    assert res.status_code == 401


def test_admin_teacher_subjects_teacher_forbidden(client, as_user):
    res = client.post(
        "/api/v1/admin/teacher-subjects",
        json={"user_id": FACULTY_TOM, "subject_code": "DB-SYS"},
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"


def test_admin_teacher_subjects_assignment_flow(client, as_user):
    as_user(_user(ADMIN_ID, Role.ADMIN))

    res = client.post(
        "/api/v1/admin/teacher-subjects",
        json={"user_id": FACULTY_SARA, "subject_code": " ml "},  # normalization + whitespace
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["user_id"] == FACULTY_SARA
    assert data["subject_code"] == "ML"

    # Duplicate -> 409
    dup = client.post(
        "/api/v1/admin/teacher-subjects",
        json={"user_id": FACULTY_SARA, "subject_code": "ML"},
    )
    assert dup.status_code == 409
    assert FACULTY_SARA in dup.json()["error"]["message"]

    # Unknown user -> 404
    missing = client.post(
        "/api/v1/admin/teacher-subjects",
        json={"user_id": "n4-ghost", "subject_code": "ML"},
    )
    assert missing.status_code == 404

    # Non-FACULTY target -> 422
    not_faculty = client.post(
        "/api/v1/admin/teacher-subjects",
        json={"user_id": ADMIN_ID, "subject_code": "ML"},
    )
    assert not_faculty.status_code == 422

    # Deactivated FACULTY target -> 422
    deactivated = client.post(
        "/api/v1/admin/teacher-subjects",
        json={"user_id": FACULTY_OFF, "subject_code": "ML"},
    )
    assert deactivated.status_code == 422

    # Listing (filter by user)
    listing = client.get("/api/v1/admin/teacher-subjects", params={"user_id": FACULTY_SARA})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["subject_code"] == "ML"


def test_admin_teacher_subjects_assignment_audited(client, as_user, test_db_engine):
    as_user(_user(ADMIN_ID, Role.ADMIN))
    res = client.post(
        "/api/v1/admin/teacher-subjects",
        json={"user_id": FACULTY_SARA, "subject_code": "ES"},
    )
    assert res.status_code == 201

    TestingSessionLocal = sessionmaker(bind=test_db_engine, class_=Session, expire_on_commit=False)
    with TestingSessionLocal() as db:
        rows = db.execute(
            select(AuditLog).where(
                AuditLog.action == "TEACHER_SUBJECT_ASSIGN",
                AuditLog.actor_id == ADMIN_ID,
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].entity_id == f"{FACULTY_SARA}:ES"
        assert rows[0].new_value == "ES"


# ==============================================================================
# 4. POST /api/sessions (N4 scoping)
# ==============================================================================

def test_session_create_requires_authentication(client, as_user):
    as_user(None)
    res = client.post(
        "/api/v1/sessions",
        json={"session_id": "N4-SESS-1", "date": "2026-11-10", "subject": "Machine Learning"},
    )
    assert res.status_code == 401


def test_faculty_can_create_session_for_assigned_subject(client, as_user, test_db_engine):
    res = client.post(
        "/api/v1/sessions",
        json={
            "session_id": "N4-SESS-TOM-1",
            "date": "2026-11-10",
            "subject": "Machine Learning",
            "subject_code": "ML",
        },
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["teacher_id"] == FACULTY_TOM  # bound to token subject, not body
    assert data["subject_code"] == "ML"
    assert data["created_at"] is not None

    TestingSessionLocal = sessionmaker(bind=test_db_engine, class_=Session, expire_on_commit=False)
    with TestingSessionLocal() as db:
        rows = db.execute(
            select(AuditLog).where(
                AuditLog.action == "SESSION_CREATE",
                AuditLog.actor_id == FACULTY_TOM,
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].entity_id == "N4-SESS-TOM-1"


def test_faculty_cannot_create_session_for_unassigned_subject(client, as_user):
    res = client.post(
        "/api/v1/sessions",
        json={
            "session_id": "N4-SESS-TOM-2",
            "date": "2026-11-10",
            "subject": "Distributed Systems",
            "subject_code": "DIST-SYS",
        },
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"


def test_faculty_session_without_subject_code_rejected(client, as_user):
    res = client.post(
        "/api/v1/sessions",
        json={"session_id": "N4-SESS-TOM-3", "date": "2026-11-10", "subject": "Machine Learning"},
    )
    assert res.status_code == 422


def test_faculty_teacher_id_in_body_is_ignored(client, as_user, test_db_engine):
    res = client.post(
        "/api/v1/sessions",
        json={
            "session_id": "N4-SESS-TOM-4",
            "date": "2026-11-10",
            "subject": "Computer Networks",
            "subject_code": "CN",
            "teacher_id": ADMIN_ID,  # must be ignored: identity comes from the token only
        },
    )
    assert res.status_code == 201
    assert res.json()["teacher_id"] == FACULTY_TOM


def test_admin_can_create_session_for_any_subject(client, as_user):
    as_user(_user(ADMIN_ID, Role.ADMIN))
    res = client.post(
        "/api/v1/sessions",
        json={
            "session_id": "N4-SESS-ADMIN-1",
            "date": "2026-11-10",
            "subject": "Distributed Systems",
            "subject_code": "DIST-SYS",
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["teacher_id"] is None
    assert res.json()["subject_code"] == "DIST-SYS"

    # No subject code at all is also fine for admin
    res2 = client.post(
        "/api/v1/sessions",
        json={"session_id": "N4-SESS-ADMIN-2", "date": "2026-11-11", "subject": "Open Elective"},
    )
    assert res2.status_code == 201
    assert res2.json()["subject_code"] is None


def test_admin_can_attribute_session_to_existing_faculty(client, as_user):
    as_user(_user(ADMIN_ID, Role.ADMIN))
    res = client.post(
        "/api/v1/sessions",
        json={
            "session_id": "N4-SESS-ADMIN-3",
            "date": "2026-11-10",
            "subject": "Machine Learning",
            "subject_code": "ML",
            "teacher_id": FACULTY_TOM,
        },
    )
    assert res.status_code == 201
    assert res.json()["teacher_id"] == FACULTY_TOM

    # Unknown teacher -> 404
    res2 = client.post(
        "/api/v1/sessions",
        json={
            "session_id": "N4-SESS-ADMIN-4",
            "date": "2026-11-10",
            "subject": "Machine Learning",
            "subject_code": "ML",
            "teacher_id": "n4-ghost",
        },
    )
    assert res2.status_code == 404

    # Non-faculty teacher -> 422
    res3 = client.post(
        "/api/v1/sessions",
        json={
            "session_id": "N4-SESS-ADMIN-5",
            "date": "2026-11-10",
            "subject": "Machine Learning",
            "subject_code": "ML",
            "teacher_id": ADMIN_ID,
        },
    )
    assert res3.status_code == 422


def test_session_duplicate_conflict(client, as_user):
    res = client.post(
        "/api/v1/sessions",
        json={
            "session_id": "N4-SESS-DUP",
            "date": "2026-11-10",
            "subject": "Machine Learning",
            "subject_code": "ML",
        },
    )
    assert res.status_code == 201
    dup = client.post(
        "/api/v1/sessions",
        json={
            "session_id": "N4-SESS-DUP",
            "date": "2026-11-10",
            "subject": "Machine Learning",
            "subject_code": "ML",
        },
    )
    assert dup.status_code == 409


def test_viewer_cannot_create_sessions(client, as_user):
    as_user(_user("n4-viewer", Role.VIEWER))
    res = client.post(
        "/api/v1/sessions",
        json={
            "session_id": "N4-SESS-V",
            "date": "2026-11-10",
            "subject": "Machine Learning",
            "subject_code": "ML",
        },
    )
    assert res.status_code == 403


def test_sessions_list_includes_scoping_fields(client, as_user):
    client.post(
        "/api/v1/sessions",
        json={
            "session_id": "N4-SESS-LIST",
            "date": "2026-11-10",
            "subject": "Machine Learning",
            "subject_code": "ML",
        },
    )
    res = client.get("/api/v1/sessions", params={"search": "N4-SESS-LIST"})
    assert res.status_code == 200
    item = res.json()["items"][0]
    assert item["session_id"] == "N4-SESS-LIST"
    assert item["teacher_id"] == FACULTY_TOM
    assert item["subject_code"] == "ML"
    assert item["created_at"] is not None
