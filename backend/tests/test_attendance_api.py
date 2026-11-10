"""Tests for Phase 5.4: Attendance & Reconciliation API Routers.

Verifies:
1. Session attendance retrieval with joined student & room metadata.
2. 404 for missing sessions.
3. Single record creation, upsert update, duplicate 409 rejection.
4. Validation errors: invalid status, confidence out of bounds.
5. Bulk insertion with conflict checking and atomic rollback.
6. Attendance replacement (PUT) preserving transactional cleanup for that session only.
7. Session-specific deletion (DELETE) leaving session and master records intact.
8. Student attendance history retrieval.
9. Reconciliation behavior:
   - Roster reconciliation preserving PENDING for missing sheets and UNREVIEWED for low confidence marks.
   - Explicit manual resolution updates.
   - Strict rule: PENDING and UNREVIEWED are never coerced to ABSENT.
10. Foreign-key validation (invalid session, student USN, or room ID).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Student, Room, Session as DbSession, Attendance
from app.dependencies import get_db
from app.main import app


@pytest.fixture
def test_db_engine():
    """In-memory SQLite database isolated per test session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def seeded_client(test_db_engine):
    """FastAPI TestClient with isolated in-memory DB dependency override and seeded master data."""
    TestingSessionLocal = sessionmaker(bind=test_db_engine, class_=Session, expire_on_commit=False)

    # Seed master data
    with TestingSessionLocal() as session:
        session.add_all([
            Student(usn="1MS21CS001", name="Alice Smith", branch="CSE"),
            Student(usn="1MS21CS002", name="Bob Jones", branch="CSE"),
            Student(usn="1MS21CS003", name="Charlie Brown", branch="ECE"),
            Student(usn="1MS21CS004", name="David Miller", branch="ECE"),
        ])
        session.add_all([
            Room(room_id="LH-101", name="Lecture Hall 101"),
            Room(room_id="LH-102", name="Lecture Hall 102"),
        ])
        session.add_all([
            DbSession(session_id="SESS-001", date="2026-03-15", subject="Computer Networks"),
            DbSession(session_id="SESS-002", date="2026-03-16", subject="Operating Systems"),
        ])
        session.commit()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app, raise_server_exceptions=False)
    yield test_client
    app.dependency_overrides.clear()


# ==============================================================================
# 1. Session Attendance Retrieval & Missing Session (404)
# ==============================================================================

def test_get_session_attendance_empty_and_populated(seeded_client):
    # Empty session attendance
    res = seeded_client.get("/api/v1/attendance/sessions/SESS-001")
    assert res.status_code == 200
    assert res.json() == []

    # Insert a record
    rec_res = seeded_client.post(
        "/api/v1/attendance/sessions/SESS-001/record",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "source": "csv", "confidence": 0.95},
    )
    assert rec_res.status_code == 201

    # Fetch detailed session attendance
    get_res = seeded_client.get("/api/v1/attendance/sessions/SESS-001")
    assert get_res.status_code == 200
    records = get_res.json()
    assert len(records) == 1
    assert records[0]["session_id"] == "SESS-001"
    assert records[0]["usn"] == "1MS21CS001"
    assert records[0]["student_name"] == "Alice Smith"
    assert records[0]["room_id"] == "LH-101"
    assert records[0]["room_name"] == "Lecture Hall 101"
    assert records[0]["status"] == "PRESENT"


def test_get_session_attendance_missing_session_returns_404(seeded_client):
    res = seeded_client.get("/api/v1/attendance/sessions/NONEXISTENT-SESSION")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


# ==============================================================================
# 2. Single Record Creation, Upsert Update, and Duplicate 409
# ==============================================================================

