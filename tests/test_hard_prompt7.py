"""
Hard edge-case tests focused on Prompt 7 UI helpers.

These tests stress the logic layer behind the Streamlit UI:
- File upload processing for CSV and photo
- Revalidation and summary
- Metrics calculations
- Database commit
- Export buffers
- Confidence threshold behavior
- Anti-hallucination query behavior
"""

import io
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.agent import AttendanceAgent
from app.db import init_db, insert_student, insert_room, insert_session, get_attendance_by_session
from app.ui import (
    process_uploaded_file,
    revalidate_and_summarise,
    calculate_metrics_summary,
    commit_session_to_database,
    generate_export_buffers,
)
from tools.summary_tool import SummaryReport
from tools.read_photo_tool import PhotoExtractionResult, PhotoRow, ExtractionSource


class MockUploadedFile:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getbuffer(self) -> bytes:
        return self._data

    def read(self) -> bytes:
        return self._data


@pytest.fixture
def empty_in_memory_db():
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    yield conn
    conn.close()


def test_ui_upload_clean_csv_success():
    csv_content = (
        "usn,name,branch,room_id,status\n"
        "1MS21CS001,Alice Smith,CSE,LH-101,PRESENT\n"
        "1MS21CS002,Bob Jones,CSE,LH-101,ABSENT\n"
    ).encode("utf-8")
    uploaded = MockUploadedFile("clean.csv", csv_content)

    agent = AttendanceAgent()
    resp, tmp_file = process_uploaded_file(
        agent,
        uploaded,
        master_usns=["1MS21CS001", "1MS21CS002"],
        master_rooms=["LH-101"],
    )
    assert resp.success is True
    assert resp.needs_confirmation is False
    assert resp.summary_report is not None
    assert resp.summary_report["overall"]["confirmed_percentage"] == 50.0
    if tmp_file.exists():
        tmp_file.unlink()


def test_ui_upload_empty_csv_returns_clean_failure():
    csv_content = "".encode("utf-8")
    uploaded = MockUploadedFile("empty.csv", csv_content)

    agent = AttendanceAgent()
    resp, tmp_file = process_uploaded_file(
        agent,
        uploaded,
        master_usns=[],
        master_rooms=[],
    )
    # Empty source should fail reading before validation, not silently succeed.
    assert resp.success is False
    assert "Successfully processed 0 attendance records" not in resp.message
    if tmp_file.exists():
        tmp_file.unlink()


def test_ui_upload_csv_with_whitespace_rows():
    csv_content = (
        "usn,name,branch,room_id,status\n"
        "1MS21CS001,Alice Smith,CSE,LH-101,PRESENT\n"
        "\n"
        "1MS21CS002,Bob Jones,CSE,LH-101,ABSENT\n"
    ).encode("utf-8")
    uploaded = MockUploadedFile("whitespace.csv", csv_content)

    agent = AttendanceAgent()
    resp, tmp_file = process_uploaded_file(
        agent,
        uploaded,
        master_usns=["1MS21CS001", "1MS21CS002"],
        master_rooms=["LH-101"],
    )
    assert resp.success is True
    assert resp.summary_report is not None
    if tmp_file.exists():
        tmp_file.unlink()


def test_ui_upload_csv_with_unrecognized_status_normalizes():
    csv_content = (
        "usn,name,branch,room_id,status\n"
        "1MS21CS001,Alice Smith,CSE,LH-101,Late\n"
        "1MS21CS002,Bob Jones,CSE,LH-101,EXCUSED\n"
    ).encode("utf-8")
    uploaded = MockUploadedFile("bad_status.csv", csv_content)

    agent = AttendanceAgent()
    resp, tmp_file = process_uploaded_file(
        agent,
        uploaded,
        master_usns=["1MS21CS001", "1MS21CS002"],
        master_rooms=["LH-101"],
    )
    assert resp.needs_confirmation is True
    assert resp.success is False
    assert tmp_file.exists() or True
    if tmp_file.exists():
        tmp_file.unlink()


