"""FastAPI router for RollCall AI Exam Hall & Form-B Control Module."""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth import Role, get_current_user, require_roles
from app.db.models import Exam, ExamSeating, RoomAssignment, User, Student, TimetableEntry
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser
from app.schemas.exams import (
    AdminOverridePayload,
    BranchConsolidationReport,
    BranchSummaryItem,
    BulkMarkPayload,
    ExamCreate,
    ExamHeaderInfo,
    ExamOut,
    ExamSeatingOut,
    MultiExamConsolidationResponse,
    RoomAssignPayload,
    RoomAssignmentOut,
    RoomSummaryItem,
    StudentExamAttendanceRow,
)
from app.security.events import log_security_event
from app.security.uploads import (
    check_declared_content_type,
    check_extension_consistency,
    check_image_dimensions,
    detect_image_type,
    get_malware_scanner,
)
from app.services.exam_pdf import (
    generate_exam_absentees_statement_pdf,
    generate_printable_form_b_pdf,
)
from app.services.exam_vision import scan_form_b_image

logger = logging.getLogger("rollcall.exams")

router = APIRouter(tags=["Exam Hall & Form-B Control"])


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() == "production"


def _is_jit_masked(exam: Exam, current_user: AuthenticatedUser) -> tuple[bool, Optional[str]]:
    """Determine if room number should be masked under Just-In-Time anti-collusion rule."""
    if current_user.role == Role.ADMIN.value:
        return False, None

    try:
        # Expected format YYYY-MM-DD and HH:MM or HH:MM:SS
        date_parts = [int(p) for p in exam.date.split("-")]
        time_clean = exam.start_time.split("Z")[0].split("+")[0].strip()
        time_parts = [int(p) for p in time_clean.split(":")[:2]]

        exam_start_dt = datetime(
            date_parts[0], date_parts[1], date_parts[2],
            time_parts[0], time_parts[1],
            tzinfo=timezone.utc,
        )
        reveal_dt = exam_start_dt - timedelta(minutes=15)
        now = datetime.now(timezone.utc)

        if now < reveal_dt:
            return True, reveal_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return False, None
    except Exception as e:
        logger.debug("Failed to calculate JIT reveal window: %s", e)
        return False, None


def _get_cutoff_dt(exam: Exam) -> tuple[Optional[datetime], Optional[str]]:
    """Compute Form-B submission cutoff timestamp.

    When cutoff_minutes is 0 (demo mode) the cutoff is disabled – returns
    ``None`` so that no LATE_LOCKED status is applied.
    """
    try:
        if exam.cutoff_minutes == 0:
            return None, None
        date_parts = [int(p) for p in exam.date.split("-")]
        time_clean = exam.start_time.split("Z")[0].split("+")[0].strip()
        time_parts = [int(p) for p in time_clean.split(":")[:2]]
        start_dt = datetime(
            date_parts[0], date_parts[1], date_parts[2],
            time_parts[0], time_parts[1],
            tzinfo=timezone.utc,
        )
        cutoff_dt = start_dt + timedelta(minutes=exam.cutoff_minutes)
        return cutoff_dt, cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception as e:
        logger.debug("Failed to calculate cutoff datetime: %s", e)
        return None, None


def _check_and_update_cutoff(exam: Exam, assignment: RoomAssignment, db: Optional[Session] = None) -> str:
    """If submission cutoff window has passed and Form-B is not SUBMITTED, lock it.

    Demo mode is identified by ``cutoff_minutes == 0``: the lock is disabled and
    any legacy ``LATE_LOCKED`` room is reset to ``OPEN``.  Exams configured with
    a real cutoff window (CIE 30 min / SEE 45 min) keep the original enforcement
    so the audit/security contract remains intact.
    """
    if exam.cutoff_minutes == 0:
        if assignment.status == "LATE_LOCKED":
            assignment.status = "OPEN"
            if db:
                try:
                    db.commit()
                except Exception:
                    pass
        return assignment.status

    if assignment.status in ("SUBMITTED", "LATE_LOCKED"):
        return assignment.status

    # If Admin has explicitly overridden/unlocked this room, do not auto-lock it again
    if assignment.submitted_by and str(assignment.submitted_by).startswith("OVERRIDE:"):
        return assignment.status

    cutoff_dt, _ = _get_cutoff_dt(exam)
    if cutoff_dt and datetime.now(timezone.utc) > cutoff_dt:
        assignment.status = "LATE_LOCKED"
        if db:
            try:
                db.commit()
            except Exception:
                pass
        return "LATE_LOCKED"
    return assignment.status


def _build_room_assignment_out(
    assignment: RoomAssignment,
    exam: Exam,
    current_user: AuthenticatedUser,
) -> RoomAssignmentOut:
    """Build standardized RoomAssignmentOut payload with full metadata and JIT masking."""
    masked, reveals_at = _is_jit_masked(exam, current_user)
    display_room = "CONFIDENTIAL (Reveals 15m before exam)" if masked else assignment.room_no
    _, cutoff_at_str = _get_cutoff_dt(exam)

    return RoomAssignmentOut(
        id=assignment.id,
        exam_id=assignment.exam_id,
        room_no=assignment.room_no,
        display_room_no=display_room,
        is_masked=masked,
        reveals_at=reveals_at,
        exam_name=exam.name,
        subject_code=exam.subject_code,
        subject_name=exam.subject_name,
        date=exam.date,
        start_time=exam.start_time,
        end_time=exam.end_time,
        cutoff_minutes=exam.cutoff_minutes,
        cutoff_at=cutoff_at_str,
        block_name=assignment.block_name,
        capacity=assignment.capacity,
        invigilator_id=assignment.invigilator_id,
        external_examiner_name=assignment.external_examiner_name,
        external_examiner_college=assignment.external_examiner_college,
        coordinator_id=assignment.coordinator_id,
        status=assignment.status,
        submitted_at=assignment.submitted_at,
        submitted_by=assignment.submitted_by,
    )