def test_record_attendance_creation_and_duplicate_handling(seeded_client):
    payload = {
        "usn": "1MS21CS001",
        "room_id": "LH-101",
        "status": "PRESENT",
        "source": "manual",
        "confidence": 1.0,
    }
    # Initial creation
    res1 = seeded_client.post("/api/v1/attendance/sessions/SESS-001/record", json=payload)
    assert res1.status_code == 201
    assert res1.json()["status"] == "PRESENT"

    # Duplicate without upsert returns 409
    res2 = seeded_client.post("/api/v1/attendance/sessions/SESS-001/record", json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"].lower()

    # Update with upsert=true succeeds
    update_payload = {
        "usn": "1MS21CS001",
        "room_id": "LH-101",
        "status": "ABSENT",
        "source": "verified_manual",
        "confidence": 1.0,
    }
    res3 = seeded_client.post("/api/v1/attendance/sessions/SESS-001/record?upsert=true", json=update_payload)
    assert res3.status_code == 200
    assert res3.json()["status"] == "ABSENT"


def test_record_attendance_all_four_canonical_states(seeded_client):
    states = [
        ("1MS21CS001", "PRESENT"),
        ("1MS21CS002", "ABSENT"),
        ("1MS21CS003", "PENDING"),
        ("1MS21CS004", "UNREVIEWED"),
    ]
    for usn, st in states:
        res = seeded_client.post(
            "/api/v1/attendance/sessions/SESS-001/record",
            json={"usn": usn, "room_id": "LH-101", "status": st, "source": "test"},
        )
        assert res.status_code == 201
        assert res.json()["status"] == st


# ==============================================================================
# 3. Validation Errors: Status & Confidence
# ==============================================================================

def test_record_attendance_invalid_status_rejected(seeded_client):
    bad_payload = {
        "usn": "1MS21CS001",
        "room_id": "LH-101",
        "status": "EXCUSED",  # Not one of the 4 canonical states
        "source": "test",
    }
    res = seeded_client.post("/api/v1/attendance/sessions/SESS-001/record", json=bad_payload)
    assert res.status_code == 422


def test_record_attendance_confidence_bounds_rejected(seeded_client):
    # Confidence < 0.0
    res_neg = seeded_client.post(
        "/api/v1/attendance/sessions/SESS-001/record",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "confidence": -0.1},
    )
    assert res_neg.status_code == 422

    # Confidence > 1.0
    res_over = seeded_client.post(
        "/api/v1/attendance/sessions/SESS-001/record",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "confidence": 1.2},
    )
    assert res_over.status_code == 422


# ==============================================================================
# 4. Foreign-Key Validation
# ==============================================================================

def test_foreign_key_validation(seeded_client):
    # Missing session
    res_sess = seeded_client.post(
        "/api/v1/attendance/sessions/INVALID-SESS/record",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT"},
    )
    assert res_sess.status_code == 404
    assert "session" in res_sess.json()["detail"].lower()

    # Missing student USN
    res_stu = seeded_client.post(
        "/api/v1/attendance/sessions/SESS-001/record",
        json={"usn": "NONEXISTENT-USN", "room_id": "LH-101", "status": "PRESENT"},
    )
    assert res_stu.status_code == 404
    assert "student" in res_stu.json()["detail"].lower()

    # Missing room
    res_room = seeded_client.post(
        "/api/v1/attendance/sessions/SESS-001/record",
        json={"usn": "1MS21CS001", "room_id": "NONEXISTENT-ROOM", "status": "PRESENT"},
    )
    assert res_room.status_code == 404
    assert "room" in res_room.json()["detail"].lower()


# ==============================================================================
# 5. Bulk Insertion & Atomic Rollback
# ==============================================================================

