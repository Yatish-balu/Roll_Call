"""N8 / N10 / N11 / N12 endpoint tests.

Covers the endpoints that were previously dead code or missing:
  * GET /api/admin/overview          (branch/room attendance overview)
  * GET /api/admin/faculty-uploads   (per-teacher upload activity)
  * GET /api/defaulters              (defaulter engine, role-scoped)
  * GET /api/admin/defaulters.pdf    (defaulter PDF + audit row)
  * GET /api/students/lookup         (static route, never shadowed)
  * GET /api/students/{usn}/ledger   (ledger with room_id)

Real HTTP API, real JWT verification, isolated in-memory database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.jwt import create_access_token
from app.db import crud
from app.db.base import Base
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

TEST_SECRET = "test-secret-key-for-n8-n12-endpoints-at-least-32-chars"


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


OWNER = _headers("faculty_cn", "FACULTY")
ADMIN = _headers("admin_root", "ADMIN")
UNMAPPED = _headers("faculty_none", "FACULTY")


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

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = now[:10]

    with factory() as db:
        for uid, role in (
            ("admin_root", "ADMIN"),
            ("faculty_cn", "FACULTY"),
            ("faculty_ml", "FACULTY"),
            ("faculty_none", "FACULTY"),
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
        db.add(TeacherSubject(user_id="faculty_cn", subject_code="CN"))
        db.add(TeacherSubject(user_id="faculty_ml", subject_code="ML"))

        db.add(Room(room_id="LH-101", name="Lecture Hall 101"))
        for usn, name in (
            ("1MS21CS001", "Alice Smith"),
            ("1MS21CS002", "Bob Jones"),
            ("1MS21CS003", "Cara Diaz"),
        ):
            db.add(Student(usn=usn, name=name, branch="CSE"))

        # 4 CN classes. Student 001 = 3/4 = 75.0 (NOT a defaulter),
        # student 002 = 0/4 (defaulter), student 003 = 4/4 (clear).
        marks = {
            "SESS-CN-1": {"1MS21CS001": "PRESENT", "1MS21CS002": "ABSENT", "1MS21CS003": "PRESENT"},
            "SESS-CN-2": {"1MS21CS001": "PRESENT", "1MS21CS002": "ABSENT", "1MS21CS003": "PRESENT"},
            "SESS-CN-3": {"1MS21CS001": "PRESENT", "1MS21CS002": "ABSENT", "1MS21CS003": "PRESENT"},
            "SESS-CN-4": {"1MS21CS001": "ABSENT", "1MS21CS002": "ABSENT", "1MS21CS003": "PRESENT"},
        }
        for index, (session_id, statuses) in enumerate(marks.items(), start=1):
            db.add(
                DbSession(
                    session_id=session_id,
                    date=today,
                    subject="Computer Networks",
                    created_at=now,
                    teacher_id="faculty_cn",
                    subject_code="CN",
                    lifecycle_status="COMPLETED",
                )
            )
            for usn, status in statuses.items():
                db.add(
                    Attendance(
                        attendance_id=f"ATT-{session_id}-{usn}",
                        session_id=session_id,
                        usn=usn,
                        room_id="LH-101",
                        status=status,
                        source="camera",
                        confidence=0.95,
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


def _audit_actions(factory):
    with factory() as db:
        return [row.action for row in db.execute(select(AuditLog)).scalars().all()]


# ---------------------------------------------------------------------------
# N10: GET /api/defaulters
# ---------------------------------------------------------------------------

def test_defaulters_is_strictly_below_the_threshold(api):
    client, _ = api
    res = client.get("/api/defaulters?subject=CN", headers=OWNER)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["status"] == "success"
    assert body["threshold"] == 75.0
    by_usn = {s["usn"]: s for s in body["students"]}

    # Exactly 75.0 is NOT a defaulter.
    assert by_usn["1MS21CS001"]["percent"] == 75.0
    assert by_usn["1MS21CS001"]["is_defaulter"] is False
    assert by_usn["1MS21CS001"]["classes_needed"] == 0

    assert by_usn["1MS21CS002"]["percent"] == 0.0
    assert by_usn["1MS21CS002"]["is_defaulter"] is True
    # 0/4 at 75% needs 12 consecutive classes: 3*4 - 4*0 = 12.
    assert by_usn["1MS21CS002"]["classes_needed"] == 12

    assert by_usn["1MS21CS003"]["is_defaulter"] is False
    assert body["defaulter_count"] == 1


def test_defaulters_via_unversioned_playbook_mount(api):
    client, _ = api
    res = client.get("/api/defaulters?subject=CN", headers=ADMIN)
    assert res.status_code == 200, res.text
    assert res.json()["defaulter_count"] == 1


def test_defaulters_are_scoped_to_the_teacher_subjects(api):
    client, _ = api
    # faculty_ml teaches ML and has no ML sessions -> sees nothing, not everything.
    res = client.get("/api/defaulters", headers=_headers("faculty_ml", "FACULTY"))
    assert res.status_code == 200, res.text
    assert res.json()["students"] == []
    assert res.json()["defaulter_count"] == 0

    # A caller with no subject mapping must not see the institution-wide list.
    res = client.get("/api/defaulters", headers=UNMAPPED)
    assert res.status_code == 200, res.text
    assert res.json()["students"] == []


def test_defaulters_admin_sees_all_branches(api):
    client, _ = api
    res = client.get("/api/defaulters", headers=ADMIN)
    assert res.status_code == 200, res.text
    assert {s["usn"] for s in res.json()["students"]} == {
        "1MS21CS001",
        "1MS21CS002",
        "1MS21CS003",
    }


def test_defaulters_rejects_an_out_of_range_threshold(api):
    client, _ = api
    res = client.get("/api/defaulters?threshold=150", headers=OWNER)
    assert res.status_code == 422, res.text


# ---------------------------------------------------------------------------
# N8: admin overview + faculty uploads
# ---------------------------------------------------------------------------

def test_admin_overview_returns_branch_and_room_aggregates(api):
    client, _ = api
    res = client.get("/api/admin/overview", headers=ADMIN)
    assert res.status_code == 200, res.text
    body = res.json()
    assert "room_wise" in body
    assert "branch_wise" in body
    assert "overall" in body
    assert body["total_sessions"] == 4
    assert body["total_records"] == 12


def test_admin_faculty_uploads_reports_per_teacher_activity(api):
    client, _ = api
    res = client.get("/api/admin/faculty-uploads", headers=ADMIN)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] >= 3
    cn = next(i for i in body["items"] if i["user_id"] == "faculty_cn")
    assert cn["total_sessions"] == 4
    assert cn["sessions_last_7_days"] == 4
    assert cn["last_upload_at_utc"] is not None
    faculty_none = next(i for i in body["items"] if i["user_id"] == "faculty_none")
    assert faculty_none["total_sessions"] == 0
    assert faculty_none["last_upload_at_utc"] is None


def test_admin_only_endpoints_reject_faculty(api):
    client, _ = api
    for path in ("/api/admin/overview", "/api/admin/faculty-uploads"):
        res = client.get(path, headers=OWNER)
        assert res.status_code == 403, f"{path}: {res.text}"
        assert res.json()["error"]["code"] == "FORBIDDEN"


# ---------------------------------------------------------------------------
# N11: defaulter PDF
# ---------------------------------------------------------------------------

def test_defaulter_pdf_is_generated_and_audited(api):
    client, factory = api
    res = client.get("/api/admin/defaulters.pdf", headers=ADMIN)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/pdf")
    assert res.content.startswith(b"%PDF-")
    assert len(res.content) > 500

    with factory() as db:
        rows = db.execute(
            select(AuditLog).where(AuditLog.action == "DEFAULTER_EXPORT")
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].actor_id == "admin_root"
    assert rows[0].actor_role == "ADMIN"


def test_defaulter_pdf_is_admin_only(api):
    client, _ = api
    res = client.get("/api/admin/defaulters.pdf", headers=OWNER)
    assert res.status_code == 403, res.text


# ---------------------------------------------------------------------------
# N12: student lookup + ledger
# ---------------------------------------------------------------------------

def test_student_lookup_is_not_shadowed_by_the_usn_route(api):
    client, _ = api
    res = client.get("/api/v1/students/lookup?q=1MS21CS", headers=ADMIN)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 3
    assert {r["usn"] for r in body["results"]} == {
        "1MS21CS001",
        "1MS21CS002",
        "1MS21CS003",
    }


def test_student_lookup_honours_the_teacher_scope(api):
    client, _ = api
    res = client.get("/api/v1/students/lookup?q=alice", headers=OWNER)
    assert res.status_code == 200, res.text
    assert {r["usn"] for r in res.json()["results"]} <= {"1MS21CS001"}


def test_student_ledger_reports_room_and_percentage(api):
    client, _ = api
    res = client.get("/api/v1/students/1MS21CS001/ledger", headers=ADMIN)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["usn"] == "1MS21CS001"
    assert body["total_classes"] == 4
    assert body["present"] == 3
    assert body["absent"] == 1
    assert body["attendance_percentage"] == "75.0%"
    assert all(entry["room_id"] == "LH-101" for entry in body["ledger"])
