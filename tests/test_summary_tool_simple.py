"""Simple smoke test for summary_tool after restoring single symbol-map config."""

import pytest
from tools.summary_tool import summary_tool, normalize_status, SummaryReport


def test_summary_tool_smoke():
    """Quick check: summary_tool runs end-to-end on basic valid records."""
    records = [
        {"room_id": "LH-101", "branch": "CSE", "status": "present"},
        {"room_id": "LH-101", "branch": "CSE", "status": "PRESENT"},
        {"room_id": "LH-101", "branch": "CSE", "status": "absent"},
        {"room_id": "LH-102", "branch": "ISE", "status": "p"},
        {"room_id": "LH-102", "branch": "ISE", "status": "0"},
    ]

    report = summary_tool(records)
    assert isinstance(report, SummaryReport)
    assert report.room_wise.shape[0] >= 2
    assert report.branch_wise.shape[0] >= 2
    assert report.overall["present"] == 3
    assert report.overall["absent"] == 2
    assert report.overall["percentage"] == pytest.approx(60.0, abs=1e-6)


def test_summary_tool_empty():
    """Quick check: empty input does not crash and returns zero metrics."""
    report = summary_tool([])
    assert report.overall["total"] == 0
    assert report.overall["percentage"] == 0.0
    assert report.room_wise.empty
    assert report.branch_wise.empty


def test_normalize_status_keep_default_semantics():
    """Quick check: blank and unknown marks are not silently remapped to ABSENT."""
    assert normalize_status("") == "PENDING"
    assert normalize_status(None) == "PENDING"
    assert normalize_status("ambiguous") == "UNREVIEWED"
    assert normalize_status("absent") == "ABSENT"
    assert normalize_status("present") == "PRESENT"
