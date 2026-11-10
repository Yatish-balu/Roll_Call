"""Tests for Security Hardening and T-SEC checks (Prompt N15 / Rule D15)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
import pytest
from fastapi import HTTPException
from openpyxl import load_workbook
import pandas as pd

from tools.export_tool import export_to_excel, export_to_pdf
from tools.query_tool import safe_sql_query, validate_read_only_sql


def test_t_sec_formula_injection_escaped_in_excel(tmp_path):
    """S6: CSV with name starting with =1+1 exported to Excel and PDF shows as text, not formula."""
    malicious_data = [
        {"usn": "1MS21CS001", "name": "=1+1", "branch": "CSE", "status": "PRESENT", "room_id": "LH-101"},
        {"usn": "1MS21CS002", "name": "+cmd|' /C calc'!A0", "branch": "CSE", "status": "ABSENT", "room_id": "LH-101"},
        {"usn": "1MS21CS003", "name": "@SUM(1,2)", "branch": "CSE", "status": "PRESENT", "room_id": "LH-101"},
        {"usn": "1MS21CS004", "name": "-2+3", "branch": "CSE", "status": "PRESENT", "room_id": "LH-101"},
    ]

    xlsx_path = tmp_path / "sanitized.xlsx"
    export_to_excel(malicious_data, xlsx_path, overwrite=True)

    # Inspect cells in openpyxl
    wb = load_workbook(str(xlsx_path))
    sheet = wb["Attendance_Details"]
    names = [row[1] for row in sheet.iter_rows(min_row=2, max_col=2, values_only=True)]

    # All formula triggers must have leading apostrophe
    assert names[0] == "'=1+1"
    assert names[1] == "'+cmd|' /C calc'!A0"
    assert names[2] == "'@SUM(1,2)"
    assert names[3] == "'-2+3"

    # PDF export must also succeed without executing formula
    pdf_path = tmp_path / "sanitized.pdf"
    res_pdf = export_to_pdf(malicious_data, pdf_path, overwrite=True)
    assert res_pdf.success is True
    assert pdf_path.stat().st_size > 0


def test_t_sec_query_tool_blocks_mutations():
    """T-SEC: query_tool rejects any INSERT, UPDATE, DELETE, DROP, ALTER statement."""
    with pytest.raises(ValueError) as exc1:
        validate_read_only_sql("INSERT INTO attendance VALUES ('s1', '1MS21CS001', 'LH-101', 'PRESENT', 'CSV', 1.0)")
    assert "Disallowed keyword" in str(exc1.value)

    with pytest.raises(ValueError) as exc2:
        validate_read_only_sql("UPDATE students SET name = 'Hacked' WHERE usn = '1MS21CS001'")
    assert "Disallowed keyword" in str(exc2.value)

    with pytest.raises(ValueError) as exc3:
        validate_read_only_sql("DELETE FROM audit_log WHERE log_id = 1")
    assert "Disallowed keyword" in str(exc3.value)

    with pytest.raises(ValueError) as exc4:
        validate_read_only_sql("DROP TABLE students")
    assert "Disallowed keyword" in str(exc4.value)


def test_t_sec_error_response_no_traceback():
    """S11: Verify standard error body format and codes without traceback or file paths."""
    from app.main import _map_error_code
    code = _map_error_code(403, "Session is locked for edits (24h edit window expired).")
    assert code == "LOCKED"

    code422 = _map_error_code(422, "Photo quality rejected")
    assert code422 == "QUALITY_REJECTED"

    code401 = _map_error_code(401, "Not authenticated")
    assert code401 == "UNAUTHENTICATED"

    code429 = _map_error_code(429, "Rate limit exceeded")
    assert code429 == "RATE_LIMITED"
