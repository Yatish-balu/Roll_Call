"""Tests for Phase 5.3: Master Data API Routers (Students, Rooms, Sessions).

Verifies:
1. Student endpoints: list, lookup, create, bulk create, duplicate 409 handling, 422 validation.
2. Room endpoints: list, lookup, create, bulk create, duplicate 409 handling, 422 validation.
3. Session endpoints: list, date filtering, lookup, create, bulk create, duplicate 409 handling, 422 validation.
4. Missing records (404 Not Found).
5. Atomic transaction rollback on bulk insertion conflict/failure.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Student, Room, Session as DbSession
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
def client(test_db_engine):
    """FastAPI TestClient with isolated in-memory DB dependency override."""
    TestingSessionLocal = sessionmaker(bind=test_db_engine, class_=Session, expire_on_commit=False)

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
# 1. Student API Tests
# ==============================================================================

def test_list_students_empty_and_populated(client):
    res = client.get("/api/v1/students")
    assert res.status_code == 200
    assert res.json()["items"] == []
    assert res.json()["total"] == 0

    # Insert a student
    create_res = client.post(
        "/api/v1/students",
        json={"usn": "1MS21CS001", "name": "Alice Smith", "branch": "CSE"},
    )
    assert create_res.status_code == 201

    res = client.get("/api/v1/students")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["usn"] == "1MS21CS001"
    assert data["items"][0]["name"] == "Alice Smith"
    assert data["items"][0]["branch"] == "CSE"


def test_list_students_filter_by_branch(client):
    client.post("/api/v1/students", json={"usn": "1MS21CS001", "name": "Alice", "branch": "CSE"})
    client.post("/api/v1/students", json={"usn": "1MS21EC001", "name": "Bob", "branch": "ECE"})

    res_cse = client.get("/api/v1/students?branch=CSE")
    assert res_cse.status_code == 200
    cse_data = res_cse.json()
    assert cse_data["total"] == 1
    assert len(cse_data["items"]) == 1
    assert cse_data["items"][0]["usn"] == "1MS21CS001"

    res_ece = client.get("/api/v1/students?branch=ECE")
    assert res_ece.status_code == 200
    ece_data = res_ece.json()
    assert ece_data["total"] == 1
    assert len(ece_data["items"]) == 1
    assert ece_data["items"][0]["usn"] == "1MS21EC001"


def test_get_student_by_usn(client):
    client.post("/api/v1/students", json={"usn": "1MS21CS050", "name": "Charlie", "branch": "CSE"})

    # Found
    res = client.get("/api/v1/students/1MS21CS050")
    assert res.status_code == 200
    assert res.json()["name"] == "Charlie"

    # Case insensitive lookup (USN is capitalized in validator)
    res_lower = client.get("/api/v1/students/1ms21cs050")
    assert res_lower.status_code == 200
    assert res_lower.json()["name"] == "Charlie"

    # Not found
    res_404 = client.get("/api/v1/students/NONEXISTENT")
    assert res_404.status_code == 404
    assert "not found" in res_404.json()["detail"].lower()


def test_create_student_duplicate_returns_409(client):
    payload = {"usn": "1MS21CS100", "name": "David", "branch": "CSE"}
    res1 = client.post("/api/v1/students", json=payload)
    assert res1.status_code == 201

    # Conflict
    res2 = client.post("/api/v1/students", json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"]


def test_create_student_validation_errors(client):
    # Empty USN
    res = client.post("/api/v1/students", json={"usn": "", "name": "David", "branch": "CSE"})
    assert res.status_code == 422

    # Empty name
    res = client.post("/api/v1/students", json={"usn": "1MS21CS101", "name": "   ", "branch": "CSE"})
    assert res.status_code == 422


def test_bulk_create_students_success(client):
    payload = {
        "students": [
            {"usn": "1MS21CS001", "name": "Student 1", "branch": "CSE"},
            {"usn": "1MS21CS002", "name": "Student 2", "branch": "CSE"},
            {"usn": "1MS21CS003", "name": "Student 3", "branch": "CSE"},
        ]
    }
    res = client.post("/api/v1/students/bulk", json=payload)
    assert res.status_code == 201
    assert res.json()["inserted_count"] == 3

    # Check that all 3 exist
    all_res = client.get("/api/v1/students")
    assert all_res.json()["total"] == 3
    assert len(all_res.json()["items"]) == 3


def test_bulk_create_students_rollback_on_conflict(client):
    # Pre-seed one student
    client.post("/api/v1/students", json={"usn": "1MS21CS002", "name": "Existing", "branch": "CSE"})

    # Attempt bulk insert containing that student along with new ones
    payload = {
        "students": [
            {"usn": "1MS21CS010", "name": "New Ten", "branch": "CSE"},
            {"usn": "1MS21CS002", "name": "Duplicate Conflict", "branch": "CSE"},
            {"usn": "1MS21CS011", "name": "New Eleven", "branch": "CSE"},
        ]
    }
    res = client.post("/api/v1/students/bulk", json=payload)
    assert res.status_code == 409
    assert "already exists" in res.json()["detail"]

    # Verify atomic rollback: New Ten and New Eleven must NOT have been inserted!
    assert client.get("/api/v1/students/1MS21CS010").status_code == 404
    assert client.get("/api/v1/students/1MS21CS011").status_code == 404


def test_bulk_create_students_duplicate_in_payload(client):
    payload = {
        "students": [
            {"usn": "1MS21CS020", "name": "Student A", "branch": "CSE"},
            {"usn": "1MS21CS020", "name": "Student B", "branch": "CSE"},
        ]
    }
    res = client.post("/api/v1/students/bulk", json=payload)
    assert res.status_code == 409
    assert "duplicate student USNs" in res.json()["detail"]


# ==============================================================================
# 2. Room API Tests
# ==============================================================================

def test_list_rooms_and_get_by_id(client):
    res = client.get("/api/v1/rooms")
    assert res.status_code == 200
    assert res.json()["items"] == []
    assert res.json()["total"] == 0

    # Create room
    create_res = client.post("/api/v1/rooms", json={"room_id": "LH-101", "name": "Lecture Hall 101"})
    assert create_res.status_code == 201
    assert create_res.json()["room_id"] == "LH-101"

    # Lookup
    get_res = client.get("/api/v1/rooms/LH-101")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Lecture Hall 101"

    # 404
    res_404 = client.get("/api/v1/rooms/NONEXISTENT")
    assert res_404.status_code == 404


def test_create_room_duplicate_returns_409(client):
    payload = {"room_id": "LH-201", "name": "Lecture Hall 201"}
    res1 = client.post("/api/v1/rooms", json=payload)
    assert res1.status_code == 201

    res2 = client.post("/api/v1/rooms", json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"]


def test_create_room_validation_errors(client):
    res = client.post("/api/v1/rooms", json={"room_id": "R1", "name": "  "})
    assert res.status_code == 422


def test_bulk_create_rooms_success_and_rollback(client):
    # Success
    payload = {
        "rooms": [
            {"room_id": "LAB-1", "name": "Computer Lab 1"},
            {"room_id": "LAB-2", "name": "Computer Lab 2"},
        ]
    }
    res = client.post("/api/v1/rooms/bulk", json=payload)
    assert res.status_code == 201
    assert res.json()["inserted_count"] == 2

    # Conflict and rollback
    conflict_payload = {
        "rooms": [
            {"room_id": "LAB-3", "name": "Computer Lab 3"},
            {"room_id": "LAB-1", "name": "Duplicate Lab 1"},
        ]
    }
    conflict_res = client.post("/api/v1/rooms/bulk", json=conflict_payload)
    assert conflict_res.status_code == 409
    # Verify LAB-3 was rolled back and not left orphaned
    assert client.get("/api/v1/rooms/LAB-3").status_code == 404


# ==============================================================================
# 3. Session API Tests
# ==============================================================================

def test_session_lifecycle(client):
    # Empty
    res = client.get("/api/v1/sessions")
    assert res.status_code == 200
    assert res.json()["items"] == []
    assert res.json()["total"] == 0

    # Create
    create_res = client.post(
        "/api/v1/sessions",
        json={"session_id": "SESS-001", "date": "2026-03-15", "subject": "Machine Learning"},
    )
    assert create_res.status_code == 201
    assert create_res.json()["session_id"] == "SESS-001"

    # Get by ID
    get_res = client.get("/api/v1/sessions/SESS-001")
    assert get_res.status_code == 200
    assert get_res.json()["subject"] == "Machine Learning"

    # 404 Not Found
    res_404 = client.get("/api/v1/sessions/NONEXISTENT")
    assert res_404.status_code == 404


def test_session_date_filter(client):
    client.post("/api/v1/sessions", json={"session_id": "S1", "date": "2026-03-15", "subject": "ML"})
    client.post("/api/v1/sessions", json={"session_id": "S2", "date": "2026-03-16", "subject": "Networks"})

    res_15 = client.get("/api/v1/sessions?date=2026-03-15")
    assert res_15.status_code == 200
    data_15 = res_15.json()
    assert data_15["total"] == 1
    assert len(data_15["items"]) == 1
    assert data_15["items"][0]["session_id"] == "S1"

    res_16 = client.get("/api/v1/sessions?date=2026-03-16")
    assert res_16.status_code == 200
    data_16 = res_16.json()
    assert data_16["total"] == 1
    assert len(data_16["items"]) == 1
    assert data_16["items"][0]["session_id"] == "S2"

    res_empty = client.get("/api/v1/sessions?date=2026-03-17")
    assert res_empty.status_code == 200
    assert res_empty.json()["items"] == []
    assert res_empty.json()["total"] == 0


def test_session_invalid_date_format(client):
    res = client.get("/api/v1/sessions?date=15-03-2026")
    assert res.status_code == 422


def test_create_session_duplicate_returns_409(client):
    payload = {"session_id": "SESS-100", "date": "2026-04-01", "subject": "Operating Systems"}
    res1 = client.post("/api/v1/sessions", json=payload)
    assert res1.status_code == 201

    res2 = client.post("/api/v1/sessions", json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"]


def test_bulk_create_sessions_success_and_rollback(client):
    payload = {
        "sessions": [
            {"session_id": "S-10", "date": "2026-05-01", "subject": "Sub 1"},
            {"session_id": "S-11", "date": "2026-05-02", "subject": "Sub 2"},
        ]
    }
    res = client.post("/api/v1/sessions/bulk", json=payload)
    assert res.status_code == 201
    assert res.json()["inserted_count"] == 2

    # Conflict payload
    conflict_payload = {
        "sessions": [
            {"session_id": "S-12", "date": "2026-05-03", "subject": "Sub 3"},
            {"session_id": "S-10", "date": "2026-05-01", "subject": "Duplicate"},
        ]
    }
    conflict_res = client.post("/api/v1/sessions/bulk", json=conflict_payload)
    assert conflict_res.status_code == 409
    # Verify atomic rollback: S-12 must not exist
    assert client.get("/api/v1/sessions/S-12").status_code == 404

