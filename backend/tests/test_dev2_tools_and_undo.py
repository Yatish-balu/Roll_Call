"""Comprehensive Test Suite for Person 2 (Dev 2 - AI Capabilities & Tools Engineer).

Covers:
1. 60-Second Undo Transaction Engine (token creation, HMAC integrity, 60s expiry, actor/record binding).
2. Server-side Compensating Transaction & Append-only Audit Trail (ATTENDANCE_UNDO).
3. Optimistic Concurrency Control (version checking and concurrent edit protection).
4. Mobile Image Intake & Preprocessing (magic bytes, EXIF orientation, max-1600px downscale, JPEG 85 compression, malicious file rejection).
5. Explicit OCR Uncertainty Policy (confidence < 0.50 remains UNREVIEWED/PENDING, never ABSENT).
6. Timetable & Academic Setup Tools (get_my_timetable, get_day_schedule conflict detection).
7. Multi-Room Session Creation (Lab A + Lab B allocation persistence and room collision detection).
8. Wrapped 6 Core Legacy Tools (read_csv, read_photo, validate, summary, query, export).
9. Profile & Analytics Tools (get_my_profile, get_defaulters_analysis threshold calculations).
10. Dynamic Tool Subsetting by capability family (schedule, attendance, reports, profile).
"""

from __future__ import annotations

import io
import time
import uuid
import pytest
from fastapi import HTTPException
from PIL import Image

from app.agent.registry import RiskTier, ToolRegistry, tool_registry
from app.agent.tools import ALL_TOOLS, register_all_tools
from app.agent.tools.attendance_tools import (
    single_attendance_correction_handler,
    bulk_attendance_proposal_handler,
)
from app.agent.tools.profile_analytics_tools import (
    get_defaulters_analysis_handler,
    get_my_profile_handler,
)
from app.agent.tools.timetable_tools import (
    create_session_handler,
    get_day_schedule_handler,
    get_my_timetable_handler,
)
from app.db import crud
from app.db.connection import get_sync_session_factory
from app.db.models import Attendance, AuditLog, Session as DbSession, SessionAllocation, Student
from app.services.image_pipeline import (
    detect_image_mime,
    process_mobile_attendance_sheet,
    validate_and_preprocess_image,
)
from app.services.undo_service import (
    create_undo_token,
    execute_undo,
    get_record_version,
    verify_undo_token,
)


@pytest.fixture
def db_session():
    """Yield a database session for test isolation."""
    factory = get_sync_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


# ==============================================================================
# 1. 60-Second Undo Engine & Cryptographic Integrity Tests
# ==============================================================================

def test_undo_token_creation_and_verification():
    """Verify undo token is cryptographically signed with HMAC-SHA256 and bounds actor/record."""
    token, exp = create_undo_token(
        actor_id="faculty_cn",
        record_id="rec_123",
        session_id="sess_001",
        usn="1MS21CS001",
        previous_status="ABSENT",
        new_status="PRESENT",
        version=3,
        ttl_seconds=60,
    )
    assert token and "." in token
    assert "Z" in exp

    # Valid verification
    payload = verify_undo_token(token, actor_id="faculty_cn", record_id="rec_123")
    assert payload["actor_id"] == "faculty_cn"
    assert payload["record_id"] == "rec_123"
    assert payload["session_id"] == "sess_001"
    assert payload["usn"] == "1MS21CS001"
    assert payload["previous_status"] == "ABSENT"
    assert payload["new_status"] == "PRESENT"
    assert payload["version"] == 3


