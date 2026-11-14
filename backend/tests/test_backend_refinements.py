"""Tests for Phase 6.2: Backend Query Refinements and Performance Fixes.

Verifies:
1. Pagination boundaries (limit min/max, offset bounds, 422 on invalid).
2. Student search across USN, name, and branch.
3. Room search across room_id and name.
4. Session search across session_id and subject.
5. Existing branch/date filters combined with search and pagination.
6. Correct total count reporting alongside paginated items.
7. Batch duplicate detection in agent confirm (single batch query, 409 Conflict).
8. Chunked file upload size rejection without full memory buffering.
9. Temporary file cleanup on processing failure.
10. CORS configuration ensuring wildcard '*' is never combined with credentials.
"""

from __future__ import annotations

import io
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db import crud
from app.dependencies import get_db
from app.main import app, get_allowed_origins, DEFAULT_ALLOWED_ORIGINS
from tests.conftest import seed_test_admin_user


@pytest.fixture
def test_db_engine():
    """Isolated in-memory SQLite database for refinements test suite."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)
    seed_test_admin_user(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def client(test_db_engine):
    """FastAPI TestClient with in-memory database override."""
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
# 1. Pagination Boundaries & Validation
# ==============================================================================

def test_pagination_boundaries_and_limits(client):
    # Seed 5 students
    for i in range(1, 6):
        client.post("/api/v1/students", json={"usn": f"1MS21CS00{i}", "name": f"Student {i}", "branch": "CSE"})

    # Limit = 2, Offset = 0 -> returns first 2
    res1 = client.get("/api/v1/students?limit=2&offset=0")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["total"] == 5
    assert data1["limit"] == 2
    assert data1["offset"] == 0
    assert len(data1["items"]) == 2
    assert data1["items"][0]["usn"] == "1MS21CS001"
    assert data1["items"][1]["usn"] == "1MS21CS002"

    # Limit = 2, Offset = 4 -> returns last 1
    res2 = client.get("/api/v1/students?limit=2&offset=4")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["total"] == 5
    assert len(data2["items"]) == 1
    assert data2["items"][0]["usn"] == "1MS21CS005"

    # Limit = 2, Offset = 10 -> returns 0 items
    res3 = client.get("/api/v1/students?limit=2&offset=10")
    assert res3.status_code == 200
    data3 = res3.json()
    assert data3["total"] == 5
    assert len(data3["items"]) == 0

    # Limit out of bounds (0 < 1) -> 422
    assert client.get("/api/v1/students?limit=0").status_code == 422

    # Limit out of bounds (201 > 200) -> 422
    assert client.get("/api/v1/students?limit=201").status_code == 422

    # Offset out of bounds (< 0) -> 422
    assert client.get("/api/v1/students?offset=-1").status_code == 422


# ==============================================================================
# 2. Search Across Students, Rooms, and Sessions
# ==============================================================================

def test_student_search_across_fields(client):
    client.post("/api/v1/students", json={"usn": "1MS21CS042", "name": "Alice Wonder", "branch": "CSE"})
    client.post("/api/v1/students", json={"usn": "1MS21EC099", "name": "Bob Builder", "branch": "ECE"})
    client.post("/api/v1/students", json={"usn": "1MS21ME010", "name": "Charlie Chaplin", "branch": "MECH"})

    # Search by USN
    res_usn = client.get("/api/v1/students?search=CS042")
    assert res_usn.status_code == 200
    data = res_usn.json()
    assert data["total"] == 1
    assert data["items"][0]["usn"] == "1MS21CS042"

    # Search by Name (case-insensitive)
    res_name = client.get("/api/v1/students?search=builder")
    assert res_name.status_code == 200
    data = res_name.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Bob Builder"

    # Search by Branch
    res_br = client.get("/api/v1/students?search=mech")
    assert res_br.status_code == 200
    data = res_br.json()
    assert data["total"] == 1
    assert data["items"][0]["usn"] == "1MS21ME010"


def test_room_search_across_fields(client):
    client.post("/api/v1/rooms", json={"room_id": "LH-101", "name": "Lecture Hall 101"})
    client.post("/api/v1/rooms", json={"room_id": "AUD-MAIN", "name": "Grand Auditorium"})
    client.post("/api/v1/rooms", json={"room_id": "LAB-CS", "name": "Advanced Computing Lab"})

    # Search by room_id
    res_id = client.get("/api/v1/rooms?search=aud")
    assert res_id.status_code == 200
    data = res_id.json()
    assert data["total"] == 1
    assert data["items"][0]["room_id"] == "AUD-MAIN"

    # Search by name (case-insensitive)
    res_name = client.get("/api/v1/rooms?search=computing")
    assert res_name.status_code == 200
    data = res_name.json()
    assert data["total"] == 1
    assert data["items"][0]["room_id"] == "LAB-CS"


def test_session_search_across_fields(client):
    client.post("/api/v1/sessions", json={"session_id": "SESS-ML-01", "date": "2026-03-15", "subject": "Machine Learning"})
    client.post("/api/v1/sessions", json={"session_id": "SESS-NET-01", "date": "2026-03-16", "subject": "Computer Networks"})
    client.post("/api/v1/sessions", json={"session_id": "SESS-DB-01", "date": "2026-03-17", "subject": "Database Systems"})

    # Search by session_id
    res_id = client.get("/api/v1/sessions?search=NET")
    assert res_id.status_code == 200
    data = res_id.json()
    assert data["total"] == 1
    assert data["items"][0]["session_id"] == "SESS-NET-01"

    # Search by subject
    res_sub = client.get("/api/v1/sessions?search=learning")
    assert res_sub.status_code == 200
    data = res_sub.json()
    assert data["total"] == 1
    assert data["items"][0]["subject"] == "Machine Learning"


# ==============================================================================
# 3. Filters Combined with Pagination and Search
# ==============================================================================

def test_combined_filters_search_and_pagination(client):
    # Seed 4 CSE students and 2 ECE students
    client.post("/api/v1/students", json={"usn": "1MS21CS001", "name": "John Doe", "branch": "CSE"})
    client.post("/api/v1/students", json={"usn": "1MS21CS002", "name": "Jane Doe", "branch": "CSE"})
    client.post("/api/v1/students", json={"usn": "1MS21CS003", "name": "Alice Smith", "branch": "CSE"})
    client.post("/api/v1/students", json={"usn": "1MS21CS004", "name": "Bob Smith", "branch": "CSE"})
    client.post("/api/v1/students", json={"usn": "1MS21EC001", "name": "Richard Doe", "branch": "ECE"})
    client.post("/api/v1/students", json={"usn": "1MS21EC002", "name": "Mary Smith", "branch": "ECE"})

    # Filter by branch=CSE + search=Doe + limit=1
    res = client.get("/api/v1/students?branch=CSE&search=Doe&limit=1&offset=0")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2  # John Doe, Jane Doe (Richard Doe is ECE, excluded)
    assert len(data["items"]) == 1
    assert data["items"][0]["usn"] == "1MS21CS001"

    # Offset=1 gets the second matching record
    res_page2 = client.get("/api/v1/students?branch=CSE&search=Doe&limit=1&offset=1")
    assert res_page2.status_code == 200
    data_page2 = res_page2.json()
    assert data_page2["total"] == 2
    assert len(data_page2["items"]) == 1
    assert data_page2["items"][0]["usn"] == "1MS21CS002"


def test_session_date_filter_combined_with_search(client):
    client.post("/api/v1/sessions", json={"session_id": "S1", "date": "2026-03-15", "subject": "Calculus 1"})
    client.post("/api/v1/sessions", json={"session_id": "S2", "date": "2026-03-15", "subject": "Physics 1"})
    client.post("/api/v1/sessions", json={"session_id": "S3", "date": "2026-03-16", "subject": "Calculus 2"})

    # Date = 2026-03-15 AND search = Calculus
    res = client.get("/api/v1/sessions?date=2026-03-15&search=Calculus")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["session_id"] == "S1"


# ==============================================================================
# 4. Batch Duplicate Detection in Agent Confirm
# ==============================================================================

def test_batch_duplicate_detection_agent_confirm(client):
    client.post("/api/v1/rooms", json={"room_id": "LH-101", "name": "Lecture Hall 101"})
    client.post("/api/v1/students", json={"usn": "1MS21CS001", "name": "Alice", "branch": "CSE"})
    client.post("/api/v1/students", json={"usn": "1MS21CS002", "name": "Bob", "branch": "CSE"})
    client.post("/api/v1/sessions", json={"session_id": "CONF-SESS-01", "date": "2026-03-15", "subject": "ML"})

    # Record 1 student already in DB
    client.post(
        "/api/v1/attendance/sessions/CONF-SESS-01/record",
        json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "confidence": 1.0}
    )

    # Attempt agent confirmation with a batch containing that student and another
    payload = {
        "session_id": "CONF-SESS-01",
        "confirmed": True,
        "records": [
            {"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "confidence": 1.0},
            {"usn": "1MS21CS002", "room_id": "LH-101", "status": "PRESENT", "confidence": 1.0},
        ],
    }

    # Spy on get_existing_attendance_usns to ensure single batch lookup was invoked
    with patch("app.db.crud.get_existing_attendance_usns", wraps=crud.get_existing_attendance_usns) as spy_batch:
        res = client.post("/api/v1/agent/confirm", json=payload)
        assert res.status_code == 409
        assert "already exists in database" in res.json()["detail"]
        assert "1MS21CS001" in res.json()["detail"]
        assert spy_batch.call_count == 1  # Exactly one batch query instead of loop


# ==============================================================================
# 5. Chunked File Upload & Tempfile Cleanup
# ==============================================================================

def test_chunked_file_upload_streaming_size_enforcement(client):
    # 11MB file (exceeds 10MB limit)
    oversized = b"X" * (11 * 1024 * 1024)
    files = {"file": ("oversized.csv", io.BytesIO(oversized), "text/csv")}

    created_paths = []
    orig_mkstemp = tempfile.mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, path = orig_mkstemp(*args, **kwargs)
        created_paths.append(path)
        return fd, path

    with patch("app.routers.agent.tempfile.mkstemp", side_effect=tracking_mkstemp):
        res = client.post("/api/v1/agent/process-file", files=files)
        assert res.status_code == 413
        assert "exceeds maximum allowed limit" in res.json()["detail"]

        # Verify the temp file that was created during streaming was cleaned up immediately
        assert len(created_paths) == 1
        assert not os.path.exists(created_paths[0]), f"Temp file {created_paths[0]} was not cleaned up!"


def test_empty_file_upload_rejected_and_cleaned(client):
    files = {"file": ("empty.csv", io.BytesIO(b""), "text/csv")}

    created_paths = []
    orig_mkstemp = tempfile.mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, path = orig_mkstemp(*args, **kwargs)
        created_paths.append(path)
        return fd, path

    with patch("app.routers.agent.tempfile.mkstemp", side_effect=tracking_mkstemp):
        res = client.post("/api/v1/agent/process-file", files=files)
        assert res.status_code == 400
        assert "Uploaded file is empty" in res.json()["detail"]

        assert len(created_paths) == 1
        assert not os.path.exists(created_paths[0]), f"Temp file {created_paths[0]} was not cleaned up!"


# ==============================================================================
# 6. CORS Configuration & Wildcard Rejection
# ==============================================================================

def test_cors_get_allowed_origins_rejects_wildcard():
    # 1. ALLOWED_ORIGINS contains wildcard only
    with patch.dict(os.environ, {"ALLOWED_ORIGINS": "*"}):
        origins = get_allowed_origins()
        assert "*" not in origins
        assert origins == DEFAULT_ALLOWED_ORIGINS

    # 2. ALLOWED_ORIGINS contains wildcard alongside valid origin
    with patch.dict(os.environ, {"ALLOWED_ORIGINS": "*,https://app.example.com"}):
        origins = get_allowed_origins()
        assert "*" not in origins
        assert origins == ["https://app.example.com"]

    # 3. Unset / blank ALLOWED_ORIGINS
    with patch.dict(os.environ, {"ALLOWED_ORIGINS": "   "}):
        origins = get_allowed_origins()
        assert origins == DEFAULT_ALLOWED_ORIGINS
        assert "http://localhost:3000" in origins
        assert "http://localhost:5173" in origins


# ==============================================================================
# 7. Model Discovery Endpoints (/models, /v1/models)
# ==============================================================================

def test_models_endpoints_support_openai_discovery():
    client = TestClient(app)
    for path in ("/models", "/v1/models", "/api/v1/models", "/api/models"):
        res = client.get(path)
        assert res.status_code == 200, f"Failed for {path}"
        data = res.json()
        assert data["object"] == "list"
        ids = [m["id"] for m in data["data"]]
        assert "gemini-3.5-flash-lite" in ids
        assert "rollcall-ai-agent" in ids
