"""N5 regression tests: unlimited attendance editing with complete audit logging.

The approved policy:
  * faculty may edit attendance regardless of session age or lifecycle status;
  * there is NO 24-hour editing lock and no mandatory admin override reason;
  * every successful modification is audited (actor, role, session, student,
    previous status, new status, UTC timestamp);
  * failed, rejected and unauthorized modifications never produce a
    successful-edit audit event;
  * authentication, RBAC, session ownership and authorization stay enforced.

These tests exercise the real HTTP API (TestClient) with real JWT verification
and inspect the append-only audit log directly.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

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

TEST_SECRET = "test-secret-key-for-n5-audit-must-be-at-least-32-chars-long"

# A session that is years old and already completed: it must stay editable.
OLD_DATE = "2020-01-01"
OLD_TIMESTAMP = "2020-01-01T09:00:00Z"


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


@pytest.fixture
def api(monkeypatch):
    """App client over an in-memory database with real JWT verification."""
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
        ):
            db.add(
                User(
                    user_id=uid,
                    email=f"{uid}@rollcall.edu",
                    role=role,
                    hashed_password=None,
                    is_active=1,
                    created_at=OLD_TIMESTAMP,
                )
            )
        db.add(Room(room_id="LH-101", name="Lecture Hall 101"))
        db.add(Student(usn="1MS21CS001", name="Alice Smith", branch="CSE"))
        db.add(Student(usn="1MS21CS002", name="Bob Jones", branch="CSE"))
        # Old, completed, owned by faculty_ds.
        db.add(
            DbSession(
                session_id="SESS-OLD",
                date=OLD_DATE,
                subject="Distributed Systems",
                created_at=OLD_TIMESTAMP,
                teacher_id="faculty_ds",
                subject_code="DIST-SYS",
                lifecycle_status="COMPLETED",
            )
        )
        db.add(
            DbSession(
                session_id="SESS-RECENT",
                date="2026-03-15",
                subject="Distributed Systems",
                created_at="2026-03-15T09:00:00Z",
                teacher_id="faculty_ds",
                subject_code="DIST-SYS",
                lifecycle_status="COMPLETED",
            )
        )
        db.add(TeacherSubject(user_id="faculty_ds", subject_code="DIST-SYS"))
        db.add(TeacherSubject(user_id="faculty_ml", subject_code="ML"))
        db.add(
            Attendance(
                attendance_id="ATT-OLD-1",
                session_id="SESS-OLD",
                usn="1MS21CS001",
                room_id="LH-101",
                status="PRESENT",
                source="camera",
                confidence=0.95,
                recorded_at=OLD_TIMESTAMP,
            )
        )
        db.add(
            Attendance(
                attendance_id="ATT-OLD-2",
                session_id="SESS-OLD",
                usn="1MS21CS002",
                room_id="LH-101",
                status="PRESENT",
                source="camera",
                confidence=0.95,
                recorded_at=OLD_TIMESTAMP,
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


def _audit_rows(factory, **filters):
    table = AuditLog.__table__
    with factory() as db:
        stmt = select(table).order_by(table.c.log_id)
        for column, value in filters.items():
            stmt = stmt.where(table.c[column] == value)
        return [dict(row) for row in db.execute(stmt).mappings().all()]


# ---------------------------------------------------------------------------
# 1 + 2. Unlimited editing: old sessions and COMPLETED sessions stay editable
# ---------------------------------------------------------------------------

def test_edit_allowed_on_session_older_than_24_hours(api):
    client, _ = api
    res = client.post(
        "/api/v1/attendance/sessions/SESS-OLD/record?upsert=true",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ABSENT"


def test_edit_allowed_on_completed_session(api):
    client, factory = api
    with factory() as db:
        assert db.get(DbSession, "SESS-OLD").lifecycle_status == "COMPLETED"

    res = client.post(
        "/api/v1/attendance/sessions/SESS-OLD/record?upsert=true",
        json={"usn": "1MS21CS002", "room_id": "LH-101", "status": "PENDING"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "PENDING"


def test_bulk_edit_allowed_on_old_completed_session(api):
    client, _ = api
    res = client.post(
        "/api/v1/attendance/sessions/SESS-OLD/bulk?upsert=true",
        json={
            "records": [
                {"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
                {"usn": "1MS21CS002", "room_id": "LH-101", "status": "ABSENT"},
            ]
        },
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 201, res.text


# ---------------------------------------------------------------------------
# 3 + 4 + 5. Audit records: per student, with actor identity and role
# ---------------------------------------------------------------------------

def test_individual_edit_writes_one_audit_record_with_actor_and_role(api):
    client, factory = api
    res = client.post(
        "/api/v1/attendance/sessions/SESS-OLD/record?upsert=true",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text

    rows = _audit_rows(factory, action="ATTENDANCE_UPSERT", usn="1MS21CS001")
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["actor_id"] == "faculty_ds"
    assert row["actor_role"] == "FACULTY"
    assert row["session_id"] == "SESS-OLD"
    assert row["old_value"] == "PRESENT"
    assert row["new_value"] == "ABSENT"
    # UTC timestamp in canonical ISO 8601 Z form.
    assert row["timestamp"].endswith("Z")
    datetime.strptime(row["timestamp"], "%Y-%m-%dT%H:%M:%SZ")


def test_bulk_edit_writes_one_audit_record_per_student(api):
    client, factory = api
    res = client.post(
        "/api/v1/attendance/sessions/SESS-OLD/bulk?upsert=true",
        json={
            "records": [
                {"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
                {"usn": "1MS21CS002", "room_id": "LH-101", "status": "PENDING"},
            ]
        },
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 201, res.text

    rows = _audit_rows(factory, action="ATTENDANCE_BULK_UPSERT")
    assert len(rows) == 2, rows
    by_usn = {r["usn"]: r for r in rows}
    assert set(by_usn) == {"1MS21CS001", "1MS21CS002"}
    for row in rows:
        assert row["actor_id"] == "faculty_ds"
        assert row["actor_role"] == "FACULTY"
        assert row["session_id"] == "SESS-OLD"
        assert row["old_value"] == "PRESENT"
        assert row["timestamp"].endswith("Z")
    assert by_usn["1MS21CS001"]["new_value"] == "ABSENT"
    assert by_usn["1MS21CS002"]["new_value"] == "PENDING"


def test_replace_edit_writes_one_audit_record_per_affected_student(api):
    client, factory = api
    res = client.put(
        "/api/v1/attendance/sessions/SESS-OLD",
        json={
            "records": [
                {"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
            ]
        },
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text

    rows = _audit_rows(factory, action="ATTENDANCE_REPLACE")
    # Both students were affected: one changed, one removed.
    assert len(rows) == 2, rows
    by_usn = {r["usn"]: r for r in rows}
    assert by_usn["1MS21CS001"]["old_value"] == "PRESENT"
    assert by_usn["1MS21CS001"]["new_value"] == "ABSENT"
    assert by_usn["1MS21CS002"]["old_value"] == "PRESENT"
    assert by_usn["1MS21CS002"]["new_value"] is None


def test_actor_identity_and_role_come_from_the_verified_authentication(api):
    """A token claiming ADMIN does not make the actor an administrator."""
    client, factory = api
    # The token claims ADMIN, but the database role is authoritative (FACULTY).
    res = client.post(
        "/api/v1/attendance/sessions/SESS-OLD/record?upsert=true",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
        headers=_headers("faculty_ds", "ADMIN"),
    )
    assert res.status_code == 200, res.text

    rows = _audit_rows(factory, action="ATTENDANCE_UPSERT")
    assert len(rows) == 1
    assert rows[0]["actor_id"] == "faculty_ds"
    assert rows[0]["actor_role"] == "FACULTY", rows[0]


def test_admin_edit_is_audited_with_the_admin_role(api):
    client, factory = api
    res = client.post(
        "/api/v1/attendance/sessions/SESS-OLD/record?upsert=true",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
        headers=_headers("admin_root", "ADMIN"),
    )
    assert res.status_code == 200, res.text
    rows = _audit_rows(factory, action="ATTENDANCE_UPSERT")
    assert rows[0]["actor_id"] == "admin_root"
    assert rows[0]["actor_role"] == "ADMIN"


# ---------------------------------------------------------------------------
# 6. The attendance change and its audit live in one transaction
# ---------------------------------------------------------------------------

def test_attendance_change_rolls_back_when_the_audit_insert_fails(api, monkeypatch):
    client, factory = api

    def boom(*args, **kwargs):
        raise RuntimeError("audit backend unavailable")

    monkeypatch.setattr(crud, "create_audit_entry", boom)

    res = client.post(
        "/api/v1/attendance/sessions/SESS-OLD/record?upsert=true",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code >= 500, res.text

    monkeypatch.undo()
    with factory() as db:
        row = db.execute(
            select(Attendance).where(
                Attendance.session_id == "SESS-OLD",
                Attendance.usn == "1MS21CS001",
            )
        ).scalars().one()
        assert row.status == "PRESENT", "the attendance change must be rolled back"
    assert _audit_rows(factory, action="ATTENDANCE_UPSERT") == []


# ---------------------------------------------------------------------------
# 7. Unauthorized / rejected edits never produce a successful-edit audit event
# ---------------------------------------------------------------------------

def test_unauthorized_edit_creates_no_audit_record(api):
    client, factory = api
    res = client.post(
        "/api/v1/attendance/sessions/SESS-OLD/record?upsert=true",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
        headers=_headers("faculty_ml", "FACULTY"),
    )
    assert res.status_code == 403, res.text
    assert _audit_rows(factory) == []
    with factory() as db:
        row = db.execute(
            select(Attendance).where(
                Attendance.session_id == "SESS-OLD",
                Attendance.usn == "1MS21CS001",
            )
        ).scalars().one()
        assert row.status == "PRESENT"


def test_rejected_duplicate_edit_creates_no_audit_record(api):
    client, factory = api
    res = client.post(
        "/api/v1/attendance/sessions/SESS-OLD/record",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 409, res.text
    assert _audit_rows(factory) == []


def test_invalid_status_edit_creates_no_audit_record(api):
    client, factory = api
    res = client.post(
        "/api/v1/attendance/sessions/SESS-OLD/record?upsert=true",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "MAYBE"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code in (400, 422), res.text
    assert _audit_rows(factory) == []


# ---------------------------------------------------------------------------
# 8. Chat confirmation uses the same authorization and audit path
# ---------------------------------------------------------------------------

def test_chat_confirmation_is_authorized_and_audited(api):
    client, factory = api
    res = client.post(
        "/api/v1/agent/confirm",
        json={
            "session_id": "SESS-RECENT",
            "confirmed": True,
            "records": [
                {"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "confidence": 1.0}
            ],
        },
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text

    rows = _audit_rows(factory, action="ATTENDANCE_AGENT_CONFIRM")
    assert len(rows) == 1, rows
    assert rows[0]["actor_id"] == "faculty_ds"
    assert rows[0]["actor_role"] == "FACULTY"
    assert rows[0]["session_id"] == "SESS-RECENT"
    assert rows[0]["usn"] == "1MS21CS001"
    assert rows[0]["new_value"] == "PRESENT"
    assert rows[0]["timestamp"].endswith("Z")


def test_chat_confirmation_for_an_unauthorized_session_is_denied_and_unaudited(api):
    client, factory = api
    res = client.post(
        "/api/v1/agent/confirm",
        json={
            "session_id": "SESS-OLD",
            "confirmed": True,
            "records": [
                {"usn": "1MS21CS002", "room_id": "LH-101", "status": "ABSENT", "confidence": 1.0}
            ],
        },
        headers=_headers("faculty_ml", "FACULTY"),
    )
    assert res.status_code == 403, res.text
    assert _audit_rows(factory) == []


def test_chat_confirmation_never_trusts_role_claims_from_the_payload(api):
    """A chat payload cannot elevate the caller's role."""
    client, factory = api
    res = client.post(
        "/api/v1/agent/confirm",
        json={
            "session_id": "SESS-OLD",
            "confirmed": True,
            "role": "ADMIN",
            "actor_id": "admin_root",
            "records": [
                {"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT", "confidence": 1.0}
            ],
        },
        headers=_headers("faculty_ml", "FACULTY"),
    )
    assert res.status_code == 403, res.text
    assert _audit_rows(factory) == []