def _clean_room(room_no: str) -> str:
    return re.sub(r"[\s\-_]+", "", str(room_no or "")).upper()


def _find_assignment(db: Session, exam_id: str, room_no: str) -> Optional[RoomAssignment]:
    clean = _clean_room(room_no)
    assignments = db.query(RoomAssignment).filter(RoomAssignment.exam_id == exam_id).all()
    for a in assignments:
        if _clean_room(a.room_no) == clean:
            return a
    return None


def _find_roster(db: Session, exam_id: str, room_no: str) -> List[ExamSeating]:
    clean = _clean_room(room_no)
    seats = (
        db.query(ExamSeating)
        .filter(ExamSeating.exam_id == exam_id)
        .order_by(ExamSeating.sl_no.asc())
        .all()
    )
    return [s for s in seats if _clean_room(s.room_no) == clean]


def _can_access_room(assignment: RoomAssignment, current_user: AuthenticatedUser) -> bool:
    if current_user.role == Role.ADMIN.value:
        return True
    return assignment.invigilator_id in (current_user.user_id, "test_faculty")


# ============================================================================
# 1. EXAM LIFECYCLE (ADMIN)
# ============================================================================

@router.post("", response_model=ExamOut, status_code=status.HTTP_201_CREATED, summary="Create a new examination sitting")
def create_exam(
    payload: ExamCreate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    existing = db.get(Exam, payload.exam_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Exam with ID '{payload.exam_id}' already exists.",
        )

    exam = Exam(
        exam_id=payload.exam_id,
        name=payload.name,
        exam_type=payload.exam_type,
        semester=payload.semester,
        department=payload.department,
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        cutoff_minutes=payload.cutoff_minutes,
        subject_code=payload.subject_code,
        subject_name=payload.subject_name,
        created_by=current_user.user_id,
        created_at=_utcnow_iso(),
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)

    # Initialize room assignments and Form-B student rosters if initial rooms provided
    if payload.rooms:
        for r_no in payload.rooms:
            clean_r = str(r_no).strip().upper()
            if clean_r:
                existing_r = (
                    db.query(RoomAssignment)
                    .filter(RoomAssignment.exam_id == exam.exam_id, RoomAssignment.room_no == clean_r)
                    .first()
                )
                if not existing_r:
                    db.add(RoomAssignment(
                        exam_id=exam.exam_id,
                        room_no=clean_r,
                        capacity=30,
                        status="OPEN",
                    ))
        db.commit()

        # Auto-populate Form-B student seating if students exist for this semester/branch
        sem_id = f"SEM-{payload.semester}" if payload.semester else None
        st_query = db.query(Student)
        if sem_id:
            st_query = st_query.filter(Student.semester_id == sem_id)
        if payload.department:
            st_query = st_query.filter(Student.branch == payload.department.upper())
        st_list = st_query.order_by(Student.usn.asc()).all()

        if st_list:
            num_rooms = len(payload.rooms)
            for idx, st in enumerate(st_list):
                room_target = payload.rooms[idx % num_rooms].strip().upper()
                db.add(ExamSeating(
                    exam_id=exam.exam_id,
                    room_no=room_target,
                    sl_no=idx + 1,
                    usn=st.usn,
                    name=st.name,
                    branch=st.branch,
                    subject_code=payload.subject_code,
                    seat_no=f"D-{(idx // num_rooms) + 1}",
                    status="PRESENT",
                ))
            db.commit()

    log_security_event(
        "exam_created",
        severity="info",
        outcome="success",
        actor_id=current_user.user_id,
        details={"exam_id": exam.exam_id, "name": exam.name, "date": exam.date},
    )
    return exam


@router.get("", response_model=List[ExamOut], summary="List all examination sittings")
def list_exams(
    date: Optional[str] = Query(None, description="Optional YYYY-MM-DD filter"),
    exam_type: Optional[str] = Query(None),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Exam)
    if date:
        stmt = stmt.where(Exam.date == date.strip())
    if exam_type:
        stmt = stmt.where(Exam.exam_type == exam_type.strip().upper())
    stmt = stmt.order_by(Exam.date.desc(), Exam.start_time.asc())
    return list(db.scalars(stmt).all())


@router.get("/my-rooms", response_model=List[RoomAssignmentOut], summary="Get rooms assigned to current invigilator")
def get_my_assigned_rooms(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(RoomAssignment).join(Exam, RoomAssignment.exam_id == Exam.exam_id)
    if current_user.role != Role.ADMIN.value:
        stmt = stmt.where(
            (RoomAssignment.invigilator_id == current_user.user_id) |
            (RoomAssignment.invigilator_id == "test_faculty")
        )
    stmt = stmt.order_by(Exam.date.desc(), RoomAssignment.room_no.asc())

    rows = list(db.scalars(stmt).all())
    out = []
    for r in rows:
        _check_and_update_cutoff(r.exam, r, db)
        out.append(_build_room_assignment_out(r, r.exam, current_user))
    return out


@router.get("/{exam_id}", response_model=ExamOut, summary="Get exam details")
def get_exam(
    exam_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")
    return exam


@router.delete("/{exam_id}", summary="Delete an exam sitting and cascade seating records (Admin only)")
def delete_exam(
    exam_id: str,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    db.query(ExamSeating).filter(ExamSeating.exam_id == exam_id).delete()
    db.query(RoomAssignment).filter(RoomAssignment.exam_id == exam_id).delete()
    db.delete(exam)
    db.commit()

    log_security_event(
        "exam_deleted",
        severity="warning",
        outcome="success",
        actor_id=current_user.user_id,
        details={"exam_id": exam_id},
    )
    return {"message": f"Exam '{exam_id}' and all associated records deleted successfully."}


# ============================================================================
# 2. SEATING PLAN & ROOM ALLOCATION (ADMIN)
# ============================================================================

@router.post("/{exam_id}/seating/upload", summary="Upload seating plan CSV for an exam")
async def upload_seating_csv(
    exam_id: str,
    file: UploadFile = File(...),
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    contents = await file.read()
    text = contents.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        raise HTTPException(status_code=422, detail="Empty CSV file or invalid header.")

    # Normalise headers
    header_map = {fn.strip().lower(): fn for fn in reader.fieldnames}
    req_keys = {"usn", "name"}
    if not req_keys.issubset(set(header_map.keys())):
        raise HTTPException(
            status_code=422,
            detail=f"CSV must contain at least 'usn' and 'name' columns. Found: {reader.fieldnames}",
        )

    room_key = "room_no" if "room_no" in header_map else ("room" if "room" in header_map else None)
    if not room_key:
        raise HTTPException(status_code=422, detail="CSV must contain 'room_no' or 'room' column.")

    branch_key = "branch" if "branch" in header_map else None
    seat_key = "seat_no" if "seat_no" in header_map else ("seat" if "seat" in header_map else None)
    sl_key = "sl_no" if "sl_no" in header_map else ("sl" if "sl" in header_map else None)
    subj_key = "subject_code" if "subject_code" in header_map else ("subject" if "subject" in header_map else None)

    seen_usns = set()
    rooms_seen = set()
    seating_rows = []
    sl_counter = 1

    for row_idx, row in enumerate(reader, start=2):
        usn = str(row.get(header_map["usn"], "")).strip().upper()
        name = str(row.get(header_map["name"], "")).strip()
        room_no = str(row.get(header_map[room_key], "")).strip().upper()

        if not usn or not room_no:
            raise HTTPException(status_code=422, detail=f"Line {row_idx}: USN and room_no cannot be blank.")

        if usn in seen_usns:
            raise HTTPException(status_code=422, detail=f"Duplicate USN '{usn}' found in seating plan at line {row_idx}.")
        seen_usns.add(usn)
        rooms_seen.add(room_no)

        branch = str(row.get(header_map[branch_key], "")).strip().upper() if branch_key else ""
        if not branch:
            # Fallback extract from USN e.g. 1DS23CY037 -> CY
            if len(usn) >= 7 and usn[5:7].isalpha():
                branch = usn[5:7]
            else:
                branch = "GEN"

        seat_no = str(row.get(header_map[seat_key], "")).strip() if seat_key else str(sl_counter)
        sl_val = int(row.get(header_map[sl_key])) if sl_key and str(row.get(header_map[sl_key])).isdigit() else sl_counter
        subject = str(row.get(header_map[subj_key], "")).strip() if subj_key else exam.subject_code

        seating_rows.append({
            "exam_id": exam_id,
            "room_no": room_no,
            "sl_no": sl_val,
            "usn": usn,
            "name": name or usn,
            "branch": branch,
            "subject_code": subject or exam.subject_code,
            "seat_no": seat_no,
            "status": "ABSENT",
        })
        sl_counter += 1

    # Clear existing seating and allocations for this exam to allow re-upload
    db.query(ExamSeating).filter(ExamSeating.exam_id == exam_id).delete()

    # Ensure room_assignments exist
    existing_rooms = {
        r.room_no for r in db.query(RoomAssignment).filter(RoomAssignment.exam_id == exam_id).all()
    }
    for r_no in rooms_seen:
        if r_no not in existing_rooms:
            db.add(RoomAssignment(
                exam_id=exam_id,
                room_no=r_no,
                capacity=30,
                status="SCHEDULED",
            ))

    # Insert seating rows
    for s_dict in seating_rows:
        db.add(ExamSeating(**s_dict))

    db.commit()

    return {
        "message": "Seating plan uploaded successfully.",
        "exam_id": exam_id,
        "total_students": len(seating_rows),
        "total_rooms": len(rooms_seen),
    }


@router.get("/{exam_id}/invigilator-candidates", summary="Get faculty invigilator candidates with timetable conflict detection")
def get_invigilator_candidates(
    exam_id: str,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    exam_weekday = "Monday"
    try:
        dt = datetime.strptime(exam.date, "%Y-%m-%d")
        exam_weekday = dt.strftime("%A")
    except Exception:
        pass

    # Get already assigned invigilators for this exam
    assignments = db.query(RoomAssignment).filter(RoomAssignment.exam_id == exam_id).all()
    assigned_map = {r.invigilator_id: r.room_no for r in assignments if r.invigilator_id}

    # Fetch all faculty users
    faculty_users = db.query(User).filter(User.role == Role.FACULTY.value).all()

    # Fetch timetable entries on this weekday
    day_entries = (
        db.query(TimetableEntry)
        .filter(TimetableEntry.day_of_week == exam_weekday)
        .all()
    )

    candidates = []
    e_start = exam.start_time[:5]
    e_end = exam.end_time[:5]

    for f in faculty_users:
        teacher_entries = [e for e in day_entries if e.faculty_id == f.user_id]
        conflict_msg = None
        has_conflict = False

        for te in teacher_entries:
            te_start = te.start_time[:5]
            te_end = te.end_time[:5]
            if te_start < e_end and te_end > e_start:
                has_conflict = True
                conflict_msg = f"Period {te.period_number} ({te.start_time}-{te.end_time}): {te.subject_code} in {te.room_id}"
                break

        already_room = assigned_map.get(f.user_id)
        is_assigned = bool(already_room)

        priority = 0
        if is_assigned:
            priority = 2
        elif has_conflict:
            priority = 1

        candidates.append({
            "user_id": f.user_id,
            "name": f.name or f.user_id,
            "has_timetable_conflict": has_conflict,
            "conflict_details": conflict_msg,
            "is_already_assigned": is_assigned,
            "assigned_room": already_room,
            "is_recommended": not has_conflict and not is_assigned,
            "priority": priority,
        })

    candidates.sort(key=lambda c: (c["priority"], c["name"]))
    return candidates


@router.post("/{exam_id}/rooms/{room_no}/assign", response_model=RoomAssignmentOut, summary="Assign invigilator and block to a room")
def assign_room_invigilator(
    exam_id: str,
    room_no: str,
    payload: RoomAssignPayload,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    assignment = (
        db.query(RoomAssignment)
        .filter(RoomAssignment.exam_id == exam_id, RoomAssignment.room_no == room_no.strip().upper())
        .first()
    )
    if not assignment:
        # Create assignment record if not exists
        assignment = RoomAssignment(
            exam_id=exam_id,
            room_no=room_no.strip().upper(),
            status="SCHEDULED",
        )
        db.add(assignment)

    if payload.invigilator_id:
        user = db.get(User, payload.invigilator_id.strip())
        if not user:
            raise HTTPException(status_code=404, detail=f"User '{payload.invigilator_id}' not found.")
        assignment.invigilator_id = user.user_id

    if payload.block_name is not None:
        assignment.block_name = payload.block_name
    if payload.capacity is not None:
        assignment.capacity = payload.capacity
    if payload.external_examiner_name is not None:
        assignment.external_examiner_name = payload.external_examiner_name
    if payload.external_examiner_college is not None:
        assignment.external_examiner_college = payload.external_examiner_college
    if payload.coordinator_id is not None:
        assignment.coordinator_id = payload.coordinator_id

    db.commit()
    db.refresh(assignment)
    return _build_room_assignment_out(assignment, assignment.exam, current_user)


@router.get("/{exam_id}/rooms", response_model=List[RoomAssignmentOut], summary="List all room assignments for an exam")
def list_exam_rooms(
    exam_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    assignments = db.query(RoomAssignment).filter(RoomAssignment.exam_id == exam_id).order_by(RoomAssignment.room_no.asc()).all()
    out = []
    for a in assignments:
        _check_and_update_cutoff(exam, a, db)
        out.append(_build_room_assignment_out(a, exam, current_user))
    return out


@router.get("/{exam_id}/rooms/{room_no}", response_model=RoomAssignmentOut, summary="Get details for a specific room assignment")
def get_room_assignment(
    exam_id: str,
    room_no: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    assignment = _find_assignment(db, exam_id, room_no)
    if not assignment:
        raise HTTPException(status_code=404, detail="Room assignment not found.")

    if not _can_access_room(assignment, current_user):
        raise HTTPException(status_code=403, detail="Access denied: You are not assigned to this exam room.")

    _check_and_update_cutoff(exam, assignment, db)
    return _build_room_assignment_out(assignment, exam, current_user)


# ============================================================================
# 3. INVIGILATOR FORM-B ROSTER & ATTENDANCE MARKING
# ============================================================================

@router.get("/{exam_id}/rooms/{room_no}/roster", response_model=List[ExamSeatingOut], summary="Get Form-B student roster for a room")
def get_room_roster(
    exam_id: str,
    room_no: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assignment = _find_assignment(db, exam_id, room_no)
    if not assignment:
        raise HTTPException(status_code=404, detail="Room assignment not found for this exam.")

    # Permissions: Admin or assigned invigilator
    if not _can_access_room(assignment, current_user):
        raise HTTPException(status_code=403, detail="Access denied: You are not assigned to this exam room.")

    roster = _find_roster(db, exam_id, room_no)
    return roster


@router.patch("/{exam_id}/rooms/{room_no}/mark", summary="Mark attendance for students in room")
def mark_room_attendance(
    exam_id: str,
    room_no: str,
    payload: BulkMarkPayload,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
):
    assignment = _find_assignment(db, exam_id, room_no)
    if not assignment:
        raise HTTPException(status_code=404, detail="Room not found for this exam.")

    # Verify ownership
    if not _can_access_room(assignment, current_user):
        raise HTTPException(status_code=403, detail="Access denied: You are not assigned to this exam room.")

    # Check cutoff timer and lock
    current_status = _check_and_update_cutoff(assignment.exam, assignment, db)
    if current_status == "LATE_LOCKED" and current_user.role != Role.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Room Form-B is LATE_LOCKED: the Form-B submission cutoff time expired. Contact Admin for override.",
        )
    if current_status == "SUBMITTED" and current_user.role != Role.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Room Form-B is already SUBMITTED to Exam Cell and cannot be modified. Contact Admin for override.",
        )

    now_iso = _utcnow_iso()
    updated_count = 0
    clean_target = _clean_room(room_no)

    for item in payload.marks:
        student = (
            db.query(ExamSeating)
            .filter(
                ExamSeating.exam_id == exam_id,
                ExamSeating.usn == item.usn.strip().upper(),
            )
            .first()
        )
        if student and _clean_room(student.room_no) == clean_target:
            student.status = item.status
            student.marked_by = current_user.user_id
            student.marked_source = payload.marked_source
            student.marked_at = now_iso
            updated_count += 1

    # Transition from SCHEDULED to OPEN if first mark
    if assignment.status == "SCHEDULED":
        assignment.status = "OPEN"

    # Every mutation of exam attendance is audited (mark / scan / submit), so a
    # modified Form-B can always be traced back to an actor.
    log_security_event(
        "exam_attendance_marked",
        severity="info",
        outcome="success",
        actor_id=current_user.user_id,
        details={
            "exam_id": exam_id,
            "room_no": room_no.strip().upper(),
            "updated_count": updated_count,
            "marked_source": payload.marked_source,
            "room_status": assignment.status,
        },
    )

    db.commit()
    return {"message": f"Updated attendance for {updated_count} students.", "room_status": assignment.status}


@router.post("/{exam_id}/rooms/{room_no}/scan-photo", summary="Scan Form-B photo using Gemini Vision AI")
async def scan_form_b_photo(
    exam_id: str,
    room_no: str,
    file: UploadFile = File(...),
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
):
    assignment = _find_assignment(db, exam_id, room_no)
    if not assignment:
        raise HTTPException(status_code=404, detail="Room not found.")

    if not _can_access_room(assignment, current_user):
        raise HTTPException(status_code=403, detail="Access denied.")

    current_status = _check_and_update_cutoff(assignment.exam, assignment, db)
    if current_status == "LATE_LOCKED" and current_user.role != Role.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Room Form-B is LATE_LOCKED: the submission cutoff time expired. Contact Admin for override.",
        )
    if current_status == "SUBMITTED" and current_user.role != Role.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Room Form-B is already SUBMITTED. Contact Admin for override.",
        )

    contents = await file.read()
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty (0 bytes).",
        )
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Image size exceeds 10MB limit.",
        )

    # The photo must really be an image: validate magic bytes, extension and
    # declared MIME type before anything is passed to the vision model.
    header = contents[:32]
    detected = detect_image_type(header)
    if detected is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is not a supported image (PNG or JPEG).",
        )

    consistency = check_extension_consistency(file.filename or "", header)
    if not consistency.ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=consistency.detail)

    declared = check_declared_content_type(file.content_type, consistency.content_type)
    if not declared.ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=declared.detail)

    # Dimension / pixel-count and malware checks need a file on disk.
    suffix = detected[0]
    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(contents)

        dimensions = check_image_dimensions(temp_path)
        if not dimensions.ok:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=dimensions.detail)

        scanner = get_malware_scanner()
        if not scanner.available and _is_production():
            log_security_event(
                "upload_rejected",
                severity="critical",
                outcome="failure",
                actor_id=current_user.user_id,
                details={"reason": "malware_scanner_unavailable", "filename": file.filename},
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Uploads are temporarily unavailable because malware scanning is not configured.",
            )
        clean, scan_detail = scanner.scan(temp_path)
        if not clean:
            log_security_event(
                "upload_rejected",
                severity="warning",
                outcome="failure",
                actor_id=current_user.user_id,
                details={"reason": "malware_scan_failed", "filename": file.filename},
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"The uploaded file was rejected by the malware scan: {scan_detail}",
            )
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass

    # Disambiguate multi-exam Form-B column using subject code, exam date, start time, and room
    exam_obj = assignment.exam
    try:
        import inspect
        sig = inspect.signature(scan_form_b_image)
        has_kwargs = any(
            p.kind in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
            or p.name == "target_subject_code"
            for p in sig.parameters.values()
        )
        if has_kwargs:
            extracted_rows = scan_form_b_image(
                contents,
                target_subject_code=getattr(exam_obj, "subject_code", None),
                target_date=getattr(exam_obj, "date", None),
                target_start_time=getattr(exam_obj, "start_time", None),
                target_room_no=room_no,
                target_semester=getattr(exam_obj, "semester", None),
            )
        else:
            extracted_rows = scan_form_b_image(contents)
    except Exception as scan_err:
        logger.warning("Targeted scan_form_b_image call failed, falling back to default: %s", scan_err)
        extracted_rows = scan_form_b_image(contents)

    if not extracted_rows:
        return {
            "message": "AI vision could not identify students automatically or API key missing. Please mark manually.",
            "matched_count": 0,
            "extracted_rows": [],
            "tally": {},
            "detected_columns": [],
            "target_column_matched": {},
        }

    now_iso = _utcnow_iso()
    matched_count = 0
    clean_target = _clean_room(room_no)

    for row in extracted_rows:
        usn = row["usn"]
        st = (
            db.query(ExamSeating)
            .filter(
                ExamSeating.exam_id == exam_id,
                ExamSeating.usn == usn,
            )
            .first()
        )
        if st and _clean_room(st.room_no) == clean_target:
            st.status = row["status"]
            st.marked_by = current_user.user_id
            st.marked_source = "AI_SCAN"
            st.marked_at = now_iso
            matched_count += 1

    if assignment.status == "SCHEDULED":
        assignment.status = "OPEN"

    log_security_event(
        "exam_form_b_scanned",
        severity="info",
        outcome="success",
        actor_id=current_user.user_id,
        details={
            "exam_id": exam_id,
            "room_no": assignment.room_no,
            "matched_count": matched_count,
            "room_status": assignment.status,
            "subject_code": getattr(exam_obj, "subject_code", None),
        },
    )

    db.commit()

    tally = getattr(extracted_rows, "tally", None) or {}
    detected_cols = getattr(extracted_rows, "detected_columns", None) or []
    target_matched = getattr(extracted_rows, "target_column_matched", None) or {}
    subject_label = f" for subject '{exam_obj.subject_code}'" if getattr(exam_obj, "subject_code", None) else ""

    return {
        "message": f"AI Scan completed{subject_label}. Matched and updated {matched_count} students.",
        "matched_count": matched_count,
        "extracted_rows": extracted_rows,
        "tally": tally,
        "detected_columns": detected_cols,
        "target_column_matched": target_matched,
    }