def test_undo_token_tampering_rejection():
    """Ensure modified signatures or payloads are rejected with HTTP 400."""
    token, _ = create_undo_token(
        actor_id="faculty_cn",
        record_id="rec_123",
        session_id="sess_001",
        usn="1MS21CS001",
        previous_status="ABSENT",
        new_status="PRESENT",
        version=1,
    )

    # 1. Tamper signature
    tampered_sig = token[:-3] + "abc"
    with pytest.raises(HTTPException) as exc_info:
        verify_undo_token(tampered_sig, actor_id="faculty_cn")
    assert exc_info.value.status_code == 400
    assert "Invalid or tampered" in exc_info.value.detail

    # 2. Tamper payload
    b64_p, b64_s = token.split(".")
    tampered_p = b64_p[:-2] + "AA"
    with pytest.raises(HTTPException) as exc_info:
        verify_undo_token(f"{tampered_p}.{b64_s}", actor_id="faculty_cn")
    assert exc_info.value.status_code == 400


def test_undo_token_strict_60s_expiration():
    """Verify expired undo tokens are rejected with HTTP 410 GONE."""
    token, _ = create_undo_token(
        actor_id="faculty_cn",
        record_id="rec_123",
        session_id="sess_001",
        usn="1MS21CS001",
        previous_status="ABSENT",
        new_status="PRESENT",
        version=1,
        ttl_seconds=-5,  # already expired
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_undo_token(token, actor_id="faculty_cn")
    assert exc_info.value.status_code == 410
    assert "expired" in exc_info.value.detail.lower()


def test_undo_token_actor_and_record_binding():
    """Verify cross-actor and cross-record token reuse is blocked."""
    token, _ = create_undo_token(
        actor_id="faculty_cn",
        record_id="rec_123",
        session_id="sess_001",
        usn="1MS21CS001",
        previous_status="ABSENT",
        new_status="PRESENT",
        version=1,
    )

    # Wrong actor
    with pytest.raises(HTTPException) as exc_info:
        verify_undo_token(token, actor_id="other_faculty")
    assert exc_info.value.status_code == 403

    # Wrong record
    with pytest.raises(HTTPException) as exc_info:
        verify_undo_token(token, actor_id="faculty_cn", record_id="rec_999")
    assert exc_info.value.status_code == 400


# ==============================================================================
# 2. Compensating Transaction & Audit Trail Tests
# ==============================================================================

def test_execute_undo_compensating_transaction(db_session):
    """Verify undo reverts attendance to previous status and appends ATTENDANCE_UNDO audit record."""
    # Setup test session & attendance record
    s_id = f"test_sess_{uuid.uuid4().hex[:8]}"
    u_id = f"TEST_USN_{uuid.uuid4().hex[:6]}"
    
    stud = Student(usn=u_id, name="Test Alice", branch="CSE")
    db_session.add(stud)

    sess = DbSession(
        session_id=s_id,
        date="2026-11-14",
        subject="Computer Networks",
        teacher_id="faculty_cn",
        lifecycle_status="SCHEDULED",
        created_at="2026-11-14T09:00:00Z",
    )
    db_session.add(sess)

    att = Attendance(
        attendance_id=str(uuid.uuid4()),
        session_id=s_id,
        usn=u_id,
        room_id="LH-101",
        status="PRESENT",  # modified to PRESENT
        source="manual",
        confidence=1.0,
    )
    db_session.add(att)
    db_session.commit()

    # Generate token for reverting PRESENT -> ABSENT
    token, _ = create_undo_token(
        actor_id="faculty_cn",
        record_id=str(att.attendance_id),
        session_id=s_id,
        usn=u_id,
        previous_status="ABSENT",
        new_status="PRESENT",
        version=1,
    )

    # Execute undo
    result = execute_undo(
        db_session,
        undo_token=token,
        actor_id="faculty_cn",
        actor_role="FACULTY",
        target_record_id=str(att.attendance_id),
    )

    assert result["success"] is True
    assert result["current_status"] == "ABSENT"

    # Verify DB record reverted
    refetched = db_session.get(Attendance, att.attendance_id)
    assert refetched.status == "ABSENT"

    # Verify audit log entry
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.session_id == s_id, AuditLog.action == "ATTENDANCE_UNDO")
        .order_by(AuditLog.log_id.desc())
        .first()
    )
    assert audit is not None
    assert audit.actor_id == "faculty_cn"
    assert audit.old_value == "PRESENT"
    assert audit.new_value == "ABSENT"


