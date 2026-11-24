"""Uploaded documents must be analysed from their content, never fabricated."""

from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.agent.legacy_agent import AttendanceAgent


def _agent():
    return AttendanceAgent(actor_id="faculty_cn", actor_name="Faculty CN")


def test_blank_calendar_pdf_is_not_filled_with_canned_events(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    pdf = tmp_path / "calendar.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(pdf, "wb") as fh:
        writer.write(fh)

    res = _agent()._handle_calendar_events_file(pdf, "req-1", "update the calendar")

    assert res.success is False
    assert not res.data
    assert "could not read any text" in res.message.lower()


def test_calendar_query_reports_only_stored_events():
    res = _agent()._handle_calendar_intent("show the calendar", "req-2")

    assert res.success is True
    assert not res.data
    assert "no academic calendar events stored" in res.message.lower()


def test_unreadable_timetable_is_not_replaced_by_a_canned_schedule(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    image = tmp_path / "timetable.png"
    image.write_bytes(b"not a real image")

    res = _agent()._handle_timetable_file(image, "req-3", "")

    assert res.success is False
    assert "could not identify timetable slots" in res.message.lower()