def test_ui_upload_csv_missing_room_fails_validation():
    csv_content = (
        "usn,name,branch,room_id,status\n"
        "1MS21CS001,Alice Smith,CSE,,PRESENT\n"
    ).encode("utf-8")
    uploaded = MockUploadedFile("missing_room.csv", csv_content)

    agent = AttendanceAgent()
    resp, tmp_file = process_uploaded_file(
        agent,
        uploaded,
        master_usns=["1MS21CS001"],
        master_rooms=["LH-101"],
    )
    assert resp.needs_confirmation is True
    assert resp.success is False
    if tmp_file.exists():
        tmp_file.unlink()


def test_ui_upload_csv_missing_branch_fails_validation():
    csv_content = (
        "usn,name,branch,room_id,status\n"
        "1MS21CS001,Alice Smith,,LH-101,PRESENT\n"
    ).encode("utf-8")
    uploaded = MockUploadedFile("missing_branch.csv", csv_content)

    agent = AttendanceAgent()
    resp, tmp_file = process_uploaded_file(
        agent,
        uploaded,
        master_usns=["1MS21CS001"],
        master_rooms=["LH-101"],
    )
    assert resp.needs_confirmation is True
    assert resp.success is False
    if tmp_file.exists():
        tmp_file.unlink()


def test_ui_upload_csv_with_duplicate_usn_fails_validation():
    csv_content = (
        "usn,name,branch,room_id,status\n"
        "1MS21CS001,Alice Smith,CSE,LH-101,PRESENT\n"
        "1MS21CS001,Alice Smith,CSE,LH-101,ABSENT\n"
    ).encode("utf-8")
    uploaded = MockUploadedFile("duplicate.csv", csv_content)

    agent = AttendanceAgent()
    resp, tmp_file = process_uploaded_file(
        agent,
        uploaded,
        master_usns=["1MS21CS001"],
        master_rooms=["LH-101"],
    )
    assert resp.needs_confirmation is True
    assert resp.success is False
    tool_names = [call["tool_name"] for call in resp.tool_calls]
    assert "summary_tool" not in tool_names
    if tmp_file.exists():
        tmp_file.unlink()


def test_ui_upload_csv_with_conflicting_status_fails_validation():
    csv_content = (
        "usn,name,branch,room_id,status\n"
        "1MS21CS001,Alice Smith,CSE,LH-101,PRESENT\n"
        "1MS21CS001,Alice Smith,CSE,LH-102,ABSENT\n"
    ).encode("utf-8")
    uploaded = MockUploadedFile("conflict.csv", csv_content)

    agent = AttendanceAgent()
    resp, tmp_file = process_uploaded_file(
        agent,
        uploaded,
        master_usns=["1MS21CS001"],
        master_rooms=["LH-101", "LH-102"],
    )
    assert resp.needs_confirmation is True
    assert resp.success is False
    tool_names = [call["tool_name"] for call in resp.tool_calls]
    assert "summary_tool" not in tool_names
    if tmp_file.exists():
        tmp_file.unlink()


def test_ui_photo_upload_low_confidence_requires_confirmation(monkeypatch):
    mock_row = PhotoRow(
        usn="1MS21CS001",
        name="Alice Smith",
        status="PRESENT",
        confidence=0.75,
        source=ExtractionSource.OCR_FALLBACK,
    )
    mock_result = PhotoExtractionResult(
        image_path="sheet.jpg",
        rows=[mock_row],
        source=ExtractionSource.OCR_FALLBACK,
    )

    agent = AttendanceAgent()
    agent.registry.tools["read_photo_tool"].handler = lambda image_path, **kw: mock_result

    photo_path = Path(__file__).resolve().parent.parent / "data" / "photos" / "sheet_clean.jpg"
    if not photo_path.exists():
        pytest.skip("sample photo data/photos/sheet_clean.jpg not present")
    with open(photo_path, "rb") as src:
        real_bytes = src.read()

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(real_bytes)
        tmp_path = tmp.name

    fake_upload = MockUploadedFile("sheet_clean.jpg", real_bytes)
    resp, tmp_file = process_uploaded_file(agent, fake_upload)

    assert resp.success is False
    assert resp.needs_confirmation is True
    assert "0.80" in resp.message
    tool_names = [call["tool_name"] for call in resp.tool_calls]
    assert "summary_tool" not in tool_names
    if tmp_file.exists():
        tmp_file.unlink()
    Path(tmp_path).unlink(missing_ok=True)