# ---------------------------------------------------------------------------
# 9. The legacy UI commit goes through the same audit path
# ---------------------------------------------------------------------------

def test_ui_commit_is_audited(tmp_path):
    from app.db.schema import init_db
    from app.ui import commit_session_to_database

    db_file = tmp_path / "ui_commit.db"
    conn = sqlite3.connect(db_file)
    init_db(conn)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute(
        "INSERT INTO users (user_id, email, role, hashed_password, is_active, created_at) "
        "VALUES (?, ?, ?, NULL, 1, ?)",
        ("faculty_ds", "faculty_ds@rollcall.edu", "FACULTY", "2026-01-01T00:00:00Z"),
    )
    conn.execute("INSERT INTO students (usn, name, branch) VALUES (?, ?, ?)",
                 ("1MS21CS001", "Alice Smith", "CSE"))
    conn.execute("INSERT INTO rooms (room_id, name) VALUES (?, ?)", ("LH-101", "Lecture Hall 101"))
    conn.commit()
    conn.close()

    ok, msg = commit_session_to_database(
        db_target=str(db_file),
        session_id="SESS-UI-01",
        records=[
            {"usn": "1MS21CS001", "name": "Alice Smith", "room_id": "LH-101", "status": "PRESENT", "confidence": 1.0}
        ],
        actor_id="faculty_ds",
        actor_role="FACULTY",
    )
    assert ok is True, msg

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM audit_log").fetchall()]
    conn.close()
    assert len(rows) == 1, rows
    assert rows[0]["actor_id"] == "faculty_ds"
    assert rows[0]["actor_role"] == "FACULTY"
    assert rows[0]["session_id"] == "SESS-UI-01"
    assert rows[0]["usn"] == "1MS21CS001"
    assert rows[0]["new_value"] == "PRESENT"


