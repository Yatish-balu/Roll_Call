"""Integration and unit tests for Wave 1 Prompt N1: RBAC tables, triggers, backfill, and atomic edits."""

import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session as SqlSession

from alembic.config import Config
from alembic import command

from tests import pg_support

from app.db.base import Base
from app.db.connection import get_connection
from app.db.models import (
    User,
    TeacherSubject,
    AuditLog,
    LoginAttempt,
    PendingEdit,
    Session as DbSession,
    Attendance,
    Student,
    Room,
)
from app.db.crud import (
    create_user,
    get_user,
    assign_teacher_subject,
    get_teacher_subjects,
    create_audit_entry,
    record_login_attempt,
    create_pending_edit,
    consume_pending_edit_atomic,
    apply_attendance_edit_atomic,
)


@pytest.fixture
def disposable_sqlite_db():
    """Create a completely disposable, isolated SQLite database in a temp directory."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "disposable_test.db")
    engine = create_engine(f"sqlite:///{db_path}")

    # Set up tables using Base metadata
    Base.metadata.create_all(bind=engine)

    yield db_path, engine

    engine.dispose()
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_five_new_tables_crud_and_schema(disposable_sqlite_db):
    """Test 1: Verify CRUD operations and column constraints across all 5 new tables."""
    db_path, engine = disposable_sqlite_db

    with SqlSession(engine) as session:
        # 1. users
        u = create_user(session, user_id="prof_oak", email="oak@kanto.edu", role="FACULTY", is_active=1)
        session.commit()
        assert u["user_id"] == "prof_oak"
        assert u["role"] == "FACULTY"

        fetched_user = get_user(session, user_id="prof_oak")
        assert fetched_user is not None
        assert fetched_user["email"] == "oak@kanto.edu"

        # 2. teacher_subjects
        ts = assign_teacher_subject(session, user_id="prof_oak", subject_code="ML")
        session.commit()
        assert ts["subject_code"] == "ML"
        subjects = get_teacher_subjects(session, user_id="prof_oak")
        assert "ML" in subjects

        # Unique constraint on (user_id, subject_code)
        with pytest.raises(IntegrityError):
            assign_teacher_subject(session, user_id="prof_oak", subject_code="ML")
        session.rollback()

        # 3. audit_log

        audit = create_audit_entry(
            session,
            actor_id="prof_oak",
            action="LOGIN",
            entity_type="user",
            entity_id="prof_oak",
            reason="Routine sign-in",
        )
        assert audit["log_id"] is not None
        assert audit["action"] == "LOGIN"

        # 4. login_attempts (both known user and NULL user for unknown attempt)
        att1 = record_login_attempt(session, user_id="prof_oak", ip_address="192.168.1.1", success=1)
        assert att1["id"] is not None
        assert att1["success"] == 1

        att2 = record_login_attempt(session, user_id=None, ip_address="10.0.0.99", success=0)
        assert att2["user_id"] is None
        assert att2["success"] == 0

        # 5. pending_edits
        # First ensure parent session, student, and room exist for FK integrity
        stud = Student(usn="1DS24CY001", name="Ash Ketchum", branch="CSE")
        room = Room(room_id="R101", name="Auditorium")
        sess = DbSession(session_id="SESS-001", date="2026-10-24", subject="Machine Learning", subject_code="ML")
        session.add_all([stud, room, sess])
        session.flush()

        attendance = Attendance(
            session_id="SESS-001",
            usn="1DS24CY001",
            room_id="R101",
            status="PRESENT",
            source="AI",
            confidence=0.98,
        )
        session.add(attendance)
        session.flush()

        pe = create_pending_edit(
            session,
            user_id="prof_oak",
            session_id="SESS-001",
            usn="1DS24CY001",
            old_status="PRESENT",
            new_status="ABSENT",
        )
        assert pe["edit_id"] is not None
        assert pe["consumed"] == 0
        session.commit()


def test_audit_log_append_only_triggers(disposable_sqlite_db):
    """Test 2: Verify database-level triggers strictly forbid UPDATE and DELETE on audit_log."""
    db_path, engine = disposable_sqlite_db

    # Manually install the triggers on the test DB.
    # "IF NOT EXISTS" keeps this idempotent: the triggers are also created from
    # the SQLAlchemy model metadata, so they may already be present.
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update
                BEFORE UPDATE ON audit_log
                BEGIN
                    SELECT RAISE(ABORT, 'audit_log is append-only: updates forbidden');
                END;
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete
                BEFORE DELETE ON audit_log
                BEGIN
                    SELECT RAISE(ABORT, 'audit_log is append-only: deletions forbidden');
                END;
                """
            )
        )
        conn.commit()

    with SqlSession(engine) as session:
        # Create actor user
        create_user(session, user_id="admin_1", email="admin@rollcall.edu", role="ADMIN")
        session.commit()

        # Insert audit log
        entry = create_audit_entry(
            session,
            actor_id="admin_1",
            action="CREATE_SESSION",
            entity_type="session",
            entity_id="SESS-100",
        )
        session.commit()
        log_id = entry["log_id"]

        # Attempt UPDATE -> must be rejected by trigger
        with pytest.raises((OperationalError, IntegrityError)) as excinfo:
            session.execute(
                text("UPDATE audit_log SET action = 'MUTATED' WHERE log_id = :log_id"),
                {"log_id": log_id},
            )
            session.commit()
        session.rollback()
        assert "append-only" in str(excinfo.value).lower()

        # Attempt DELETE -> must be rejected by trigger
        with pytest.raises((OperationalError, IntegrityError)) as excinfo:
            session.execute(
                text("DELETE FROM audit_log WHERE log_id = :log_id"),
                {"log_id": log_id},
            )
            session.commit()
        session.rollback()
        assert "append-only" in str(excinfo.value).lower()

        # Verify entry remains completely unchanged
        log_row = session.get(AuditLog, log_id)
        assert log_row is not None
        assert log_row.action == "CREATE_SESSION"


