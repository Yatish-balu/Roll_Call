"""Tests for Phase 5.5: Report Export API Router (Excel & PDF).

Verifies:
1. Excel export returns valid downloadable workbook with sheets.
2. PDF export returns valid downloadable PDF document (%PDF header).
3. Correct MIME types and Content-Disposition headers.
4. Handling of invalid and missing session IDs (404 Not Found).
5. Date-filtered report export.
6. Exported data accurately reflects verified database records.
"""

import io
import pytest
import pandas as pd
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
    """FastAPI TestClient with isolated in-memory DB and pre-seeded dataset."""
    TestingSessionLocal = sessionmaker(bind=test_db_engine, class_=Session, expire_on_commit=False)

    with TestingSessionLocal() as session:
        session.add_all([
            Student(usn="1MS21CS001", name="Alice", branch="CSE"),
            Student(usn="1MS21CS002", name="Bob", branch="CSE"),
        ])
        session.add_all([
            Room(room_id="LH-101", name="Lecture Hall 101"),
        ])
        session.add_all([
            DbSession(session_id="SESS-001", date="2026-03-15", subject="Computer Networks"),
        ])
        session.add_all([
            Attendance(session_id="SESS-001", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="csv", confidence=0.98),
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
# 1. Excel Export Tests
# ==============================================================================

def test_export_excel_success(seeded_client):
    payload = {"session_id": "SESS-001", "include_branch_summary": True}
    res = seeded_client.post("/api/v1/reports/export/excel", json=payload)

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert 'attachment; filename="attendance_report_SESS-001.xlsx"' in res.headers["content-disposition"]
    assert len(res.content) > 0

    # Parse Excel content in memory and verify sheets & data
    excel_bytes = io.BytesIO(res.content)
    xl = pd.ExcelFile(excel_bytes)
    sheets = xl.sheet_names
    assert "Room_Summary" in sheets
    assert "Branch_Summary" in sheets
    assert "Attendance_Details" in sheets

    # Verify detail data matches database records
    detail_df = xl.parse("Attendance_Details")
    assert len(detail_df) == 2
    usns = set(detail_df["usn"])
    assert usns == {"1MS21CS001", "1MS21CS002"}


def test_export_excel_missing_session_returns_404(seeded_client):
    res = seeded_client.post("/api/v1/reports/export/excel", json={"session_id": "NONEXISTENT"})
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_export_excel_by_date(seeded_client):
    payload = {"date": "2026-03-15"}
    res = seeded_client.post("/api/v1/reports/export/excel", json=payload)
    assert res.status_code == 200
    assert 'filename="attendance_report_2026-03-15.xlsx"' in res.headers["content-disposition"]
    assert len(res.content) > 0


# ==============================================================================
# 2. PDF Export Tests
# ==============================================================================

def test_export_pdf_success(seeded_client):
    payload = {
        "session_id": "SESS-001",
        "title": "Semester 6 Roll Call Report",
    }
    res = seeded_client.post("/api/v1/reports/export/pdf", json=payload)

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert 'attachment; filename="attendance_report_SESS-001.pdf"' in res.headers["content-disposition"]
    assert len(res.content) > 0
    # PDF magic bytes
    assert res.content.startswith(b"%PDF")


def test_export_pdf_missing_session_returns_404(seeded_client):
    res = seeded_client.post("/api/v1/reports/export/pdf", json={"session_id": "NONEXISTENT"})
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_export_all_sessions(seeded_client):
    """Verify export without filter exports all session data."""
    res_excel = seeded_client.post("/api/v1/reports/export/excel", json={})
    assert res_excel.status_code == 200
    assert 'filename="attendance_report_all.xlsx"' in res_excel.headers["content-disposition"]

    res_pdf = seeded_client.post("/api/v1/reports/export/pdf", json={})
    assert res_pdf.status_code == 200
    assert 'filename="attendance_report_all.pdf"' in res_pdf.headers["content-disposition"]
    assert res_pdf.content.startswith(b"%PDF")

