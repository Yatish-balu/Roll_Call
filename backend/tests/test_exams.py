"""Comprehensive test suite for RollCall AI Exam Hall & Form-B Control Module."""

from __future__ import annotations

import io
import pytest
from fastapi.testclient import TestClient

from app.auth.jwt import create_access_token
from app.main import app


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _auth_headers(user_id: str, role: str) -> dict:
    token = create_access_token({"sub": user_id, "role": role})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.no_auth_override
def test_create_exam_admin_and_rbac(client: TestClient):
    admin_hdr = _auth_headers("admin_root", "ADMIN")
    faculty_hdr = _auth_headers("faculty_cn", "FACULTY")

    exam_payload = {
        "exam_id": "TEST-CIE-2026-UNIT",
        "name": "Unit Test Assessment 2026",
        "exam_type": "THEORY_CIE",
        "semester": 5,
        "department": "Computer Science",
        "date": "2026-11-25",
        "start_time": "10:00:00",
        "end_time": "11:30:00",
        "cutoff_minutes": 30,
        "subject_code": "21CS51",
        "subject_name": "Management & Entrepreneurship",
    }

    # 1. Faculty cannot create exam -> 403
    fac_res = client.post("/api/v1/exams", json=exam_payload, headers=faculty_hdr)
    assert fac_res.status_code == 403

    # 2. Admin creates exam -> 201
    adm_res = client.post("/api/v1/exams", json=exam_payload, headers=admin_hdr)
    assert adm_res.status_code == 201, adm_res.text
    exam_data = adm_res.json()
    assert exam_data["exam_id"] == "TEST-CIE-2026-UNIT"
    assert exam_data["name"] == "Unit Test Assessment 2026"

    # 3. Duplicate exam_id -> 409
    dup_res = client.post("/api/v1/exams", json=exam_payload, headers=admin_hdr)
    assert dup_res.status_code == 409

    # 4. List exams
    list_res = client.get("/api/v1/exams", headers=admin_hdr)
    assert list_res.status_code == 200
    exams = list_res.json()
    assert any(e["exam_id"] == "TEST-CIE-2026-UNIT" for e in exams)


