"""Integration tests for Attendance Unlock Request workflow (>24h teacher permissions)."""

import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.db.models import User, Session as AcademicSession, AttendanceUnlockRequest, Department, College
from app.db.connection import get_sync_session_factory
from app.auth.jwt import create_access_token


@pytest.fixture
def auth_tokens():
    SessionLocal = get_sync_session_factory()
    with SessionLocal() as db:
        # Ensure college & department
        col = db.get(College, "DSCE")
        if not col:
            col = College(college_id="DSCE", name="DSCE", code="DSCE")
            db.add(col)
        dept = db.get(Department, "CSE")
        if not dept:
            dept = Department(dept_id="CSE", name="CSE", college_id="DSCE", code="CSE")
            db.add(dept)

        # Create/ensure admin & teacher
        now_iso = datetime.now(timezone.utc).isoformat()
        admin = db.get(User, "admin_test_ulr")
        if not admin:
            admin = User(
                user_id="admin_test_ulr",
                name="Admin Tester",
                email="admin_ulr@institution.edu",
                role="ADMIN",
                is_active=1,
                created_at=now_iso,
            )
            db.add(admin)

        teacher = db.get(User, "teacher_test_ulr")
        if not teacher:
            teacher = User(
                user_id="teacher_test_ulr",
                name="Teacher Tester",
                email="teacher_ulr@institution.edu",
                role="FACULTY",
                is_active=1,
                created_at=now_iso,
            )
            db.add(teacher)

        # Create locked session (>48h ago)
        old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        sess = db.get(AcademicSession, "SESS-LOCKED-001")
        if not sess:
            sess = AcademicSession(
                session_id="SESS-LOCKED-001",
                teacher_id="teacher_test_ulr",
                subject="Computer Networks",
                subject_code="CN",
                date="2026-11-10",
                created_at=old_time,
            )
            db.add(sess)
        db.commit()

    admin_token = create_access_token({"sub": "admin_test_ulr", "role": "ADMIN"})
    teacher_token = create_access_token({"sub": "teacher_test_ulr", "role": "FACULTY"})

    return {
        "admin_token": admin_token,
        "teacher_token": teacher_token,
    }


@pytest.mark.no_auth_override
def test_unlock_request_workflow(auth_tokens):
    client = TestClient(app)
    teacher_headers = {"Authorization": f"Bearer {auth_tokens['teacher_token']}"}
    admin_headers = {"Authorization": f"Bearer {auth_tokens['admin_token']}"}

    # 1. Teacher submits an unlock request
    req_payload = {
        "session_id": "SESS-LOCKED-001",
        "reason": "Student 1DS24CY015 was present but marked absent by mistake due to late arrival.",
        "target_usns": ["1DS24CY015"],
        "requested_change": "Mark 1DS24CY015 PRESENT",
    }
    resp = client.post("/api/v1/attendance/unlock-requests", json=req_payload, headers=teacher_headers)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["session_id"] == "SESS-LOCKED-001"
    assert data["status"] == "PENDING"
    assert data["teacher_id"] == "teacher_test_ulr"
    req_id = data["request_id"]

    # 2. Duplicate submission blocked with 409
    resp_dup = client.post("/api/v1/attendance/unlock-requests", json=req_payload, headers=teacher_headers)
    assert resp_dup.status_code == 409

    # 3. List unlock requests
    list_resp = client.get("/api/v1/attendance/unlock-requests?status=PENDING", headers=admin_headers)
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert any(item["request_id"] == req_id for item in items)

    # 4. Admin approves the request
    review_payload = {
        "decision": "APPROVED",
        "admin_notes": "Approved for 24h correction.",
        "unlock_hours": 24,
    }
    review_resp = client.post(
        f"/api/v1/attendance/unlock-requests/{req_id}/review",
        json=review_payload,
        headers=admin_headers,
    )
    assert review_resp.status_code == 200
    rev_data = review_resp.json()
    assert rev_data["status"] == "APPROVED"
    assert rev_data["expires_at"] is not None

    # 5. Teacher now edits attendance on the locked session; assert_session_edit_unlocked passes!
    from app.services.attendance_edits import assert_session_edit_unlocked
    from app.schemas.auth import AuthenticatedUser
    from app.auth.roles import Role

    teacher_user = AuthenticatedUser(
        user_id="teacher_test_ulr",
        email="teacher_ulr@institution.edu",
        role=Role.FACULTY,
    )
    SessionLocal = get_sync_session_factory()
    with SessionLocal() as db:
        old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        session_dict = {
            "session_id": "SESS-LOCKED-001",
            "created_at": old_time,
        }
        # This call should succeed without raising 403 because active unlock request exists in db!
        assert_session_edit_unlocked(teacher_user, session_dict, db=db)
