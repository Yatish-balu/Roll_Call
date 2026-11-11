"""Tests for Phase 5.6: Agent & Tool Integration API.

Verifies:
1. Agent chat with verified database query results.
2. Unknown attendance questions respond with 'I do not have that data.' without hallucinating numbers.
3. Read-only SQL restrictions reject data-modifying statements.
4. CSV processing returns records and summary metrics.
5. Photo processing runs extraction and returns structured records.
6. Security: rejects invalid file types (400) and oversized files > 10MB (413).
7. Low-confidence extraction requires human confirmation and does not auto-commit.
8. Rejection (confirmed=False) leaves the database unchanged.
9. Successful confirmation (confirmed=True) validates and atomically commits records.
10. Confirmation rollback on failure and duplicate attendance prevention.
11. Provider status endpoint reports availability without exposing credentials or keys.
"""

import io
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Student, Room, Session as DbSession, Attendance
from app.dependencies import get_db
from app.main import app
from tests.conftest import seed_test_admin_user
from tools.read_photo_tool import PhotoExtractionResult, PhotoRow, ExtractionSource


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
    seed_test_admin_user(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def seeded_client(test_db_engine):
    """FastAPI TestClient with isolated in-memory DB and pre-seeded dataset."""
    TestingSessionLocal = sessionmaker(bind=test_db_engine, class_=Session, expire_on_commit=False)

    with TestingSessionLocal() as session:
        session.add_all([
            Student(usn="1MS21CS001", name="Alice Smith", branch="CSE"),
            Student(usn="1MS21CS002", name="Bob Jones", branch="CSE"),
            Student(usn="1MS21CS003", name="Charlie Brown", branch="ECE"),
        ])
        session.add_all([
            Room(room_id="LH-101", name="Lecture Hall 101"),
            Room(room_id="LH-102", name="Lecture Hall 102"),
        ])
        session.add_all([
            DbSession(session_id="SESS-001", date="2026-03-15", subject="Computer Networks"),
        ])
        session.add_all([
            Attendance(session_id="SESS-001", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="csv", confidence=1.0),
            Attendance(session_id="SESS-001", usn="1MS21CS002", room_id="LH-101", status="ABSENT", source="csv", confidence=1.0),
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
# 1. Agent Chat Tests
# ==============================================================================

def test_agent_chat_successful_query(seeded_client):
    res = seeded_client.post("/api/v1/agent/chat", json={"query": "Who is absent in session SESS-001?"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "1 absent student" in data["message"]
    assert len(data["data"]) == 1
    assert data["data"][0]["usn"] == "1MS21CS002"
    assert len(data["tool_calls"]) > 0


def test_agent_chat_unknown_question_no_hallucination(seeded_client):
    # Query for nonexistent student or unsupported metric
    res = seeded_client.post("/api/v1/agent/chat", json={"query": "What is the average exam score for session SESS-001?"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    # Anti-hallucination constraint
    assert "I do not have that data." in data["message"]


def test_agent_chat_readonly_sql_rejection(seeded_client):
    res = seeded_client.post(
        "/api/v1/agent/chat",
        json={"query": "DELETE FROM attendance WHERE session_id = 'SESS-001'"}
    )
    assert res.status_code == 400
    assert "Only SELECT or WITH" in res.json()["detail"]


# ==============================================================================
# 2. File Upload & Processing Tests
# ==============================================================================

def test_process_file_csv_success(seeded_client):
    csv_content = (
        b"usn,name,branch,room_id,status\n"
        b"1MS21CS001,Alice Smith,CSE,LH-101,PRESENT\n"
        b"1MS21CS002,Bob Jones,CSE,LH-101,ABSENT\n"
        b"1MS21CS003,Charlie Brown,ECE,LH-101,PRESENT\n"
    )
    files = {"file": ("attendance.csv", io.BytesIO(csv_content), "text/csv")}
    data = {"session_id": "SESS-001"}

    res = seeded_client.post("/api/v1/agent/process-file", files=files, data=data)
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["needs_confirmation"] is False
    assert len(body["data"]) == 3
    assert body["summary_report"] is not None
    assert body["summary_report"]["overall"]["present"] == 2
    assert body["summary_report"]["overall"]["absent"] == 1


def test_process_file_photo_success(seeded_client):
    # Mock read_photo_tool to return genuine high confidence rows
    fake_rows = [
        PhotoRow(usn="1MS21CS001", name="Alice", status="PRESENT", confidence=0.95, source=ExtractionSource.LLM),
        PhotoRow(usn="1MS21CS002", name="Bob", status="ABSENT", confidence=0.90, source=ExtractionSource.LLM),
    ]
    fake_result = PhotoExtractionResult(image_path="sheet.png", rows=fake_rows, source=ExtractionSource.LLM)

    with patch("app.agent.read_photo_tool", return_value=fake_result):
        # A minimal but *valid* 1x1 PNG image (the upload endpoint rejects
        # malformed images, so the fixture must be decodable).
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
            b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe"
            b"\x02\xfe\r\xefF\xb8\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        files = {"file": ("sheet.png", io.BytesIO(png_bytes), "image/png")}
        data = {"session_id": "SESS-001", "default_room": "LH-101"}

        res = seeded_client.post("/api/v1/agent/process-file", files=files, data=data)
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["needs_confirmation"] is False
        assert len(body["data"]) == 2


def test_process_file_invalid_extension_rejected(seeded_client):
    files = {"file": ("script.py", io.BytesIO(b"print('hello')"), "text/x-python")}
    res = seeded_client.post("/api/v1/agent/process-file", files=files)
    assert res.status_code == 400
    assert "Unsupported file extension" in res.json()["detail"]


def test_process_file_oversized_rejected(seeded_client):
    # 11MB file (exceeds 10MB limit)
    large_bytes = b"0" * (11 * 1024 * 1024)
    files = {"file": ("large.csv", io.BytesIO(large_bytes), "text/csv")}
    res = seeded_client.post("/api/v1/agent/process-file", files=files)
    assert res.status_code == 413
    assert "exceeds maximum allowed limit" in res.json()["detail"]


def test_process_file_low_confidence_triggers_confirmation(seeded_client):
    # Mock low confidence photo row (< 0.80)
    fake_rows = [
        PhotoRow(usn="1MS21CS001", name="Alice", status="PRESENT", confidence=0.65, source=ExtractionSource.LLM),  # Low confidence!
    ]
    fake_result = PhotoExtractionResult(image_path="sheet.png", rows=fake_rows, source=ExtractionSource.LLM)

    with patch("app.agent.read_photo_tool", return_value=fake_result):
        # A minimal but *valid* 1x1 PNG image.
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
            b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe"
            b"\x02\xfe\r\xefF\xb8\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        files = {"file": ("sheet.png", io.BytesIO(png_bytes), "image/png")}
        res = seeded_client.post("/api/v1/agent/process-file", files=files)
        assert res.status_code == 200
        body = res.json()
        assert body["needs_confirmation"] is True
        assert body["confirmation_request"] is not None
        assert "Low confidence" in body["confirmation_request"]["question"]


# ==============================================================================
# 3. Confirmation Endpoint Tests
# ==============================================================================

def test_agent_confirm_rejection_leaves_db_unchanged(seeded_client):
    # Reject action
    payload = {
        "session_id": "SESS-001",
        "confirmed": False,
        "records": [{"usn": "1MS21CS003", "room_id": "LH-101", "status": "PRESENT"}],
    }
    res = seeded_client.post("/api/v1/agent/confirm", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["confirmed"] is False
    assert data["committed_count"] == 0

    # Verify student 3 was NOT committed to SESS-001
    sess_res = seeded_client.get("/api/v1/attendance/sessions/SESS-001")
    usns = [r["usn"] for r in sess_res.json()]
    assert "1MS21CS003" not in usns


def test_agent_confirm_success(seeded_client):
    # Create new session SESS-002
    seeded_client.post(
        "/api/v1/sessions",
        json={"session_id": "SESS-002", "date": "2026-03-16", "subject": "Math"},
    )

    payload = {
        "session_id": "SESS-002",
        "confirmed": True,
        "records": [
            {"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT", "confidence": 1.0},
            {"usn": "1MS21CS002", "room_id": "LH-101", "status": "ABSENT", "confidence": 1.0},
        ],
    }
    res = seeded_client.post("/api/v1/agent/confirm", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["confirmed"] is True
    assert data["committed_count"] == 2

    # Verify persisted in database
    sess_res = seeded_client.get("/api/v1/attendance/sessions/SESS-002")
    assert len(sess_res.json()) == 2


def test_agent_confirm_duplicate_prevention(seeded_client):
    # Attempt to confirm record for student who is already in SESS-001
    payload = {
        "session_id": "SESS-001",
        "confirmed": True,
        "records": [
            {"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT"},  # 1MS21CS001 already in SESS-001!
        ],
    }
    res = seeded_client.post("/api/v1/agent/confirm", json=payload)
    assert res.status_code == 409
    assert "already exists" in res.json()["detail"].lower()


# ==============================================================================
# 4. Status Endpoint Tests
# ==============================================================================

def test_agent_status_without_secret_leak(seeded_client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super_secret_ai_key_12345")

    res = seeded_client.get("/api/v1/agent/status")
    assert res.status_code == 200
    data = res.json()
    assert data["gemini_configured"] is True
    assert data["easyocr_available"] is True
    assert data["confidence_threshold"] == 0.80
    assert len(data["available_tools"]) == 6

    # Verify secret is NEVER exposed in the JSON response
    raw_text = res.text
    assert "super_secret_ai_key_12345" not in raw_text