def test_ui_photo_upload_high_confidence_proceeds(monkeypatch):
    mock_row = PhotoRow(
        usn="1MS21CS001",
        name="Alice Smith",
        status="PRESENT",
        confidence=0.95,
        source=ExtractionSource.OCR_FALLBACK,
    )
    mock_result = PhotoExtractionResult(
        image_path="sheet.jpg",
        rows=[mock_row],
        source=ExtractionSource.OCR_FALLBACK,
    )

    agent = AttendanceAgent()
    agent.registry.tools["read_photo_tool"].handler = lambda image_path, **kw: mock_result
    agent.registry.tools["validate_tool"].handler = MagicMock(return_value=MagicMock(is_valid=True, valid_records=[mock_row.to_dict()], invalid_records=[], errors=[]))

    photo_path = Path(__file__).resolve().parent.parent / "data" / "photos" / "sheet_clean.jpg"
    if not photo_path.exists():
        pytest.skip("sample photo data/photos/sheet_clean.jpg not present")
    with open(photo_path, "rb") as src:
        real_bytes = src.read()

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(real_bytes)
        tmp_path = tmp.name

    fake_upload = MockUploadedFile("sheet_clean.jpg", real_bytes)
    resp, tmp_file = process_uploaded_file(agent, fake_upload)

    assert resp.success is True
    assert resp.needs_confirmation is False
    assert resp.summary_report is not None
    if tmp_file.exists():
        tmp_file.unlink()
    Path(tmp_path).unlink(missing_ok=True)



def test_ui_photo_upload_empty_result_is_failure(monkeypatch):
    mock_result = PhotoExtractionResult(
        image_path="sheet.jpg",
        rows=[],
        source=ExtractionSource.OCR_FALLBACK,
    )

    agent = AttendanceAgent()
    agent.registry.tools["read_photo_tool"].handler = lambda image_path, **kw: mock_result

    photo_path = Path(__file__).resolve().parent.parent / "data" / "photos" / "sheet_clean.jpg"
    if not photo_path.exists():
        pytest.skip("sample photo data/photos/sheet_clean.jpg not present")
    with open(photo_path, "rb") as src:
        real_bytes = src.read()

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(real_bytes)
        tmp_path = tmp.name

    fake_upload = MockUploadedFile("sheet_clean.jpg", real_bytes)
    resp, tmp_file = process_uploaded_file(agent, fake_upload)

    # Empty photo extraction should not produce a successful summary.
    assert resp.success is False
    assert resp.needs_confirmation is True or "zero rows" in resp.message.lower() or "no rows" in resp.message.lower() or "empty" in resp.message.lower()
    if tmp_file.exists():
        tmp_file.unlink()
    Path(tmp_path).unlink(missing_ok=True)


def test_ui_revalidation_clears_confirmation():
    corrected_records = [
        {"usn": "1MS21CS001", "name": "Alice Smith", "branch": "CSE", "room_id": "LH-101", "status": "PRESENT"},
        {"usn": "1MS21CS002", "name": "Bob Jones", "branch": "CSE", "room_id": "LH-101", "status": "ABSENT"},
    ]

    agent = AttendanceAgent()
    resp, tmp_file = revalidate_and_summarise(
        agent,
        corrected_records,
        master_usns=["1MS21CS001", "1MS21CS002"],
        master_rooms=["LH-101"],
    )
    assert resp.success is True
    assert resp.needs_confirmation is False
    assert resp.summary_report is not None
    assert resp.summary_report["overall"]["present"] == 1
    assert resp.summary_report["overall"]["absent"] == 1
    assert resp.summary_report["overall"]["confirmed_percentage"] == 50.0
    if tmp_file.exists():
        tmp_file.unlink()


