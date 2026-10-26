"""Tests for export_tool: Excel and PDF report generation."""

from pathlib import Path
import pytest
import pandas as pd
from tools.export_tool import export_tool, export_to_excel, export_to_pdf, ExportResult
from tools.summary_tool import SummaryReport


@pytest.fixture
def sample_attendance_df():
    return pd.DataFrame([
        {"session_id": "SESS-01", "usn": "1MS21CS001", "name": "Alice Smith", "branch": "CSE", "room_id": "LH-101", "status": "PRESENT", "confidence": 1.0},
        {"session_id": "SESS-01", "usn": "1MS21CS002", "name": "Bob Jones", "branch": "CSE", "room_id": "LH-101", "status": "ABSENT", "confidence": 1.0},
        {"session_id": "SESS-01", "usn": "1MS21IS001", "name": "Charlie Brown", "branch": "ISE", "room_id": "LH-102", "status": "PENDING", "confidence": 0.9},
        {"session_id": "SESS-01", "usn": "1MS21EC001", "name": "David Miller", "branch": "ECE", "room_id": "LH-102", "status": "UNREVIEWED", "confidence": 0.85},
    ])


def test_export_to_excel_success(sample_attendance_df, tmp_path):
    out_file = tmp_path / "test_report.xlsx"
    res = export_to_excel(sample_attendance_df, output_path=out_file, overwrite=True)

    assert res.success is True
    assert res.format == "excel"
    assert out_file.exists()
    assert out_file.stat().st_size > 0
    assert "Room_Summary" in res.summary_sheets
    assert "Branch_Summary" in res.summary_sheets
    assert "Attendance_Details" in res.summary_sheets

    # Verify workbook content
    excel_file = pd.ExcelFile(out_file)
    assert "Room_Summary" in excel_file.sheet_names
    assert "Branch_Summary" in excel_file.sheet_names
    assert "Attendance_Details" in excel_file.sheet_names

    details = pd.read_excel(excel_file, sheet_name="Attendance_Details")
    assert len(details) == 4
    statuses = set(details["status"])
    assert statuses == {"PRESENT", "ABSENT", "PENDING", "UNREVIEWED"}


def test_export_to_excel_overwrite_protection(sample_attendance_df, tmp_path):
    out_file = tmp_path / "protected.xlsx"
    out_file.write_text("existing content")

    with pytest.raises(FileExistsError):
        export_to_excel(sample_attendance_df, output_path=out_file, overwrite=False)

    # With overwrite=True it succeeds
    res = export_to_excel(sample_attendance_df, output_path=out_file, overwrite=True)
    assert res.success is True


def test_export_to_pdf_success(sample_attendance_df, tmp_path):
    out_file = tmp_path / "test_report.pdf"
    res = export_to_pdf(sample_attendance_df, output_path=out_file, overwrite=True)

    assert res.success is True
    assert res.format == "pdf"
    assert out_file.exists()
    assert out_file.stat().st_size > 500  # valid PDF file size
    assert "Room_Summary" in res.summary_sheets
    assert "Branch_Summary" in res.summary_sheets


def test_export_to_pdf_handles_zero_attendance(tmp_path):
    zero_df = pd.DataFrame([
        {"session_id": "SESS-01", "usn": "1MS21CS001", "name": "Alice", "branch": "CSE", "room_id": "LH-101", "status": "PENDING", "confidence": 0.9},
    ])
    out_file = tmp_path / "zero_rate.pdf"
    res = export_to_pdf(zero_df, output_path=out_file, overwrite=True)
    assert res.success is True
    assert out_file.exists()


def test_export_tool_dispatcher(sample_attendance_df, tmp_path):
    excel_path = tmp_path / "disp.xlsx"
    res_excel = export_tool(sample_attendance_df, format="excel", output_path=excel_path)
    assert res_excel.success is True
    assert excel_path.exists()

    pdf_path = tmp_path / "disp.pdf"
    res_pdf = export_tool(sample_attendance_df, format="pdf", output_path=pdf_path)
    assert res_pdf.success is True
    assert pdf_path.exists()

    with pytest.raises(ValueError, match="Unsupported export format"):
        export_tool(sample_attendance_df, format="docx", output_path=tmp_path / "disp.docx")
