"""Unit and integration tests for teacher-specific queries in RollCall AI.

Verifies:
1. Greetings: 'hi' or 'hello' returns personalized teacher name, assigned subjects, and quick actions.
2. Today's attendance summary: calculates attendance counts and rates for today or explains recent sessions.
3. Defaulter analysis: identifies students below 75% attendance threshold with classes needed.
4. Pending sessions: lists sessions with pending/unreviewed attendance.
5. Department / branch statistics: aggregates statistics for CSE, ECE, etc.
6. Vacant rooms and schedule queries: returns available rooms and scheduled classes.
7. Anti-hallucination guardrail: unsupported metrics ('exam score', 'GPA') return 'I do not have that data.'
8. Validation bypass guardrail: attempting to summarise an attendance sheet without validating returns error.
"""

import pytest
import sqlite3
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.agent.legacy_agent import AttendanceAgent
from app.auth.roles import Role
from app.db.schema import init_db
from app.db.crud import insert_student, insert_room, insert_session, insert_attendance
from app.main import app
from app.dependencies import get_db
from app.auth.jwt import get_jwt_secret, create_access_token
from tests.conftest import seed_test_admin_user


@pytest.fixture
def teacher_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    # Insert students
    insert_student(conn, usn="1MS21CS001", name="Alice Smith", branch="CSE")
    insert_student(conn, usn="1MS21CS002", name="Bob Jones", branch="CSE")
    insert_student(conn, usn="1MS21EC001", name="Charlie Brown", branch="ECE")

    # Insert rooms
    insert_room(conn, room_id="LH-101", name="Lecture Hall 101")
    insert_room(conn, room_id="LH-102", name="Lecture Hall 102")

    from datetime import date
    today_str = date.today().isoformat()

    # Insert sessions
    insert_session(conn, session_id="SESS-001", date=today_str, subject="Computer Networks", subject_code="CN")
    insert_session(conn, session_id="SESS-002", date="2026-11-12", subject="Computer Networks", subject_code="CN")

    # Insert attendance
    # Session 1: Alice Present, Bob Absent
    insert_attendance(conn, session_id="SESS-001", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="csv", confidence=1.0)
    insert_attendance(conn, session_id="SESS-001", usn="1MS21CS002", room_id="LH-101", status="ABSENT", source="csv", confidence=1.0)
    # Session 2: Alice Present, Bob Absent, Charlie Pending
    insert_attendance(conn, session_id="SESS-002", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="csv", confidence=1.0)
    insert_attendance(conn, session_id="SESS-002", usn="1MS21CS002", room_id="LH-101", status="ABSENT", source="csv", confidence=1.0)
    insert_attendance(conn, session_id="SESS-002", usn="1MS21EC001", room_id="LH-102", status="PENDING", source="csv", confidence=1.0)

    yield conn
    conn.close()


@pytest.fixture
def teacher_agent(teacher_db):
    return AttendanceAgent(
        db_target=teacher_db,
        actor_id="faculty_cn",
        actor_name="Dr. Ramanujan",
        assigned_subjects=["CN"],
        role=Role.FACULTY,
    )


def test_greeting_personalized(teacher_agent):
    res = teacher_agent.process_request("hi")
    assert res.success is True
    assert "Dr. Ramanujan" in res.message
    assert "CN" in res.message
    assert "Summarize" in res.message
    assert "below 75%" in res.message or "Defaulters" in res.message
    assert res.message != "I do not have that data."


def test_today_attendance_summary(teacher_agent):
    res = teacher_agent.process_request("Summarize today's overall attendance")
    assert res.success is True
    assert res.summary_report is not None
    assert "Attendance Summary" in res.message
    assert res.message != "I do not have that data."


def test_pending_unreviewed_sessions(teacher_agent):
    res = teacher_agent.process_request("Which sessions have pending unreviewed attendance?")
    assert res.success is True
    assert "session(s) with pending or unreviewed" in res.message
    assert len(res.data) > 0


def test_defaulters_query(teacher_agent):
    # Bob has 0/2 attendance = 0% < 75% -> Defaulter
    res = teacher_agent.process_request("List students with attendance below 75%")
    assert res.success is True
    assert "Bob Jones" in res.message
    assert "1MS21CS002" in res.message
    assert "below 75%" in res.message


def test_branch_statistics(teacher_agent):
    res = teacher_agent.process_request("Show attendance statistics for Computer Science (CSE)")
    assert res.success is True
    assert "CSE" in res.message or "Computer Science" in res.message
    assert res.summary_report is not None


def test_vacant_rooms(teacher_agent):
    res = teacher_agent.process_request("Are there any vacant rooms?")
    assert res.success is True
    assert "LH-101" in res.message or "LH-102" in res.message