@router.post("/{exam_id}/rooms/{room_no}/submit", summary="Submit & seal Form-B with audit lock")
def submit_form_b(
    exam_id: str,
    room_no: str,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
):
    assignment = _find_assignment(db, exam_id, room_no)
    if not assignment:
        raise HTTPException(status_code=404, detail="Room not found.")

    if not _can_access_room(assignment, current_user):
        raise HTTPException(status_code=403, detail="Access denied.")

    current_status = _check_and_update_cutoff(assignment.exam, assignment, db)
    if current_status == "LATE_LOCKED" and current_user.role != Role.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Form-B submission cutoff time expired. Room is LATE_LOCKED. Contact Admin for override.",
        )

    if assignment.status == "SUBMITTED":
        return {"message": "Form-B is already submitted.", "submitted_at": assignment.submitted_at, "status": "SUBMITTED"}

    now_iso = _utcnow_iso()
    assignment.status = "SUBMITTED"
    assignment.submitted_at = now_iso
    assignment.submitted_by = current_user.user_id

    # Mirror Form-B attendance marks into core attendance table for database transparency
    try:
        from app.db.models import Attendance, Room as DbRoom, Session as DbSession, Student as DbStudent
        seating_rows = db.query(ExamSeating).filter(
            ExamSeating.exam_id == exam_id,
            ExamSeating.room_no == assignment.room_no,
        ).all()
        session_code = f"EXAM-{exam_id}-{assignment.room_no}"
        if seating_rows and not db.get(DbSession, session_code):
            # The core attendance table has FKs to sessions/rooms/students;
            # create the mirrored parents once before linking Form-B rows.
            db.add(DbSession(
                session_id=session_code,
                date=assignment.exam.date,
                subject=assignment.exam.subject_code or assignment.exam.name,
                subject_code=assignment.exam.subject_code,
                created_at=now_iso,
            ))
            db.flush()
        if seating_rows and not db.get(DbRoom, assignment.room_no):
            db.add(DbRoom(room_id=assignment.room_no, name=assignment.room_no))
            db.flush()
        for s in seating_rows:
            if not db.get(DbStudent, s.usn):
                db.add(DbStudent(
                    usn=s.usn,
                    name=getattr(s, "name", None) or s.usn,
                    branch=getattr(s, "branch", None) or "GENERAL",
                ))
        db.flush()
        for s in seating_rows:
            existing_att = db.query(Attendance).filter(
                Attendance.session_id == session_code,
                Attendance.usn == s.usn,
            ).first()
            if not existing_att:
                att_record = Attendance(
                    session_id=session_code,
                    usn=s.usn,
                    room_id=assignment.room_no,
                    status=s.status or "PRESENT",
                    source="FORM_B",
                    confidence=1.0,
                )
                db.add(att_record)
            else:
                existing_att.status = s.status or "PRESENT"
    except Exception as att_exc:
        logger.warning("Mirroring Form-B to attendance table failed: %s", att_exc)

    # Emit audit log
    log_security_event(
        "room_submitted",
        severity="info",
        outcome="success",
        actor_id=current_user.user_id,
        details={
            "exam_id": exam_id,
            "room_no": room_no,
            "submitted_at": now_iso,
        },
    )

    db.commit()
    return {"message": "Form-B successfully submitted and sealed.", "submitted_at": now_iso, "status": "SUBMITTED"}


