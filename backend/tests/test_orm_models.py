"""Tests for Phase 2: Database foundation ORM models and engines."""

import pytest
from sqlalchemy import inspect
from app.db.base import Base
from app.db.models import Student, Room, Session, Attendance, AttendanceStatus
from app.db.connection import create_sync_engine, get_sync_session_factory


def test_models_metadata_registered():
    """Verify that all 4 models are properly registered in Base.metadata."""
    table_names = set(Base.metadata.tables.keys())
    expected = {"students", "rooms", "sessions", "attendance"}
    assert expected.issubset(table_names), f"Missing tables in metadata: {expected - table_names}"


def test_attendance_table_constraints():
    """Verify attendance surrogate primary key, foreign keys, indexes, and check constraint."""
    att_table = Base.metadata.tables["attendance"]

    # Surrogate PK
    pk_cols = [c.name for c in att_table.primary_key.columns]
    assert pk_cols == ["attendance_id"]

    # Foreign Keys
    fks = {fk.column.table.name: (fk.parent.name, fk.ondelete) for fk in att_table.foreign_keys}
    assert "sessions" in fks
    assert fks["sessions"] == ("session_id", "CASCADE")
    assert "students" in fks
    assert fks["students"] == ("usn", "CASCADE")
    assert "rooms" in fks
    assert fks["rooms"] == ("room_id", "RESTRICT")

    # Indexes
    idx_names = {idx.name for idx in att_table.indexes}
    assert "idx_attendance_session" in idx_names
    assert "idx_attendance_usn" in idx_names
    assert "idx_attendance_room" in idx_names
    assert "idx_attendance_allocation" in idx_names

    # Check constraint
    ck_names = [ck.name for ck in att_table.constraints if hasattr(ck, "sqltext")]
    assert "check_attendance_status" in ck_names


def test_sqlite_in_memory_engine_creation():
    """Verify that an in-memory SQLite engine and tables can be created via SQLAlchemy."""
    engine = create_sync_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert {"students", "rooms", "sessions", "attendance"}.issubset(set(tables))


    # Basic insert & query smoke test
    SessionLocal = get_sync_session_factory(engine)
    with SessionLocal() as session:
        stu = Student(usn="1MS21CS001", name="Test Student", branch="CSE")
        room = Room(room_id="LH-101", name="Hall 101")
        sess = Session(session_id="SESS-TEST-01", date="2026-10-25", subject="Testing")
        att = Attendance(
            session_id="SESS-TEST-01",
            usn="1MS21CS001",
            room_id="LH-101",
            status=AttendanceStatus.PRESENT.value,
            source="test",
            confidence=1.0,
        )
        session.add_all([stu, room, sess, att])
        session.commit()

        queried_att = session.query(Attendance).first()
        assert queried_att is not None
        assert queried_att.usn == "1MS21CS001"
        assert queried_att.status == "PRESENT"
        assert queried_att.confidence == 1.0

    engine.dispose()

