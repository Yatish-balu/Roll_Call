"""Tests for consolidated faculty-subject mapping (Ticket RC-DB-001).

Validates that faculty_subjects is used exclusively, teacher_subjects is not referenced,
unique constraint on (user_id, subject_code) is strictly enforced, and the optional
semester and dept_id columns work as expected.
"""

import os
import shutil
import tempfile
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as SqlSession

from app.db.base import Base
from app.db.models import User, FacultySubject, Department
from app.db.crud import (
    create_user,
    assign_teacher_subject,
    get_teacher_subjects,
    list_teacher_subject_mappings,
    is_teacher_assigned_to_subject,
)


@pytest.fixture
def mapping_sqlite_db():
    """Create an isolated, temporary SQLite database using current Base metadata."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "mapping_test.db")
    engine = create_engine(f"sqlite:///{db_path}")

    Base.metadata.create_all(bind=engine)

    yield db_path, engine

    engine.dispose()
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_faculty_subject_exclusive_usage(mapping_sqlite_db):
    """Verify that assignments are written to faculty_subjects and teacher_subjects does not exist."""
    db_path, engine = mapping_sqlite_db

    # Verify teacher_subjects table is NOT created by current Base metadata
    with engine.connect() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
        assert "faculty_subjects" in tables
        assert "teacher_subjects" not in tables

    with SqlSession(engine) as session:
        # Create test users
        u1 = create_user(session, user_id="prof_oak", email="oak@kanto.edu", role="FACULTY", is_active=1)
        u2 = create_user(session, user_id="prof_elm", email="elm@johto.edu", role="FACULTY", is_active=1)
        session.commit()

        # Assign subject
        mapping1 = assign_teacher_subject(session, user_id="prof_oak", subject_code="ML", semester=6)
        session.commit()
        assert mapping1["user_id"] == "prof_oak"
        assert mapping1["subject_code"] == "ML"
        assert mapping1.get("semester") == 6

        # Assign another subject with dept_id (works without needing full institutional hierarchy)
        mapping2 = assign_teacher_subject(session, user_id="prof_oak", subject_code="DIST-SYS", dept_id="CSE")
        session.commit()
        assert mapping2["user_id"] == "prof_oak"
        assert mapping2["subject_code"] == "DIST-SYS"
        assert mapping2.get("dept_id") == "CSE"

        # Check retrieval
        subjects = get_teacher_subjects(session, user_id="prof_oak")
        assert subjects == ["DIST-SYS", "ML"]

        # Check boolean lookup
        assert is_teacher_assigned_to_subject(session, user_id="prof_oak", subject_code="ML") is True
        assert is_teacher_assigned_to_subject(session, user_id="prof_oak", subject_code="CRYPTO") is False

        # Verify duplicate assignment triggers IntegrityError
        with pytest.raises(IntegrityError):
            assign_teacher_subject(session, user_id="prof_oak", subject_code="ML")
        session.rollback()

        # Check listing helper
        mappings = list_teacher_subject_mappings(session, user_id="prof_oak")
        assert len(mappings) == 2
        assert {m["subject_code"] for m in mappings} == {"ML", "DIST-SYS"}

        # Check raw DB row directly in faculty_subjects table
        fs_record = session.execute(
            select(FacultySubject).where(FacultySubject.user_id == "prof_oak", FacultySubject.subject_code == "ML")
        ).scalar_one_or_none()
        assert fs_record is not None
        assert fs_record.semester == 6
