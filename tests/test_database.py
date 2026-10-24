"""Tests for SQLite database schema and CRUD operations."""

import sqlite3
import pytest
from app.db import (
    init_db,
    get_connection,
    insert_student,
    insert_students_bulk,
    get_student,
    get_all_students,
    get_students_by_branch,
    insert_room,
    insert_rooms_bulk,
    get_room,
    get_all_rooms,
    insert_session,
    insert_sessions_bulk,
    get_session,
    get_all_sessions,
    get_sessions_by_date,
    insert_attendance,
    insert_attendance_bulk,
    delete_session_attendance,
    replace_session_attendance,
    reconcile_session_roster,
    get_attendance_record,
    get_attendance_by_session,
    get_attendance_by_student,
    get_session_attendance_details,
    VALID_ATTENDANCE_STATUSES,
)
from tools.database import setup_database, inspect_database
import tempfile
from pathlib import Path


@pytest.fixture
def db_conn():
    """Fixture providing an in-memory database with initialized schema."""
    conn = get_connection(":memory:")
    init_db(conn)
    yield conn
    conn.close()


# ==========================================
# Schema Tests
# ==========================================

def test_init_db_creates_tables(db_conn):
    """Verify that all four required tables are properly created."""
    cursor = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name ASC;"
    )
    tables = [row["name"] for row in cursor.fetchall()]
    assert "students" in tables
    assert "rooms" in tables
    assert "sessions" in tables
    assert "attendance" in tables


# ==========================================
# Students Tests
# ==========================================

def test_insert_and_get_student(db_conn):
    """Test inserting and retrieving a single student."""
    insert_student(db_conn, usn="1MS21CS001", name="Alice Smith", branch="CSE")
    student = get_student(db_conn, "1MS21CS001")

    assert student is not None
    assert student["usn"] == "1MS21CS001"
    assert student["name"] == "Alice Smith"
    assert student["branch"] == "CSE"


def test_insert_duplicate_student_fails(db_conn):
    """Test that inserting a student with duplicate USN raises IntegrityError."""
    insert_student(db_conn, usn="1MS21CS001", name="Alice Smith", branch="CSE")
    with pytest.raises(sqlite3.IntegrityError):
        insert_student(db_conn, usn="1MS21CS001", name="Alice Duplicate", branch="ISE")


def test_insert_students_bulk_and_queries(db_conn):
    """Test bulk insertion and filtering by branch."""
    students = [
        {"usn": "1MS21CS002", "name": "Bob Jones", "branch": "CSE"},
        {"usn": "1MS21IS001", "name": "Charlie Brown", "branch": "ISE"},
        {"usn": "1MS21CS003", "name": "Diana Prince", "branch": "CSE"},
    ]
    inserted_count = insert_students_bulk(db_conn, students)
    assert inserted_count == 3

    all_students = get_all_students(db_conn)
    assert len(all_students) == 3

    cse_students = get_students_by_branch(db_conn, "CSE")
    assert len(cse_students) == 2
    assert [s["usn"] for s in cse_students] == ["1MS21CS002", "1MS21CS003"]


# ==========================================
# Rooms Tests
# ==========================================

def test_insert_and_get_room(db_conn):
    """Test inserting and retrieving rooms."""
    insert_room(db_conn, room_id="LH-101", name="Lecture Hall 101")
    room = get_room(db_conn, "LH-101")

    assert room is not None
    assert room["room_id"] == "LH-101"
    assert room["name"] == "Lecture Hall 101"


def test_insert_rooms_bulk_and_get_all(db_conn):
    """Test bulk inserting rooms and retrieving list."""
    rooms = [
        {"room_id": "CR-201", "name": "Classroom 201"},
        {"room_id": "LAB-1", "name": "Computer Lab 1"},
    ]
    count = insert_rooms_bulk(db_conn, rooms)
    assert count == 2

    all_rooms = get_all_rooms(db_conn)
    assert len(all_rooms) == 2


# ==========================================
# Sessions Tests
# ==========================================

def test_insert_and_get_session(db_conn):
    """Test inserting and retrieving a session."""
    insert_session(db_conn, session_id="SESS-001", date="2026-10-23", subject="Operating Systems")
    sess = get_session(db_conn, "SESS-001")

    assert sess is not None
    assert sess["session_id"] == "SESS-001"
    assert sess["date"] == "2026-10-23"
    assert sess["subject"] == "Operating Systems"