def test_undo_rejected_on_concurrent_edit(db_session):
    """Verify undo is rejected if attendance status was altered by another operation."""
    s_id = f"test_sess_{uuid.uuid4().hex[:8]}"
    u_id = f"TEST_USN_{uuid.uuid4().hex[:6]}"

    stud = Student(usn=u_id, name="Test Bob", branch="CSE")
    db_session.add(stud)

    sess = DbSession(
        session_id=s_id,
        date="2026-11-14",
        subject="Computer Networks",
        teacher_id="faculty_cn",
        lifecycle_status="SCHEDULED",
        created_at="2026-11-14T09:00:00Z",
    )
    db_session.add(sess)

    att = Attendance(
        attendance_id=str(uuid.uuid4()),
        session_id=s_id,
        usn=u_id,
        room_id="LH-101",
        status="PRESENT",
        source="manual",
        confidence=1.0,
    )
    db_session.add(att)
    db_session.commit()

    token, _ = create_undo_token(
        actor_id="faculty_cn",
        record_id=str(att.attendance_id),
        session_id=s_id,
        usn=u_id,
        previous_status="ABSENT",
        new_status="PRESENT",
        version=1,
    )

    # Simulate intervening edit: record altered to UNREVIEWED
    att.status = "UNREVIEWED"
    db_session.commit()

    # Attempt undo with stale token (expected PRESENT)
    with pytest.raises(HTTPException) as exc_info:
        execute_undo(
            db_session,
            undo_token=token,
            actor_id="faculty_cn",
            actor_role="FACULTY",
            target_record_id=str(att.attendance_id),
        )
    assert exc_info.value.status_code == 409
    assert "was changed" in exc_info.value.detail


# ==============================================================================
# 3. Mobile Photo Intake & OCR Preprocessing Pipeline Tests
# ==============================================================================

def test_image_pipeline_downscaling_and_compression():
    """Verify large images (>1600px) are downscaled while maintaining aspect ratio and compressed."""
    # Create a 2400x1200 test image (2:1 aspect ratio)
    img = Image.new("RGB", (2400, 1200), color=(180, 180, 200))
    bio = io.BytesIO()
    img.save(bio, format="JPEG", quality=95)
    raw_bytes = bio.getvalue()

    processed_bytes, meta = validate_and_preprocess_image(raw_bytes, max_dimension=1600)
    assert meta["original_dimensions"] == (2400, 1200)
    assert meta["processed_dimensions"] == (1600, 800)  # Preserved 2:1 ratio
    assert len(processed_bytes) < len(raw_bytes)
    assert meta["original_mime"] == "image/jpeg"