def test_ui_commit_without_an_actor_is_audited_as_the_system_principal(tmp_path):
    from app.db.schema import init_db
    from app.ui import commit_session_to_database

    db_file = tmp_path / "ui_commit_system.db"
    conn = sqlite3.connect(db_file)
    init_db(conn)
    conn.execute("INSERT INTO students (usn, name, branch) VALUES (?, ?, ?)",
                 ("1MS21CS001", "Alice Smith", "CSE"))
    conn.execute("INSERT INTO rooms (room_id, name) VALUES (?, ?)", ("LH-101", "Lecture Hall 101"))
    conn.commit()
    conn.close()

    ok, msg = commit_session_to_database(
        db_target=str(db_file),
        session_id="SESS-UI-02",
        records=[
            {"usn": "1MS21CS001", "name": "Alice Smith", "room_id": "LH-101", "status": "PRESENT", "confidence": 1.0}
        ],
    )
    assert ok is True, msg

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM audit_log").fetchall()]
    conn.close()
    assert len(rows) == 1, rows
    assert rows[0]["actor_id"] == "system"
    assert rows[0]["actor_role"] == "SYSTEM"


# ---------------------------------------------------------------------------
# 10. Pending-edit expiry, single use and replay protection stay intact
# ---------------------------------------------------------------------------