def test_insert_sessions_bulk_and_filter_date(db_conn):
    """Test bulk sessions insertion and filtering by date."""
    sessions = [
        {"session_id": "SESS-101", "date": "2026-10-23", "subject": "Data Structures"},
        {"session_id": "SESS-102", "date": "2026-10-23", "subject": "Algorithms"},
        {"session_id": "SESS-103", "date": "2026-10-24", "subject": "Computer Networks"},
    ]
    count = insert_sessions_bulk(db_conn, sessions)
    assert count == 3

    oct_23_sessions = get_sessions_by_date(db_conn, "2026-10-23")
    assert len(oct_23_sessions) == 2
    assert {s["session_id"] for s in oct_23_sessions} == {"SESS-101", "SESS-102"}

    all_sess = get_all_sessions(db_conn)
    assert len(all_sess) == 3


# ==========================================
# Attendance Tests
# ==========================================

@pytest.fixture
def seeded_db(db_conn):
    """Seeds prerequisite foreign key entities."""
    insert_student(db_conn, usn="1MS21CS001", name="Alice Smith", branch="CSE")
    insert_student(db_conn, usn="1MS21CS002", name="Bob Jones", branch="CSE")
    insert_student(db_conn, usn="1MS21CS003", name="Charlie Brown", branch="CSE")
    insert_student(db_conn, usn="1MS21CS004", name="Diana Prince", branch="CSE")
    insert_room(db_conn, room_id="LH-101", name="Lecture Hall 101")
    insert_room(db_conn, room_id="LH-102", name="Lecture Hall 102")
    insert_session(db_conn, session_id="SESS-001", date="2026-10-23", subject="Machine Learning")
    insert_session(db_conn, session_id="SESS-002", date="2026-10-24", subject="Cloud Computing")
    return db_conn


def test_insert_and_get_attendance(seeded_db):
    """Test recording and reading attendance."""
    record = insert_attendance(
        seeded_db,
        session_id="SESS-001",
        usn="1MS21CS001",
        room_id="LH-101",
        status="present",
        source="camera",
        confidence=0.98,
    )
    assert record["status"] == "PRESENT"
    assert record["confidence"] == 0.98

    retrieved = get_attendance_record(seeded_db, "SESS-001", "1MS21CS001")
    assert retrieved is not None
    assert retrieved["room_id"] == "LH-101"
    assert retrieved["status"] == "PRESENT"
    assert retrieved["source"] == "camera"
    assert round(retrieved["confidence"], 2) == 0.98


def test_four_state_attendance_support(seeded_db):
    """
    Requirement 1: Verify attendance status field supports four distinct states:
    PRESENT, ABSENT, PENDING, and UNREVIEWED.
    Ensure invalid status raises ValueError.
    """
    states = ["PRESENT", "ABSENT", "PENDING", "UNREVIEWED"]
    usns = ["1MS21CS001", "1MS21CS002", "1MS21CS003", "1MS21CS004"]

    for usn, st in zip(usns, states):
        rec = insert_attendance(
            seeded_db,
            session_id="SESS-001",
            usn=usn,
            room_id="LH-101",
            status=st,
            source="test",
            confidence=1.0,
        )
        assert rec["status"] == st
        fetched = get_attendance_record(seeded_db, "SESS-001", usn)
        assert fetched["status"] == st

    # Invalid status raises ValueError
    with pytest.raises(ValueError, match="Invalid attendance status"):
        insert_attendance(
            seeded_db,
            session_id="SESS-001",
            usn="1MS21CS001",
            room_id="LH-101",
            status="MAYBE_ATTENDED",
            source="test",
            upsert=True,
        )