def test_legacy_subject_backfill_and_sentinel_teacher():
    """Test 3: Verify explicit CASE mapping, sentinel user properties, and session backfill via Alembic."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "alembic_test.db")

    # Set up Alembic configuration pointing to temp db
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    ini_path = os.path.join(backend_dir, "alembic.ini")
    alembic_cfg = Config(ini_path)
    db_url = f"sqlite:///{db_path.replace(os.sep, '/')}"
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    # 1. Upgrade to 0001_initial_schema
    command.upgrade(alembic_cfg, "0001_initial_schema")

    # 2. Populate the 5 canonical historical sessions
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    sessions_data = [
        ("SESS-20261024-01", "2026-10-24", "Distributed Systems"),
        ("SESS-20261024-02", "2026-10-24", "Machine Learning"),
        ("SESS-20261025-01", "2026-10-25", "Computer Networks"),
        ("SESS-20261025-02", "2026-10-25", "Database Systems"),
        ("SESS-20261026-01", "2026-10-26", "Embedded Systems"),
    ]
    cur.executemany("INSERT INTO sessions (session_id, date, subject) VALUES (?, ?, ?)", sessions_data)
    conn.commit()
    conn.close()

    # 3. Upgrade to 0002_rbac_tables
    command.upgrade(alembic_cfg, "0002_rbac_tables")

    # 4. Validate backfill assertions
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Sentinel user assertions
    cur.execute("SELECT user_id, email, role, hashed_password, is_active FROM users WHERE user_id = 'legacy'")
    sentinel = cur.fetchone()
    assert sentinel is not None
    assert sentinel[0] == "legacy"
    assert sentinel[1] == "legacy@rollcall.internal"
    assert sentinel[2] == "ADMIN"
    assert sentinel[3] is None  # hashed_password MUST be NULL
    assert sentinel[4] == 0     # is_active MUST be 0 (inactive)

    # Explicit subject_code mapping assertions
    expected_mapping = {
        "Distributed Systems": "DIST-SYS",
        "Machine Learning": "ML",
        "Computer Networks": "CN",
        "Database Systems": "DB-SYS",
        "Embedded Systems": "ES",
    }

    cur.execute("SELECT session_id, subject, subject_code, teacher_id, created_at FROM sessions ORDER BY date")
    rows = cur.fetchall()
    assert len(rows) == 5

    for sess_id, subj, code, teacher, created_at in rows:
        assert code == expected_mapping[subj], f"Expected {expected_mapping[subj]} for {subj}, got {code}"
        assert teacher == "legacy"
        assert created_at.endswith("T00:00:00Z")

    # SQLite integrity and foreign key checks
    cur.execute("PRAGMA integrity_check")
    assert cur.fetchone()[0] == "ok"
    cur.execute("PRAGMA foreign_key_check")
    assert len(cur.fetchall()) == 0

    conn.close()
    shutil.rmtree(temp_dir, ignore_errors=True)


def _build_migration_fixture_db(test_db: str, *, session_count: int = 5, students_per_session: int = 10) -> int:
    """Create a disposable database at revision 0002 with known attendance data.

    The fixture is self-contained: the test suite must never depend on the
    mutable live database (``data/attendance.db``), whose contents legitimately
    change whenever the application is used.
    """
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    ini_path = os.path.join(backend_dir, "alembic.ini")
    alembic_cfg = Config(ini_path)
    db_url = f"sqlite:///{test_db.replace(os.sep, '/')}"
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(alembic_cfg, "0002_rbac_tables")

    conn = sqlite3.connect(test_db)
    cur = conn.cursor()
    total_rows = 0
    for s in range(1, session_count + 1):
        session_id = f"FIXTURE-SESS-{s:02d}"
        cur.execute(
            "INSERT INTO sessions (session_id, date, subject) VALUES (?, ?, ?)",
            (session_id, f"2026-01-{s:02d}", f"Fixture Subject {s}"),
        )
        cur.execute(
            "INSERT INTO rooms (room_id, name) VALUES (?, ?)",
            (f"LAB-{s:02d}", f"Fixture Lab {s}"),
        )
        for i in range(1, students_per_session + 1):
            usn = f"9FIX{s:02d}CS{i:03d}"
            cur.execute(
                "INSERT INTO students (usn, name, branch) VALUES (?, ?, ?)",
                (usn, f"Fixture Student {s}-{i}", "CSE"),
            )
            cur.execute(
                "INSERT INTO attendance (session_id, usn, room_id, status, source, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, usn, f"LAB-{s:02d}", "PRESENT", "camera", 0.95),
            )
            total_rows += 1
    conn.commit()
    conn.close()
    return total_rows


def test_existing_attendance_data_unchanged():
    """Test 4: migration data preservation on a disposable, populated fixture.

    The attendance rows are created by the test itself, so the result never
    depends on the mutable live database.
    """
    temp_dir = tempfile.mkdtemp()
    test_db = os.path.join(temp_dir, "attendance_fixture.db")
    expected_rows = _build_migration_fixture_db(test_db)

    # Configure Alembic
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    ini_path = os.path.join(backend_dir, "alembic.ini")
    alembic_cfg = Config(ini_path)
    db_url = f"sqlite:///{test_db.replace(os.sep, '/')}"
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    # Ensure the fixture starts at the 0001_initial_schema baseline
    command.downgrade(alembic_cfg, "0001_initial_schema")

    # Snapshot pre-migration attendance
    conn = sqlite3.connect(test_db)
    cur = conn.cursor()
    cur.execute("SELECT session_id, usn, room_id, status, source, confidence FROM attendance ORDER BY session_id, usn")
    pre_attendance = cur.fetchall()
    assert len(pre_attendance) == expected_rows, (
        f"Expected {expected_rows} attendance records, found {len(pre_attendance)}"
    )
    conn.close()

    # Upgrade to 0002
    command.upgrade(alembic_cfg, "0002_rbac_tables")

    # Assert post-migration attendance is 100% identical
    conn = sqlite3.connect(test_db)
    cur = conn.cursor()
    cur.execute("SELECT session_id, usn, room_id, status, source, confidence FROM attendance ORDER BY session_id, usn")
    post_attendance = cur.fetchall()
    assert pre_attendance == post_attendance, "Attendance records were altered or lost during migration!"

    cur.execute("PRAGMA foreign_key_check")
    assert len(cur.fetchall()) == 0
    cur.execute("PRAGMA integrity_check")
    assert cur.fetchone()[0] == "ok"
    conn.close()

    # Test downgrade safely preserves attendance
    command.downgrade(alembic_cfg, "0001_initial_schema")
    conn = sqlite3.connect(test_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM attendance")
    assert cur.fetchone()[0] == expected_rows
    cur.execute("SELECT COUNT(*) FROM sessions")
    assert cur.fetchone()[0] == 5
    conn.close()

    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.skipif(
    not os.path.exists(
        os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "data", "attendance.db")
        )
    ),
    reason="Live database snapshot is not present.",
)
def test_live_database_attendance_survives_migration():
    """Opt-in: verify the live snapshot migrates without losing attendance.

    This checks the live file's *current* contents (not a hard-coded row count)
    so it stays valid while the application is in use.
    """
    temp_dir = tempfile.mkdtemp()
    src_db = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "attendance.db")
    )
    if not os.path.exists(src_db):
        pytest.skip("Live database snapshot is not present.")
    test_db = os.path.join(temp_dir, "attendance_live_clone.db")
    shutil.copy2(src_db, test_db)

    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    ini_path = os.path.join(backend_dir, "alembic.ini")
    alembic_cfg = Config(ini_path)
    db_url = f"sqlite:///{test_db.replace(os.sep, '/')}"
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    conn = sqlite3.connect(test_db)
    cur = conn.cursor()
    cur.execute("SELECT session_id, usn, room_id, status, source, confidence FROM attendance ORDER BY session_id, usn")
    pre_attendance = cur.fetchall()
    conn.close()
    assert pre_attendance, "The live snapshot contains no attendance rows."

    command.downgrade(alembic_cfg, "0001_initial_schema")
    command.upgrade(alembic_cfg, "0002_rbac_tables")

    conn = sqlite3.connect(test_db)
    cur = conn.cursor()
    cur.execute("SELECT session_id, usn, room_id, status, source, confidence FROM attendance ORDER BY session_id, usn")
    post_attendance = cur.fetchall()
    cur.execute("PRAGMA foreign_key_check")
    assert len(cur.fetchall()) == 0
    conn.close()
    assert pre_attendance == post_attendance, "Live attendance records were altered during migration!"

    shutil.rmtree(temp_dir, ignore_errors=True)


def test_foreign_key_runtime_enforcement_in_sqlite(disposable_sqlite_db):
    """Test 5: Verify foreign keys are strictly enforced at runtime in SQLite."""
    db_path, engine = disposable_sqlite_db

    with SqlSession(engine) as session:
        # Ensure sentinel user exists
        create_user(session, user_id="valid_teacher", email="teacher@school.edu", role="FACULTY")
        session.commit()

        # 1. Invalid teacher_id in sessions -> rejected
        invalid_session = DbSession(
            session_id="SESS-INVALID",
            date="2026-11-10",
            subject="Algorithms",
            teacher_id="nonexistent_user",
        )
        session.add(invalid_session)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # 2. Valid teacher_id in sessions -> accepted
        valid_session = DbSession(
            session_id="SESS-VALID",
            date="2026-11-10",
            subject="Algorithms",
            teacher_id="valid_teacher",
        )
        session.add(valid_session)
        session.commit()

        # 3. Restrict deletion of teacher with referenced session
        with pytest.raises(IntegrityError):
            session.execute(text("DELETE FROM users WHERE user_id = 'valid_teacher'"))
            session.commit()
        session.rollback()



def test_pending_edit_ownership_expiry_and_single_use(disposable_sqlite_db):
    """Test 6: Verify user ownership, 5-minute expiry, and single-use atomic consumption."""
    db_path, engine = disposable_sqlite_db

    with SqlSession(engine) as session:
        # Setup prerequisites
        create_user(session, user_id="teacher_a", email="a@school.edu", role="FACULTY")
        create_user(session, user_id="teacher_b", email="b@school.edu", role="FACULTY")
        stud = Student(usn="1DS24CY050", name="Bob", branch="CSE")
        room = Room(room_id="R200", name="Lab 1")
        sess = DbSession(session_id="SESS-200", date="2026-10-24", subject="Computer Networks", subject_code="CN", teacher_id="teacher_a")
        session.add_all([stud, room, sess])
        session.flush()

        att = Attendance(session_id="SESS-200", usn="1DS24CY050", room_id="R200", status="PRESENT", source="AI", confidence=1.0)
        session.add(att)
        session.commit()

        # 1. Create pending edit for teacher_a
        edit = create_pending_edit(
            session,
            user_id="teacher_a",
            session_id="SESS-200",
            usn="1DS24CY050",
            old_status="PRESENT",
            new_status="ABSENT",
        )
        edit_id = edit["edit_id"]
        session.commit()

        # 2. Consume by wrong user (teacher_b) -> returns None
        result_wrong_owner = consume_pending_edit_atomic(session, edit_id=edit_id, user_id="teacher_b")
        assert result_wrong_owner is None

        # 3. Consume by correct owner (teacher_a) -> succeeds
        result_owner = consume_pending_edit_atomic(session, edit_id=edit_id, user_id="teacher_a")
        assert result_owner is not None
        assert result_owner["consumed"] == 1
        session.commit()

        # 4. Second consume by teacher_a -> returns None (single-use enforced!)
        result_second = consume_pending_edit_atomic(session, edit_id=edit_id, user_id="teacher_a")
        assert result_second is None

        # 5. Expiry test: create an edit that expired in the past
        past_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        expired_edit = PendingEdit(
            edit_id=str(uuid4()),
            user_id="teacher_a",
            session_id="SESS-200",
            usn="1DS24CY050",
            old_status="PRESENT",
            new_status="ABSENT",
            created_at=past_iso,
            expires_at=past_iso,
            consumed=0,
        )
        session.add(expired_edit)
        session.commit()

        # Attempt to consume expired edit -> returns None
        result_expired = consume_pending_edit_atomic(session, edit_id=expired_edit.edit_id, user_id="teacher_a")
        assert result_expired is None


def test_stale_pending_edit_rejection(disposable_sqlite_db):
    """Test 7: Verify compare-and-set rejects stale edits when status changed concurrently."""
    db_path, engine = disposable_sqlite_db

    with SqlSession(engine) as session:
        create_user(session, user_id="teacher_1", email="t1@school.edu", role="FACULTY")
        assign_teacher_subject(session, user_id="teacher_1", subject_code="CN")
        stud = Student(usn="1DS24CY099", name="Charlie", branch="CSE")
        room = Room(room_id="R300", name="Room 300")
        sess = DbSession(session_id="SESS-300", date="2026-10-24", subject="Computer Networks", subject_code="CN", teacher_id="teacher_1")
        session.add_all([stud, room, sess])
        session.flush()

        att = Attendance(attendance_id=str(uuid4()), session_id="SESS-300", usn="1DS24CY099", room_id="R300", status="PRESENT", source="AI", confidence=1.0)
        session.add(att)
        session.commit()
        att_id = att.attendance_id

        # Proposal created when status was 'PRESENT'
        edit = create_pending_edit(
            session,
            user_id="teacher_1",
            session_id="SESS-300",
            usn="1DS24CY099",
            old_status="PRESENT",
            new_status="ABSENT",
        )
        session.commit()

        # Concurrent modification occurs before confirmation: status changes to 'PENDING'
        att.status = "PENDING"
        session.commit()

        # Confirmation attempt must reject stale edit
        with pytest.raises(ValueError) as excinfo:
            apply_attendance_edit_atomic(
                session,
                edit_id=edit["edit_id"],
                user_id="teacher_1",
                authenticated_role="FACULTY",
            )
        session.rollback()
        assert "stale edit rejected" in str(excinfo.value).lower()

        # Verify attendance record remained 'PENDING'
        rechecked_att = session.get(Attendance, att_id)
        assert rechecked_att.status == "PENDING"

        # Verify pending edit was NOT consumed
        rechecked_edit = session.get(PendingEdit, edit["edit_id"])
        assert rechecked_edit.consumed == 0


def test_atomic_attendance_update_and_audit_rollback(disposable_sqlite_db):
    """Test 8: Verify atomic transaction: audit log insertion and attendance update commit/rollback together."""
    db_path, engine = disposable_sqlite_db

    with SqlSession(engine) as session:
        create_user(session, user_id="admin_user", email="admin@school.edu", role="ADMIN")
        stud = Student(usn="1DS24CY077", name="Diana", branch="CSE")
        room = Room(room_id="R400", name="Room 400")
        sess = DbSession(session_id="SESS-400", date="2026-10-24", subject="Database Systems", subject_code="DB-SYS")
        session.add_all([stud, room, sess])
        session.flush()

        att = Attendance(attendance_id=str(uuid4()), session_id="SESS-400", usn="1DS24CY077", room_id="R400", status="ABSENT", source="MANUAL", confidence=1.0)
        session.add(att)
        session.commit()
        att_id = att.attendance_id

        # 1. Successful atomic execution
        edit1 = create_pending_edit(
            session,
            user_id="admin_user",
            session_id="SESS-400",
            usn="1DS24CY077",
            old_status="ABSENT",
            new_status="PRESENT",
        )
        session.commit()

        res = apply_attendance_edit_atomic(
            session,
            edit_id=edit1["edit_id"],
            user_id="admin_user",
            authenticated_role="ADMIN",
            reason="Medical certificate verified",
        )
        session.commit()

        assert res["consumed"] == 1
        updated_att = session.get(Attendance, att_id)
        assert updated_att.status == "PRESENT"
        audit = session.get(AuditLog, res["audit_log_id"])
        assert audit.action == "ATTENDANCE_EDIT"
        assert audit.reason == "Medical certificate verified"

        # 2. Simulated failure during audit insertion -> full rollback
        edit2 = create_pending_edit(
            session,
            user_id="admin_user",
            session_id="SESS-400",
            usn="1DS24CY077",
            old_status="PRESENT",
            new_status="ABSENT",
        )
        session.commit()

        # Install trigger that blocks specific action to simulate audit failure
        with engine.connect() as conn:
            conn.execute(
                text(
                    """
                    CREATE TRIGGER trg_fail_specific_audit
                    BEFORE INSERT ON audit_log
                    WHEN NEW.reason = 'FORCE_FAILURE'
                    BEGIN
                        SELECT RAISE(ABORT, 'Simulated audit log write failure');
                    END;
                    """
                )
            )
            conn.commit()

        with pytest.raises((OperationalError, IntegrityError)):
            apply_attendance_edit_atomic(
                session,
                edit_id=edit2["edit_id"],
                user_id="admin_user",
                authenticated_role="ADMIN",
                reason="FORCE_FAILURE",
            )
        session.rollback()

        # Verify attendance status did NOT change to ABSENT
        re_att = session.get(Attendance, att_id)
        assert re_att.status == "PRESENT"

        # Verify pending edit was NOT marked consumed
        re_edit = session.get(PendingEdit, edit2["edit_id"])
        assert re_edit.consumed == 0


def test_postgresql_compatibility_integration():
    """Test 9: PostgreSQL live integration on an explicitly configured disposable DB.

    Runs only when TEST_DATABASE_URL points at a disposable PostgreSQL database
    (validated before any destructive operation). When unset, verifies migration
    head availability and offline safety invariants.
    """
    if not os.getenv("TEST_DATABASE_URL"):
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        cfg = Config(os.path.join(backend_dir, "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
        from alembic.script import ScriptDirectory
        script = ScriptDirectory.from_config(cfg)
        head = script.get_current_head()
        assert head is not None
        assert head.startswith("00")
        assert pg_support.configured_test_url() is None
        return

    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import text

    test_url = pg_support.configured_test_url()
    assert test_url, "TEST_DATABASE_URL must be set for this integration test"
    pg_support.validate_disposable(test_url)

    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    cfg = Config(os.path.join(backend_dir, "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", test_url)
    cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))

    engine = pg_support.create_test_engine(test_url)
    try:
        command.upgrade(cfg, "head")

        with engine.connect() as conn:
            # 1. Migration chain reached head.
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert version == "0012_students_academic_fks", version

            # 2. Native foreign keys are enforced by PostgreSQL.
            fk_names = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE contype = 'f' "
                        "AND conrelid IN ('attendance'::regclass, 'sessions'::regclass, "
                        "'students'::regclass)"
                    )
                )
            }
            for expected in (
                "fk_attendance_allocation_id",
                "fk_attendance_session_id",
                "fk_attendance_usn",
                "fk_students_dept_id",
                "fk_students_semester_id",
                "fk_students_section_id",
                "fk_students_batch_id",
            ):
                assert expected in fk_names, f"missing PostgreSQL FK {expected}: {sorted(fk_names)}"
            assert any("teacher_id" in name for name in fk_names), fk_names

            # 3. The two partial unique indexes exist.
            index_sql = {
                row[0]: row[1]
                for row in conn.execute(
                    text(
                        "SELECT indexname, indexdef FROM pg_indexes "
                        "WHERE tablename = 'attendance'"
                    )
                )
            }
            assert "idx_attendance_allocation_usn" in index_sql
            assert "idx_attendance_legacy_session_usn" in index_sql
            assert "WHERE" in index_sql["idx_attendance_allocation_usn"].upper()
            assert "WHERE" in index_sql["idx_attendance_legacy_session_usn"].upper()

        # 4. audit_log is append-only: UPDATE and DELETE are rejected by trigger.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (user_id, email, role, hashed_password, is_active, created_at) "
                    "VALUES ('pg_it_user', 'pg_it@rollcall.edu', 'ADMIN', NULL, 1, '2026-01-01T00:00:00Z') "
                    "ON CONFLICT (user_id) DO NOTHING"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO audit_log (actor_id, action, entity_type, entity_id, timestamp) "
                    "VALUES ('pg_it_user', 'PG_INTEGRATION', 'test', 'pg-it', '2026-01-01T00:00:00Z')"
                )
            )

        with pytest.raises(Exception) as update_exc:
            with engine.begin() as conn:
                conn.execute(text("UPDATE audit_log SET action = 'TAMPERED'"))
        assert "append-only" in str(update_exc.value).lower() or "reject" in str(update_exc.value).lower()

        with pytest.raises(Exception) as delete_exc:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM audit_log"))
        assert "append-only" in str(delete_exc.value).lower() or "reject" in str(delete_exc.value).lower()

        with engine.connect() as conn:
            assert conn.execute(text("SELECT action FROM audit_log")).scalar() == "PG_INTEGRATION"

        # 5. UPDATE ... WHERE rowcount serialization: only one consumer wins.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO rooms (room_id, name) VALUES ('LH-101', 'Lecture Hall') "
                    "ON CONFLICT (room_id) DO NOTHING"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO students (usn, name, branch) VALUES ('PG-IT-USN', 'PG Student', 'CSE') "
                    "ON CONFLICT (usn) DO NOTHING"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO sessions (session_id, date, subject, teacher_id) "
                    "VALUES ('pg-it-sess', '2026-01-01', 'PG Integration', 'pg_it_user') "
                    "ON CONFLICT (session_id) DO NOTHING"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO attendance (attendance_id, session_id, usn, room_id, status, source, "
                    "confidence, recorded_at) VALUES ('pg_it_att', 'pg-it-sess', 'PG-IT-USN', "
                    "'LH-101', 'PRESENT', 'test', 1.0, '2026-01-01T00:00:00Z') "
                    "ON CONFLICT DO NOTHING"
                )
            )
        claim = text(
            "UPDATE attendance SET status = 'ABSENT' "
            "WHERE attendance_id = 'pg_it_att' AND status = 'PRESENT'"
        )
        with engine.begin() as conn:
            first = conn.execute(claim).rowcount
        with engine.begin() as conn:
            second = conn.execute(claim).rowcount
        assert first == 1 and second == 0
    finally:
        try:
            command.downgrade(cfg, "base")
        finally:
            engine.dispose()


def test_postgresql_integration_requires_explicit_disposable_url(monkeypatch):
    """Documents and enforces the safety gate on PostgreSQL integration tests."""
    # No "test" in the database name -> refused.
    with pytest.raises(pg_support.UnsafeTestDatabase):
        pg_support.validate_disposable("postgresql+psycopg://u:p@db.prod.internal:5432/rollcall")

    # Identical to the production write URL -> refused.
    prod_like = "postgresql+psycopg://u:p@localhost:5432/rollcall_test"
    monkeypatch.setenv("DATABASE_URL_SYNC", prod_like)
    with pytest.raises(pg_support.UnsafeTestDatabase):
        pg_support.validate_disposable(prod_like)

    # A distinct disposable test database is accepted.
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    pg_support.validate_disposable("postgresql+psycopg://u:p@localhost:5432/rollcall_disposable_test")