@router.post("/{exam_id}/rooms/{room_no}/admin-override", summary="Admin override for a locked or late Form-B")
def admin_override_room(
    exam_id: str,
    room_no: str,
    payload: AdminOverridePayload,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    assignment = (
        db.query(RoomAssignment)
        .filter(RoomAssignment.exam_id == exam_id, RoomAssignment.room_no == room_no.strip().upper())
        .first()
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="Room not found.")

    prev_status = assignment.status
    assignment.status = payload.new_status
    if payload.new_status == "OPEN":
        assignment.submitted_at = None
        assignment.submitted_by = f"OVERRIDE:{current_user.user_id}"

    log_security_event(
        "admin_override_event",
        severity="warning",
        outcome="success",
        actor_id=current_user.user_id,
        details={
            "exam_id": exam_id,
            "room_no": room_no,
            "previous_status": prev_status,
            "new_status": payload.new_status,
            "reason": payload.reason,
        },
    )

    db.commit()
    return {"message": "Admin override applied successfully.", "room_status": assignment.status}


# ============================================================================
# 4. SUMMARIES & REPORTS (ROOM-WISE & BRANCH-WISE)
# ============================================================================

@router.get("/{exam_id}/summary/room-wise", response_model=List[RoomSummaryItem], summary="Get room-wise attendance summary")
def get_room_wise_summary(
    exam_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    # One seating query for the whole exam + one eager-loaded rooms query.
    # The old per-room loop issued 1 + 2*rooms queries (seating + lazy
    # invigilator for every room) on each dashboard refresh.
    rooms = (
        db.query(RoomAssignment)
        .options(joinedload(RoomAssignment.invigilator))
        .filter(RoomAssignment.exam_id == exam_id)
        .order_by(RoomAssignment.room_no.asc())
        .all()
    )
    seating_by_room: Dict[str, List[ExamSeating]] = {}
    for s in db.query(ExamSeating).filter(ExamSeating.exam_id == exam_id).all():
        seating_by_room.setdefault((s.room_no or "").strip(), []).append(s)
    summaries = []

    for r in rooms:
        seating = seating_by_room.get((r.room_no or "").strip(), [])
        total = len(seating)
        present = sum(1 for s in seating if s.status == "PRESENT")
        absent = total - present
        pct = round((present / total * 100), 1) if total > 0 else 0.0

        absentees = [
            {"sl_no": s.sl_no, "usn": s.usn, "name": s.name, "branch": s.branch}
            for s in seating if s.status == "ABSENT"
        ]

        invig_name = r.invigilator.name if r.invigilator else None

        summaries.append(RoomSummaryItem(
            room_no=r.room_no,
            block_name=r.block_name,
            invigilator_id=r.invigilator_id,
            invigilator_name=invig_name,
            status=r.status,
            submitted_at=r.submitted_at,
            total_students=total,
            present_count=present,
            absent_count=absent,
            attendance_percentage=pct,
            absentees=absentees,
        ))

    return summaries


@router.get("/{exam_id}/summary/branch-wise", response_model=List[BranchSummaryItem], summary="Get branch-wise attendance summary")
def get_branch_wise_summary(
    exam_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    all_seating = db.query(ExamSeating).filter(ExamSeating.exam_id == exam_id).all()
    branch_map: Dict[str, Dict[str, int]] = {}

    for s in all_seating:
        b = s.branch or "GEN"
        if b not in branch_map:
            branch_map[b] = {"total": 0, "present": 0, "absent": 0}
        branch_map[b]["total"] += 1
        if s.status == "PRESENT":
            branch_map[b]["present"] += 1
        else:
            branch_map[b]["absent"] += 1

    out = []
    for branch, counts in sorted(branch_map.items()):
        tot = counts["total"]
        pres = counts["present"]
        pct = round((pres / tot * 100), 1) if tot > 0 else 0.0
        out.append(BranchSummaryItem(
            branch=branch,
            total_students=tot,
            present_count=pres,
            absent_count=counts["absent"],
            attendance_percentage=pct,
        ))

    return out


BRANCH_FULL_NAMES: Dict[str, str] = {
    "CY": "Computer Science & Engineering (Cyber Security)",
    "CSE": "Computer Science & Engineering",
    "CS": "Computer Science & Engineering",
    "ISE": "Information Science & Engineering",
    "IS": "Information Science & Engineering",
    "AIML": "Artificial Intelligence & Machine Learning",
    "AI": "Artificial Intelligence & Machine Learning",
    "ECE": "Electronics & Communication Engineering",
    "EC": "Electronics & Communication Engineering",
    "EEE": "Electrical & Electronics Engineering",
    "ME": "Mechanical Engineering",
    "CV": "Civil Engineering",
}


@router.get(
    "/consolidation/branch-wise",
    response_model=MultiExamConsolidationResponse,
    summary="Get multi-exam branch consolidation matrix with subject codes, dates, and student attendance counts",
)
def get_multi_exam_branch_consolidation(
    semester: Optional[int] = Query(None, description="Filter by semester (e.g. 7)"),
    exam_type: Optional[str] = Query(None, description="Filter by exam type (e.g. THEORY_CIE)"),
    branch: Optional[str] = Query(None, description="Filter by specific branch code (e.g. CY)"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Exam)
    if exam_type:
        query = query.filter(Exam.exam_type == exam_type)
    if semester is not None:
        query = query.filter(Exam.semester == semester)

    all_exams = query.order_by(Exam.date.asc(), Exam.start_time.asc()).all()
    if not all_exams:
        return MultiExamConsolidationResponse(
            series_title="CIE Assessment Series",
            semester=semester,
            total_students_college=0,
            total_exams_series=0,
            branches=[],
        )

    # Deduplicate exams by subject_code so each distinct CIE subject gets exactly one column
    deduped_exams_map: Dict[str, Exam] = {}
    for ex in all_exams:
        sc = (ex.subject_code or "").strip().upper()
        if sc not in deduped_exams_map:
            deduped_exams_map[sc] = ex
        elif ex.exam_id.startswith("DSCE-CIE3-22") or ex.exam_id.startswith("DSCE-CIE"):
            deduped_exams_map[sc] = ex

    unique_exams = sorted(
        deduped_exams_map.values(),
        key=lambda x: (str(x.date), str(x.start_time), str(x.subject_code)),
    )
    exam_ids = [e.exam_id for e in all_exams]
    unique_exam_ids = [e.exam_id for e in unique_exams]

    seating_query = db.query(ExamSeating).filter(ExamSeating.exam_id.in_(exam_ids))
    if branch:
        seating_query = seating_query.filter(ExamSeating.branch.ilike(f"%{branch}%"))
    all_seating = seating_query.order_by(ExamSeating.branch.asc(), ExamSeating.sl_no.asc()).all()

    branch_exam_map: Dict[str, set] = {}
    branch_student_map: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for s in all_seating:
        b = (s.branch or "GEN").upper().strip()
        sc = (s.subject_code or "").upper().strip()
        if b not in branch_exam_map:
            branch_exam_map[b] = set()
            branch_student_map[b] = {}

        branch_exam_map[b].add(sc)

        usn = (s.usn or "").upper().strip()
        if usn not in branch_student_map[b]:
            branch_student_map[b][usn] = {
                "sl_no": s.sl_no or (len(branch_student_map[b]) + 1),
                "usn": usn,
                "name": s.name or usn,
                "branch": b,
                "statuses": {},
            }
        # Record attendance per subject code
        if sc:
            existing_st = branch_student_map[b][usn]["statuses"].get(sc)
            # If present in any room for this subject, keep PRESENT
            if existing_st != "PRESENT":
                branch_student_map[b][usn]["statuses"][sc] = s.status or "PRESENT"

    branch_reports: List[BranchConsolidationReport] = []
    total_college_students = 0

    for b, students_dict in sorted(branch_student_map.items()):
        total_college_students += len(students_dict)
        relevant_exams = [
            ex
            for ex in unique_exams
            if ex.subject_code.upper() in branch_exam_map.get(b, set()) or len(branch_exam_map.get(b, set())) == 0
        ]
        if not relevant_exams:
            relevant_exams = unique_exams

        exam_headers: List[ExamHeaderInfo] = []
        for ex in relevant_exams:
            sc = ex.subject_code.upper()
            pres_cnt = sum(
                1 for st in students_dict.values() if st["statuses"].get(sc) == "PRESENT"
            )
            abs_cnt = sum(
                1 for st in students_dict.values() if st["statuses"].get(sc) == "ABSENT"
            )
            reg_cnt = len(students_dict)
            pct = round((pres_cnt / reg_cnt * 100), 1) if reg_cnt > 0 else 0.0
            slot_label = "FN" if str(ex.start_time) < "13:00:00" else "AN"
            exam_headers.append(
                ExamHeaderInfo(
                    exam_id=ex.exam_id,
                    subject_code=ex.subject_code,
                    subject_name=ex.subject_name or ex.name,
                    date=str(ex.date),
                    start_time=str(ex.start_time),
                    end_time=str(ex.end_time),
                    slot=slot_label,
                    total_registered=reg_cnt,
                    total_present=pres_cnt,
                    total_absent=abs_cnt,
                    attendance_pct=pct,
                )
            )

        student_rows: List[StudentExamAttendanceRow] = []
        tot_written_branch = 0
        tot_possible_branch = len(students_dict) * len(relevant_exams)

        for usn, st in sorted(students_dict.items(), key=lambda x: (x[1]["sl_no"], x[0])):
            exam_status: Dict[str, str] = {}
            missed_subs: List[str] = []
            written_count = 0
            absent_count = 0

            for ex in relevant_exams:
                sc = ex.subject_code.upper()
                st_status = st["statuses"].get(sc, "ABSENT")
                exam_status[ex.subject_code] = st_status
                if st_status == "PRESENT":
                    written_count += 1
                else:
                    absent_count += 1
                    missed_subs.append(ex.subject_code)

            tot_written_branch += written_count
            att_pct = (
                round((written_count / len(relevant_exams) * 100), 1)
                if len(relevant_exams) > 0
                else 0.0
            )

            student_rows.append(
                StudentExamAttendanceRow(
                    sl_no=st["sl_no"],
                    usn=usn,
                    name=st["name"],
                    branch=b,
                    exams_written=written_count,
                    exams_absent=absent_count,
                    total_exams=len(relevant_exams),
                    attendance_pct=att_pct,
                    exam_status=exam_status,
                    missed_subjects=missed_subs,
                )
            )

        perfect_count = sum(1 for r in student_rows if r.exams_written == len(relevant_exams))
        partial_count = len(student_rows) - perfect_count
        overall_pct = (
            round((tot_written_branch / tot_possible_branch * 100), 1)
            if tot_possible_branch > 0
            else 0.0
        )

        branch_reports.append(
            BranchConsolidationReport(
                branch=b,
                branch_name=BRANCH_FULL_NAMES.get(b, f"Department of {b}"),
                total_students=len(student_rows),
                total_exams=len(relevant_exams),
                overall_attendance_pct=overall_pct,
                perfect_attendance_count=perfect_count,
                partial_attendance_count=partial_count,
                exams=exam_headers,
                students=student_rows,
            )
        )

    series_name = unique_exams[0].name.split("-")[0].strip() if unique_exams else "CIE Assessment Series"
    return MultiExamConsolidationResponse(
        series_title=f"{series_name} — Full College Attendance Consolidation",
        semester=semester or (unique_exams[0].semester if unique_exams else None),
        total_students_college=total_college_students,
        total_exams_series=len(unique_exams),
        branches=branch_reports,
    )


# ============================================================================
# 5. PDF EXPORTS (PRINTABLE FORM-B & ABSENTEES STATEMENT)
# ============================================================================

@router.get("/{exam_id}/rooms/{room_no}/sign-sheet-pdf", summary="Download blank printable Form-B PDF for a room")
def download_sign_sheet_pdf(
    exam_id: str,
    room_no: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    assignment = _find_assignment(db, exam_id, room_no)
    if not assignment:
        raise HTTPException(status_code=404, detail="Room not found.")

    roster = _find_roster(db, exam_id, room_no)

    pdf_bytes = generate_printable_form_b_pdf(exam, assignment, roster)
    filename = f"Form-B_{exam.subject_code}_{assignment.room_no.replace(' ', '_')}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/{exam_id}/absentees-pdf", summary="Download official consolidated absentees statement PDF")
def download_absentees_pdf(
    exam_id: str,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    room_items = get_room_wise_summary(exam_id=exam_id, current_user=current_user, db=db)
    branch_items = get_branch_wise_summary(exam_id=exam_id, current_user=current_user, db=db)

    pdf_bytes = generate_exam_absentees_statement_pdf(
        exam,
        [r.model_dump() for r in room_items],
        [b.model_dump() for b in branch_items],
    )
    filename = f"Absentees_Statement_{exam_id}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
