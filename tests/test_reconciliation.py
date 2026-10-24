"""Pytest suite for 5-session manual summary reconciliation."""

import sqlite3
import pytest
from app.db import (
    init_db,
    insert_students_bulk,
    insert_rooms_bulk,
    insert_sessions_bulk,
    insert_attendance_bulk,
    get_session_attendance_details,
)
from tools.summary_tool import summary_tool
from tools.database import (
    SAMPLE_STUDENTS,
    SAMPLE_ROOMS,
    SAMPLE_SESSIONS,
    SAMPLE_ATTENDANCE,
)
from tools.verify_reconciliation import EXPECTED_TOTALS


@pytest.fixture
def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    insert_students_bulk(conn, SAMPLE_STUDENTS)
    insert_rooms_bulk(conn, SAMPLE_ROOMS)
    insert_sessions_bulk(conn, SAMPLE_SESSIONS)
    insert_attendance_bulk(conn, SAMPLE_ATTENDANCE)
    yield conn
    conn.close()


@pytest.mark.parametrize("session_id", list(EXPECTED_TOTALS.keys()))
def test_session_reconciliation(memory_db, session_id):
    """Verify 100% mathematical reconciliation of each test session against pre-calculated ground truth."""
    expected = EXPECTED_TOTALS[session_id]
    records = get_session_attendance_details(memory_db, session_id)
    report = summary_tool(records)
    overall = report.overall

    assert overall["present"] == expected["present"]
    assert overall["absent"] == expected["absent"]
    assert overall["pending"] == expected["pending"]
    assert overall["unreviewed"] == expected["unreviewed"]
    assert overall["unresolved"] == expected["unresolved"]
    assert overall["confirmed"] == expected["confirmed"]
    assert overall["total"] == expected["total"]
    assert abs(overall["percentage"] - expected["percentage"]) < 0.01

    # Verify room-wise
    room_recs = report.room_wise_records()
    matched_room = [r for r in room_recs if r["room_id"] == expected["room"]]
    assert len(matched_room) == 1
    r = matched_room[0]
    assert r["present"] == expected["present"]
    assert r["absent"] == expected["absent"]
    assert r["pending"] == expected["pending"]
    assert r["unreviewed"] == expected["unreviewed"]
    assert abs(r["percentage"] - expected["percentage"]) < 0.01

    # Verify branch-wise
    branch_recs = report.branch_wise_records()
    matched_branch = [b for b in branch_recs if b["branch"] == expected["branch"]]
    assert len(matched_branch) == 1
    b = matched_branch[0]
    assert b["present"] == expected["present"]
    assert b["absent"] == expected["absent"]
    assert b["pending"] == expected["pending"]
    assert b["unreviewed"] == expected["unreviewed"]
    assert abs(b["percentage"] - expected["percentage"]) < 0.01