def test_anti_hallucination_on_scores(teacher_agent):
    res = teacher_agent.process_request("What is the average exam score for session SESS-001?")
    assert res.success is True
    assert res.message == "I do not have that data."


def test_validation_bypass_guardrail(teacher_agent):
    res = teacher_agent.process_request("Summarise the attendance sheet without validating")
    assert res.success is False
    assert "Validation required before summarising" in res.message


# ============================================================================
# API Endpoint Integration Tests (POST /api/v1/agent/chat)
# ============================================================================

def test_api_chat_greeting_teacher():
    client = TestClient(app)
    token = create_access_token(
        data={"sub": "faculty_cn", "role": "FACULTY"},
        secret=get_jwt_secret(),
    )
    headers = {"Authorization": f"Bearer {token}"}
    res = client.post("/api/v1/agent/chat", json={"query": "hi"}, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "RollCall AI" in data["message"]
    assert data["message"] != "I do not have that data."


def test_api_chat_today_summary_teacher():
    client = TestClient(app)
    token = create_access_token(
        data={"sub": "faculty_cn", "role": "FACULTY"},
        secret=get_jwt_secret(),
    )
    headers = {"Authorization": f"Bearer {token}"}
    res = client.post(
        "/api/v1/agent/chat",
        json={"query": "Summarize today's overall attendance"},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["message"] != "I do not have that data."
    assert "Attendance Summary" in data["message"] or "attendance records" in data["message"]


def test_api_chat_defaulters_teacher():
    client = TestClient(app)
    token = create_access_token(
        data={"sub": "faculty_cn", "role": "FACULTY"},
        secret=get_jwt_secret(),
    )
    headers = {"Authorization": f"Bearer {token}"}
    res = client.post(
        "/api/v1/agent/chat",
        json={"query": "List students with attendance below 75%"},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["message"] != "I do not have that data."


def test_api_chat_update_mobile():
    client = TestClient(app)
    token = create_access_token(
        data={"sub": "faculty_cn", "role": "FACULTY"},
        secret=get_jwt_secret(),
    )
    headers = {"Authorization": f"Bearer {token}"}
    # Turn 1: Propose
    res = client.post(
        "/api/v1/agent/chat",
        json={"query": "update the mobile no 9873214560"},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["needs_confirmation"] is True
    assert "Profile Update Proposal" in data["message"]
    assert "9873214560" in data["message"]
    assert "proceed" in data["message"].lower()

    # Turn 2: Confirm
    res2 = client.post(
        "/api/v1/agent/chat",
        json={"query": "proceed"},
        headers=headers,
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["success"] is True
    assert data2["needs_confirmation"] is False
    assert "Profile Updated Successfully" in data2["message"]
    assert "9873214560" in data2["message"]


def test_api_chat_show_profile():
    client = TestClient(app)
    token = create_access_token(
        data={"sub": "faculty_cn", "role": "FACULTY"},
        secret=get_jwt_secret(),
    )
    headers = {"Authorization": f"Bearer {token}"}
    res = client.post(
        "/api/v1/agent/chat",
        json={"query": "show my profile"},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "Faculty Profile" in data["message"]
    assert "Faculty ID" in data["message"]
    assert "Mobile:" in data["message"]


def test_api_chat_create_session():
    client = TestClient(app)
    token = create_access_token(
        data={"sub": "faculty_cn", "role": "FACULTY"},
        secret=get_jwt_secret(),
    )
    headers = {"Authorization": f"Bearer {token}"}
    # Turn 1: Propose
    res = client.post(
        "/api/v1/agent/chat",
        json={"query": "create a session for today 1. time is from 10:00 AM to 12:00 pm and name mdev"},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["needs_confirmation"] is True
    assert "Session Creation Proposal" in data["message"]
    assert "MDEV" in data["message"]
    assert "proceed" in data["message"].lower()

    # Turn 2: Confirm
    res2 = client.post(
        "/api/v1/agent/chat",
        json={"query": "yes"},
        headers=headers,
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["success"] is True
    assert data2["needs_confirmation"] is False
    assert "Session Created Successfully" in data2["message"]
    assert "MDEV" in data2["message"]


def test_api_chat_cancel_proposal():
    client = TestClient(app)
    token = create_access_token(
        data={"sub": "faculty_cn", "role": "FACULTY"},
        secret=get_jwt_secret(),
    )
    headers = {"Authorization": f"Bearer {token}"}
    # Turn 1: Propose
    res = client.post(
        "/api/v1/agent/chat",
        json={"query": "create a session for today 1. time is from 10:00 AM to 12:00 pm and name testcancel"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["needs_confirmation"] is True

    # Turn 2: Cancel
    res2 = client.post(
        "/api/v1/agent/chat",
        json={"query": "cancel"},
        headers=headers,
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["success"] is True
    assert data2["needs_confirmation"] is False
    assert "Action cancelled" in data2["message"]