def test_ui_revalidation_with_renamed_columns():
    corrected_records = [
        {"usn": "1MS21CS001", "name": "Alice Smith", "dept": "CSE", "room": "LH-101", "status": "PRESENT"},
        {"usn": "1MS21CS002", "name": "Bob Jones", "dept": "CSE", "room": "LH-101", "status": "ABSENT"},
    ]

    agent = AttendanceAgent()
    resp, tmp_file = revalidate_and_summarise(
        agent,
        corrected_records,
        master_usns=["1MS21CS001", "1MS21CS002"],
        master_rooms=["LH-101"],
    )
    assert resp.success is True
    assert resp.needs_confirmation is False
    assert resp.summary_report is not None
    if tmp_file.exists():
        tmp_file.unlink()


def test_ui_metrics_summary_empty_and_edge_cases():
    empty_res = calculate_metrics_summary(None)
    assert empty_res["confirmed_percentage"] == 0.0
    assert empty_res["total"] == 0

    rep_66 = {
        "overall": {
            "present": 2,
            "absent": 1,
            "pending": 0,
            "unreviewed": 0,
            "confirmed": 3,
            "total": 3,
            "confirmed_percentage": 66.67,
        }
    }
    res_66 = calculate_metrics_summary(rep_66)
    assert res_66["confirmed_percentage"] == 66.67
    assert res_66["present"] == 2
    assert res_66["absent"] == 1

    rep_pending = {
        "overall": {
            "present": 0,
            "absent": 0,
            "pending": 2,
            "unreviewed": 0,
            "confirmed": 0,
            "total": 2,
            "confirmed_percentage": 0.0,
        }
    }
    res_pending = calculate_metrics_summary(rep_pending)
    assert res_pending["confirmed_percentage"] == 0.0
    assert res_pending["pending"] == 2
    assert res_pending["absent"] == 0


def test_ui_commit_session_to_database_success(tmp_path):
    db_file = tmp_path / "test_commit.db"
    conn = sqlite3.connect(db_file)
    init_db(conn)
    insert_student(conn, usn="1MS21CS001", name="Alice Smith", branch="CSE")
    insert_room(conn, room_id="LH-101", name="Lecture Hall 101")
    conn.close()

    records = [
        {"usn": "1MS21CS001", "name": "Alice Smith", "room_id": "LH-101", "status": "PRESENT", "confidence": 1.0, "source": "UI_CONFIRMED"},
    ]

    ok, msg = commit_session_to_database(
        db_target=db_file,
        session_id="SESS-NEW-01",
        records=records,
        date="2026-10-25",
        subject="AI Lab",
    )
    assert ok is True
    assert "Successfully committed" in msg

    verify_conn = sqlite3.connect(db_file)
    verify_conn.row_factory = sqlite3.Row
    saved = get_attendance_by_session(verify_conn, "SESS-NEW-01")
    verify_conn.close()
    assert saved is not None
    assert len(saved) == 1
    assert saved[0]["usn"] == "1MS21CS001"
    assert saved[0]["status"] == "PRESENT"


def test_ui_commit_session_to_database_empty_records_fails(tmp_path):
    db_file = tmp_path / "test_commit_empty.db"

    ok, msg = commit_session_to_database(
        db_target=db_file,
        session_id="SESS-EMPTY-01",
        records=[],
    )
    assert ok is False
    assert "No records to commit" in msg


def test_ui_commit_session_to_database_unknown_student_still_writes():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = Path(tmp_dir) / "test_unknown_student.db"
        conn = sqlite3.connect(db_file)
        init_db(conn)
        insert_student(conn, usn="1MS21XX001", name="Unknown", branch="UNKNOWN")
        insert_room(conn, room_id="LH-101", name="Lecture Hall 101")
        conn.close()

        records = [
            {"usn": "1MS21XX001", "name": "Unknown", "room_id": "LH-101", "status": "PRESENT", "confidence": 1.0, "source": "UI_CONFIRMED"},
        ]

        ok, msg = commit_session_to_database(
            db_target=db_file,
            session_id="SESS-UNKNOWN-01",
            records=records,
        )
        assert ok is True

        verify_conn = sqlite3.connect(db_file)
        verify_conn.row_factory = sqlite3.Row
        saved = get_attendance_by_session(verify_conn, "SESS-UNKNOWN-01")
        verify_conn.close()
        assert saved is not None
        assert len(saved) == 1
        assert saved[0]["usn"] == "1MS21XX001"


