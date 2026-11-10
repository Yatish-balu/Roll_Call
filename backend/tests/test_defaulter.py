"""Tests for Defaulter Calculation Engine and T-DEF matrix (Prompt N10 / Rule D9)."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Attendance, Session as DbSession, Student, Room, TeacherSubject, User
from app.routers.defaulters import list_defaulters
from app.schemas.auth import AuthenticatedUser
from tools.defaulter_tool import calculate_classes_needed, get_defaulters_data


def test_t_def_formula_all_rows():
    """Verify formula calculation for each row in table T-DEF."""
    # Row 1: 20 conducted, 12 attended, 75% -> 60.0%, Defaulter=Yes, Needed=12
    assert calculate_classes_needed(20, 12, 75.0) == 12

    # Row 2: 20 conducted, 14 attended, 75% -> 70.0%, Defaulter=Yes, Needed=4
    assert calculate_classes_needed(20, 14, 75.0) == 4

    # Row 3: 20 conducted, 15 attended, 75% -> 75.0%, Defaulter=No, Needed=0
    assert calculate_classes_needed(20, 15, 75.0) == 0

    # Row 4: 20 conducted, 18 attended, 75% -> 90.0%, Defaulter=No, Needed=0
    assert calculate_classes_needed(20, 18, 75.0) == 0

    # Row 5: 8 conducted, 5 attended, 75% -> 62.5%, Defaulter=Yes, Needed=4
    assert calculate_classes_needed(8, 5, 75.0) == 4

    # Row 6: 1 conducted, 0 attended, 75% -> 0.0%, Defaulter=Yes, Needed=3
    assert calculate_classes_needed(1, 0, 75.0) == 3

    # Row 7: 0 conducted, 0 attended -> 0 (no division by zero)
    assert calculate_classes_needed(0, 0, 75.0) == 0

    # Row 8: 10 conducted, 7 attended, threshold 80% -> 70.0%, Defaulter=Yes, Needed=5
    assert calculate_classes_needed(10, 7, 80.0) == 5


@pytest.fixture
def defaulter_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    admin = User(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN", created_at=now)
    t1 = User(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY", created_at=now)
    db.add_all([admin, t1])

    # Teacher subjects: t1 teaches DBMS
    ts1 = TeacherSubject(user_id="faculty_t1", subject_code="DBMS")
    db.add(ts1)

    r1 = Room(room_id="LH-101", name="Hall 101")
    db.add(r1)

    # Students
    s1 = Student(usn="1MS21CS001", name="Alice Defaulter (60%)", branch="CSE")
    s2 = Student(usn="1MS21CS002", name="Bob OnTheDot (75%)", branch="CSE")
    s3 = Student(usn="1MS21CS003", name="Charlie High (90%)", branch="CSE")
    s4 = Student(usn="1MS21EC001", name="Diana ECE Defaulter (50%)", branch="ECE")
    s5 = Student(usn="1MS21ME001", name="Evan Zero Conducted", branch="ME")
    db.add_all([s1, s2, s3, s4, s5])

    # Sessions for DBMS (10 sessions total)
    for i in range(1, 11):
        sess = DbSession(session_id=f"SESS-DBMS-{i}", date=f"2026-11-{i:02d}", subject="DBMS", teacher_id="faculty_t1", subject_code="DBMS", created_at=now)
        db.add(sess)

        # Alice attends 6 of 10 (60%) -> Defaulter!
        status_alice = "PRESENT" if i <= 6 else "ABSENT"
        db.add(Attendance(attendance_id=f"a1_{i}", session_id=f"SESS-DBMS-{i}", usn="1MS21CS001", room_id="LH-101", status=status_alice, source="CSV", recorded_at=now))

        # Bob attends 8 of 10 (80%) -> Not defaulter
        status_bob = "PRESENT" if i <= 8 else "ABSENT"
        db.add(Attendance(attendance_id=f"a2_{i}", session_id=f"SESS-DBMS-{i}", usn="1MS21CS002", room_id="LH-101", status=status_bob, source="CSV", recorded_at=now))

        # Charlie attends 10 of 10 (100%) -> Not defaulter
        db.add(Attendance(attendance_id=f"a3_{i}", session_id=f"SESS-DBMS-{i}", usn="1MS21CS003", room_id="LH-101", status="PRESENT", source="CSV", recorded_at=now))

        # Diana (ECE) attends 5 of 10 (50%) -> Defaulter!
        status_diana = "PRESENT" if i <= 5 else "ABSENT"
        db.add(Attendance(attendance_id=f"a4_{i}", session_id=f"SESS-DBMS-{i}", usn="1MS21EC001", room_id="LH-101", status=status_diana, source="CSV", recorded_at=now))

    # Evan has 0 attendance records (conducted = 0)
    db.commit()

    try:
        yield db
    finally:
        db.close()


def test_t_def_query_defaulters_only(defaulter_db: Session):
    """Students at 75% or higher are NOT listed. Only strictly below 75%."""
    admin = AuthenticatedUser(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN")
    res = list_defaulters(threshold=75.0, current_user=admin, db=defaulter_db)

    usns = [d["usn"] for d in res]
    assert "1MS21CS001" in usns  # 60%
    assert "1MS21EC001" in usns  # 50%
    assert "1MS21CS002" not in usns  # 80%
    assert "1MS21CS003" not in usns  # 100%
    assert "1MS21ME001" not in usns  # 0 conducted excluded

    # Lowest percent first: Diana (50%) before Alice (60%)
    assert res[0]["usn"] == "1MS21EC001"
    assert res[0]["percent"] == 50.0
    assert res[1]["usn"] == "1MS21CS001"
    assert res[1]["percent"] == 60.0


def test_t_def_teacher_subject_scope(defaulter_db: Session):
    """Teacher cannot view defaulters for unassigned subject (403)."""
    t1 = AuthenticatedUser(user_id="faculty_t1", email="t1@rollcall.internal", role="FACULTY")

    # t1 teaches DBMS: succeeds
    res = list_defaulters(subject_code="DBMS", current_user=t1, db=defaulter_db)
    assert len(res) == 2

    # t1 does not teach MATH: 403
    with pytest.raises(HTTPException) as exc_info:
        list_defaulters(subject_code="MATH", current_user=t1, db=defaulter_db)
    assert exc_info.value.status_code == 403

