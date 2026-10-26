"""Unit tests for app.agent: Tool-calling agent loop, guardrails, and logging."""

import os
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from app.agent import (
    AttendanceAgent,
    ToolLogger,
    ToolRegistry,
    AgentResponse,
    ConfirmationRequest,
    SYSTEM_INSTRUCTION,
    CONFIDENCE_CONFIRMATION_THRESHOLD,
)
from app.db.schema import init_db
from app.db.crud import insert_student, insert_room, insert_session, insert_attendance
from tools.read_photo_tool import PhotoExtractionResult, PhotoRow, ExtractionSource
from tools.query_tool import NO_DATA_MESSAGE


@pytest.fixture
def mock_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    insert_student(conn, usn="1MS21CS001", name="Alice Smith", branch="CSE")
    insert_student(conn, usn="1MS21CS002", name="Bob Jones", branch="CSE")
    insert_room(conn, room_id="LH-101", name="Hall 101")
    insert_session(conn, session_id="SESS-100", date="2026-10-24", subject="OS")
    insert_attendance(conn, session_id="SESS-100", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="csv", confidence=1.0)
    insert_attendance(conn, session_id="SESS-100", usn="1MS21CS002", room_id="LH-101", status="ABSENT", source="csv", confidence=1.0)
    return conn


@pytest.fixture
def agent(mock_db):
    return AttendanceAgent(db_target=mock_db)


@pytest.fixture
def clean_csv(tmp_path):
    p = tmp_path / "clean_attendance.csv"
    p.write_text(
        "usn,name,branch,room_id,status\n"
        "1MS21CS001,Alice Smith,CSE,LH-101,PRESENT\n"
        "1MS21CS002,Bob Jones,CSE,LH-101,ABSENT\n"
        "1MS21CS003,Charlie Brown,CSE,LH-101,PENDING\n"
    )
    return p


@pytest.fixture
def bad_csv(tmp_path):
    # Has duplicate USN and blank status
    p = tmp_path / "bad_attendance.csv"
    p.write_text(
        "usn,name,branch,room_id,status\n"
        "1MS21CS001,Alice Smith,CSE,LH-101,PRESENT\n"
        "1MS21CS001,Alice Smith,CSE,LH-101,ABSENT\n"
        "1MS21CS002,Bob Jones,CSE,LH-101,\n"
    )
    return p


# ============================================================================
# 1. System Instruction & Prompt Verification
# ============================================================================

def test_system_instruction_contains_required_rules():
    assert "RollCall AI" in SYSTEM_INSTRUCTION
    assert "Always validate extracted attendance before summarising" in SYSTEM_INSTRUCTION
    assert "Request confirmation for confidence below 0.80" in SYSTEM_INSTRUCTION
    assert "I do not have that data." in SYSTEM_INSTRUCTION
    assert CONFIDENCE_CONFIRMATION_THRESHOLD == 0.80


# ============================================================================
# 2. Tool Selection & Pipeline Order
# ============================================================================

def test_csv_pipeline_happy_path(agent, clean_csv):
    response = agent.process_request(user_input="Process attendance", file_path=clean_csv)

    assert response.success is True
    assert response.needs_confirmation is False
    assert response.validation_result is not None
    assert response.validation_result["is_valid"] is True
    assert response.summary_report is not None

    # Check summary report accuracy: 1 PRESENT, 1 ABSENT -> 50.0% confirmed rate
    overall = response.summary_report["overall"]
    assert overall["present"] == 1
    assert overall["absent"] == 1
    assert overall["pending"] == 1
    assert overall["confirmed_percentage"] == 50.0

    # Verify tool call ordering in logs: read_csv_tool -> validate_tool -> summary_tool
    logs = agent.get_logs(response.request_id)
    tool_names = [l.tool_name for l in logs]
    assert tool_names == ["read_csv_tool", "validate_tool", "summary_tool"]


def test_cannot_bypass_validation_to_summarise(agent):
    response = agent.process_request(user_input="Summarise the attendance sheet without validating")
    assert response.success is False
    assert "Validation required before summarising" in response.message


def test_validation_failure_triggers_confirmation(agent, bad_csv):
    response = agent.process_request(user_input="Process bad attendance", file_path=bad_csv)

    assert response.success is False
    assert response.needs_confirmation is True
    assert response.confirmation_request is not None
    assert response.confirmation_request.needed is True
    assert len(response.confirmation_request.affected_rows) > 0
    assert len(response.confirmation_request.issues) > 0
    assert response.summary_report is None  # summary is NOT generated when unconfirmed!

    # Verify tool logs stop at validate_tool and do NOT run summary_tool
    logs = agent.get_logs(response.request_id)
    tool_names = [l.tool_name for l in logs]
    assert "summary_tool" not in tool_names
    assert tool_names == ["read_csv_tool", "validate_tool"]


# ============================================================================
# 3. Confidence Threshold Guardrail (< 0.80 vs >= 0.80)
# ============================================================================

def test_photo_low_confidence_triggers_confirmation(agent, tmp_path):
    img_path = tmp_path / "sheet.png"
    img_path.write_bytes(b"dummy image bytes")

    # Mock read_photo_tool returning row with confidence 0.75 (< 0.80)
    mock_rows = [
        PhotoRow(usn="1MS21CS001", name="Alice Smith", status="PRESENT", confidence=0.75, source=ExtractionSource.LLM),
        PhotoRow(usn="1MS21CS002", name="Bob Jones", status="ABSENT", confidence=0.95, source=ExtractionSource.LLM),
    ]
    mock_result = PhotoExtractionResult(image_path=str(img_path), rows=mock_rows, source=ExtractionSource.LLM)

    with patch.object(agent.registry, "execute", wraps=agent.registry.execute) as mock_exec:
        def side_effect(name, **kwargs):
            if name == "read_photo_tool":
                agent.logger.log(kwargs.get("request_id", ""), name, kwargs, True, "Mock photo", 0.01)
                return mock_result
            return agent.registry.tools[name].handler(**kwargs)

        mock_exec.side_effect = side_effect
        response = agent.process_request(user_input="Read photo", file_path=img_path)

    assert response.needs_confirmation is True
    assert response.confirmation_request is not None
    assert len(response.confirmation_request.affected_rows) == 1
    assert response.confirmation_request.affected_rows[0]["usn"] == "1MS21CS001"
    assert response.summary_report is None