def test_pending_edit_is_applied_once_and_records_the_actor_role(api):
    client, factory = api
    with factory() as db:
        edit = crud.create_pending_edit(
            db,
            user_id="faculty_ds",
            session_id="SESS-OLD",
            usn="1MS21CS001",
            old_status="PRESENT",
            new_status="ABSENT",
        )
        db.commit()
        result = crud.apply_attendance_edit_atomic(
            db,
            edit_id=edit["edit_id"],
            user_id="faculty_ds",
            authenticated_role="FACULTY",
        )
        db.commit()
        assert result["new_status"] == "ABSENT"

    rows = _audit_rows(factory, action="ATTENDANCE_EDIT")
    assert len(rows) == 1, rows
    assert rows[0]["actor_id"] == "faculty_ds"
    assert rows[0]["actor_role"] == "FACULTY"
    assert rows[0]["old_value"] == "PRESENT"
    assert rows[0]["new_value"] == "ABSENT"

    # Replay: the same pending edit cannot be consumed twice.
    with factory() as db:
        with pytest.raises(ValueError):
            crud.apply_attendance_edit_atomic(
                db,
                edit_id=edit["edit_id"],
                user_id="faculty_ds",
                authenticated_role="FACULTY",
            )
        db.rollback()
    assert len(_audit_rows(factory, action="ATTENDANCE_EDIT")) == 1