def test_bulk_record_attendance_success(seeded_client):
    payload = {
        "records": [
            {"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "confidence": 0.9},
            {"usn": "1MS21CS002", "room_id": "LH-101", "status": "ABSENT", "confidence": 1.0},
        ]
    }
    res = seeded_client.post("/api/v1/attendance/sessions/SESS-001/bulk", json=payload)
    assert res.status_code == 201
    assert res.json()["inserted_count"] == 2

    # Verify both exist
    all_res = seeded_client.get("/api/v1/attendance/sessions/SESS-001")
    assert len(all_res.json()) == 2


def test_bulk_record_duplicate_usn_in_payload_rejected(seeded_client):
    payload = {
        "records": [
            {"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT"},
            {"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},
        ]
    }
    res = seeded_client.post("/api/v1/attendance/sessions/SESS-001/bulk", json=payload)
    assert res.status_code == 409
    assert "duplicate student usns" in res.json()["detail"].lower()


def test_bulk_record_atomic_rollback_on_conflict(seeded_client):
    # Pre-record student 1
    seeded_client.post(
        "/api/v1/attendance/sessions/SESS-001/record",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT"},
    )

    # Attempt bulk insert with student 2, student 1 (conflict), and student 3
    payload = {
        "records": [
            {"usn": "1MS21CS002", "room_id": "LH-101", "status": "PRESENT"},
            {"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT"},  # Conflict
            {"usn": "1MS21CS003", "room_id": "LH-101", "status": "PENDING"},
        ]
    }
    res = seeded_client.post("/api/v1/attendance/sessions/SESS-001/bulk", json=payload)
    assert res.status_code == 409

    # Verify atomic rollback: neither student 2 nor student 3 were inserted!
    session_records = seeded_client.get("/api/v1/attendance/sessions/SESS-001").json()
    usns_present = [r["usn"] for r in session_records]
    assert "1MS21CS002" not in usns_present
    assert "1MS21CS003" not in usns_present
    assert usns_present == ["1MS21CS001"]


# ==============================================================================
# 6. Session Attendance Replacement (PUT)
# ==============================================================================

def test_replace_session_attendance(seeded_client):
    # Populate SESS-001 with 1MS21CS001
    seeded_client.post(
        "/api/v1/attendance/sessions/SESS-001/record",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT"},
    )
    # Populate SESS-002 with 1MS21CS002 to test session isolation
    seeded_client.post(
        "/api/v1/attendance/sessions/SESS-002/record",
        json={"usn": "1MS21CS002", "room_id": "LH-102", "status": "ABSENT"},
    )

    # Replace SESS-001 with 1MS21CS003 and 1MS21CS004
    replace_payload = {
        "records": [
            {"usn": "1MS21CS003", "room_id": "LH-101", "status": "PRESENT"},
            {"usn": "1MS21CS004", "room_id": "LH-101", "status": "PRESENT"},
        ]
    }
    res = seeded_client.put("/api/v1/attendance/sessions/SESS-001", json=replace_payload)
    assert res.status_code == 200
    assert res.json()["replaced_count"] == 2

    # Verify SESS-001 now has 003 and 004, and 001 is gone
    sess1_records = seeded_client.get("/api/v1/attendance/sessions/SESS-001").json()
    sess1_usns = {r["usn"] for r in sess1_records}
    assert sess1_usns == {"1MS21CS003", "1MS21CS004"}

    # Verify SESS-002 was not touched
    sess2_records = seeded_client.get("/api/v1/attendance/sessions/SESS-002").json()
    assert len(sess2_records) == 1
    assert sess2_records[0]["usn"] == "1MS21CS002"


# ==============================================================================
# 7. Session-Specific Deletion (DELETE)
# ==============================================================================

def test_delete_session_attendance(seeded_client):
    # Seed SESS-001 and SESS-002
    seeded_client.post(
        "/api/v1/attendance/sessions/SESS-001/record",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT"},
    )
    seeded_client.post(
        "/api/v1/attendance/sessions/SESS-002/record",
        json={"usn": "1MS21CS002", "room_id": "LH-102", "status": "PRESENT"},
    )

    # Delete SESS-001 attendance
    del_res = seeded_client.delete("/api/v1/attendance/sessions/SESS-001")
    assert del_res.status_code == 200
    assert del_res.json()["deleted_count"] == 1

    # Verify SESS-001 has 0 attendance records
    assert seeded_client.get("/api/v1/attendance/sessions/SESS-001").json() == []

    # Verify SESS-001 session master record still exists
    sess_master = seeded_client.get("/api/v1/sessions/SESS-001")
    assert sess_master.status_code == 200

    # Verify SESS-002 attendance still exists
    sess2_recs = seeded_client.get("/api/v1/attendance/sessions/SESS-002").json()
    assert len(sess2_recs) == 1


# ==============================================================================
# 8. Student Attendance History
# ==============================================================================

def test_student_attendance_history(seeded_client):
    # Record attendance for 1MS21CS001 across SESS-001 and SESS-002
    seeded_client.post(
        "/api/v1/attendance/sessions/SESS-001/record",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT"},
    )
    seeded_client.post(
        "/api/v1/attendance/sessions/SESS-002/record",
        json={"usn": "1MS21CS001", "room_id": "LH-102", "status": "ABSENT"},
    )

    # Fetch history
    res = seeded_client.get("/api/v1/attendance/students/1MS21CS001")
    assert res.status_code == 200
    history = res.json()
    assert len(history) == 2
    assert {h["session_id"] for h in history} == {"SESS-001", "SESS-002"}

    # 404 for unknown student
    res_404 = seeded_client.get("/api/v1/attendance/students/UNKNOWN-STUDENT")
    assert res_404.status_code == 404


# ==============================================================================
# 9. Reconciliation Behavior & Preservation of PENDING / UNREVIEWED
# ==============================================================================

def test_reconciliation_roster_algorithm_preserves_pending_and_unreviewed(seeded_client):
    """
    Verify reconciliation rules:
    - Missing sheets (room LH-102) leave status as PENDING (NOT ABSENT).
    - Ambiguous marks (confidence < 0.70) leave status as UNREVIEWED (NOT ABSENT).
    - Valid marks become PRESENT or ABSENT.
    """
    payload = {
        "uploaded_records": [
            {"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "confidence": 0.95},
            {"usn": "1MS21CS002", "room_id": "LH-101", "status": "PRESENT", "confidence": 0.40},  # Low confidence
            {"usn": "1MS21CS004", "room_id": "LH-101", "status": "ABSENT", "confidence": 1.0},
        ],
        "missing_room_ids": ["LH-102"],  # Student 1MS21CS003 is in missing room
        "confidence_threshold": 0.70,
        "persist": True,
    }

    # Custom roster mapping student 3 to LH-102
    payload["roster"] = [
        {"usn": "1MS21CS001", "room_id": "LH-101"},
        {"usn": "1MS21CS002", "room_id": "LH-101"},
        {"usn": "1MS21CS003", "room_id": "LH-102"},
        {"usn": "1MS21CS004", "room_id": "LH-101"},
    ]

    res = seeded_client.post("/api/v1/attendance/sessions/SESS-001/reconcile", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["reconciled_count"] == 4

    records_by_usn = {r["usn"]: r for r in data["records"]}
    # High confidence present -> PRESENT
    assert records_by_usn["1MS21CS001"]["status"] == "PRESENT"
    # Low confidence -> UNREVIEWED (NOT ABSENT)
    assert records_by_usn["1MS21CS002"]["status"] == "UNREVIEWED"
    # Missing room sheet -> PENDING (NOT ABSENT)
    assert records_by_usn["1MS21CS003"]["status"] == "PENDING"
    # Confirmed absent -> ABSENT
    assert records_by_usn["1MS21CS004"]["status"] == "ABSENT"


def test_reconciliation_explicit_manual_resolutions(seeded_client):
    """Verify manual resolution updates existing records."""
    # Pre-seed student as PENDING
    seeded_client.post(
        "/api/v1/attendance/sessions/SESS-001/record",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PENDING"},
    )

    resolve_payload = {
        "resolutions": [
            {
                "usn": "1MS21CS001",
                "resolved_status": "PRESENT",
                "reason": "Teacher manual verification",
                "reconciled_by": "prof_smith",
            }
        ]
    }
    res = seeded_client.post("/api/v1/attendance/sessions/SESS-001/reconcile", json=resolve_payload)
    assert res.status_code == 200
    assert res.json()["reconciled_count"] == 1

    # Verify updated in session
    sess_records = seeded_client.get("/api/v1/attendance/sessions/SESS-001").json()
    assert sess_records[0]["status"] == "PRESENT"
    assert "prof_smith" in sess_records[0]["source"]

