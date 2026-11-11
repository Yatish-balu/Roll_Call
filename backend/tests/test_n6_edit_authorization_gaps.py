"""N6 verification-gap tests: write-path authorization, atomicity and persistence.

These close the gaps identified in the N6 audit:
  * subject-mapping and coordinator authorization on the attendance WRITE path;
  * the untested PermissionError branches of apply_attendance_edit_atomic()
    (wrong user, wrong role, unassigned faculty, missing session);
  * HTTP-level proof that a successful edit is persisted in the database;
  * proof that the attendance change and its audit row roll back together.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session as OrmSession, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.jwt import create_access_token
from app.db.base import Base
from app.db import crud
from app.db.models import (
    Attendance,
    AuditLog,
    Room,
    Session as DbSession,
    Student,
    TeacherSubject,
    User,
)
from app.dependencies import get_db
from app.main import app

pytestmark = pytest.mark.no_auth_override

TEST_SECRET = "test-secret-key-for-n6-gap-tests-at-least-32-characters"


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
            ("faculty_coord", "FACULTY"),
            ("faculty_other", "FACULTY"),
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
        db.add(Room(room_id="LH-101", name="Lecture Hall 101"))
        db.add(Student(usn="1MS21CS001", name="Alice Smith", branch="CSE"))
        db.add(Student(usn="1MS21CS002", name="Bob Jones", branch="CSE"))
        # The migration-0002 sentinel for sessions that predate ownership.
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

        # legacy/unowned session, reachable through the ML subject mapping
        db.add(
            DbSession(
                session_id="SESS-LEGACY-ML",
                date="2020-01-01",
                subject="Machine Learning",
                teacher_id="legacy",
                subject_code="ML",
            )
        )
        # unowned session, reachable through the coordinator
        db.add(
            DbSession(
                session_id="SESS-COORD",
                date="2020-01-02",
                subject="Computer Networks",
                teacher_id=None,
                subject_code=None,
                coordinator_faculty_id="faculty_coord",
            )
        )
        # owned by faculty_ds
        db.add(
            DbSession(
                session_id="SESS-OWNED",
                date="2020-01-03",
                subject="Distributed Systems",
                teacher_id="faculty_ds",
                subject_code="DIST-SYS",
            )
        )
        db.add(TeacherSubject(user_id="faculty_ml", subject_code="ML"))
        db.add(TeacherSubject(user_id="faculty_ds", subject_code="DIST-SYS"))
        for session_id, usn in (
            ("SESS-LEGACY-ML", "1MS21CS001"),
            ("SESS-COORD", "1MS21CS002"),
            ("SESS-OWNED", "1MS21CS001"),
        ):
            db.add(
                Attendance(
                    attendance_id=f"ATT-{session_id}-{usn}",
                    session_id=session_id,
                    usn=usn,
                    room_id="LH-101",
                    status="PRESENT",
                    source="camera",
                    confidence=0.95,
                    recorded_at="2020-01-01T09:00:00Z",
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


def _status(factory, session_id, usn):
    with factory() as db:
        row = db.execute(
            select(Attendance).where(
                Attendance.session_id == session_id, Attendance.usn == usn
            )
        ).scalars().first()
        return row.status if row else None


def _audit_rows(factory, **filters):
    table = AuditLog.__table__
    with factory() as db:
        stmt = select(table).order_by(table.c.log_id)
        for column, value in filters.items():
            stmt = stmt.where(table.c[column] == value)
        return [dict(row) for row in db.execute(stmt).mappings().all()]


# ---------------------------------------------------------------------------
# Write-path authorization: subject mapping and coordinator
# ---------------------------------------------------------------------------

def test_subject_mapping_authorizes_an_attendance_write(api):
    """A mapped faculty member may edit a legacy (unowned) session."""
    client, factory = api
    res = client.post(
        "/api/v1/attendance/sessions/SESS-LEGACY-ML/record?upsert=true",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
        headers=_headers("faculty_ml", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    assert _status(factory, "SESS-LEGACY-ML", "1MS21CS001") == "ABSENT"
    rows = _audit_rows(factory, action="ATTENDANCE_UPSERT")
    assert len(rows) == 1
    assert rows[0]["actor_id"] == "faculty_ml"
    assert rows[0]["actor_role"] == "FACULTY"


def test_unmapped_faculty_cannot_write_to_a_legacy_session(api):
    client, factory = api
    res = client.post(
        "/api/v1/attendance/sessions/SESS-LEGACY-ML/record?upsert=true",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
        headers=_headers("faculty_other", "FACULTY"),
    )
    assert res.status_code == 403, res.text
    assert _status(factory, "SESS-LEGACY-ML", "1MS21CS001") == "PRESENT"
    assert _audit_rows(factory) == []


def test_coordinator_authorizes_an_attendance_write(api):
    client, factory = api
    res = client.post(
        "/api/v1/attendance/sessions/SESS-COORD/record?upsert=true",
        json={"usn": "1MS21CS002", "room_id": "LH-101", "status": "PENDING"},
        headers=_headers("faculty_coord", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    assert _status(factory, "SESS-COORD", "1MS21CS002") == "PENDING"
    rows = _audit_rows(factory, action="ATTENDANCE_UPSERT")
    assert len(rows) == 1
    assert rows[0]["actor_id"] == "faculty_coord"


def test_viewer_cannot_write_attendance(api):
    client, factory = api
    res = client.post(
        "/api/v1/attendance/sessions/SESS-OWNED/record?upsert=true",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
        headers=_headers("viewer_ro", "VIEWER"),
    )
    assert res.status_code == 403, res.text
    assert _status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"
    assert _audit_rows(factory) == []


# ---------------------------------------------------------------------------
# HTTP-level persistence
# ---------------------------------------------------------------------------

def test_successful_single_edit_is_persisted_in_the_database(api):
    client, factory = api
    res = client.post(
        "/api/v1/attendance/sessions/SESS-OWNED/record?upsert=true",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    # Re-read the row from the database (not from the response body).
    assert _status(factory, "SESS-OWNED", "1MS21CS001") == "ABSENT"
    with factory() as db:
        row = db.execute(
            select(Attendance).where(
                Attendance.session_id == "SESS-OWNED",
                Attendance.usn == "1MS21CS001",
            )
        ).scalars().one()
        assert row.status == "ABSENT"
        assert row.source == "manual"


def test_successful_bulk_edit_is_persisted_in_the_database(api):
    client, factory = api
    res = client.post(
        "/api/v1/attendance/sessions/SESS-OWNED/bulk?upsert=true",
        json={
            "records": [
                {"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
                {"usn": "1MS21CS002", "room_id": "LH-101", "status": "PENDING"},
            ]
        },
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 201, res.text
    assert _status(factory, "SESS-OWNED", "1MS21CS001") == "ABSENT"
    assert _status(factory, "SESS-OWNED", "1MS21CS002") == "PENDING"
    rows = _audit_rows(factory, action="ATTENDANCE_BULK_UPSERT")
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# Atomicity: attendance and audit roll back together
# ---------------------------------------------------------------------------

def test_bulk_edit_rolls_back_when_the_audit_insert_fails(api, monkeypatch):
    client, factory = api

    def boom(*args, **kwargs):
        raise RuntimeError("audit backend unavailable")

    monkeypatch.setattr(crud, "create_audit_entry", boom)
    res = client.post(
        "/api/v1/attendance/sessions/SESS-OWNED/bulk?upsert=true",
        json={"records": [{"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"}]},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code >= 500, res.text
    monkeypatch.undo()
    assert _status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"
    assert _audit_rows(factory) == []


def test_replace_rolls_back_when_the_audit_insert_fails(api, monkeypatch):
    client, factory = api

    def boom(*args, **kwargs):
        raise RuntimeError("audit backend unavailable")

    monkeypatch.setattr(crud, "create_audit_entry", boom)
    res = client.put(
        "/api/v1/attendance/sessions/SESS-OWNED",
        json={"records": [{"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"}]},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code >= 500, res.text
    monkeypatch.undo()
    assert _status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"
    assert _audit_rows(factory) == []


# ---------------------------------------------------------------------------
# apply_attendance_edit_atomic: the previously untested branches
# ---------------------------------------------------------------------------

def _pending(factory, **overrides):
    payload = {
        "user_id": "faculty_ds",
        "session_id": "SESS-OWNED",
        "usn": "1MS21CS001",
        "old_status": "PRESENT",
        "new_status": "ABSENT",
    }
    payload.update(overrides)
    with factory() as db:
        edit = crud.create_pending_edit(db, **payload)
        db.commit()
        return edit["edit_id"]


def test_pending_edit_rejects_a_different_user(api):
    _, factory = api
    edit_id = _pending(factory, user_id="faculty_ds")
    with factory() as db:
        with pytest.raises(PermissionError):
            crud.apply_attendance_edit_atomic(
                db,
                edit_id=edit_id,
                user_id="faculty_other",
                authenticated_role="FACULTY",
            )
        db.rollback()
    assert _status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"
    assert _audit_rows(factory) == []


def test_pending_edit_rejects_an_unauthorized_role(api):
    _, factory = api
    edit_id = _pending(factory)
    with factory() as db:
        with pytest.raises(PermissionError):
            crud.apply_attendance_edit_atomic(
                db,
                edit_id=edit_id,
                user_id="faculty_ds",
                authenticated_role="VIEWER",
            )
        db.rollback()
    assert _status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"
    assert _audit_rows(factory) == []


def test_pending_edit_rejects_an_unassigned_faculty_member(api):
    _, factory = api
    # A pending edit that belongs to faculty_ds, applied by an unassigned peer.
    edit_id = _pending(factory, user_id="faculty_other")
    with factory() as db:
        with pytest.raises(PermissionError):
            crud.apply_attendance_edit_atomic(
                db,
                edit_id=edit_id,
                user_id="faculty_other",
                authenticated_role="FACULTY",
            )
        db.rollback()
    assert _status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"
    assert _audit_rows(factory) == []


def test_pending_edit_rejects_a_missing_session(api):
    _, factory = api
    edit_id = _pending(factory)
    with factory() as db:
        db.execute(text("DELETE FROM sessions WHERE session_id = 'SESS-OWNED'"))
        db.commit()
        with pytest.raises(ValueError) as excinfo:
            crud.apply_attendance_edit_atomic(
                db,
                edit_id=edit_id,
                user_id="faculty_ds",
                authenticated_role="FACULTY",
            )
        db.rollback()
    assert "no longer exists" in str(excinfo.value).lower()
    assert _audit_rows(factory) == []