@pytest.mark.no_auth_override
def test_seating_plan_csv_upload_and_roster(client: TestClient):
    admin_hdr = _auth_headers("admin_root", "ADMIN")
    exam_id = "TEST-SEATING-2026"

    # Create exam
    client.post(
        "/api/v1/exams",
        json={
            "exam_id": exam_id,
            "name": "Seating Test Exam",
            "exam_type": "THEORY_CIE",
            "date": "2026-11-26",
            "start_time": "09:30:00",
            "end_time": "11:00:00",
            "cutoff_minutes": 30,
            "subject_code": "21CS52",
        },
        headers=admin_hdr,
    )

    # 1. Valid CSV with 2 rooms, 4 students
    csv_content = (
        "sl_no,usn,name,branch,room_no,seat_no\n"
        "1,1DS23CY101,Alice Smith,CY,ROOM-A,1\n"
        "2,1DS23CY102,Bob Jones,CY,ROOM-A,2\n"
        "3,1DS23CS201,Charlie Brown,CSE,ROOM-B,1\n"
        "4,1DS23CS202,David Miller,CSE,ROOM-B,2\n"
    )

    files = {"file": ("seating.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    up_res = client.post(f"/api/v1/exams/{exam_id}/seating/upload", files=files, headers=admin_hdr)
    assert up_res.status_code == 200, up_res.text
    data = up_res.json()
    assert data["total_students"] == 4
    assert data["total_rooms"] == 2

    # 2. Check room assignments auto-created
    rooms_res = client.get(f"/api/v1/exams/{exam_id}/rooms", headers=admin_hdr)
    assert rooms_res.status_code == 200
    rooms = rooms_res.json()
    assert len(rooms) == 2
    room_nos = {r["room_no"] for r in rooms}
    assert "ROOM-A" in room_nos
    assert "ROOM-B" in room_nos

    # 3. Duplicate USN in seating CSV -> 422
    bad_csv = (
        "sl_no,usn,name,branch,room_no\n"
        "1,1DS23CY999,Student One,CY,ROOM-A\n"
        "2,1DS23CY999,Student Duplicate,CY,ROOM-A\n"
    )
    bad_files = {"file": ("dup.csv", io.BytesIO(bad_csv.encode("utf-8")), "text/csv")}
    bad_res = client.post(f"/api/v1/exams/{exam_id}/seating/upload", files=bad_files, headers=admin_hdr)
    assert bad_res.status_code == 422
    assert "Duplicate USN" in bad_res.json()["detail"]


@pytest.mark.no_auth_override
def test_invigilator_assignment_and_jit_masking(client: TestClient):
    admin_hdr = _auth_headers("admin_root", "ADMIN")
    faculty_hdr = _auth_headers("faculty_cn", "FACULTY")
    exam_id = "TEST-JIT-2026"

    # Future exam (tomorrow)
    client.post(
        "/api/v1/exams",
        json={
            "exam_id": exam_id,
            "name": "Future Anti-Collusion Exam",
            "exam_type": "THEORY_SEE",
            "date": "2026-11-28",
            "start_time": "14:00:00",
            "end_time": "17:00:00",
            "cutoff_minutes": 45,
            "subject_code": "21CS53",
        },
        headers=admin_hdr,
    )

    # Assign faculty_cn to SECRET-101
    assign_res = client.post(
        f"/api/v1/exams/{exam_id}/rooms/SECRET-101/assign",
        json={
            "room_no": "SECRET-101",
            "block_name": "Heritage Block",
            "invigilator_id": "faculty_cn",
        },
        headers=admin_hdr,
    )
    assert assign_res.status_code == 200

    # 1. Faculty checks my-rooms: room number is masked under JIT anti-collusion rule!
    my_rooms_res = client.get("/api/v1/exams/my-rooms", headers=faculty_hdr)
    assert my_rooms_res.status_code == 200
    my_rooms = my_rooms_res.json()
    target_room = next((r for r in my_rooms if r["exam_id"] == exam_id), None)
    assert target_room is not None
    assert target_room["is_masked"] is True
    assert "CONFIDENTIAL" in target_room["display_room_no"]

    # 2. Admin checks room list: Admin sees unmasked room number
    admin_rooms_res = client.get(f"/api/v1/exams/{exam_id}/rooms", headers=admin_hdr)
    assert admin_rooms_res.status_code == 200
    adm_room = next(r for r in admin_rooms_res.json() if r["exam_id"] == exam_id)
    assert adm_room["room_no"] == "SECRET-101"


@pytest.mark.no_auth_override
def test_attendance_marking_and_submit_lock(client: TestClient):
    admin_hdr = _auth_headers("admin_root", "ADMIN")
    faculty_hdr = _auth_headers("faculty_cn", "FACULTY")
    other_fac_hdr = _auth_headers("faculty_ds", "FACULTY")
    exam_id = "TEST-LOCK-2026"

    # Create exam
    client.post(
        "/api/v1/exams",
        json={
            "exam_id": exam_id,
            "name": "Locking Workflow Exam",
            "exam_type": "THEORY_CIE",
            "date": "2026-11-22",
            "start_time": "08:00:00",
            "end_time": "10:00:00",
            "cutoff_minutes": 180,
            "subject_code": "21CS54",
        },
        headers=admin_hdr,
    )

    # Upload seating
    csv_content = (
        "sl_no,usn,name,branch,room_no\n"
        "1,1DS23CY001,Student One,CY,HALL-1\n"
        "2,1DS23CY002,Student Two,CY,HALL-1\n"
    )
    client.post(
        f"/api/v1/exams/{exam_id}/seating/upload",
        files={"file": ("seating.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
        headers=admin_hdr,
    )

    # Assign faculty_cn
    client.post(
        f"/api/v1/exams/{exam_id}/rooms/HALL-1/assign",
        json={"room_no": "HALL-1", "invigilator_id": "faculty_cn"},
        headers=admin_hdr,
    )

    # 1. Other faculty cannot access or mark HALL-1 -> 403
    unauth_mark = client.patch(
        f"/api/v1/exams/{exam_id}/rooms/HALL-1/mark",
        json={"marks": [{"usn": "1DS23CY001", "status": "PRESENT"}]},
        headers=other_fac_hdr,
    )
    assert unauth_mark.status_code == 403

    # 2. Assigned invigilator marks attendance -> 200
    mark_res = client.patch(
        f"/api/v1/exams/{exam_id}/rooms/HALL-1/mark",
        json={"marks": [{"usn": "1DS23CY001", "status": "PRESENT"}]},
        headers=faculty_hdr,
    )
    assert mark_res.status_code == 200
    assert "Updated attendance" in mark_res.json()["message"]

    # 3. Invigilator submits Form-B -> seals room
    submit_res = client.post(f"/api/v1/exams/{exam_id}/rooms/HALL-1/submit", headers=faculty_hdr)
    assert submit_res.status_code == 200
    assert submit_res.json()["status"] == "SUBMITTED"

    # 4. Modifying after submit by invigilator -> 403 Forbidden
    edit_post_lock = client.patch(
        f"/api/v1/exams/{exam_id}/rooms/HALL-1/mark",
        json={"marks": [{"usn": "1DS23CY002", "status": "PRESENT"}]},
        headers=faculty_hdr,
    )
    assert edit_post_lock.status_code == 403

    # 5. Admin override with reason -> 200
    override_res = client.post(
        f"/api/v1/exams/{exam_id}/rooms/HALL-1/admin-override",
        json={"reason": "Student produced medical certificate in control room", "new_status": "OPEN"},
        headers=admin_hdr,
    )
    assert override_res.status_code == 200
    assert override_res.json()["room_status"] == "OPEN"


@pytest.mark.no_auth_override
def test_summaries_and_pdf_generation(client: TestClient):
    admin_hdr = _auth_headers("admin_root", "ADMIN")
    exam_id = "TEST-REPORT-2026"

    # Create exam
    client.post(
        "/api/v1/exams",
        json={
            "exam_id": exam_id,
            "name": "Report & PDF Verification Exam",
            "exam_type": "THEORY_CIE",
            "semester": 7,
            "department": "Cyber Security",
            "date": "2026-11-23",
            "start_time": "10:00:00",
            "end_time": "11:30:00",
            "cutoff_minutes": 30,
            "subject_code": "22CY72",
        },
        headers=admin_hdr,
    )

    # Upload seating with 1 Present, 1 Absent
    csv_content = (
        "sl_no,usn,name,branch,room_no\n"
        "1,1DS23CY050,Attended Student,CY,ROOM-Z\n"
        "2,1DS23CY051,Absent Student,CY,ROOM-Z\n"
    )
    client.post(
        f"/api/v1/exams/{exam_id}/seating/upload",
        files={"file": ("seating.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
        headers=admin_hdr,
    )

    # Mark 1 present
    client.patch(
        f"/api/v1/exams/{exam_id}/rooms/ROOM-Z/mark",
        json={"marks": [{"usn": "1DS23CY050", "status": "PRESENT"}]},
        headers=admin_hdr,
    )

    # 1. Room-wise summary
    r_sum_res = client.get(f"/api/v1/exams/{exam_id}/summary/room-wise", headers=admin_hdr)
    assert r_sum_res.status_code == 200
    r_data = r_sum_res.json()
    assert len(r_data) == 1
    assert r_data[0]["room_no"] == "ROOM-Z"
    assert r_data[0]["total_students"] == 2
    assert r_data[0]["present_count"] == 1
    assert r_data[0]["absent_count"] == 1
    assert len(r_data[0]["absentees"]) == 1
    assert r_data[0]["absentees"][0]["usn"] == "1DS23CY051"

    # 2. Branch-wise summary
    b_sum_res = client.get(f"/api/v1/exams/{exam_id}/summary/branch-wise", headers=admin_hdr)
    assert b_sum_res.status_code == 200
    b_data = b_sum_res.json()
    cy_branch = next(b for b in b_data if b["branch"] == "CY")
    assert cy_branch["total_students"] == 2
    assert cy_branch["present_count"] == 1
    assert cy_branch["absent_count"] == 1
    assert cy_branch["attendance_percentage"] == 50.0

    # 3. Printable Form-B PDF (application/pdf)
    form_b_res = client.get(f"/api/v1/exams/{exam_id}/rooms/ROOM-Z/sign-sheet-pdf", headers=admin_hdr)
    assert form_b_res.status_code == 200
    assert form_b_res.headers["content-type"] == "application/pdf"
    assert form_b_res.content.startswith(b"%PDF")

    # 4. Consolidated Absentees Statement PDF (application/pdf)
    abs_pdf_res = client.get(f"/api/v1/exams/{exam_id}/absentees-pdf", headers=admin_hdr)
    assert abs_pdf_res.status_code == 200
    assert abs_pdf_res.headers["content-type"] == "application/pdf"
    assert abs_pdf_res.content.startswith(b"%PDF")


@pytest.mark.no_auth_override
def test_scan_form_b_ai_mocked(client: TestClient, monkeypatch):
    admin_hdr = _auth_headers("admin_root", "ADMIN")
    faculty_hdr = _auth_headers("faculty_cn", "FACULTY")
    exam_id = "TEST-AI-SCAN-2026"

    # Create exam
    client.post(
        "/api/v1/exams",
        json={
            "exam_id": exam_id,
            "name": "AI Vision Scan Exam",
            "exam_type": "THEORY_CIE",
            "date": "2026-11-24",
            "start_time": "10:00:00",
            "end_time": "11:30:00",
            "cutoff_minutes": 30,
            "subject_code": "22CY72",
        },
        headers=admin_hdr,
    )

    # Seating: 2 students
    csv_content = (
        "sl_no,usn,name,branch,room_no\n"
        "1,1DS23CY037,Nikhita Thupakula,CY,CDS-105\n"
        "2,1DS23CY040,Pragathi B S,CY,CDS-105\n"
    )
    client.post(
        f"/api/v1/exams/{exam_id}/seating/upload",
        files={"file": ("seating.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
        headers=admin_hdr,
    )

    # Assign faculty_cn
    client.post(
        f"/api/v1/exams/{exam_id}/rooms/CDS-105/assign",
        json={"room_no": "CDS-105", "invigilator_id": "faculty_cn"},
        headers=admin_hdr,
    )

    # Mock the Gemini vision extractor
    mock_scan_results = [
        {"sl_no": 1, "usn": "1DS23CY037", "name": "Nikhita Thupakula", "status": "PRESENT", "confidence": 0.99},
        {"sl_no": 2, "usn": "1DS23CY040", "name": "Pragathi B S", "status": "ABSENT", "confidence": 0.96},
    ]

    import app.routers.exams as exams_module
    monkeypatch.setattr(exams_module, "scan_form_b_image", lambda image_bytes: mock_scan_results)

    # Invigilator uploads photo of Form-B
    fake_img = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    scan_res = client.post(
        f"/api/v1/exams/{exam_id}/rooms/CDS-105/scan-photo",
        files={"file": ("form_b.png", io.BytesIO(fake_img), "image/png")},
        headers=faculty_hdr,
    )
    assert scan_res.status_code == 200, scan_res.text
    scan_data = scan_res.json()
    assert scan_data["matched_count"] == 2

    # Verify roster was updated with AI_SCAN source
    roster_res = client.get(f"/api/v1/exams/{exam_id}/rooms/CDS-105/roster", headers=faculty_hdr)
    assert roster_res.status_code == 200
    roster = roster_res.json()
    std1 = next(s for s in roster if s["usn"] == "1DS23CY037")
    std2 = next(s for s in roster if s["usn"] == "1DS23CY040")
    assert std1["status"] == "PRESENT"
    assert std1["marked_source"] == "AI_SCAN"
    assert std2["status"] == "ABSENT"


@pytest.mark.no_auth_override
def test_unassigned_invigilator_forbidden(client: TestClient):
    admin_hdr = _auth_headers("admin_root", "ADMIN")
    invig_a_hdr = _auth_headers("faculty_cn", "FACULTY")
    invig_b_hdr = _auth_headers("faculty_ds", "FACULTY")
    exam_id = "TEST-ISOLATION-2026"

    client.post(
        "/api/v1/exams",
        json={
            "exam_id": exam_id,
            "name": "Room Isolation Exam",
            "exam_type": "THEORY_CIE",
            "date": "2026-11-25",
            "start_time": "10:00:00",
            "end_time": "11:30:00",
            "cutoff_minutes": 30,
            "subject_code": "22CY73",
        },
        headers=admin_hdr,
    )

    client.post(
        f"/api/v1/exams/{exam_id}/seating/upload",
        files={"file": ("seating.csv", io.BytesIO(b"sl_no,usn,name,branch,room_no\n1,1DS23CY001,Test User,CY,ROOM-101\n"), "text/csv")},
        headers=admin_hdr,
    )

    client.post(
        f"/api/v1/exams/{exam_id}/rooms/ROOM-101/assign",
        json={"room_no": "ROOM-101", "invigilator_id": "faculty_cn"},
        headers=admin_hdr,
    )

    # Invigilator B tries to access Room 101 roster -> 403
    roster_res = client.get(f"/api/v1/exams/{exam_id}/rooms/ROOM-101/roster", headers=invig_b_hdr)
    assert roster_res.status_code == 403

    # Invigilator B tries to submit Room 101 -> 403
    submit_res = client.post(f"/api/v1/exams/{exam_id}/rooms/ROOM-101/submit", headers=invig_b_hdr)
    assert submit_res.status_code == 403

    # Invigilator A (assigned) accesses Room 101 roster -> 200
    roster_ok = client.get(f"/api/v1/exams/{exam_id}/rooms/ROOM-101/roster", headers=invig_a_hdr)
    assert roster_ok.status_code == 200


@pytest.mark.no_auth_override
def test_admin_override_validation(client: TestClient):
    admin_hdr = _auth_headers("admin_root", "ADMIN")
    faculty_hdr = _auth_headers("faculty_cn", "FACULTY")
    exam_id = "TEST-OVERRIDE-VAL"

    client.post(
        "/api/v1/exams",
        json={
            "exam_id": exam_id,
            "name": "Override Validation Exam",
            "exam_type": "THEORY_CIE",
            "date": "2026-11-25",
            "start_time": "10:00:00",
            "end_time": "11:30:00",
            "cutoff_minutes": 30,
            "subject_code": "22CY73",
        },
        headers=admin_hdr,
    )

    client.post(
        f"/api/v1/exams/{exam_id}/seating/upload",
        files={"file": ("seating.csv", io.BytesIO(b"sl_no,usn,name,branch,room_no\n1,1DS23CY001,Test User,CY,ROOM-202\n"), "text/csv")},
        headers=admin_hdr,
    )

    # Faculty cannot call admin-override -> 403
    fac_override = client.post(
        f"/api/v1/exams/{exam_id}/rooms/ROOM-202/admin-override",
        json={"reason": "Valid reason provided", "new_status": "OPEN"},
        headers=faculty_hdr,
    )
    assert fac_override.status_code == 403

    # Admin with short reason (<5 chars) -> 422
    bad_override = client.post(
        f"/api/v1/exams/{exam_id}/rooms/ROOM-202/admin-override",
        json={"reason": "no", "new_status": "OPEN"},
        headers=admin_hdr,
    )
    assert bad_override.status_code == 422