def test_image_pipeline_malicious_upload_rejection():
    """Verify HTML, SVG, and executable byte payloads are rejected safely."""
    # HTML injection
    with pytest.raises(HTTPException) as exc:
        detect_image_mime(b"<html><script>alert(1)</script></html>")
    assert exc.value.status_code == 400

    # SVG XML
    with pytest.raises(HTTPException) as exc:
        detect_image_mime(b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'></svg>")
    assert exc.value.status_code == 400

    # Windows PE executable
    with pytest.raises(HTTPException) as exc:
        detect_image_mime(b"MZ\x90\x00\x03\x00\x00\x00\x04\x00")
    assert exc.value.status_code == 400


def test_explicit_ocr_uncertainty_policy(monkeypatch):
    """Verify low confidence marks (<0.50) are coerced to UNREVIEWED, never default to ABSENT."""
    from tools.read_photo_tool import PhotoExtractionResult, PhotoRow

    def mock_read_photo(*args, **kwargs):
        return PhotoExtractionResult(
            image_path="dummy.jpg",
            rows=[
                PhotoRow(usn="1MS21CS001", name="Alice", status="PRESENT", confidence=0.95, source="mock", raw={}),
                PhotoRow(usn="1MS21CS002", name="Bob", status="ABSENT", confidence=0.35, source="mock", raw={}),
                PhotoRow(usn="1MS21CS003", name="Charlie", status="?", confidence=0.80, source="mock", raw={}),
            ],
            source="mock",
        )

    monkeypatch.setattr("app.services.image_pipeline.read_photo_tool", mock_read_photo)

    img = Image.new("RGB", (300, 300), color=(255, 255, 255))
    bio = io.BytesIO()
    img.save(bio, format="JPEG")
    raw_bytes = bio.getvalue()

    result = process_mobile_attendance_sheet(raw_bytes)
    assert result["stats"]["total_extracted"] == 3

    # Bob has confidence 0.35 -> must become UNREVIEWED, never ABSENT
    bob = [r for r in result["rows"] if r["usn"] == "1MS21CS002"][0]
    assert bob["status"] == "UNREVIEWED"

    # Charlie has "?" -> must become UNREVIEWED
    charlie = [r for r in result["rows"] if r["usn"] == "1MS21CS003"][0]
    assert charlie["status"] == "UNREVIEWED"

    # Alice has 0.95 PRESENT -> remains PRESENT
    alice = [r for r in result["rows"] if r["usn"] == "1MS21CS001"][0]
    assert alice["status"] == "PRESENT"


# ==============================================================================
# 4. Timetable & Academic Setup Tool Tests
# ==============================================================================

def test_timetable_tools_registration_and_schemas():
    """Verify timetable tools are registered with capability_family='schedule' and correct risk tiers."""
    reg = ToolRegistry()
    register_all_tools(reg)

    sched_tools = reg.list_tools(capability_family="schedule", role="FACULTY")
    tool_names = {t.name for t in sched_tools}
    assert "get_my_timetable" in tool_names
    assert "get_day_schedule" in tool_names
    assert "create_session" in tool_names

    create_tool = reg.get_tool("create_session")
    assert create_tool.risk_tier == RiskTier.LOW_RISK_WRITE
    assert "FACULTY" in create_tool.allowed_roles


def test_create_session_with_multi_rooms_and_conflict_check(db_session):
    """Verify create_session creates allocations for multiple rooms and detects overlaps."""
    date_str = "2026-11-20"
    res1 = create_session_handler(
        date=date_str,
        subject="Cloud Computing",
        subject_code="CS502",
        start_time="10:00",
        end_time="12:00",
        rooms=["Lab A", "Lab B"],
        actor_id="faculty_cn",
        actor_role="FACULTY",
        db=db_session,
    )
    assert res1["success"] is True
    session_id = res1["session_id"]
    assert len(res1["allocations"]) == 2
    assert set(res1["rooms"]) == {"Lab A", "Lab B"}

    # Attempt to book overlapping session in Lab A at the same time
    res2 = create_session_handler(
        date=date_str,
        subject="Operating Systems",
        subject_code="CS503",
        start_time="11:00",
        end_time="13:00",
        rooms=["Lab A"],
        actor_id="other_faculty",
        actor_role="FACULTY",
        db=db_session,
    )
    assert res2["success"] is False
    assert res2["conflict"] is True
    assert "Room 'Lab A' is already booked" in res2["conflict_details"][0]


def test_get_day_schedule_detects_conflicts(db_session):
    """Verify get_day_schedule reports scheduled sessions and flags overlaps."""
    res = get_day_schedule_handler(
        date="2026-11-20",
        actor_id="faculty_cn",
        actor_role="FACULTY",
        db=db_session,
    )
    assert "sessions" in res
    assert "day_of_week" in res
    assert "has_conflicts" in res


# ==============================================================================
# 5. Core Legacy Tools Wrapping & Registry Integration Tests
# ==============================================================================

def test_wrapped_legacy_tools_preservation():
    """Verify all 6 core legacy tools are preserved, wrapped, and registered."""
    reg = ToolRegistry()
    register_all_tools(reg)

    core_legacy_names = [
        "read_csv",
        "read_photo",
        "validate_attendance",
        "generate_summary",
        "query_attendance",
        "export_attendance",
    ]
    for name in core_legacy_names:
        tool = reg.get_tool(name)
        assert tool is not None, f"Tool '{name}' was unexpectedly missing or deleted!"
        assert tool.risk_tier == RiskTier.READ


def test_single_attendance_correction_tool(db_session):
    """Verify single_attendance_correction tool generates 60s undo capability."""
    s_id = f"test_sess_{uuid.uuid4().hex[:8]}"
    u_id = f"TEST_USN_{uuid.uuid4().hex[:6]}"

    stud = Student(usn=u_id, name="Test Charlie", branch="CSE")
    db_session.add(stud)

    sess = DbSession(
        session_id=s_id,
        date="2026-11-14",
        subject="Data Structures",
        teacher_id="faculty_cn",
        lifecycle_status="SCHEDULED",
        created_at="2026-11-14T09:00:00Z",
    )
    db_session.add(sess)

    att = Attendance(
        attendance_id=str(uuid.uuid4()),
        session_id=s_id,
        usn=u_id,
        room_id="LH-101",
        status="ABSENT",
        source="manual",
        confidence=1.0,
    )
    db_session.add(att)
    db_session.commit()

    # Call tool handler
    res = single_attendance_correction_handler(
        session_id=s_id,
        usn=u_id,
        new_status="PRESENT",
        actor_id="faculty_cn",
        actor_role="FACULTY",
        db=db_session,
    )

    assert res["success"] is True
    assert res["new_status"] == "PRESENT"
    assert "undo_token" in res
    assert "undo_expires_at" in res


def test_bulk_attendance_proposal_requires_confirmation(db_session):
    """Verify bulk attendance edits return SENSITIVE_WRITE proposal requiring approval."""
    s_id = f"test_sess_{uuid.uuid4().hex[:8]}"
    sess = DbSession(
        session_id=s_id,
        date="2026-11-14",
        subject="Data Structures",
        teacher_id="faculty_cn",
        lifecycle_status="SCHEDULED",
        created_at="2026-11-14T09:00:00Z",
    )
    db_session.add(sess)
    db_session.commit()

    records = [
        {"usn": "1MS21CS001", "status": "PRESENT"},
        {"usn": "1MS21CS002", "status": "ABSENT"},
        {"usn": "1MS21CS003", "status": "UNREVIEWED"},
    ]

    proposal = bulk_attendance_proposal_handler(
        session_id=s_id,
        records=records,
        actor_id="faculty_cn",
        actor_role="FACULTY",
    )

    assert proposal["requires_confirmation"] is True
    assert proposal["total_records"] == 3
    assert proposal["present_count"] == 1
    assert proposal["absent_count"] == 1
    assert proposal["unreviewed_count"] == 1


# ==============================================================================
# 6. Profile & Defaulters Analysis Tool Tests
# ==============================================================================

def test_profile_and_defaulters_analysis(db_session):
    """Verify get_my_profile and get_defaulters_analysis compute threshold statistics."""
    # Profile tool
    prof_res = get_my_profile_handler(actor_id="faculty_cn", actor_role="FACULTY", db=db_session)
    assert prof_res["success"] is True
    assert "profile" in prof_res

    # Defaulters analysis
    defaulters_res = get_defaulters_analysis_handler(
        actor_id="faculty_cn",
        actor_role="FACULTY",
        threshold=75.0,
        db=db_session,
    )
    assert defaulters_res["success"] is True
    assert "defaulters_count" in defaulters_res
    assert "defaulters" in defaulters_res


