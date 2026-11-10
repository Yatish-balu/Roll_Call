"""Unit tests for RollCall Pydantic v2 schemas.

Verifies:
1. Field validation, whitespace stripping, and constraints.
2. Canonical 4 attendance states (PRESENT, ABSENT, PENDING, UNREVIEWED).
3. Critical rule: PENDING and UNREVIEWED are never coerced to ABSENT.
4. Confidence bounds (0.0 to 1.0).
5. ISO calendar date validation.
6. ORM attribute mapping (from_attributes=True).
7. Bulk payload validations.
8. Analytics and Agent schemas.
"""

import pytest
from pydantic import ValidationError

from app.schemas.student import (
    StudentCreate,
    StudentUpdate,
    StudentResponse,
    StudentPageResponse,
    StudentBulkCreate,
)
from app.schemas.room import (
    RoomCreate,
    RoomUpdate,
    RoomResponse,
    RoomPageResponse,
    RoomBulkCreate,
)
from app.schemas.session import (
    SessionCreate,
    SessionUpdate,
    SessionResponse,
    SessionPageResponse,
    SessionBulkCreate,
)
from app.schemas.attendance import (
    AttendanceCreate,
    AttendanceUpdate,
    AttendanceResponse,
    AttendanceBulkCreate,
    ReconcileRequest,
    BulkReconcileRequest,
)
from app.schemas.analytics import (
    RoomWiseSummary,
    BranchWiseSummary,
    OverallSummary,
    SummaryReportResponse,
)
from app.schemas.agent import (
    AgentRequest,
    ChatQueryRequest,
    ConfirmationRequestSchema,
    AgentResponseSchema,
    ToolCallLogSchema,
)
from app.db.models import Student, Room, Session, Attendance


# ============================================================================
# 1. Student Schema Tests
# ============================================================================

def test_student_create_valid():
    s = StudentCreate(usn="1ms21cs001", name=" John Doe ", branch=" cse ")
    assert s.usn == "1MS21CS001"  # Normalized to uppercase and stripped
    assert s.name == "John Doe"
    assert s.branch == "cse"


def test_student_create_invalid():
    with pytest.raises(ValidationError):
        StudentCreate(usn="", name="John", branch="CSE")
    with pytest.raises(ValidationError):
        StudentCreate(usn="1MS21CS001", name="   ", branch="CSE")
    with pytest.raises(ValidationError):
        StudentCreate(usn="1MS21CS001", name="John", branch="")


def test_student_update_valid_and_invalid():
    u = StudentUpdate(name="Jane Doe", branch=None)
    assert u.name == "Jane Doe"
    assert u.branch is None

    with pytest.raises(ValidationError):
        StudentUpdate(name="   ")


def test_student_response_from_orm():
    orm_student = Student(usn="1MS21CS099", name="Alice Smith", branch="ISE")
    resp = StudentResponse.model_validate(orm_student)
    assert resp.usn == "1MS21CS099"
    assert resp.name == "Alice Smith"
    assert resp.branch == "ISE"


def test_student_bulk_create():
    bulk = StudentBulkCreate(
        students=[
            StudentCreate(usn="1MS21CS001", name="Alice", branch="CSE"),
            StudentCreate(usn="1MS21CS002", name="Bob", branch="ECE"),
        ]
    )
    assert len(bulk.students) == 2

    with pytest.raises(ValidationError):
        StudentBulkCreate(students=[])


# ============================================================================
# 2. Room Schema Tests
# ============================================================================

def test_room_create_valid():
    r = RoomCreate(room_id="  lh-101  ", name="  Lecture Hall 101  ")
    assert r.room_id == "lh-101"
    assert r.name == "Lecture Hall 101"


def test_room_create_invalid():
    with pytest.raises(ValidationError):
        RoomCreate(room_id="", name="Room A")
    with pytest.raises(ValidationError):
        RoomCreate(room_id="R-1", name="  ")


def test_room_response_from_orm():
    orm_room = Room(room_id="AUD-01", name="Main Auditorium")
    resp = RoomResponse.model_validate(orm_room)
    assert resp.room_id == "AUD-01"
    assert resp.name == "Main Auditorium"


def test_room_bulk_create():
    bulk = RoomBulkCreate(
        rooms=[
            RoomCreate(room_id="R1", name="Room 1"),
            RoomCreate(room_id="R2", name="Room 2"),
        ]
    )
    assert len(bulk.rooms) == 2

    with pytest.raises(ValidationError):
        RoomBulkCreate(rooms=[])


# ============================================================================
# 3. Session Schema Tests
# ============================================================================