def test_expired_pending_edit_is_rejected(api):
    _, factory = api
    with factory() as db:
        # A pending edit whose expiry is already in the past.
        edit = crud.create_pending_edit(
            db,
            user_id="faculty_ds",
            session_id="SESS-OLD",
            usn="1MS21CS001",
            old_status="PRESENT",
            new_status="ABSENT",
            ttl_minutes=-1,
        )
        db.commit()
        with pytest.raises(ValueError):
            crud.apply_attendance_edit_atomic(
                db,
                edit_id=edit["edit_id"],
                user_id="faculty_ds",
                authenticated_role="FACULTY",
            )
        db.rollback()
    assert _audit_rows(factory, action="ATTENDANCE_EDIT") == []


# ---------------------------------------------------------------------------
# 11. The audit log stays append-only
# ---------------------------------------------------------------------------

def test_audit_log_cannot_be_updated_or_deleted(api):
    client, factory = api
    res = client.post(
        "/api/v1/attendance/sessions/SESS-OLD/record?upsert=true",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text

    with factory() as db:
        with pytest.raises(Exception):
            db.execute(text("UPDATE audit_log SET new_value = 'TAMPERED'"))
        db.rollback()
    with factory() as db:
        with pytest.raises(Exception):
            db.execute(text("DELETE FROM audit_log"))
        db.rollback()
    rows = _audit_rows(factory, action="ATTENDANCE_UPSERT")
    assert len(rows) == 1
    assert rows[0]["new_value"] == "ABSENT"


# ---------------------------------------------------------------------------
# 12. The meta contract reports unlimited editing and deprecates the lock
# ---------------------------------------------------------------------------

def test_meta_config_declares_unlimited_editing(api):
    client, _ = api
    res = client.get("/api/v1/meta/config", headers=_headers("admin_root", "ADMIN"))
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["unlimited_attendance_editing"] is True
    # Deprecated field kept for API compatibility.
    assert "edit_lock_hours" in payload


def test_no_backend_module_uses_the_deprecated_lock_for_authorization():
    """The deprecated lock value must never gate an edit."""
    backend_dir = Path(__file__).resolve().parents[1]
    watched = [
        backend_dir / "app" / "routers" / "attendance.py",
        backend_dir / "app" / "routers" / "agent.py",
        backend_dir / "app" / "routers" / "sessions.py",
        backend_dir / "app" / "services" / "attendance_edits.py",
        backend_dir / "app" / "auth" / "session_scope.py",
        backend_dir / "app" / "db" / "crud.py",
    ]
    for path in watched:
        source = path.read_text(encoding="utf-8")
        assert "EDIT_LOCK_HOURS" not in source, path.name
        assert "edit_lock_hours" not in source, path.name
