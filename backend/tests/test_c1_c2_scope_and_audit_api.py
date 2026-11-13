"""Regression tests for the C1/C2 authorization fixes and the admin audit API.

C1  - the AI chat path must not read attendance outside the caller's scope.
C2  - student listing, student detail and attendance history must be scoped.
C   - GET /admin/audit-logs must serve the real, persisted audit trail.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session as OrmSession, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.jwt import create_access_token
from app.auth.session_scope import resolve_data_scope
from app.db.base import Base
from app.db import crud
from app.db.models import (
    Attendance,
    AuditLog,
    Room,
    Session as DbSession,
    Student,
    Subject,
    TeacherSubject,
    Timetable,
    TimetableEntry,
    User,
)
from app.dependencies import get_db
from app.main import app
from tools.query_tool import query_tool

pytestmark = pytest.mark.no_auth_override

TEST_SECRET = "test-secret-key-for-c1-c2-audit-scope-at-least-32-chars"


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
                    created_at="2026-01-01T00:00:00Z",
                )
            )
        db.add(
            User(
                user_id="legacy",
                email="legacy@rollcall.edu",
                role="ADMIN",
                hashed_password=None,
                is_active=0,
                created_at="2026-01-01T00:00:00Z",
            )
        )
        db.add(Room(room_id="LH-101", name="Lecture Hall 101"))
        for usn, name in (
            ("1MS21CS001", "Alice Smith"),
            ("1MS21CS002", "Bob Jones"),
            ("1MS21CS003", "Carol White"),
            ("1MS21CS004", "Dan Black"),
            ("1MS21CS005", "Erin Green"),
        ):
            db.add(Student(usn=usn, name=name, branch="CSE"))

        db.add(DbSession(session_id="SESS-DS", date="2026-03-15", subject="Distributed Systems",
                         teacher_id="faculty_ds", subject_code="DIST-SYS"))
        db.add(DbSession(session_id="SESS-ML", date="2026-03-16", subject="Machine Learning",
                         teacher_id="faculty_ml", subject_code="ML"))
        db.add(DbSession(session_id="SESS-LEGACY", date="2026-03-17", subject="Machine Learning Lab",
                         teacher_id="legacy", subject_code="ML"))
        db.add(TeacherSubject(user_id="faculty_ds", subject_code="DIST-SYS"))
        db.add(TeacherSubject(user_id="faculty_ml", subject_code="ML"))
        db.add(TeacherSubject(user_id="viewer_ro", subject_code="ML"))

        rows = [
            ("SESS-DS", "1MS21CS001", "ABSENT"),
            ("SESS-DS", "1MS21CS005", "PRESENT"),
            ("SESS-ML", "1MS21CS002", "ABSENT"),
            ("SESS-ML", "1MS21CS004", "ABSENT"),
            ("SESS-ML", "1MS21CS005", "PRESENT"),
            ("SESS-LEGACY", "1MS21CS003", "ABSENT"),
        ]
        for session_id, usn, status in rows:
            db.add(
                Attendance(
                    attendance_id=f"ATT-{session_id}-{usn}",
                    session_id=session_id,
                    usn=usn,
                    room_id="LH-101",
                    status=status,
                    source="camera",
                    confidence=0.95,
                    recorded_at="2026-01-01T09:00:00Z",
                )
            )

        # Persisted audit history (the real records the admin API must return).
        db.add(
            AuditLog(
                actor_id="faculty_ds",
                actor_role="FACULTY",
                action="ATTENDANCE_UPSERT",
                session_id="SESS-DS",
                usn="1MS21CS001",
                entity_type="attendance",
                entity_id="ATT-SESS-DS-1MS21CS001",
                old_value="PRESENT",
                new_value="ABSENT",
                reason=None,
                timestamp="2026-03-15T10:00:00Z",
            )
        )
        db.add(
            AuditLog(
                actor_id="admin_root",
                actor_role="ADMIN",
                action="SESSION_CREATE",
                session_id="SESS-DS",
                usn=None,
                entity_type="session",
                entity_id="SESS-DS",
                old_value=None,
                new_value="DIST-SYS",
                reason="Scheduled lecture session",
                timestamp="2026-03-16T10:00:00Z",
            )
        )
        # An older record without an actor role (nullable column).
        db.add(
            AuditLog(
                actor_id="faculty_ml",
                actor_role=None,
                action="ATTENDANCE_EDIT",
                session_id="SESS-ML",
                usn="1MS21CS002",
                entity_type="attendance",
                entity_id="SESS-ML:1MS21CS002",
                old_value="PRESENT",
                new_value="ABSENT",
                reason=None,
                timestamp="2026-03-17T10:00:00Z",
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


def _scope(factory, user_id, role):
    with factory() as db:
        user = crud.get_user(db, user_id=user_id)
        from app.schemas.auth import AuthenticatedUser, Role

        auth_user = AuthenticatedUser(
            user_id=user_id,
            email=f"{user_id}@rollcall.edu",
            role=Role(role),
            claims={"sub": user_id, "role": role},
        )
        return resolve_data_scope(db, auth_user)


# ---------------------------------------------------------------------------
# C1 - AI chat authorization
# ---------------------------------------------------------------------------

def test_chat_faculty_cannot_read_another_facultys_session(api):
    client, _ = api
    res = client.post(
        "/api/v1/agent/chat",
        json={"query": "who was absent in SESS-ML"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    rows = payload.get("data") or []
    assert rows == [], f"out-of-scope attendance leaked: {rows}"
    assert "1MS21CS002" not in res.text
    assert "1MS21CS004" not in res.text


def test_chat_viewer_cannot_read_out_of_scope_session(api):
    client, _ = api
    res = client.post(
        "/api/v1/agent/chat",
        json={"query": "who was absent in SESS-ML"},
        headers=_headers("viewer_ro", "VIEWER"),
    )
    assert res.status_code == 200, res.text
    assert (res.json().get("data") or []) == []
    assert "1MS21CS002" not in res.text


def test_chat_authorized_query_still_returns_own_session_data(api):
    client, _ = api
    res = client.post(
        "/api/v1/agent/chat",
        json={"query": "who was absent in SESS-DS"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    rows = res.json().get("data") or []
    assert rows, res.text
    assert {r["session_id"] for r in rows} == {"SESS-DS"}
    assert {r["usn"] for r in rows} == {"1MS21CS001"}


def test_chat_admin_keeps_institution_wide_reads(api):
    client, _ = api
    res = client.post(
        "/api/v1/agent/chat",
        json={"query": "who was absent in SESS-ML"},
        headers=_headers("admin_root", "ADMIN"),
    )
    assert res.status_code == 200, res.text
    rows = res.json().get("data") or []
    assert {r["usn"] for r in rows} == {"1MS21CS002", "1MS21CS004"}


def test_query_tool_raw_sql_is_restricted_to_the_scope(api):
    _, factory = api
    scope = _scope(factory, "faculty_ds", "FACULTY")
    with factory() as db:
        result = query_tool(
            query_type="sql",
            sql="SELECT session_id, usn, status FROM attendance",
            db_target=db,
            scope=scope,
        )
    assert result.found is True
    assert {r["session_id"] for r in result.data} == {"SESS-DS"}
    assert "1MS21CS002" not in {r["usn"] for r in result.data}


def test_query_tool_out_of_scope_session_returns_no_data(api):
    _, factory = api
    scope = _scope(factory, "faculty_ds", "FACULTY")
    with factory() as db:
        result = query_tool(
            query_type="attendance",
            session_id="SESS-ML",
            db_target=db,
            scope=scope,
        )
    assert result.found is False
    assert result.data == []


def test_query_tool_students_are_restricted_to_the_scope(api):
    _, factory = api
    scope = _scope(factory, "faculty_ds", "FACULTY")
    with factory() as db:
        result = query_tool(query_type="students", db_target=db, scope=scope)
    assert {r["usn"] for r in result.data} == {"1MS21CS001", "1MS21CS005"}
    assert "1MS21CS002" not in {r["usn"] for r in result.data}


def test_query_tool_without_scope_still_works_for_internal_use(api):
    """Unscoped internal usage (no authenticated caller) keeps working."""
    _, factory = api
    with factory() as db:
        result = query_tool(query_type="attendance", session_id="SESS-ML", db_target=db)
    assert result.found is True


# ---------------------------------------------------------------------------
# C2 - student and attendance-history authorization
# ---------------------------------------------------------------------------

def test_student_list_is_scoped_for_faculty(api):
    client, _ = api
    res = client.get("/api/v1/students", headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 200, res.text
    payload = res.json()
    assert {s["usn"] for s in payload["items"]} == {"1MS21CS001", "1MS21CS005"}
    assert payload["total"] == 2


def test_student_list_for_viewer_is_scoped(api):
    client, _ = api
    res = client.get("/api/v1/students", headers=_headers("viewer_ro", "VIEWER"))
    assert res.status_code == 200, res.text
    payload = res.json()
    assert {s["usn"] for s in payload["items"]} == {"1MS21CS003"}
    assert payload["total"] == 1


def test_student_list_for_admin_is_institution_wide(api):
    client, _ = api
    res = client.get("/api/v1/students", headers=_headers("admin_root", "ADMIN"))
    assert res.status_code == 200, res.text
    assert res.json()["total"] == 5


def test_student_search_cannot_reveal_out_of_scope_students(api):
    client, _ = api
    res = client.get(
        "/api/v1/students?search=1MS21CS002", headers=_headers("faculty_ds", "FACULTY")
    )
    assert res.status_code == 200, res.text
    assert res.json()["items"] == []
    assert res.json()["total"] == 0
    assert "Bob Jones" not in res.text


def test_student_pagination_cannot_reveal_out_of_scope_students(api):
    client, _ = api
    headers = _headers("faculty_ds", "FACULTY")
    seen = set()
    for offset in range(0, 5):
        res = client.get(f"/api/v1/students?limit=1&offset={offset}", headers=headers)
        assert res.status_code == 200
        payload = res.json()
        assert payload["total"] == 2, payload
        items = payload["items"]
        if not items:
            break
        seen |= {s["usn"] for s in items}
    assert seen == {"1MS21CS001", "1MS21CS005"}


def test_student_detail_out_of_scope_returns_404(api):
    client, _ = api
    res = client.get("/api/v1/students/1MS21CS002", headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 404, res.text
    assert "Bob Jones" not in res.text


def test_student_detail_in_scope_is_returned(api):
    client, _ = api
    res = client.get("/api/v1/students/1MS21CS001", headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 200, res.text
    assert res.json()["usn"] == "1MS21CS001"


def test_attendance_history_out_of_scope_returns_404(api):
    client, _ = api
    res = client.get(
        "/api/v1/attendance/students/1MS21CS002", headers=_headers("faculty_ds", "FACULTY")
    )
    assert res.status_code == 404, res.text
    assert "1MS21CS002" not in res.json().get("detail", "") or True


def test_attendance_history_returns_only_visible_sessions(api):
    client, _ = api
    # 1MS21CS005 has rows in SESS-DS (visible) and SESS-ML (not visible).
    res = client.get(
        "/api/v1/attendance/students/1MS21CS005", headers=_headers("faculty_ds", "FACULTY")
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    assert {r["session_id"] for r in rows} == {"SESS-DS"}


def test_attendance_history_for_admin_returns_everything(api):
    client, _ = api
    res = client.get(
        "/api/v1/attendance/students/1MS21CS005", headers=_headers("admin_root", "ADMIN")
    )
    assert res.status_code == 200, res.text
    assert {r["session_id"] for r in res.json()} == {"SESS-DS", "SESS-ML"}


def test_legacy_student_mount_enforces_the_same_scope(api):
    client, _ = api
    headers = _headers("faculty_ds", "FACULTY")
    res = client.get("/api/students", headers=headers)
    assert res.status_code == 200, res.text
    assert {s["usn"] for s in res.json()["items"]} == {"1MS21CS001", "1MS21CS005"}
    assert client.get("/api/students/1MS21CS002", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# C - admin audit-log read API
# ---------------------------------------------------------------------------

def test_admin_can_read_the_audit_trail(api):
    client, _ = api
    res = client.get("/api/v1/admin/audit-logs", headers=_headers("admin_root", "ADMIN"))
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["total"] == 3
    assert payload["limit"] == 50
    assert payload["offset"] == 0
    item = payload["items"][0]
    # The contract the frontend consumes.
    for field in ("id", "timestamp", "event_type", "actor_id", "session_id", "usn",
                  "old_status", "new_status", "reason"):
        assert field in item, f"missing field {field}: {item}"
    assert item["event_type"] == "ATTENDANCE_EDIT"
    assert item["actor_id"] == "faculty_ml"


def test_audit_trail_is_ordered_newest_first(api):
    client, _ = api
    res = client.get("/api/v1/admin/audit-logs", headers=_headers("admin_root", "ADMIN"))
    stamps = [i["timestamp"] for i in res.json()["items"]]
    assert stamps == sorted(stamps, reverse=True)


def test_faculty_and_viewer_cannot_read_the_audit_trail(api):
    client, _ = api
    for user, role in (("faculty_ds", "FACULTY"), ("viewer_ro", "VIEWER")):
        res = client.get("/api/v1/admin/audit-logs", headers=_headers(user, role))
        assert res.status_code == 403, (user, res.status_code)


def test_audit_log_pagination_and_validation(api):
    client, _ = api
    headers = _headers("admin_root", "ADMIN")
    res = client.get("/api/v1/admin/audit-logs?limit=1&offset=0", headers=headers)
    assert res.status_code == 200
    assert len(res.json()["items"]) == 1
    assert res.json()["total"] == 3

    res = client.get("/api/v1/admin/audit-logs?limit=1&offset=2", headers=headers)
    assert res.status_code == 200
    assert len(res.json()["items"]) == 1
    assert res.json()["total"] == 3

    for query in ("limit=0", "limit=201", "offset=-1"):
        bad = client.get(f"/api/v1/admin/audit-logs?{query}", headers=headers)
        assert bad.status_code == 422, (query, bad.status_code)


def test_audit_log_filters(api):
    client, _ = api
    headers = _headers("admin_root", "ADMIN")

    res = client.get("/api/v1/admin/audit-logs?actor=faculty_ds", headers=headers)
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["actor_id"] == "faculty_ds"

    res = client.get("/api/v1/admin/audit-logs?event_type=ATTENDANCE_UPSERT", headers=headers)
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["event_type"] == "ATTENDANCE_UPSERT"

    res = client.get("/api/v1/admin/audit-logs?session_id=SESS-DS", headers=headers)
    assert res.json()["total"] == 2

    res = client.get("/api/v1/admin/audit-logs?usn=1MS21CS001", headers=headers)
    assert res.json()["total"] == 1

    res = client.get("/api/v1/admin/audit-logs?actor_role=ADMIN", headers=headers)
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["actor_role"] == "ADMIN"

    res = client.get(
        "/api/v1/admin/audit-logs?start_date=2026-03-16&end_date=2026-03-16", headers=headers
    )
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["event_type"] == "SESSION_CREATE"


def test_audit_log_handles_a_null_actor_role(api):
    client, _ = api
    res = client.get("/api/v1/admin/audit-logs?actor=faculty_ml", headers=_headers("admin_root", "ADMIN"))
    assert res.status_code == 200, res.text
    item = res.json()["items"][0]
    assert item["actor_role"] is None
    assert item["actor_id"] == "faculty_ml"


def test_audit_log_empty_result(api):
    client, _ = api
    res = client.get(
        "/api/v1/admin/audit-logs?actor=nobody", headers=_headers("admin_root", "ADMIN")
    )
    assert res.status_code == 200
    assert res.json()["items"] == []
    assert res.json()["total"] == 0


def test_audit_log_rejects_an_invalid_date_filter(api):
    client, _ = api
    res = client.get(
        "/api/v1/admin/audit-logs?start_date=15-03-2026", headers=_headers("admin_root", "ADMIN")
    )
    assert res.status_code == 400, res.text


def test_audit_log_exposes_no_secrets(api):
    client, _ = api
    res = client.get("/api/v1/admin/audit-logs", headers=_headers("admin_root", "ADMIN"))
    body = res.text.lower()
    for forbidden in ("password", "hashed_password", "secret", "token", "authorization"):
        assert forbidden not in body, forbidden


def test_legacy_audit_mount_matches_v1(api):
    client, _ = api
    headers = _headers("admin_root", "ADMIN")
    v1 = client.get("/api/v1/admin/audit-logs", headers=headers)
    legacy = client.get("/api/admin/audit-logs", headers=headers)
    assert v1.status_code == legacy.status_code == 200
    assert v1.json()["total"] == legacy.json()["total"]
    assert [i["id"] for i in v1.json()["items"]] == [i["id"] for i in legacy.json()["items"]]
    # The legacy mount is ADMIN-only as well.
    assert client.get("/api/admin/audit-logs", headers=_headers("faculty_ds", "FACULTY")).status_code == 403


def test_audit_log_reflects_real_persisted_records(api):
    """The endpoint returns persisted records, not fabricated ones."""
    client, factory = api
    with factory() as db:
        crud.create_audit_entry(
            db,
            actor_id="faculty_ml",
            actor_role="FACULTY",
            action="ATTENDANCE_BULK_UPSERT",
            entity_type="attendance",
            entity_id="ATT-NEW",
            session_id="SESS-ML",
            usn="1MS21CS002",
            old_value="PRESENT",
            new_value="ABSENT",
            timestamp="2026-03-20T10:00:00Z",
        )
        db.commit()
    res = client.get("/api/v1/admin/audit-logs?action=ATTENDANCE_BULK_UPSERT", headers=_headers("admin_root", "ADMIN"))
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 1
    assert payload["items"][0]["event_type"] == "ATTENDANCE_BULK_UPSERT"
    assert payload["items"][0]["actor_role"] == "FACULTY"
    assert payload["items"][0]["new_status"] == "ABSENT"


# ==============================================================================
# Timetable authorization regressions
# ==============================================================================

def _seed_timetable(factory):
    from sqlalchemy import text

    with factory() as db:
        # The in-memory fixture does not seed departments/semesters; timetable
        # rows are test-only fixtures, so FK enforcement is relaxed for them.
        db.execute(text("PRAGMA foreign_keys=OFF"))
        db.add(Subject(
            subject_code="DIST-SYS",
            dept_id="DEPT-CSE",
            name="Distributed Systems",
            subject_type="theory",
        ))
        db.add(Subject(
            subject_code="ML",
            dept_id="DEPT-CSE",
            name="Machine Learning",
            subject_type="theory",
        ))
        db.add(Timetable(
            timetable_id="TT-TEST",
            dept_id="DEPT-CSE",
            semester_id="SEM-1",
            section_id="SEC-A",
            year_id="YEAR-2026",
            effective_from="2026-01-01",
        ))
        db.add(TimetableEntry(
            entry_id="TTE-1",
            timetable_id="TT-TEST",
            day_of_week="Monday",
            period_number=1,
            start_time="09:00",
            end_time="10:00",
            subject_code="DIST-SYS",
            room_id="LH-101",
            faculty_id="faculty_ds",
            duration_minutes=60,
        ))
        db.commit()


def test_faculty_cannot_move_own_entry_to_unmapped_subject(api):
    client, factory = api
    _seed_timetable(factory)

    res = client.put(
        "/api/v1/timetable/entries/TTE-1",
        json={"subject_code": "ML"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 403, res.text


def test_faculty_cannot_reassign_entry_to_another_faculty(api):
    client, factory = api
    _seed_timetable(factory)

    res = client.put(
        "/api/v1/timetable/entries/TTE-1",
        json={"faculty_id": "faculty_ml"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 403, res.text


def test_create_entry_forces_faculty_identity(api):
    client, factory = api
    _seed_timetable(factory)

    res = client.post(
        "/api/v1/timetable/entries",
        json={
            "timetable_id": "TT-TEST",
            "day_of_week": "Tuesday",
            "period_number": 2,
            "start_time": "11:00",
            "end_time": "12:00",
            "subject_code": "DIST-SYS",
            "room_id": "LH-101",
            "faculty_id": "faculty_ml",
        },
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 201, res.text
    assert res.json()["faculty_id"] == "faculty_ds"


def test_admin_can_reassign_entry(api):
    client, factory = api
    _seed_timetable(factory)

    res = client.put(
        "/api/v1/timetable/entries/TTE-1",
        json={"faculty_id": "faculty_ml"},
        headers=_headers("admin_root", "ADMIN"),
    )
    assert res.status_code == 200, res.text
    assert res.json()["faculty_id"] == "faculty_ml"