def test_session_create_valid():
    s = SessionCreate(session_id="SESS-001", date="2026-03-15", subject="Computer Networks")
    assert s.session_id == "SESS-001"
    assert s.date == "2026-03-15"
    assert s.subject == "Computer Networks"


def test_session_create_invalid_date():
    # Not ISO format
    with pytest.raises(ValidationError):
        SessionCreate(session_id="SESS-001", date="15-03-2026", subject="Math")
    # Invalid calendar day
    with pytest.raises(ValidationError):
        SessionCreate(session_id="SESS-001", date="2026-02-30", subject="Math")
    # Invalid calendar month
    with pytest.raises(ValidationError):
        SessionCreate(session_id="SESS-001", date="2026-13-01", subject="Math")


def test_session_response_from_orm():
    orm_sess = Session(session_id="S10", date="2026-01-10", subject="Operating Systems")
    resp = SessionResponse.model_validate(orm_sess)
    assert resp.session_id == "S10"
    assert resp.date == "2026-01-10"
    assert resp.subject == "Operating Systems"


def test_session_bulk_create():
    bulk = SessionBulkCreate(
        sessions=[
            SessionCreate(session_id="S1", date="2026-01-01", subject="Physics"),
            SessionCreate(session_id="S2", date="2026-01-02", subject="Chemistry"),
        ]
    )
    assert len(bulk.sessions) == 2

    with pytest.raises(ValidationError):
        SessionBulkCreate(sessions=[])


# ============================================================================
# 4. Attendance Schema Tests (Canonical 4 States & Confidence)
# ============================================================================

@pytest.mark.parametrize("status", ["PRESENT", "ABSENT", "PENDING", "UNREVIEWED"])
def test_attendance_create_all_four_canonical_states(status):
    """Verify all 4 states are accepted and never coerced."""
    att = AttendanceCreate(
        session_id="S1",
        usn="1MS21CS001",
        room_id="LH-101",
        status=status,
        source="csv",
        confidence=0.95,
    )
    assert att.status == status


@pytest.mark.parametrize("status_input, expected_status", [
    ("present", "PRESENT"),
    ("absent", "ABSENT"),
    ("pending", "PENDING"),
    ("unreviewed", "UNREVIEWED"),
    ("  PRESENT  ", "PRESENT"),
    ("  pending  ", "PENDING"),
])
def test_attendance_status_normalization(status_input, expected_status):
    """Verify case normalization preserves PENDING and UNREVIEWED distinctly."""
    att = AttendanceCreate(
        session_id="S1",
        usn="1MS21CS001",
        room_id="LH-101",
        status=status_input,
    )
    assert att.status == expected_status
    # Explicitly ensure pending is NEVER absent
    if expected_status in ("PENDING", "UNREVIEWED"):
        assert att.status != "ABSENT"


def test_attendance_rejects_invalid_status():
    """Verify non-canonical statuses are strictly rejected."""
    for bad_status in ["EXCUSED", "LATE", "HALF_DAY", "UNKNOWN", ""]:
        with pytest.raises(ValidationError):
            AttendanceCreate(
                session_id="S1",
                usn="1MS21CS001",
                room_id="LH-101",
                status=bad_status,
            )


def test_attendance_confidence_bounds():
    # Valid boundaries
    a0 = AttendanceCreate(session_id="S1", usn="1MS21CS001", room_id="LH-101", status="PRESENT", confidence=0.0)
    assert a0.confidence == 0.0

    a1 = AttendanceCreate(session_id="S1", usn="1MS21CS001", room_id="LH-101", status="PRESENT", confidence=1.0)
    assert a1.confidence == 1.0

    # Invalid boundaries
    with pytest.raises(ValidationError):
        AttendanceCreate(session_id="S1", usn="1MS21CS001", room_id="LH-101", status="PRESENT", confidence=-0.01)

    with pytest.raises(ValidationError):
        AttendanceCreate(session_id="S1", usn="1MS21CS001", room_id="LH-101", status="PRESENT", confidence=1.05)


def test_attendance_response_from_orm():
    orm_att = Attendance(
        session_id="S1",
        usn="1MS21CS001",
        room_id="LH-101",
        status="PENDING",
        source="photo",
        confidence=0.75,
    )
    resp = AttendanceResponse.model_validate(orm_att)
    assert resp.session_id == "S1"
    assert resp.usn == "1MS21CS001"
    assert resp.room_id == "LH-101"
    assert resp.status == "PENDING"
    assert resp.source == "photo"
    assert resp.confidence == 0.75


