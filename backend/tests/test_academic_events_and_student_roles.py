import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.auth import get_current_user, Role
from app.agent.legacy_agent import AttendanceAgent
from app.db.models import AcademicEvent, Student
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser

@pytest.fixture
def client():
    return TestClient(app)

def test_calendar_events_endpoints(client):
    teacher_user = AuthenticatedUser(
        user_id="faculty_cn",
        email="faculty_cn@rollcall.edu",
        role=Role.FACULTY,
        claims={"sub": "faculty_cn", "role": "FACULTY"},
    )
    admin_user = AuthenticatedUser(
        user_id="00000000-0000-0000-0000-000000000001",
        email="admin@rollcall.edu",
        role=Role.ADMIN,
        claims={"sub": "00000000-0000-0000-0000-000000000001", "role": "ADMIN"},
    )

    # Teacher can read events
    app.dependency_overrides[get_current_user] = lambda: teacher_user
    res = client.get("/api/v1/calendar/events")
    assert res.status_code == 200
    assert "events" in res.json()

    # Teacher cannot create events (403 Forbidden)
    res = client.post(
        "/api/v1/calendar/events",
        json={"title": "Test Event", "event_date": "2026-11-20", "event_type": "CIE"},
    )
    assert res.status_code == 403

    # Admin can create events
    app.dependency_overrides[get_current_user] = lambda: admin_user
    res = client.post(
        "/api/v1/calendar/events",
        json={"title": "Test CIE Event", "event_date": "2026-11-20", "event_type": "CIE", "description": "Internal test"},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["count"] >= 1
    event_id = data["events"][0]["event_id"]

    # Month calendar includes events
    app.dependency_overrides[get_current_user] = lambda: teacher_user
    res = client.get("/api/v1/calendar?month=2026-11")
    assert res.status_code == 200
    assert "events" in res.json()

    # Day calendar includes events
    res = client.get("/api/v1/calendar/day?date=2026-11-20")
    assert res.status_code == 200
    assert any(e["title"] == "Test CIE Event" for e in res.json().get("events", []))

    # Admin can delete the test event
    app.dependency_overrides[get_current_user] = lambda: admin_user
    res = client.delete(f"/api/v1/calendar/events/{event_id}")
    assert res.status_code == 200

def test_agent_student_permission_check():
    # Teacher cannot register students via AI
    teacher_agent = AttendanceAgent(actor_role="TEACHER", actor_id="FACULTY_CN")
    res = teacher_agent.process_request(user_input="register student 1MS21CS999 John Doe", request_id="req-1")
    assert "Permission Denied" in res.message or "Administrative Access Required" in res.message
    assert res.success is False

    # Admin can register students
    db = next(get_db())
    admin_agent = AttendanceAgent(actor_role="ADMIN", actor_id="admin_root", db_target=db)
    res = admin_agent.process_request(user_input="register student 1MS21CS999 John Doe", request_id="req-2")
    assert res.success is True
    assert "Student Registered Successfully" in res.message or "already exists" in res.message

    # Clean up test student if created
    st = db.get(Student, "1MS21CS999")
    if st:
        db.delete(st)
        db.commit()

def test_agent_calendar_events_intent():
    db = next(get_db())
    agent = AttendanceAgent(actor_role="ADMIN", actor_id="admin_root", db_target=db)
    res = agent.process_request(user_input="upload it to calendar", request_id="req-3")
    assert res.success is True
    assert "Academic Calendar" in res.message
    assert "Registered" in res.message or "Synchronized" in res.message