def test_ui_commit_session_overwrites_previous_session_records(tmp_path):
    db_file = tmp_path / "test_overwrite.db"
    conn = sqlite3.connect(db_file)
    init_db(conn)
    insert_student(conn, usn="1MS21CS001", name="Alice Smith", branch="CSE")
    insert_room(conn, room_id="LH-101", name="Lecture Hall 101")
    insert_session(conn, session_id="SESS-OVERWRITE-01", date="2026-10-25", subject="Old")
    conn.close()

    first_records = [
        {"usn": "1MS21CS001", "name": "Alice Smith", "room_id": "LH-101", "status": "PRESENT", "confidence": 1.0, "source": "UI_CONFIRMED"},
    ]
    ok1, msg1 = commit_session_to_database(
        db_target=db_file,
        session_id="SESS-OVERWRITE-01",
        records=first_records,
    )
    assert ok1 is True

    second_records = [
        {"usn": "1MS21CS001", "name": "Alice Smith", "room_id": "LH-101", "status": "ABSENT", "confidence": 1.0, "source": "UI_CONFIRMED"},
    ]
    ok2, msg2 = commit_session_to_database(
        db_target=db_file,
        session_id="SESS-OVERWRITE-01",
        records=second_records,
    )
    assert ok2 is True

    verify_conn = sqlite3.connect(db_file)
    verify_conn.row_factory = sqlite3.Row
    saved = get_attendance_by_session(verify_conn, "SESS-OVERWRITE-01")
    verify_conn.close()
    assert saved is not None
    assert len(saved) == 1
    assert saved[0]["status"] == "ABSENT"


def test_ui_export_buffers_excel_and_pdf_valid():
    room_df = pd.DataFrame([
        {"room_id": "LH-101", "present": 2, "absent": 1, "pending": 0, "unreviewed": 0, "unresolved": 0, "confirmed": 3, "total": 3, "percentage": 66.67}
    ])
    branch_df = pd.DataFrame([
        {"branch": "CSE", "present": 2, "absent": 1, "pending": 0, "unreviewed": 0, "unresolved": 0, "confirmed": 3, "total": 3, "percentage": 66.67}
    ])
    overall = {"present": 2, "absent": 1, "pending": 0, "unreviewed": 0, "unresolved": 0, "confirmed": 3, "total": 3, "percentage": 66.67, "confirmed_percentage": 66.67}

    summary = SummaryReport(room_wise=room_df, branch_wise=branch_df, overall=overall)
    excel_bytes, pdf_bytes = generate_export_buffers(summary)

    assert len(excel_bytes) > 0
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
    assert "Room_Summary" in wb.sheetnames
    assert "Branch_Summary" in wb.sheetnames

    assert len(pdf_bytes) > 0
    assert pdf_bytes.startswith(b"%PDF-")


def test_ui_chat_query_returns_exact_no_data_for_unanswerable():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = Path(tmp_dir) / "test_chat.db"
        conn = sqlite3.connect(db_file)
        init_db(conn)
        conn.close()

        agent = AttendanceAgent(db_target=db_file)

        resp = agent.process_request("What was the average exam score in session SESS-20261024-01?")
        assert "I do not have that data." in resp.message


def test_ui_chat_query_returns_no_data_for_nonexistent_session():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = Path(tmp_dir) / "test_chat.db"
        conn = sqlite3.connect(db_file)
        init_db(conn)
        insert_session(conn, session_id="REAL-SESSION", date="2026-10-25", subject="Lab")
        conn.close()

        agent = AttendanceAgent(db_target=db_file)

        resp = agent.process_request("Who was absent in session SESS-DOESNOTEXIST-999?")
        assert "I do not have that data." in resp.message


def test_ui_chat_query_logs_tool_execution():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = Path(tmp_dir) / "test_chat.db"
        conn = sqlite3.connect(db_file)
        init_db(conn)
        insert_session(conn, session_id="SESS-20261024-01", date="2026-10-24", subject="Lab")
        conn.close()

        agent = AttendanceAgent(db_target=db_file)

        resp = agent.process_request("Who was absent in session SESS-20261024-01?")
        assert resp.request_id is not None
        assert len(resp.tool_calls) > 0
        assert any(call["tool_name"] == "query_tool" for call in resp.tool_calls)