def test_reconcile_request():
    rec = ReconcileRequest(
        session_id="S1",
        usn="1MS21CS001",
        resolved_status="PRESENT",
        reason="Verified manually against physical sheet",
        reconciled_by="teacher",
    )
    assert rec.resolved_status == "PRESENT"
    assert rec.reconciled_by == "teacher"
    assert rec.confidence == 1.0

    # Bulk reconcile
    bulk_rec = BulkReconcileRequest(resolutions=[rec])
    assert len(bulk_rec.resolutions) == 1

    # Invalid status in reconcile
    with pytest.raises(ValidationError):
        ReconcileRequest(
            session_id="S1",
            usn="1MS21CS001",
            resolved_status="INVALID_STATUS",
        )


# ============================================================================
# 5. Analytics Schema Tests
# ============================================================================

def test_analytics_schemas():
    overall = OverallSummary(
        present=80,
        absent=20,
        pending=5,
        unreviewed=3,
        unresolved=8,
        confirmed=100,
        total=108,
        percentage=80.0,
        confirmed_percentage=80.0,
        unresolved_by_status={"pending": 5, "unreviewed": 3},
    )
    assert overall.total == 108
    assert overall.confirmed == 100

    room = RoomWiseSummary(
        room_id="LH-101",
        present=40,
        absent=10,
        pending=2,
        unreviewed=1,
        unresolved=3,
        confirmed=50,
        total=53,
        percentage=80.0,
    )
    assert room.room_id == "LH-101"

    branch = BranchWiseSummary(
        branch="CSE",
        present=50,
        absent=10,
        pending=0,
        unreviewed=0,
        unresolved=0,
        confirmed=60,
        total=60,
        percentage=83.33,
    )
    assert branch.branch == "CSE"

    report = SummaryReportResponse(
        room_wise=[room],
        branch_wise=[branch],
        overall=overall,
        session_id="S1",
        date="2026-03-15",
    )
    assert len(report.room_wise) == 1
    assert report.session_id == "S1"


# ============================================================================
# 6. Agent Schema Tests
# ============================================================================

def test_agent_schemas():
    req = AgentRequest(
        prompt="Process attendance CSV for session 1",
        file_path="uploads/att.csv",
        session_id="S1",
    )
    assert req.file_path == "uploads/att.csv"

    chat_req = ChatQueryRequest(query="Who was absent in Room 101?")
    assert chat_req.query == "Who was absent in Room 101?"

    conf = ConfirmationRequestSchema(
        needed=True,
        affected_rows=[{"usn": "1MS21CS001", "confidence": 0.65}],
        issues=["Low confidence score: 0.65"],
        question="Should USN 1MS21CS001 be marked PRESENT?",
    )
    assert conf.needed is True
    assert len(conf.affected_rows) == 1

    tool_log = ToolCallLogSchema(
        log_id="uuid-1",
        request_id="req-1",
        timestamp="2026-03-15T10:00:00Z",
        tool_name="validate_tool",
        arguments={"count": 50},
        success=True,
        result_summary="All 50 records valid",
        duration_seconds=0.045,
    )
    assert tool_log.success is True

    agent_resp = AgentResponseSchema(
        request_id="req-1",
        message="Attendance validated successfully.",
        success=True,
        needs_confirmation=False,
        confirmation_request=None,
        tool_calls=[tool_log.model_dump()],
    )
    assert agent_resp.success is True
    assert len(agent_resp.tool_calls) == 1


def test_page_schemas():
    # StudentPageResponse
    stu_page = StudentPageResponse(
        items=[StudentResponse(usn="1MS21CS001", name="Alice", branch="CSE")],
        total=1,
        limit=50,
        offset=0,
    )
    assert stu_page.total == 1
    assert stu_page.limit == 50
    assert len(stu_page.items) == 1

    # RoomPageResponse
    room_page = RoomPageResponse(
        items=[RoomResponse(room_id="LH-101", name="Lecture Hall 101")],
        total=1,
        limit=20,
        offset=0,
    )
    assert room_page.total == 1
    assert room_page.limit == 20

    # SessionPageResponse
    sess_page = SessionPageResponse(
        items=[SessionResponse(session_id="S1", date="2026-03-15", subject="ML")],
        total=1,
        limit=10,
        offset=0,
    )
    assert sess_page.total == 1
    assert sess_page.limit == 10

    # Validation errors on limit/offset bounds
    with pytest.raises(ValidationError):
        StudentPageResponse(items=[], total=0, limit=0, offset=0)  # limit < 1

    with pytest.raises(ValidationError):
        StudentPageResponse(items=[], total=0, limit=201, offset=0)  # limit > 200

    with pytest.raises(ValidationError):
        StudentPageResponse(items=[], total=0, limit=50, offset=-1)  # offset < 0


