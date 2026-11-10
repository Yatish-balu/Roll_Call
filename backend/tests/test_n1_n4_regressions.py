"""Regression tests for defects found in the independent N1-N4 audit.

Each test names the defect it guards. These are deliberately narrow: they pin
the specific behaviour that was broken, not the whole module.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.auth.jwt import create_access_token
from app.db.base import Base
from app.db.models import (
    Attendance,
    PendingEdit,
    Room,
    Session as DbSession,
    Student,
    TeacherSubject,
    User,
)
from app.db.connection import get_sync_session_factory
from app.dependencies import get_db
from app.main import app

pytestmark = pytest.mark.no_auth_override

TEST_SECRET = "test-secret-key-for-auth-tests-must-be-at-least-32-chars-long"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _seed(engine, *, session_teacher: str = "faculty_ds"):
    """Seed two faculty accounts, a room, a student and one owned session."""
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    now = _iso(datetime.now(timezone.utc))
    with factory() as db:
        for uid, role in (
            ("faculty_ds", "FACULTY"),
            ("faculty_ml", "FACULTY"),
            ("admin_root", "ADMIN"),
        ):
            if db.get(User, uid) is None:
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
        # Idempotent: some tests re-seed an engine the api fixture already seeded.
        if db.get(Room, "LH-101") is None:
            db.add(Room(room_id="LH-101", name="Lecture Hall 101"))
        if db.get(Student, "1MS21CS001") is None:
            db.add(Student(usn="1MS21CS001", name="Alice Smith", branch="CSE"))
        if db.get(Student, "1MS21CS002") is None:
            db.add(Student(usn="1MS21CS002", name="Bob Jones", branch="CSE"))
        if db.get(DbSession, "SESS-OWN") is None:
            db.add(
                DbSession(
                    session_id="SESS-OWN",
                    date="2026-03-15",
                    subject="Distributed Systems",
                    teacher_id=session_teacher,
                )
            )
        db.commit()
    return factory


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


@pytest.fixture
def api(monkeypatch):
    """App client with an in-memory DB and real JWT verification."""
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_SECRET)
    engine = _make_engine()
    factory = _seed(engine)

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


# ---------------------------------------------------------------------------
# N1/N4 attendance integrity
# ---------------------------------------------------------------------------

def test_pg_bulk_upsert_uses_partial_index_predicates():
    """Bulk PG upsert must carry index_where, or PG rejects the conflict target.

    Regression: ON CONFLICT (session_id, usn) without the partial predicate does
    not match idx_attendance_legacy_session_usn and PostgreSQL raises
    "there is no unique or exclusion constraint matching the ON CONFLICT spec".
    """
    from app.db import crud

    captured = []

    class _Bind:
        dialect = type("D", (), {"name": "postgresql"})()

    fake = object.__new__(Session)
    fake.get_bind = lambda: _Bind()  # type: ignore[method-assign]
    fake.execute = lambda stmt, *a, **k: captured.append(stmt)  # type: ignore[method-assign]
    fake.flush = lambda: None  # type: ignore[method-assign]

    crud.insert_attendance_bulk(
        fake,
        records=[
            {"session_id": "SESS-OWN", "usn": "1MS21CS001", "room_id": "LH-101",
             "status": "PRESENT", "source": "csv", "confidence": 1.0},
            {"session_id": "SESS-OWN", "usn": "1MS21CS002", "room_id": "LH-101",
             "status": "ABSENT", "source": "csv", "confidence": 1.0,
             "allocation_id": "ALLOC-1"},
        ],
        upsert=True,
    )

    sqls = [
        " ".join(str(stmt.compile(dialect=postgresql.dialect())).split()).lower()
        for stmt in captured
    ]
    assert len(sqls) == 2, sqls
    assert any(
        "on conflict (session_id, usn) where allocation_id is null" in s for s in sqls
    ), sqls
    assert any(
        "on conflict (allocation_id, usn) where allocation_id is not null" in s for s in sqls
    ), sqls


def test_pg_single_upsert_uses_partial_index_predicates():
    """Same regression for the single-record upsert path."""
    from app.db import crud

    captured = []

    class _Bind:
        dialect = type("D", (), {"name": "postgresql"})()

    fake = object.__new__(Session)
    fake.get_bind = lambda: _Bind()  # type: ignore[method-assign]
    fake.execute = lambda stmt, *a, **k: captured.append(stmt)  # type: ignore[method-assign]
    fake.flush = lambda: None  # type: ignore[method-assign]

    for allocation_id in (None, "ALLOC-1"):
        crud.insert_attendance(
            fake,
            session_id="SESS-OWN",
            usn="1MS21CS001",
            room_id="LH-101",
            status="PRESENT",
            source="csv",
            upsert=True,
            allocation_id=allocation_id,
        )

    sqls = [
        " ".join(str(stmt.compile(dialect=postgresql.dialect())).split()).lower()
        for stmt in captured
    ]
    assert len(sqls) == 2, sqls
    assert any("where allocation_id is null" in s for s in sqls), sqls
    assert any("where allocation_id is not null" in s for s in sqls), sqls


def test_bulk_upsert_preserves_attendance_id_and_pending_edits():
    """Update-first upsert must keep the surrogate id (pending_edits cascade)."""
    from app.db import crud

    engine = _make_engine()
    factory = _seed(engine)
    now = _iso(datetime.now(timezone.utc))

    with factory() as db:
        crud.insert_attendance(
            db, session_id="SESS-OWN", usn="1MS21CS001", room_id="LH-101",
            status="PRESENT", source="csv",
        )
        db.commit()
        original = db.execute(select(Attendance)).scalars().one()
        original_id = original.attendance_id
        db.add(
            PendingEdit(
                edit_id="EDIT-1",
                user_id="faculty_ds",
                session_id="SESS-OWN",
                attendance_id=original_id,
                usn="1MS21CS001",
                old_status="PRESENT",
                new_status="ABSENT",
                created_at=now,
                expires_at=now,
                consumed=0,
            )
        )
        db.commit()

        crud.insert_attendance_bulk(
            db,
            records=[
                {"session_id": "SESS-OWN", "usn": "1MS21CS001", "room_id": "LH-101",
                 "status": "ABSENT", "source": "csv", "confidence": 1.0},
            ],
            upsert=True,
        )
        db.commit()

        rows = db.execute(select(Attendance)).scalars().all()
        assert len(rows) == 1, "upsert must not duplicate the row"
        assert rows[0].attendance_id == original_id, "attendance_id must be preserved"
        assert rows[0].status == "ABSENT"
        assert db.get(PendingEdit, "EDIT-1") is not None, "pending edit must survive"
    engine.dispose()


def test_replace_session_attendance_preserves_ids_and_pending_edits():
    """PUT /replace must update in place instead of DELETE+INSERT.

    Regression: the old implementation deleted every row for the session, which
    discarded attendance_id values and cascade-deleted pending_edits.
    """
    from app.db import crud

    engine = _make_engine()
    factory = _seed(engine)
    now = _iso(datetime.now(timezone.utc))

    with factory() as db:
        crud.insert_attendance(
            db, session_id="SESS-OWN", usn="1MS21CS001", room_id="LH-101",
            status="PRESENT", source="csv",
        )
        crud.insert_attendance(
            db, session_id="SESS-OWN", usn="1MS21CS002", room_id="LH-101",
            status="PRESENT", source="csv",
        )
        db.commit()
        keep = db.execute(
            select(Attendance).where(Attendance.usn == "1MS21CS001")
        ).scalars().one()
        drop = db.execute(
            select(Attendance).where(Attendance.usn == "1MS21CS002")
        ).scalars().one()
        keep_id, drop_id = keep.attendance_id, drop.attendance_id

        db.add(
            PendingEdit(
                edit_id="EDIT-KEEP", user_id="faculty_ds", session_id="SESS-OWN",
                attendance_id=keep_id, usn="1MS21CS001", old_status="PRESENT",
                new_status="ABSENT", created_at=now, expires_at=now, consumed=0,
            )
        )
        db.commit()

        crud.replace_session_attendance(
            db,
            session_id="SESS-OWN",
            records=[
                {"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT",
                 "source": "ui", "confidence": 1.0},
            ],
        )
        db.commit()

        rows = db.execute(select(Attendance)).scalars().all()
        assert [r.usn for r in rows] == ["1MS21CS001"], "stale rows must be removed"
        assert rows[0].attendance_id == keep_id, "kept row must keep its attendance_id"
        assert drop_id != keep_id
        assert rows[0].status == "ABSENT"
        assert db.get(PendingEdit, "EDIT-KEEP") is not None, "pending edit must survive"
    engine.dispose()


def test_replace_session_attendance_raw_sqlite_preserves_ids(tmp_path):
    """Same guarantee for the raw sqlite3.Connection code path."""
    from app.db import crud

    db_path = str(tmp_path / "raw.db")
    Base.metadata.create_all(create_engine(f"sqlite:///{db_path}"))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        crud.insert_attendance(
            conn, session_id="SESS-OWN", usn="1MS21CS001", room_id="LH-101",
            status="PRESENT", source="csv",
        )
        first_id = conn.execute("SELECT attendance_id FROM attendance").fetchone()[0]
        crud.replace_session_attendance(
            conn,
            session_id="SESS-OWN",
            records=[{"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT",
                      "source": "ui", "confidence": 1.0}],
        )
        rows = conn.execute("SELECT attendance_id, status FROM attendance").fetchall()
        assert len(rows) == 1
        assert rows[0]["attendance_id"] == first_id
        assert rows[0]["status"] == "ABSENT"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# N3 authorization + audit
# ---------------------------------------------------------------------------

def test_faculty_cannot_access_another_facultys_session(api):
    client, _factory = api
    ds_headers = {"Authorization": f"Bearer {_token('faculty_ds', 'FACULTY')}"}
    ml_headers = {"Authorization": f"Bearer {_token('faculty_ml', 'FACULTY')}"}

    # Owner can read and write.
    assert client.get("/api/v1/attendance/sessions/SESS-OWN", headers=ds_headers).status_code == 200
    created = client.post(
        "/api/v1/attendance/sessions/SESS-OWN/record",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT"},
        headers=ds_headers,
    )
    assert created.status_code == 201, created.text

    # A different faculty member cannot read or modify it.
    assert client.get("/api/v1/attendance/sessions/SESS-OWN", headers=ml_headers).status_code == 403
    blocked = client.post(
        "/api/v1/attendance/sessions/SESS-OWN/record",
        json={"usn": "1MS21CS002", "room_id": "LH-101", "status": "PRESENT"},
        headers=ml_headers,
    )
    assert blocked.status_code == 403
    assert client.delete("/api/v1/attendance/sessions/SESS-OWN", headers=ml_headers).status_code == 403


def test_admin_can_access_any_session(api):
    client, _factory = api
    headers = {"Authorization": f"Bearer {_token('admin_root', 'ADMIN')}"}
    assert client.get("/api/v1/attendance/sessions/SESS-OWN", headers=headers).status_code == 200


def test_attendance_mutations_are_audited(api):
    client, factory = api
    headers = {"Authorization": f"Bearer {_token('faculty_ds', 'FACULTY')}"}

    assert client.post(
        "/api/v1/attendance/sessions/SESS-OWN/record",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT"},
        headers=headers,
    ).status_code == 201
    assert client.post(
        "/api/v1/attendance/sessions/SESS-OWN/bulk?upsert=true",
        json={"records": [
            {"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
            {"usn": "1MS21CS002", "room_id": "LH-101", "status": "PRESENT"},
        ]},
        headers=headers,
    ).status_code == 201
    assert client.put(
        "/api/v1/attendance/sessions/SESS-OWN",
        json={"records": [{"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT"}]},
        headers=headers,
    ).status_code == 200
    assert client.post(
        "/api/v1/attendance/sessions/SESS-OWN/reconcile",
        json={"resolutions": [{"usn": "1MS21CS001", "resolved_status": "ABSENT"}]},
        headers=headers,
    ).status_code == 200
    admin_headers = {"Authorization": f"Bearer {_token('admin_root', 'ADMIN')}"}
    assert client.delete("/api/v1/attendance/sessions/SESS-OWN", headers=admin_headers).status_code == 200

    with factory() as db:
        actions = [r[0] for r in db.execute(select(__import__("app.db.models", fromlist=["AuditLog"]).AuditLog.action)).all()]
    for expected in (
        "ATTENDANCE_RECORD",
        "ATTENDANCE_BULK_UPSERT",
        "ATTENDANCE_REPLACE",
        "ATTENDANCE_RECONCILE",
        "ATTENDANCE_DELETE",
    ):
        assert expected in actions, f"missing audit action {expected}: {actions}"


# ---------------------------------------------------------------------------
# N2 authentication / rate limiting
# ---------------------------------------------------------------------------

def test_unknown_user_logins_are_rate_limited_by_ip():
    """Regression: unknown accounts were never throttled (user_id stored NULL)."""
    from app.routers.auth import _check_rate_limit, _record_attempt

    now_dt = datetime.now(timezone.utc)
    now_iso = _iso(now_dt)
    ip = "203.0.113.77"
    factory = get_sync_session_factory()

    def _clean():
        with factory() as db:
            db.execute(__import__("sqlalchemy").text("DELETE FROM login_attempts WHERE ip_address = :ip"), {"ip": ip})
            db.commit()

    _clean()
    try:
        with factory() as db:
            assert _check_rate_limit(db, "ghost_user", now_dt, ip_address=ip) is True
            for _ in range(20):
                _record_attempt(db, user_id=None, ip_address=ip, success=0, timestamp=now_iso)
            # Unknown user: the per-user quota cannot match NULL rows, but the IP
            # quota must still block the attempt.
            assert _check_rate_limit(db, "ghost_user", now_dt, ip_address=ip) is False
    finally:
        _clean()


def test_known_user_failures_are_rate_limited_even_from_a_new_ip():
    from app.routers.auth import _check_rate_limit, _record_attempt

    now_dt = datetime.now(timezone.utc)
    now_iso = _iso(now_dt)
    ip = "203.0.113.78"
    factory = get_sync_session_factory()
    # login_attempts.user_id is a real FK, so use an existing account.
    target = "faculty_cn"

    def _clean():
        with factory() as db:
            db.execute(
                __import__("sqlalchemy").text("DELETE FROM login_attempts WHERE user_id = :u"),
                {"u": target},
            )
            db.commit()

    _clean()
    try:
        with factory() as db:
            for _ in range(5):
                _record_attempt(db, user_id=target, ip_address="198.51.100.1", success=0, timestamp=now_iso)
            # Same account, brand-new IP: the per-user quota must still apply.
            assert _check_rate_limit(db, target, now_dt, ip_address=ip) is False
            # A different account from a clean IP is unaffected.
            assert _check_rate_limit(db, "faculty_ml", now_dt, ip_address="198.51.100.9") is True
    finally:
        _clean()


def test_authentication_fails_closed_when_database_is_unavailable(api, monkeypatch):
    """Regression: a DB error used to fall through and trust the token role."""
    client, _factory = api
    headers = {"Authorization": f"Bearer {_token('faculty_ds', 'FACULTY')}"}

    def boom():
        raise RuntimeError("database down")

    monkeypatch.setattr("app.auth.dependencies.get_sync_session_factory", boom)
    res = client.get("/api/v1/students", headers=headers)
    assert res.status_code == 503, res.text


# ---------------------------------------------------------------------------
# N1 migration safety
# ---------------------------------------------------------------------------

def _alembic_config(db_url: str):
    from alembic.config import Config

    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    cfg = Config(os.path.join(backend_dir, "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
    return cfg


def test_migration_chain_preserves_historical_attendance_rows(tmp_path):
    """Regression: rebuilding `sessions` must not cascade-delete attendance.

    Alembic runs with SQLite foreign-key enforcement disabled for the duration
    of the migration, so rebuilding a parent table cannot remove child rows and
    every attendance_id survives the full chain.
    """
    from alembic import command

    db_path = (tmp_path / "mig_rows.db").as_posix()
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_config(db_url)

    command.upgrade(cfg, "0003_auth_sessions")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT INTO students (usn, name, branch) VALUES ('USN-1', 'A', 'CSE')")
        conn.execute("INSERT INTO students (usn, name, branch) VALUES ('USN-2', 'B', 'CSE')")
        conn.execute("INSERT INTO rooms (room_id, name) VALUES ('LH-101', 'Hall')")
        conn.execute(
            "INSERT INTO sessions (session_id, date, subject) VALUES ('SESS-HIST', '2026-01-01', 'History')"
        )
        # At revision 0003 the attendance PK is still (session_id, usn) and there
        # is no attendance_id / recorded_at column yet.
        conn.execute(
            "INSERT INTO attendance (session_id, usn, room_id, status, source, confidence) "
            "VALUES ('SESS-HIST', 'USN-1', 'LH-101', 'PRESENT', 'csv', 1.0)"
        )
        conn.execute(
            "INSERT INTO attendance (session_id, usn, room_id, status, source, confidence) "
            "VALUES ('SESS-HIST', 'USN-2', 'LH-101', 'ABSENT', 'csv', 1.0)"
        )
        conn.commit()
    finally:
        conn.close()

    command.upgrade(cfg, "head")

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT usn, status, attendance_id FROM attendance ORDER BY usn"
        ).fetchall()
        assert [(r[0], r[1]) for r in rows] == [("USN-1", "PRESENT"), ("USN-2", "ABSENT")]
        assert all(r[2] for r in rows), "every migrated row must get an attendance_id"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_fresh_migration_chain_matches_sqlalchemy_models(tmp_path):
    """Regression: migrated schema must match the models (no FK/index drift)."""
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    db_path = (tmp_path / "mig_drift.db").as_posix()
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(conn, opts={"compare_type": True})
            diffs = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    # SQLite reflection reports TEXT vs String and nullable quirks that are not
    # real drift; anything structural (FKs, indexes, columns, tables) is.
    structural = [
        d for d in diffs
        if not (isinstance(d, list) and d and d[0][0] in ("modify_type", "modify_nullable"))
    ]
    assert structural == [], structural


# ---------------------------------------------------------------------------
# Follow-up 1: legacy (unowned) session access policy
# ---------------------------------------------------------------------------

def _seed_legacy_session(engine, subject_code="ML", teacher="legacy"):
    """Add an unowned/legacy session plus a room for it."""
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as db:
        # sessions.teacher_id is a real FK; the legacy sentinel is a users row.
        if db.get(User, teacher or "legacy") is None and teacher:
            db.add(
                User(
                    user_id=teacher,
                    email=f"{teacher}@rollcall.edu",
                    role="ADMIN",
                    hashed_password=None,
                    is_active=0,
                    created_at=_iso(datetime.now(timezone.utc)),
                )
            )
        if db.get(Room, "LAB-7") is None:
            db.add(Room(room_id="LAB-7", name="Lab 7"))
        db.add(
            DbSession(
                session_id="SESS-LEGACY",
                date="2026-01-05",
                subject="Machine Learning",
                teacher_id=teacher,
                subject_code=subject_code,
            )
        )
        db.add(TeacherSubject(user_id="faculty_ml", subject_code=subject_code))
        db.commit()
    return factory


def test_legacy_session_access_requires_subject_mapping(api):
    """Legacy sessions are authorized by subject mapping, not by being world-readable."""
    client, factory = api
    _seed_legacy_session(factory.kw["bind"])

    headers_ml = {"Authorization": f"Bearer {_token('faculty_ml', 'FACULTY')}"}
    headers_ds = {"Authorization": f"Bearer {_token('faculty_ds', 'FACULTY')}"}
    headers_admin = {"Authorization": f"Bearer {_token('admin_root', 'ADMIN')}"}

    # Mapped to the session's subject code -> allowed.
    assert client.get("/api/v1/attendance/sessions/SESS-LEGACY", headers=headers_ml).status_code == 200
    # Unmapped faculty -> denied, even though the session has no owner.
    assert client.get("/api/v1/attendance/sessions/SESS-LEGACY", headers=headers_ds).status_code == 403
    # ADMIN keeps institutional access.
    assert client.get("/api/v1/attendance/sessions/SESS-LEGACY", headers=headers_admin).status_code == 200


def test_legacy_session_without_subject_code_is_admin_only(api):
    client, factory = api
    _seed_legacy_session(factory.kw["bind"], subject_code="", teacher=None)

    headers = {"Authorization": f"Bearer {_token('faculty_ml', 'FACULTY')}"}
    resp = client.get("/api/v1/attendance/sessions/SESS-LEGACY", headers=headers)
    assert resp.status_code == 403
    assert "administrator" in resp.json()["detail"].lower()


def test_legacy_session_access_does_not_mutate_ownership(api):
    """Authorizing by subject mapping must not assign the session to that faculty."""
    client, factory = api
    _seed_legacy_session(factory.kw["bind"])
    headers = {"Authorization": f"Bearer {_token('faculty_ml', 'FACULTY')}"}
    assert client.get("/api/v1/attendance/sessions/SESS-LEGACY", headers=headers).status_code == 200

    with factory() as db:
        assert db.get(DbSession, "SESS-LEGACY").teacher_id == "legacy"


# ---------------------------------------------------------------------------
# Follow-up 2: staged edits must survive / block attendance deletion
# ---------------------------------------------------------------------------

def _fk_enforcing_engine():
    engine = _make_engine()
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def _seed_attendance_with_pending_edit(engine):
    from app.db import crud

    factory = _seed(engine)
    now = _iso(datetime.now(timezone.utc))
    with factory() as db:
        crud.insert_attendance(
            db, session_id="SESS-OWN", usn="1MS21CS001", room_id="LH-101",
            status="PRESENT", source="csv",
        )
        db.commit()
        att = db.execute(
            select(Attendance).where(Attendance.usn == "1MS21CS001")
        ).scalars().one()
        db.add(
            PendingEdit(
                edit_id="EDIT-STAGED",
                user_id="faculty_ds",
                session_id="SESS-OWN",
                attendance_id=att.attendance_id,
                usn="1MS21CS001",
                old_status="PRESENT",
                new_status="ABSENT",
                created_at=now,
                expires_at=now,
                consumed=0,
            )
        )
        db.commit()
    return factory


def test_pending_edit_fk_is_restrict_and_blocks_silent_loss():
    """The DB itself must refuse to drop a row that a staged edit depends on."""
    from sqlalchemy.exc import IntegrityError

    engine = _fk_enforcing_engine()
    factory = _seed_attendance_with_pending_edit(engine)
    with factory() as db:
        att = db.execute(select(Attendance)).scalars().one()
        db.delete(att)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    engine.dispose()


def test_delete_session_attendance_refuses_when_edits_are_staged():
    from app.db import crud

    engine = _fk_enforcing_engine()
    factory = _seed_attendance_with_pending_edit(engine)
    with factory() as db:
        with pytest.raises(ValueError, match="pending edits"):
            crud.delete_session_attendance(db, session_id="SESS-OWN")
        db.rollback()
        assert db.execute(select(Attendance)).scalars().all(), "rows must be preserved"
        assert db.get(PendingEdit, "EDIT-STAGED") is not None
    engine.dispose()


def test_replace_refuses_to_drop_a_student_with_staged_edits():
    from app.db import crud

    engine = _fk_enforcing_engine()
    factory = _seed_attendance_with_pending_edit(engine)
    with factory() as db:
        with pytest.raises(ValueError, match="1MS21CS001"):
            crud.replace_session_attendance(
                db,
                session_id="SESS-OWN",
                records=[
                    {"usn": "1MS21CS002", "room_id": "LH-101", "status": "PRESENT",
                     "source": "csv", "confidence": 1.0},
                ],
            )
        db.rollback()
        usns = {r.usn for r in db.execute(select(Attendance)).scalars().all()}
        assert usns == {"1MS21CS001"}, "nothing may be deleted when the replace is refused"
    engine.dispose()


def test_api_delete_returns_409_when_edits_are_staged(api):
    client, factory = api
    _seed_attendance_with_pending_edit(factory.kw["bind"])
    headers = {"Authorization": f"Bearer {_token('admin_root', 'ADMIN')}"}
    resp = client.delete("/api/v1/attendance/sessions/SESS-OWN", headers=headers)
    assert resp.status_code == 409
    assert "pending edits" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Follow-up 3: no hardcoded room fallback
# ---------------------------------------------------------------------------

def _seed_allocation(engine, room_id="LAB-7"):
    from app.db.models import SessionAllocation

    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as db:
        if db.get(Room, room_id) is None:
            db.add(Room(room_id=room_id, name="Lab 7"))
        db.add(
            SessionAllocation(
                allocation_id="ALLOC-1",
                session_id="SESS-OWN",
                allocation_date="2026-03-15",
                room_id=room_id,
                start_time="09:00",
                end_time="10:00",
                lifecycle_status="SCHEDULED",
                created_at=_iso(datetime.now(timezone.utc)),
            )
        )
        db.commit()
    return factory


def test_replace_uses_session_allocation_room_not_placeholder():
    from app.db import crud

    engine = _make_engine()
    _seed(engine)
    factory = _seed_allocation(engine)
    with factory() as db:
        crud.replace_session_attendance(
            db,
            session_id="SESS-OWN",
            records=[
                {"usn": "1MS21CS001", "status": "PRESENT", "source": "csv", "confidence": 1.0},
            ],
        )
        db.commit()
        row = db.execute(select(Attendance)).scalars().one()
        assert row.room_id == "LAB-7", "must use the session's real room"
        assert row.room_id != "LH-101"
    engine.dispose()


def test_replace_requires_a_room_when_session_has_none():
    from app.db import crud

    engine = _make_engine()
    factory = _seed(engine)
    with factory() as db:
        with pytest.raises(ValueError, match="room_id is required"):
            crud.replace_session_attendance(
                db,
                session_id="SESS-OWN",
                records=[{"usn": "1MS21CS001", "status": "PRESENT", "source": "csv"}],
            )
        assert db.execute(select(Attendance)).scalars().all() == []
    engine.dispose()


def test_reconcile_persists_with_the_session_room():
    from app.db import crud

    engine = _make_engine()
    _seed(engine)
    factory = _seed_allocation(engine)
    with factory() as db:
        out = crud.reconcile_session_roster(
            db,
            session_id="SESS-OWN",
            roster=[{"usn": "1MS21CS001"}],
            uploaded_records=[{"usn": "1MS21CS001", "status": "PRESENT", "confidence": 1.0}],
            persist=True,
        )
        assert out[0]["room_id"] == "LAB-7"
        db.commit()
        assert {r.room_id for r in db.execute(select(Attendance)).scalars().all()} == {"LAB-7"}
    engine.dispose()


def test_reconcile_persist_fails_loudly_without_a_room():
    from app.db import crud

    engine = _make_engine()
    factory = _seed(engine)
    with factory() as db:
        with pytest.raises(ValueError, match="no room is known"):
            crud.reconcile_session_roster(
                db,
                session_id="SESS-OWN",
                roster=[{"usn": "1MS21CS001"}],
                uploaded_records=[{"usn": "1MS21CS001", "status": "PRESENT"}],
                persist=True,
            )
    engine.dispose()


# ---------------------------------------------------------------------------
# Follow-up 2 (migration): 0013 round-trip
# ---------------------------------------------------------------------------

def _fk_actions(db_path):
    conn = sqlite3.connect(db_path)
    try:
        # PRAGMA columns: id, seq, table, from, to, on_update, on_delete, match
        return {
            row[3]: row[6] for row in conn.execute("PRAGMA foreign_key_list(pending_edits)")
        }
    finally:
        conn.close()


def test_migration_0013_switches_pending_edit_fk_to_restrict(tmp_path):
    from alembic import command

    db_path = (tmp_path / "fk_restrict.db").as_posix()
    cfg = _alembic_config(f"sqlite:///{db_path}")

    command.upgrade(cfg, "0012_students_academic_fks")
    assert _fk_actions(db_path).get("attendance_id") == "CASCADE"

    command.upgrade(cfg, "head")
    assert _fk_actions(db_path).get("attendance_id") == "RESTRICT"

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT INTO students (usn, name, branch) VALUES ('USN-9', 'Z', 'CSE')")
        conn.execute("INSERT INTO rooms (room_id, name) VALUES ('R1', 'Room 1')")
        conn.execute(
            "INSERT INTO sessions (session_id, date, subject) VALUES ('S9', '2026-02-02', 'X')"
        )
        conn.execute(
            "INSERT INTO attendance (attendance_id, session_id, usn, room_id, status, source, "
            "confidence, recorded_at) "
            "VALUES ('A9', 'S9', 'USN-9', 'R1', 'PRESENT', 'csv', 1.0, '2026-02-02T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO users (user_id, email, role, is_active, created_at) "
            "VALUES ('u9', 'u9@x.edu', 'FACULTY', 1, '2026-02-02T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO pending_edits (edit_id, user_id, session_id, attendance_id, usn, "
            "old_status, new_status, created_at, expires_at, consumed) "
            "VALUES ('E9', 'u9', 'S9', 'A9', 'USN-9', 'PRESENT', 'ABSENT', "
            "'2026-02-02T00:00:00Z', '2026-02-02T01:00:00Z', 0)"
        )
        conn.commit()
    finally:
        conn.close()

    command.downgrade(cfg, "0012_students_academic_fks")
    assert _fk_actions(db_path).get("attendance_id") == "CASCADE"
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM pending_edits").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0] == 1
    finally:
        conn.close()