def test_roster_reconciliation_missing_sheet_and_ambiguity(seeded_db):
    """
    Requirement 1 & 2:
    - Missing sheets leave status as PENDING.
    - Ambiguous extracted entries leave status as UNREVIEWED.
    - Neither PENDING nor UNREVIEWED should ever be defaulted or miscounted as ABSENT.
    """
    roster = [
        {"usn": "1MS21CS001", "room_id": "LH-101"},
        {"usn": "1MS21CS002", "room_id": "LH-101"},
        {"usn": "1MS21CS003", "room_id": "LH-102"},  # Room LH-102 has missing sheet
        {"usn": "1MS21CS004", "room_id": "LH-101"},
    ]

    uploaded_records = [
        {"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "confidence": 0.95},
        # 1MS21CS002 has ambiguous low confidence entry
        {"usn": "1MS21CS002", "room_id": "LH-101", "status": "PRESENT", "confidence": 0.45},
        # 1MS21CS004 is explicitly absent
        {"usn": "1MS21CS004", "room_id": "LH-101", "status": "ABSENT", "confidence": 1.0},
    ]

    reconciled = reconcile_session_roster(
        seeded_db,
        session_id="SESS-001",
        roster=roster,
        uploaded_records=uploaded_records,
        missing_room_ids={"LH-102"},
        confidence_threshold=0.70,
        persist=True,
    )

    by_usn = {r["usn"]: r for r in reconciled}

    # 1MS21CS001: high confidence present -> PRESENT
    assert by_usn["1MS21CS001"]["status"] == "PRESENT"
    # 1MS21CS002: low confidence (0.45 < 0.70) -> UNREVIEWED (NOT ABSENT!)
    assert by_usn["1MS21CS002"]["status"] == "UNREVIEWED"
    # 1MS21CS003: missing room sheet -> PENDING (NOT ABSENT!)
    assert by_usn["1MS21CS003"]["status"] == "PENDING"
    # 1MS21CS004: confirmed absent -> ABSENT
    assert by_usn["1MS21CS004"]["status"] == "ABSENT"

    # Verify persisted in database
    db_records = get_attendance_by_session(seeded_db, "SESS-001")
    db_by_usn = {r["usn"]: r for r in db_records}
    assert db_by_usn["1MS21CS002"]["status"] == "UNREVIEWED"
    assert db_by_usn["1MS21CS003"]["status"] == "PENDING"


def test_attendance_foreign_key_enforcement(seeded_db):
    """Verify that inserting attendance with non-existent foreign keys fails."""
    # Invalid session
    with pytest.raises(sqlite3.IntegrityError):
        insert_attendance(
            seeded_db,
            session_id="INVALID-SESSION",
            usn="1MS21CS001",
            room_id="LH-101",
            status="PRESENT",
            source="manual",
        )

    # Invalid student USN
    with pytest.raises(sqlite3.IntegrityError):
        insert_attendance(
            seeded_db,
            session_id="SESS-001",
            usn="NON-EXISTENT-USN",
            room_id="LH-101",
            status="PRESENT",
            source="manual",
        )

    # Invalid room
    with pytest.raises(sqlite3.IntegrityError):
        insert_attendance(
            seeded_db,
            session_id="SESS-001",
            usn="1MS21CS001",
            room_id="ROOM-404",
            status="PRESENT",
            source="manual",
        )


def test_attendance_duplicate_and_upsert(seeded_db):
    """Test duplicate error when upsert=False and successful update when upsert=True."""
    insert_attendance(
        seeded_db,
        session_id="SESS-001",
        usn="1MS21CS001",
        room_id="LH-101",
        status="ABSENT",
        source="manual",
        confidence=1.0,
        upsert=False,
    )

    # Duplicate without upsert raises IntegrityError
    with pytest.raises(sqlite3.IntegrityError):
        insert_attendance(
            seeded_db,
            session_id="SESS-001",
            usn="1MS21CS001",
            room_id="LH-101",
            status="PRESENT",
            source="camera",
            confidence=0.95,
            upsert=False,
        )

    # With upsert=True, it updates status and confidence
    insert_attendance(
        seeded_db,
        session_id="SESS-001",
        usn="1MS21CS001",
        room_id="LH-101",
        status="PRESENT",
        source="camera",
        confidence=0.95,
        upsert=True,
    )
    updated = get_attendance_record(seeded_db, "SESS-001", "1MS21CS001")
    assert updated["status"] == "PRESENT"
    assert updated["source"] == "camera"
    assert round(updated["confidence"], 2) == 0.95


def test_reupload_session_clean_without_corrupting_other_sessions(seeded_db):
    """
    Requirement 2: Ensure re-uploading attendance data for a session updates that
    session cleanly without corrupting other sessions.
    """
    # 1. Populate SESS-001 and SESS-002
    insert_attendance(
        seeded_db,
        session_id="SESS-001",
        usn="1MS21CS001",
        room_id="LH-101",
        status="ABSENT",
        source="initial_upload",
    )
    insert_attendance(
        seeded_db,
        session_id="SESS-002",
        usn="1MS21CS001",
        room_id="LH-101",
        status="PRESENT",
        source="initial_upload",
    )
    insert_attendance(
        seeded_db,
        session_id="SESS-002",
        usn="1MS21CS002",
        room_id="LH-101",
        status="ABSENT",
        source="initial_upload",
    )

    # Verify SESS-002 has 2 records
    sess2_before = get_attendance_by_session(seeded_db, "SESS-002")
    assert len(sess2_before) == 2

    # 2. Re-upload attendance for SESS-001 only with corrected data
    new_sess1_records = [
        {"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "source": "reupload", "confidence": 1.0},
        {"usn": "1MS21CS002", "room_id": "LH-101", "status": "PENDING", "source": "reupload", "confidence": 1.0},
    ]
    replaced_count = replace_session_attendance(seeded_db, "SESS-001", new_sess1_records)
    assert replaced_count == 2

    # Verify SESS-001 is updated cleanly
    sess1_after = get_attendance_by_session(seeded_db, "SESS-001")
    assert len(sess1_after) == 2
    sess1_dict = {r["usn"]: r for r in sess1_after}
    assert sess1_dict["1MS21CS001"]["status"] == "PRESENT"
    assert sess1_dict["1MS21CS001"]["source"] == "reupload"
    assert sess1_dict["1MS21CS002"]["status"] == "PENDING"

    # Verify SESS-002 is completely uncorrupted and intact
    sess2_after = get_attendance_by_session(seeded_db, "SESS-002")
    assert len(sess2_after) == 2
    sess2_dict = {r["usn"]: r for r in sess2_after}
    assert sess2_dict["1MS21CS001"]["status"] == "PRESENT"
    assert sess2_dict["1MS21CS001"]["source"] == "initial_upload"
    assert sess2_dict["1MS21CS002"]["status"] == "ABSENT"


def test_attendance_bulk_and_session_queries(seeded_db):
    """Test bulk attendance insertion and queries by session & student."""
    records = [
        {
            "session_id": "SESS-001",
            "usn": "1MS21CS001",
            "room_id": "LH-101",
            "status": "PRESENT",
            "source": "rfid",
            "confidence": 1.0,
        },
        {
            "session_id": "SESS-001",
            "usn": "1MS21CS002",
            "room_id": "LH-101",
            "status": "ABSENT",
            "source": "manual",
            "confidence": 1.0,
        },
    ]
    count = insert_attendance_bulk(seeded_db, records)
    assert count == 2

    by_session = get_attendance_by_session(seeded_db, "SESS-001")
    assert len(by_session) == 2

    by_student = get_attendance_by_student(seeded_db, "1MS21CS001")
    assert len(by_student) == 1
    assert by_student[0]["status"] == "PRESENT"


def test_session_attendance_details_join(seeded_db):
    """Test detailed joined report querying session, students, and room."""
    insert_attendance(
        seeded_db,
        session_id="SESS-001",
        usn="1MS21CS001",
        room_id="LH-101",
        status="PRESENT",
        source="camera",
        confidence=0.94,
    )

    details = get_session_attendance_details(seeded_db, "SESS-001")
    assert len(details) == 1
    d = details[0]
    assert d["session_id"] == "SESS-001"
    assert d["session_date"] == "2026-10-23"
    assert d["subject"] == "Machine Learning"
    assert d["usn"] == "1MS21CS001"
    assert d["student_name"] == "Alice Smith"
    assert d["branch"] == "CSE"
    assert d["room_id"] == "LH-101"
    assert d["room_name"] == "Lecture Hall 101"
    assert d["status"] == "PRESENT"
    assert d["source"] == "camera"
    assert round(d["confidence"], 2) == 0.94


def test_fresh_setup_and_data_persistence():
    """
    Requirement 5: Fresh Setup & Data Persistence.
    Verify that running the database initialization script creates a clean
    database and persists data correctly across restarts.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    try:
        # Step 1: Initialize and seed clean database
        setup_res = setup_database(temp_db_path, seed=True)
        assert setup_res["status"] == "success"
        assert setup_res["seeded"]["students"] == 200
        assert setup_res["seeded"]["rooms"] == 6
        assert setup_res["seeded"]["sessions"] == 5

        # Step 2: Open a fresh connection across process/connection restart
        conn1 = get_connection(temp_db_path)
        all_students = get_all_students(conn1)
        assert len(all_students) == 200

        all_rooms = get_all_rooms(conn1)
        assert len(all_rooms) == 6

        all_sessions = get_all_sessions(conn1)
        assert len(all_sessions) == 5

        # Step 3: Insert new record, commit, close
        insert_student(conn1, usn="1MS21CS999", name="Persistence Test Student", branch="CSE")
        conn1.close()

        # Step 4: Re-open yet another connection and verify persistence
        conn2 = get_connection(temp_db_path)
        persisted_student = get_student(conn2, "1MS21CS999")
        assert persisted_student is not None
        assert persisted_student["name"] == "Persistence Test Student"
        conn2.close()

    finally:
        Path(temp_db_path).unlink(missing_ok=True)
