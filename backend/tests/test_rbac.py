"""RBAC & Global Admin Scope Tests (Ticket RC-RBAC-002).

Covers:
1. ``app.deps``: ``UserContext``, ``require_role('admin')``, ``require_login``,
   and ``get_user_context`` across admin, teacher/faculty, viewer, and
   unauthenticated callers.
2. College-wide admin scope across departments, branches, rooms, and subjects,
   verifying that ``departments.head_of_dept_id`` and ``department_staff`` remain
   deferred and never filter admin queries.
3. Cross-department access across sessions, attendance overrides, overview,
   audit logs, teacher-subject mappings, defaulters, student ledgers, and
   roster reports.
4. ``tools.query_tool``: zero ``dept_id`` / ``subject_code`` WHERE injection
   when ``UserContext.role == 'admin'``, strict mapped ``subject_code``
   filtering when ``UserContext.role == 'teacher'``.
5. T-DEF (75% threshold) defaulter calculation cases queried as admin.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Dict

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.jwt import create_access_token
from app.db.base import Base
from app.db.models import (
    Attendance,
    AuditLog,
    College,
    Department,
    DepartmentStaff,
    Room,
    Session as DbSession,
    SessionAllocation,
    Student,
    Subject,
    TeacherSubject,
    User,
)
from app.dependencies import get_db
from app.deps import UserContext, get_user_context, require_login, require_role
from app.main import app
from tools.query_tool import (
    NO_DATA_MESSAGE,
    _apply_scope_to_sql,
    query_attendance,
    query_session_stats,
    query_students,
    query_tool,
    safe_sql_query,
)

pytestmark = pytest.mark.no_auth_override

TEST_SECRET = "rc-rbac-002-test-secret-key-at-least-32-bytes"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _headers(user_id: str, role: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id, role)}"}


@pytest.fixture
def rbac_env(monkeypatch):
    """Multi-department isolated DB and TestClient for RC-RBAC-002."""
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    monkeypatch.setenv("SESSION_AUTO_INIT", "0")
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    monkeypatch.setenv("SESSION_AUTO_INIT", "0")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_SECRET)

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    old_date = (now - timedelta(days=5)).strftime("%Y-%m-%d")
    today_date = now.strftime("%Y-%m-%d")

    with factory() as db:
        # Users: admin, two department teachers, one viewer, inactive sentinel
        db.add_all(
            [
                User(
                    user_id="admin_global",
                    email="admin_global@rollcall.edu",
                    role="ADMIN",
                    hashed_password=None,
                    is_active=1,
                    created_at=_utcnow_iso(),
                ),
                User(
                    user_id="teacher_cse",
                    email="teacher_cse@rollcall.edu",
                    role="FACULTY",
                    hashed_password=None,
                    is_active=1,
                    created_at=_utcnow_iso(),
                ),
                User(
                    user_id="teacher_ece",
                    email="teacher_ece@rollcall.edu",
                    role="FACULTY",
                    hashed_password=None,
                    is_active=1,
                    created_at=_utcnow_iso(),
                ),
                User(
                    user_id="viewer_1",
                    email="viewer_1@rollcall.edu",
                    role="VIEWER",
                    hashed_password=None,
                    is_active=1,
                    created_at=_utcnow_iso(),
                ),
                User(
                    user_id="legacy",
                    email="legacy@rollcall.edu",
                    role="ADMIN",
                    hashed_password=None,
                    is_active=0,
                    created_at=_utcnow_iso(),
                ),
            ]
        )

        # College & multiple departments with HOD columns populated (must NOT restrict admin)
        db.add(College(college_id="COL-1", name="Test Institute", code="TI"))
        db.flush()
        db.add_all(
            [
                Department(
                    dept_id="DEPT-CSE",
                    college_id="COL-1",
                    name="Computer Science",
                    code="CSE",
                    head_of_dept_id="teacher_cse",
                ),
                Department(
                    dept_id="DEPT-ECE",
                    college_id="COL-1",
                    name="Electronics",
                    code="ECE",
                    head_of_dept_id="teacher_ece",
                ),
                Department(
                    dept_id="DEPT-ME",
                    college_id="COL-1",
                    name="Mechanical",
                    code="ME",
                    head_of_dept_id=None,
                ),
            ]
        )
        db.flush()
        # DepartmentStaff entries (including admin_global scoped to DEPT-CSE on paper - must be ignored!)
        db.add_all(
            [
                DepartmentStaff(user_id="admin_global", dept_id="DEPT-CSE", role_in_dept="staff"),
                DepartmentStaff(user_id="teacher_cse", dept_id="DEPT-CSE", role_in_dept="hod"),
                DepartmentStaff(user_id="teacher_ece", dept_id="DEPT-ECE", role_in_dept="hod"),
            ]
        )

        db.add_all(
            [
                Subject(
                    subject_code="CS101",
                    name="Data Structures",
                    dept_id="DEPT-CSE",
                    subject_type="theory",
                ),
                Subject(
                    subject_code="EC101",
                    name="Signals & Systems",
                    dept_id="DEPT-ECE",
                    subject_type="theory",
                ),
                Subject(
                    subject_code="ME101",
                    name="Thermodynamics",
                    dept_id="DEPT-ME",
                    subject_type="theory",
                ),
            ]
        )

        db.add_all(
            [
                TeacherSubject(user_id="teacher_cse", subject_code="CS101"),
                TeacherSubject(user_id="teacher_ece", subject_code="EC101"),
            ]
        )

        db.add_all(
            [
                Room(room_id="LH-101", name="CS Hall"),
                Room(room_id="LH-202", name="EC Hall"),
                Room(room_id="LH-303", name="ME Hall"),
            ]
        )

        db.add_all(
            [
                Student(usn="1MS21CS001", name="Alice CS", branch="CSE", dept_id="DEPT-CSE"),
                Student(usn="1MS21EC001", name="Bob EC", branch="ECE", dept_id="DEPT-ECE"),
                Student(usn="1MS21ME001", name="Carol ME", branch="ME", dept_id="DEPT-ME"),
            ]
        )
        db.flush()

        db.add_all(
            [
                DbSession(
                    session_id="SESS-CSE",
                    date=today_date,
                    subject="Data Structures",
                    subject_code="CS101",
                    teacher_id="teacher_cse",
                    created_at=_utcnow_iso(),
                ),
                DbSession(
                    session_id="SESS-ECE",
                    date=today_date,
                    subject="Signals & Systems",
                    subject_code="EC101",
                    teacher_id="teacher_ece",
                    created_at=_utcnow_iso(),
                ),
                DbSession(
                    session_id="SESS-LEGACY",
                    date=old_date,
                    subject="Thermodynamics",
                    subject_code="ME101",
                    teacher_id="legacy",
                    created_at=old_ts,
                ),
                DbSession(
                    session_id="SESS-UNASSIGNED",
                    date=old_date,
                    subject="General Assembly",
                    subject_code=None,
                    teacher_id=None,
                    created_at=old_ts,
                ),
            ]
        )

        db.add_all(
            [
                SessionAllocation(
                    allocation_id="ALLOC-1",
                    session_id="SESS-CSE",
                    room_id="LH-101",
                    faculty_id="teacher_cse",
                    allocation_date=today_date,
                    start_time="09:00",
                    end_time="10:00",
                ),
                SessionAllocation(
                    allocation_id="ALLOC-2",
                    session_id="SESS-ECE",
                    room_id="LH-202",
                    faculty_id="teacher_ece",
                    allocation_date=today_date,
                    start_time="10:00",
                    end_time="11:00",
                ),
            ]
        )

        db.add_all(
            [
                # SESS-CSE: Alice absent (0/1 = 0% -> defaulter)
                Attendance(
                    attendance_id="ATT-CSE-1",
                    session_id="SESS-CSE",
                    usn="1MS21CS001",
                    room_id="LH-101",
                    status="ABSENT",
                    source="camera",
                    confidence=0.95,
                    recorded_at=_utcnow_iso(),
                ),
                # SESS-ECE: Bob absent (0/1 = 0% -> defaulter)
                Attendance(
                    attendance_id="ATT-ECE-1",
                    session_id="SESS-ECE",
                    usn="1MS21EC001",
                    room_id="LH-202",
                    status="ABSENT",
                    source="camera",
                    confidence=0.95,
                    recorded_at=_utcnow_iso(),
                ),
                # SESS-LEGACY: Carol absent (0/1 = 0% -> defaulter)
                Attendance(
                    attendance_id="ATT-LEG-1",
                    session_id="SESS-LEGACY",
                    usn="1MS21ME001",
                    room_id="LH-303",
                    status="ABSENT",
                    source="manual",
                    confidence=1.0,
                    recorded_at=old_ts,
                ),
                # SESS-UNASSIGNED: Alice present (overall 1/2 = 50% -> still defaulter)
                Attendance(
                    attendance_id="ATT-UNA-1",
                    session_id="SESS-UNASSIGNED",
                    usn="1MS21CS001",
                    room_id="LH-101",
                    status="PRESENT",
                    source="manual",
                    confidence=1.0,
                    recorded_at=old_ts,
                ),
            ]
        )

        db.add_all(
            [
                AuditLog(
                    actor_id="teacher_cse",
                    actor_role="FACULTY",
                    action="ATTENDANCE_RECORD",
                    session_id="SESS-CSE",
                    usn="1MS21CS001",
                    entity_type="attendance",
                    entity_id="ATT-CSE-1",
                    old_value=None,
                    new_value="ABSENT",
                    timestamp=_utcnow_iso(),
                ),
                AuditLog(
                    actor_id="teacher_ece",
                    actor_role="FACULTY",
                    action="ATTENDANCE_RECORD",
                    session_id="SESS-ECE",
                    usn="1MS21EC001",
                    entity_type="attendance",
                    entity_id="ATT-ECE-1",
                    old_value=None,
                    new_value="ABSENT",
                    timestamp=_utcnow_iso(),
                ),
            ]
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


# ==============================================================================
# 1. app.deps unit & dependency tests
# ==============================================================================


def test_user_context_admin_is_always_unrestricted():
    ctx = UserContext(
        user_id="admin_global",
        role="admin",
        dept_id="DEPT-CSE",
        subject_codes=["CS101"],
    )
    assert ctx.role == "admin"
    assert ctx.unrestricted is True
    assert ctx.is_admin is True
    assert ctx.session_condition() is None
    assert ctx.student_condition() is None


def test_user_context_teacher_is_strictly_scoped():
    ctx = UserContext(
        user_id="teacher_cse",
        role="teacher",
        dept_id="DEPT-CSE",
        subject_codes=["cs101", " CS102 "],
    )
    assert ctx.role == "teacher"
    assert ctx.unrestricted is False
    assert ctx.is_admin is False
    assert ctx.subject_codes == ("CS101", "CS102")
    assert ctx.session_condition() is not None
    assert ctx.student_condition() is not None


def test_require_role_dependency_enforces_admin_and_teacher(rbac_env):
    _, factory = rbac_env

    probe_app = FastAPI()

    def _override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    probe_app.dependency_overrides[get_db] = _override_db

    @probe_app.get("/probe/admin")
    def _admin_only(
        user=Depends(require_role("admin")),
        ctx: UserContext = Depends(get_user_context),
    ):
        return {
            "user_id": user.user_id,
            "unrestricted": ctx.unrestricted,
            "role": ctx.role,
        }

    @probe_app.get("/probe/teacher")
    def _teacher_or_admin(user=Depends(require_role("teacher"))):
        return {"user_id": user.user_id}

    @probe_app.get("/probe/login")
    def _any_logged_in(user=Depends(require_login)):
        return {"user_id": user.user_id}

    probe_client = TestClient(probe_app)

    # Unauthenticated -> 401
    assert probe_client.get("/probe/admin").status_code == 401
    assert probe_client.get("/probe/teacher").status_code == 401
    assert probe_client.get("/probe/login").status_code == 401

    # Viewer -> 403 on admin & teacher, 200 on login
    assert (
        probe_client.get("/probe/admin", headers=_headers("viewer_1", "VIEWER")).status_code
        == 403
    )
    assert (
        probe_client.get("/probe/teacher", headers=_headers("viewer_1", "VIEWER")).status_code
        == 403
    )
    assert (
        probe_client.get("/probe/login", headers=_headers("viewer_1", "VIEWER")).status_code
        == 200
    )

    # Teacher -> 403 on admin, 200 on teacher & login
    assert (
        probe_client.get("/probe/admin", headers=_headers("teacher_cse", "FACULTY")).status_code
        == 403
    )
    assert (
        probe_client.get("/probe/teacher", headers=_headers("teacher_cse", "FACULTY")).status_code
        == 200
    )

    # Admin -> 200 everywhere with unrestricted UserContext
    res = probe_client.get("/probe/admin", headers=_headers("admin_global", "ADMIN"))
    assert res.status_code == 200
    assert res.json()["unrestricted"] is True
    assert res.json()["role"] == "admin"
    assert (
        probe_client.get("/probe/teacher", headers=_headers("admin_global", "ADMIN")).status_code
        == 200
    )


# ==============================================================================
# 2. Cross-department Admin Access across all T-RBAC endpoints
# ==============================================================================


def test_admin_sees_all_sessions_including_legacy_and_other_depts(rbac_env):
    client, _ = rbac_env
    admin_hdr = _headers("admin_global", "ADMIN")
    cse_hdr = _headers("teacher_cse", "FACULTY")

    # Unauthenticated -> 401
    assert client.get("/api/sessions").status_code == 401

    # Teacher sees only own CSE session
    res_teacher = client.get("/api/sessions", headers=cse_hdr)
    assert res_teacher.status_code == 200
    teacher_ids = {item["session_id"] for item in res_teacher.json()["items"]}
    assert teacher_ids == {"SESS-CSE"}

    # Admin sees ALL sessions across CSE, ECE, legacy, and unassigned
    res_admin = client.get("/api/sessions", headers=admin_hdr)
    assert res_admin.status_code == 200
    admin_ids = {item["session_id"] for item in res_admin.json()["items"]}
    assert {"SESS-CSE", "SESS-ECE", "SESS-LEGACY", "SESS-UNASSIGNED"} <= admin_ids

    # Allocations also unrestricted for admin
    alloc_res = client.get("/api/sessions/allocations", headers=admin_hdr)
    assert alloc_res.status_code == 200
    alloc_sessions = {item["session_id"] for item in alloc_res.json()["items"]}
    assert {"SESS-CSE", "SESS-ECE"} <= alloc_sessions

    # Single session detail + summary across departments
    assert client.get("/api/analytics/sessions/SESS-ECE/summary", headers=cse_hdr).status_code == 403
    for sid in ("SESS-CSE", "SESS-ECE", "SESS-LEGACY", "SESS-UNASSIGNED"):
        assert client.get(f"/api/sessions/{sid}", headers=admin_hdr).status_code == 200
        assert client.get(f"/api/analytics/sessions/{sid}/summary", headers=admin_hdr).status_code == 200


def test_admin_cross_department_and_historical_attendance_override(rbac_env):
    client, _ = rbac_env
    admin_hdr = _headers("admin_global", "ADMIN")
    cse_hdr = _headers("teacher_cse", "FACULTY")

    # Teacher cannot edit ECE session -> 403
    res_forbidden = client.post(
        "/api/attendance/sessions/SESS-ECE/record?upsert=true",
        json={
            "usn": "1MS21EC001",
            "room_id": "LH-202",
            "status": "PRESENT",
            "source": "manual",
            "confidence": 1.0,
        },
        headers=cse_hdr,
    )
    assert res_forbidden.status_code == 403

    # Admin can override both ECE session and >24h legacy ME session
    res_ece = client.post(
        "/api/attendance/sessions/SESS-ECE/record?upsert=true",
        json={
            "usn": "1MS21EC001",
            "room_id": "LH-202",
            "status": "PRESENT",
            "source": "manual",
            "confidence": 1.0,
        },
        headers=admin_hdr,
    )
    assert res_ece.status_code == 200

    res_legacy = client.post(
        "/api/attendance/sessions/SESS-LEGACY/record?upsert=true",
        json={
            "usn": "1MS21ME001",
            "room_id": "LH-303",
            "status": "PRESENT",
            "source": "manual",
            "confidence": 1.0,
        },
        headers=admin_hdr,
    )
    assert res_legacy.status_code == 200


def test_admin_overview_audit_logs_defaulters_and_ledgers_are_global(rbac_env):
    client, _ = rbac_env
    admin_hdr = _headers("admin_global", "ADMIN")
    cse_hdr = _headers("teacher_cse", "FACULTY")

    # Overview: all branches & all rooms visible to admin
    assert client.get("/api/analytics/overview").status_code == 401
    ov_res = client.get("/api/analytics/overview", headers=admin_hdr)
    assert ov_res.status_code == 200
    ov_body = ov_res.json()
    branches = {b["branch"] for b in ov_body["branch_wise"]}
    rooms = {r["room_id"] for r in ov_body["room_wise"]}
    assert {"CSE", "ECE", "ME"} <= branches
    assert {"LH-101", "LH-202", "LH-303"} <= rooms

    # Audit logs: 401 unauthenticated, 403 teacher, 200 all actors for admin
    assert client.get("/api/admin/audit-logs").status_code == 401
    assert client.get("/api/admin/audit-logs", headers=cse_hdr).status_code == 403
    audit_res = client.get("/api/admin/audit-logs", headers=admin_hdr)
    assert audit_res.status_code == 200
    actors = {item["actor_id"] for item in audit_res.json()["items"]}
    assert {"teacher_cse", "teacher_ece"} <= actors

    # Teacher-subjects management: 403 teacher, 200/201 admin
    assert client.get("/api/admin/teacher-subjects", headers=cse_hdr).status_code == 403
    assert client.get("/api/admin/teacher-subjects", headers=admin_hdr).status_code == 200

    # Defaulters: teacher sees only CSE; admin sees ALL departments unless filtered
    assert client.get("/api/analytics/defaulters").status_code == 401
    def_teacher = client.get("/api/analytics/defaulters", headers=cse_hdr)
    assert def_teacher.status_code == 200
    teacher_def_usns = {item["usn"] for item in def_teacher.json()["items"]}
    assert "1MS21EC001" not in teacher_def_usns
    assert "1MS21ME001" not in teacher_def_usns

    def_admin = client.get("/api/analytics/defaulters", headers=admin_hdr)
    assert def_admin.status_code == 200
    admin_def_usns = {item["usn"] for item in def_admin.json()["items"]}
    assert {"1MS21CS001", "1MS21EC001", "1MS21ME001"} <= admin_def_usns

    # Explicit branch filter narrows admin defaulters only when requested
    def_filtered = client.get("/api/analytics/defaulters?branch=ECE", headers=admin_hdr)
    assert def_filtered.status_code == 200
    filtered_usns = {item["usn"] for item in def_filtered.json()["items"]}
    assert filtered_usns == {"1MS21EC001"}

    # Student directory & ledgers: admin reads all departments
    st_admin = client.get("/api/students", headers=admin_hdr)
    assert st_admin.status_code == 200
    assert {s["usn"] for s in st_admin.json()["items"]} == {
        "1MS21CS001",
        "1MS21EC001",
        "1MS21ME001",
    }
    for usn in ("1MS21CS001", "1MS21EC001", "1MS21ME001"):
        ledger = client.get(f"/api/attendance/students/{usn}", headers=admin_hdr)
        assert ledger.status_code == 200
        assert len(ledger.json()) >= 1

    # PDF export & filters cover all branches for admin
    filt = client.get("/api/reports/students/filters", headers=admin_hdr)
    assert filt.status_code == 200
    assert {"CSE", "ECE", "ME"} <= set(filt.json()["branches"])
    pdf_res = client.post("/api/reports/students/pdf", json={}, headers=admin_hdr)
    assert pdf_res.status_code == 200
    assert pdf_res.content.startswith(b"%PDF-")


# ==============================================================================
# 3. tools/query_tool.py UserContext scope enforcement
# ==============================================================================


def test_query_tool_admin_injects_no_where_filter_and_teacher_filters_by_subject(tmp_path):
    db_file = tmp_path / "rbac_query_tool.db"
    conn = sqlite3.connect(db_file)
    conn.executescript(
        """
        CREATE TABLE students (usn TEXT PRIMARY KEY, name TEXT, branch TEXT, dept_id TEXT);
        CREATE TABLE rooms (room_id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE subjects (subject_code TEXT PRIMARY KEY, name TEXT, dept_id TEXT);
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            date TEXT,
            subject TEXT,
            subject_code TEXT,
            teacher_id TEXT
        );
        CREATE TABLE attendance (
            attendance_id TEXT PRIMARY KEY,
            session_id TEXT,
            usn TEXT,
            room_id TEXT,
            status TEXT,
            source TEXT,
            confidence REAL
        );
        INSERT INTO students VALUES ('1MS21CS001', 'Alice', 'CSE', 'DEPT-CSE');
        INSERT INTO students VALUES ('1MS21EC001', 'Bob', 'ECE', 'DEPT-ECE');
        INSERT INTO rooms VALUES ('LH-101', 'Hall 101'), ('LH-202', 'Hall 202');
        INSERT INTO subjects VALUES ('CS101', 'DS', 'DEPT-CSE'), ('EC101', 'SS', 'DEPT-ECE');
        INSERT INTO sessions VALUES ('SESS-CS', '2026-03-15', 'DS', 'CS101', 'teacher_cs');
        INSERT INTO sessions VALUES ('SESS-EC', '2026-03-15', 'SS', 'EC101', 'teacher_ec');
        INSERT INTO sessions VALUES ('SESS-CS-LEG', '2026-03-16', 'DS Lab', 'CS101', 'legacy');
        INSERT INTO attendance VALUES ('A1', 'SESS-CS', '1MS21CS001', 'LH-101', 'ABSENT', 'csv', 1.0);
        INSERT INTO attendance VALUES ('A2', 'SESS-EC', '1MS21EC001', 'LH-202', 'ABSENT', 'csv', 1.0);
        INSERT INTO attendance VALUES ('A3', 'SESS-CS-LEG', '1MS21CS001', 'LH-101', 'PRESENT', 'csv', 1.0);
        """
    )
    conn.commit()
    conn.close()

    admin_ctx = UserContext(user_id="admin_global", role="admin", dept_id="DEPT-CSE")
    teacher_ctx = UserContext(
        user_id="teacher_cs",
        role="teacher",
        dept_id="DEPT-CSE",
        subject_codes=["CS101"],
    )

    # 1. Static SQL rewrite check: admin injects zero WHERE/dept_id/subject_code filters
    raw_sql = "SELECT * FROM sessions"
    admin_sql, admin_params = _apply_scope_to_sql(raw_sql, admin_ctx)
    assert admin_sql == raw_sql
    assert admin_params == {}

    teacher_sql, teacher_params = _apply_scope_to_sql(raw_sql, teacher_ctx)
    assert teacher_sql != raw_sql
    assert "subject_code" in teacher_sql.lower()
    assert "CS101" in teacher_params.values()

    # 2. Execution against DB: admin sees all departments & sessions
    res_admin_att = query_attendance(db_target=str(db_file), scope=admin_ctx)
    assert res_admin_att.found is True
    assert {r["session_id"] for r in res_admin_att.data} == {"SESS-CS", "SESS-EC", "SESS-CS-LEG"}

    res_admin_stu = query_students(db_target=str(db_file), scope=admin_ctx)
    assert {r["usn"] for r in res_admin_stu.data} == {"1MS21CS001", "1MS21EC001"}

    res_admin_sql = safe_sql_query("SELECT session_id FROM sessions", db_target=str(db_file), scope=admin_ctx)
    assert {r["session_id"] for r in res_admin_sql.data} == {"SESS-CS", "SESS-EC", "SESS-CS-LEG"}

    # 3. Execution against DB: teacher sees strictly CS101 sessions/students
    res_t_att = query_attendance(db_target=str(db_file), scope=teacher_ctx)
    assert res_t_att.found is True
    assert {r["session_id"] for r in res_t_att.data} == {"SESS-CS", "SESS-CS-LEG"}

    res_t_stu = query_students(db_target=str(db_file), scope=teacher_ctx)
    assert {r["usn"] for r in res_t_stu.data} == {"1MS21CS001"}

    res_t_blocked = query_session_stats("SESS-EC", db_target=str(db_file), scope=teacher_ctx)
    assert res_t_blocked.found is False
    assert res_t_blocked.message == NO_DATA_MESSAGE

    res_admin_ec = query_session_stats("SESS-EC", db_target=str(db_file), scope=admin_ctx)
    assert res_admin_ec.found is True

    res_t_sql = query_tool(
        "sql",
        sql="SELECT session_id FROM sessions",
        db_target=str(db_file),
        user_context=teacher_ctx,
    )
    assert {r["session_id"] for r in res_t_sql.data} == {"SESS-CS", "SESS-CS-LEG"}


# ==============================================================================
# 4. T-DEF Admin Defaulter Cases (75% threshold from docs/TESTS.md)
# ==============================================================================


@pytest.mark.parametrize(
    ("conducted", "attended", "expected_pct", "is_defaulter", "expected_needed"),
    [
        (20, 12, 60.0, True, 12),
        (20, 14, 70.0, True, 4),
        (20, 15, 75.0, False, 0),
        (20, 18, 90.0, False, 0),
        (8, 5, 62.5, True, 4),
        (1, 0, 0.0, True, 3),
    ],
)
def test_t_def_admin_defaulter_calculations(
    monkeypatch,
    conducted: int,
    attended: int,
    expected_pct: float,
    is_defaulter: bool,
    expected_needed: int,
):
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    monkeypatch.setenv("SESSION_AUTO_INIT", "0")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_SECRET)

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    with factory() as db:
        db.add(
            User(
                user_id="admin_def",
                email="admin_def@rollcall.edu",
                role="ADMIN",
                is_active=1,
                created_at=_utcnow_iso(),
            )
        )
        db.add(Room(room_id="LH-101", name="Hall 101"))
        db.add(Student(usn="1MS21CS999", name="Test Student", branch="CSE"))

        for idx in range(conducted):
            sid = f"SESS-DEF-{idx}"
            db.add(
                DbSession(
                    session_id=sid,
                    date="2026-03-01",
                    subject="Algorithms",
                    subject_code="CS201",
                    teacher_id="admin_def",
                    created_at=_utcnow_iso(),
                )
            )
            db.add(
                Attendance(
                    attendance_id=f"ATT-DEF-{idx}",
                    session_id=sid,
                    usn="1MS21CS999",
                    room_id="LH-101",
                    status="PRESENT" if idx < attended else "ABSENT",
                    source="manual",
                    confidence=1.0,
                    recorded_at=_utcnow_iso(),
                )
            )
        db.commit()

    def _override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        res = client.get("/api/analytics/defaulters", headers=_headers("admin_def", "ADMIN"))
        assert res.status_code == 200
        body = res.json()
        assert body["threshold_percent"] == 75.0
        assert body["evaluated_students"] == 1
        items = body["items"]
        if is_defaulter:
            assert len(items) == 1
            item = items[0]
            assert item["conducted_classes"] == conducted
            assert item["attended_classes"] == attended
            assert item["attendance_percentage"] == expected_pct
            assert item["classes_needed_to_recover"] == expected_needed
        else:
            assert items == []
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
