"""Comprehensive test suite for RollCall AI Exam Hall & Form-B Control Module."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from app.auth.jwt import create_access_token
from app.main import app

# A genuinely valid 1x1 PNG: the scan-photo endpoint now rejects malformed
# image payloads before they reach the vision model.
VALID_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe"
    b"\x02\xfe\r\xefF\xb8\x00\x00\x00\x00IEND\xaeB`\x82"
)


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

    # Active exam currently running within cutoff window
    now_dt = datetime.now(timezone.utc)
    today_str = now_dt.strftime("%Y-%m-%d")
    start_str = (now_dt - timedelta(minutes=5)).strftime("%H:%M:%S")
    end_str = (now_dt + timedelta(minutes=90)).strftime("%H:%M:%S")

    client.post(
        "/api/v1/exams",
        json={
            "exam_id": exam_id,
            "name": "Locking Workflow Exam",
            "exam_type": "THEORY_CIE",
            "date": today_str,
            "start_time": start_str,
            "end_time": end_str,
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

    # A non-image payload is rejected before it reaches the vision model.
    bad_scan = client.post(
        f"/api/v1/exams/{exam_id}/rooms/CDS-105/scan-photo",
        files={"file": ("form_b.png", io.BytesIO(b"this is not an image"), "image/png")},
        headers=faculty_hdr,
    )
    assert bad_scan.status_code == 400, bad_scan.text

    # Invigilator uploads photo of Form-B
    fake_img = VALID_PNG
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


@pytest.mark.no_auth_override
def test_late_locked_cutoff_enforcement(client: TestClient):
    admin_hdr = _auth_headers("admin_root", "ADMIN")
    faculty_hdr = _auth_headers("faculty_cn", "FACULTY")
    exam_id = "TEST-LATE-LOCK"

    # Past exam (yesterday)
    client.post(
        "/api/v1/exams",
        json={
            "exam_id": exam_id,
            "name": "Past Cutoff Exam",
            "exam_type": "THEORY_CIE",
            "date": "2026-11-20",
            "start_time": "09:00:00",
            "end_time": "10:30:00",
            "cutoff_minutes": 30,
            "subject_code": "22CY74",
        },
        headers=admin_hdr,
    )

    client.post(
        f"/api/v1/exams/{exam_id}/seating/upload",
        files={"file": ("seating.csv", io.BytesIO(b"sl_no,usn,name,branch,room_no\n1,1DS23CY010,Late Student,CY,ROOM-LATE\n"), "text/csv")},
        headers=admin_hdr,
    )

    client.post(
        f"/api/v1/exams/{exam_id}/rooms/ROOM-LATE/assign",
        json={"room_no": "ROOM-LATE", "invigilator_id": "faculty_cn"},
        headers=admin_hdr,
    )

    # 1. Faculty checks room detail -> status is auto-marked LATE_LOCKED
    detail_res = client.get(f"/api/v1/exams/{exam_id}/rooms/ROOM-LATE", headers=faculty_hdr)
    assert detail_res.status_code == 200
    assert detail_res.json()["status"] == "LATE_LOCKED"
    assert detail_res.json()["cutoff_at"] is not None

    # 2. Invigilator tries to mark attendance -> 403 Forbidden
    mark_res = client.patch(
        f"/api/v1/exams/{exam_id}/rooms/ROOM-LATE/mark",
        json={"marks": [{"usn": "1DS23CY010", "status": "PRESENT"}]},
        headers=faculty_hdr,
    )
    assert mark_res.status_code == 403
    assert "LATE_LOCKED" in mark_res.json()["detail"]

    # 3. Invigilator tries to submit -> 403 Forbidden
    submit_res = client.post(f"/api/v1/exams/{exam_id}/rooms/ROOM-LATE/submit", headers=faculty_hdr)
    assert submit_res.status_code == 403
    assert "LATE_LOCKED" in submit_res.json()["detail"]

    # 4. Admin override allows reopening
    override_res = client.post(
        f"/api/v1/exams/{exam_id}/rooms/ROOM-LATE/admin-override",
        json={"reason": "Approved late submission due to network outage in block", "new_status": "OPEN"},
        headers=admin_hdr,
    )
    assert override_res.status_code == 200
    assert override_res.json()["room_status"] == "OPEN"

    # 5. Invigilator can now submit
    submit_ok = client.post(f"/api/v1/exams/{exam_id}/rooms/ROOM-LATE/submit", headers=faculty_hdr)
    assert submit_ok.status_code == 200
    assert submit_ok.json()["status"] == "SUBMITTED"

    # 6. Double submit returns already submitted
    submit_again = client.post(f"/api/v1/exams/{exam_id}/rooms/ROOM-LATE/submit", headers=faculty_hdr)
    assert submit_again.status_code == 200
    assert "already submitted" in submit_again.json()["message"]


@pytest.mark.no_auth_override
def test_room_detail_and_delete_exam_cascade(client: TestClient):
    admin_hdr = _auth_headers("admin_root", "ADMIN")
    faculty_hdr = _auth_headers("faculty_cn", "FACULTY")
    exam_id = "TEST-CASCADE-DEL"

    client.post(
        "/api/v1/exams",
        json={
            "exam_id": exam_id,
            "name": "Cascade Delete Exam",
            "exam_type": "THEORY_CIE",
            "date": "2026-11-27",
            "start_time": "10:00:00",
            "end_time": "11:30:00",
            "cutoff_minutes": 30,
            "subject_code": "22CY75",
        },
        headers=admin_hdr,
    )

    client.post(
        f"/api/v1/exams/{exam_id}/seating/upload",
        files={"file": ("seating.csv", io.BytesIO(b"sl_no,usn,name,branch,room_no\n1,1DS23CY020,Cascade Stud,CY,ROOM-CAS\n"), "text/csv")},
        headers=admin_hdr,
    )

    client.post(
        f"/api/v1/exams/{exam_id}/rooms/ROOM-CAS/assign",
        json={"room_no": "ROOM-CAS", "invigilator_id": "faculty_cn"},
        headers=admin_hdr,
    )

    # 1. Invigilator reads room detail
    detail_res = client.get(f"/api/v1/exams/{exam_id}/rooms/ROOM-CAS", headers=faculty_hdr)
    assert detail_res.status_code == 200
    data = detail_res.json()
    assert data["exam_id"] == exam_id
    assert data["exam_name"] == "Cascade Delete Exam"
    assert data["subject_code"] == "22CY75"

    # 2. Faculty cannot delete exam -> 403
    fac_del = client.delete(f"/api/v1/exams/{exam_id}", headers=faculty_hdr)
    assert fac_del.status_code == 403

    # 3. Admin deletes exam -> 200
    adm_del = client.delete(f"/api/v1/exams/{exam_id}", headers=admin_hdr)
    assert adm_del.status_code == 200

    # 4. Verifying exam is deleted
    assert client.get(f"/api/v1/exams/{exam_id}", headers=admin_hdr).status_code == 404
    assert client.get(f"/api/v1/exams/{exam_id}/rooms/ROOM-CAS", headers=admin_hdr).status_code == 404


@pytest.mark.no_auth_override
def test_csv_upload_validation_errors(client: TestClient):
    admin_hdr = _auth_headers("admin_root", "ADMIN")
    exam_id = "TEST-CSV-VAL"

    client.post(
        "/api/v1/exams",
        json={
            "exam_id": exam_id,
            "name": "CSV Validation Exam",
            "exam_type": "THEORY_CIE",
            "date": "2026-11-28",
            "start_time": "10:00:00",
            "end_time": "11:30:00",
            "cutoff_minutes": 30,
            "subject_code": "22CY76",
        },
        headers=admin_hdr,
    )

    # 1. Missing usn column -> 422
    bad_csv = b"name,room_no\nStudent,ROOM-1\n"
    res1 = client.post(
        f"/api/v1/exams/{exam_id}/seating/upload",
        files={"file": ("test.csv", io.BytesIO(bad_csv), "text/csv")},
        headers=admin_hdr,
    )
    assert res1.status_code == 422
    assert "usn" in res1.json()["detail"].lower()

    # 2. Missing room_no column -> 422
    bad_csv2 = b"usn,name\n1DS23CY001,Student\n"
    res2 = client.post(
        f"/api/v1/exams/{exam_id}/seating/upload",
        files={"file": ("test.csv", io.BytesIO(bad_csv2), "text/csv")},
        headers=admin_hdr,
    )
    assert res2.status_code == 422
    assert "room" in res2.json()["detail"].lower()

    # 3. Invalid exam_id -> 404
    res3 = client.post(
        "/api/v1/exams/NON-EXISTENT-EXAM/seating/upload",
        files={"file": ("test.csv", io.BytesIO(b"usn,name,room_no\n1DS23CY001,Student,R1\n"), "text/csv")},
        headers=admin_hdr,
    )
    assert res3.status_code == 404


@pytest.mark.no_auth_override
def test_exam_agent_tools_execution(client: TestClient):
    from app.agent.registry import tool_registry

    admin_hdr = _auth_headers("admin_root", "ADMIN")
    exam_id = "TEST-AGENT-EXAM"

    # 1. Create exam with 2 students in CDS 105
    client.post(
        "/api/v1/exams",
        json={
            "exam_id": exam_id,
            "name": "AI Agent Inspection Exam",
            "exam_type": "THEORY_CIE",
            "date": "2026-11-22",
            "start_time": "10:00:00",
            "end_time": "11:30:00",
            "cutoff_minutes": 30,
            "subject_code": "22CY77",
        },
        headers=admin_hdr,
    )

    client.post(
        f"/api/v1/exams/{exam_id}/seating/upload",
        files={"file": ("seating.csv", io.BytesIO(b"sl_no,usn,name,branch,room_no\n1,1DS23CY111,Present Person,CY,ROOM-AG\n2,1DS23CY112,Absent Person,CY,ROOM-AG\n"), "text/csv")},
        headers=admin_hdr,
    )

    client.patch(
        f"/api/v1/exams/{exam_id}/rooms/ROOM-AG/mark",
        json={"marks": [{"usn": "1DS23CY111", "status": "PRESENT"}]},
        headers=admin_hdr,
    )

    # 2. Test query_exam_status tool
    status_tool = tool_registry.get("query_exam_status")
    assert status_tool is not None
    status_out = status_tool.handler(exam_id=exam_id)
    assert status_out["status"] == "success"
    assert status_out["count"] >= 1
    found_ex = next(e for e in status_out["exams"] if e["exam_id"] == exam_id)
    assert found_ex["total_students"] == 2
    assert found_ex["present_count"] == 1
    assert found_ex["absent_count"] == 1

    # 3. Test query_exam_absentees tool
    abs_tool = tool_registry.get("query_exam_absentees")
    assert abs_tool is not None
    abs_out = abs_tool.handler(exam_id=exam_id)
    assert abs_out["status"] == "success"
    assert abs_out["total_absentees"] == 1
    assert abs_out["absentees"][0]["usn"] == "1DS23CY112"

    # 4. Test query_exam_branch_summary tool
    br_tool = tool_registry.get("query_exam_branch_summary")
    assert br_tool is not None
    br_out = br_tool.handler(exam_id=exam_id)
    assert br_out["status"] == "success"
    cy_br = next(b for b in br_out["branches"] if b["branch"] == "CY")
    assert cy_br["total"] == 2
    assert cy_br["present"] == 1
    assert cy_br["absent"] == 1
    assert cy_br["percentage"] == 50.0


def test_exam_form_b_multi_column_disambiguation_logic():
    """Verify build_exam_form_b_prompt properly embeds target disambiguation rules."""
    from app.services.exam_vision import build_exam_form_b_prompt, ExamScanResultList

    prompt = build_exam_form_b_prompt(
        target_subject_code="22CY741",
        target_date="2026-11-03",
        target_start_time="10:00:00",
        target_room_no="CDS-105",
        target_semester=7,
    )

    assert "22CY741" in prompt
    assert "03-11-2026" in prompt or "2026-11-03" in prompt
    assert "Forenoon / Morning (FN)" in prompt
    assert "CDS-105" in prompt
    assert "7" in prompt
    assert "No. of Students Present" in prompt
    assert "No. of Students Absent" in prompt

    # Verify ExamScanResultList behavior
    rows = [{"usn": "1DS23CY037", "status": "PRESENT"}]
    tally = {"students_present": 31, "students_absent": 1}
    res_list = ExamScanResultList(
        rows=rows,
        tally=tally,
        detected_columns=[{"column_index": 3, "subject_code": "22CY741"}],
        target_column_matched={"column_index": 3, "subject_code": "22CY741"},
    )
    assert len(res_list) == 1
    assert res_list[0]["usn"] == "1DS23CY037"
    assert res_list.tally["students_absent"] == 1
    assert res_list.target_column_matched["subject_code"] == "22CY741"


def test_agent_exam_form_b_detection_and_safe_routing(tmp_path):
    """Verify AttendanceAgent detects Form-B exam documents and routes them without classroom session_id errors."""
    from pathlib import Path
    from app.agent.legacy_agent import AttendanceAgent

    agent = AttendanceAgent(role="FACULTY", actor_role="FACULTY", actor_id="faculty_test")

    dummy_file = tmp_path / "exam_form_b_sample.png"
    dummy_file.write_bytes(b"dummy image bytes")

    # 1. Detection via user query or filename
    assert agent._is_exam_form_b_document(dummy_file, user_input="Process this Form-B attendance sheet") is True
    assert agent._is_exam_form_b_document(dummy_file, user_input="Continuous Internal Assessment Test-III") is True
    assert agent._is_exam_form_b_document(Path("test_lecture_attendance.csv"), user_input="Regular class attendance") is False

    # 2. Handler execution returns safe structured response without session_id errors
    resp = agent._handle_exam_form_b_file(
        file_path=dummy_file,
        request_id="req-test-form-b-1",
        user_input="Process this Form-B attendance sheet",
    )
    assert resp.success is True
    assert resp.needs_confirmation is False
    assert resp.data.get("is_exam_form_b") is True
    assert "Form-B" in resp.message
    assert "22CY741" in resp.message or "22CY72" in resp.message