def test_photo_high_confidence_proceeds(agent, tmp_path):
    img_path = tmp_path / "sheet_good.png"
    img_path.write_bytes(b"dummy image bytes")

    # Both >= 0.80
    mock_rows = [
        PhotoRow(usn="1MS21CS001", name="Alice Smith", status="PRESENT", confidence=0.80, source=ExtractionSource.LLM),
        PhotoRow(usn="1MS21CS002", name="Bob Jones", status="ABSENT", confidence=0.95, source=ExtractionSource.LLM),
    ]
    mock_result = PhotoExtractionResult(image_path=str(img_path), rows=mock_rows, source=ExtractionSource.LLM)

    with patch.object(agent.registry, "execute", wraps=agent.registry.execute) as mock_exec:
        def side_effect(name, **kwargs):
            if name == "read_photo_tool":
                agent.logger.log(kwargs.get("request_id", ""), name, kwargs, True, "Mock photo", 0.01)
                return mock_result
            return agent.registry.tools[name].handler(**kwargs)

        mock_exec.side_effect = side_effect
        response = agent.process_request(user_input="Read photo for room LH-101", file_path=img_path, default_room="LH-101")

    assert response.needs_confirmation is False
    assert response.summary_report is not None


def test_photo_genuine_ocr_pipeline(agent):
    """Integration test using genuine EasyOCR on generated sheet_clean.jpg without mocking."""
    sheet_clean = Path("data/photos/sheet_clean.jpg")
    if not sheet_clean.exists():
        pytest.skip("data/photos/sheet_clean.jpg not present")

    # Run genuine OCR fallback (no API key configured)
    response = agent.process_request(
        user_input="Process attendance photo for room LH-101",
        file_path=sheet_clean,
        default_room="LH-101",
        default_branch="CSE",
    )
    # Validate that tool calls ran genuine read_photo_tool
    logs = agent.get_logs(response.request_id)
    photo_log = [l for l in logs if l.tool_name == "read_photo_tool"]
    assert len(photo_log) == 1
    assert "PhotoExtractionResult" in photo_log[0].result_summary
    assert "ocr_fallback" in photo_log[0].result_summary  # Distinguishes genuine OCR from LLM mock


# ============================================================================
# 4. Anti-Hallucination & Safe DB Querying
# ============================================================================

def test_query_tool_absentees_found(agent):
    response = agent.process_request(user_input="Who was absent in session SESS-100?")
    assert response.success is True
    assert "Found 1 absent student(s)" in response.message
    assert len(response.data) == 1
    assert response.data[0]["usn"] == "1MS21CS002"


def test_query_tool_missing_data_exact_message(agent):
    response = agent.process_request(user_input="Show absentees for session SESS-DOES-NOT-EXIST")
    assert response.success is True
    assert response.message == NO_DATA_MESSAGE
    assert response.data == []


def test_query_student_info(agent):
    response = agent.process_request(user_input="Find details for student 1MS21CS001")
    assert response.success is True
    assert "Alice Smith" in response.message


def test_query_unknown_student_returns_no_data(agent):
    response = agent.process_request(user_input="Find details for student 1MS21CS999")
    assert response.success is True
    assert response.message == NO_DATA_MESSAGE


# ============================================================================
# 5. Export Integration & Verification
# ============================================================================

def test_pipeline_with_excel_export(agent, clean_csv, tmp_path):
    exp_file = tmp_path / "export_final.xlsx"
    response = agent.process_request(
        user_input="Process and export attendance",
        file_path=clean_csv,
        export_format="excel",
        export_path=exp_file,
    )
    assert response.success is True
    assert exp_file.exists()
    assert exp_file.stat().st_size > 0
    assert response.export_result is not None
    assert response.export_result["success"] is True


def test_pipeline_with_pdf_export(agent, clean_csv, tmp_path):
    exp_file = tmp_path / "export_final.pdf"
    response = agent.process_request(
        user_input="Process and export attendance to pdf",
        file_path=clean_csv,
        export_format="pdf",
        export_path=exp_file,
    )
    assert response.success is True
    assert exp_file.exists()
    assert exp_file.stat().st_size > 0
    assert response.export_result is not None


# ============================================================================
# 6. Structured Tool Logging & Sanitization
# ============================================================================

def test_tool_logger_redacts_sensitive_keys():
    tlogger = ToolLogger()
    entry = tlogger.log(
        request_id="req-123",
        tool_name="test_tool",
        arguments={"api_key": "secret123", "password": "pass", "safe_arg": "value"},
        success=True,
        result_summary="Success",
        duration_seconds=0.05,
    )
    assert entry.arguments["api_key"] == "[REDACTED]"
    assert entry.arguments["password"] == "[REDACTED]"
    assert entry.arguments["safe_arg"] == "value"


def test_failed_tool_call_cannot_be_reported_as_successful(agent):
    with pytest.raises(ValueError, match="Unknown tool"):
        agent.registry.execute("non_existent_tool", request_id="fail-req")

    logs = agent.get_logs("fail-req")
    assert len(logs) == 1
    assert logs[0].success is False
    assert "Unknown tool" in logs[0].error_message
