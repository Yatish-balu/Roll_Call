"""FastAPI router for Attendance and Reconciliation endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Role, get_current_user, require_roles
from app.auth.session_scope import resolve_data_scope
from app.db import crud
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser
from app.db.models import Attendance
from app.schemas.attendance import (
    AttendanceBulkCreate,
    AttendanceCorrectionRequest,
    AttendanceCorrectionResponse,
    AttendanceCreate,
    AttendanceDetailResponse,
    AttendanceResponse,
    AttendanceUndoRequest,
    AttendanceUndoResponse,
    BulkReconcileRequest,
    ReconcileRequest,
    SessionReconcilePayload,
)
from app.services.undo_service import (
    create_undo_token,
    execute_undo,
    get_record_version,
)
from app.services.attendance_edits import (
    AttendanceChange,
    actor_identity,
    assert_session_edit_authorized,
    capture_attendance_statuses,
    write_attendance_audit,
)

logger = logging.getLogger("rollcall.routers.attendance")

router = APIRouter(prefix="/attendance", tags=["Attendance"])


def _verify_session_exists(db: Session, session_id: str) -> Dict[str, Any]:
    """Verify session exists in database; raise 404 if missing."""
    clean_id = session_id.strip()
    session = crud.get_session(db, session_id=clean_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{clean_id}' not found.",
        )
    return session


def _verify_student_exists(db: Session, usn: str) -> Dict[str, Any]:
    """Verify student exists in database; raise 404 if missing."""
    clean_usn = usn.strip().upper()
    student = crud.get_student(db, usn=clean_usn)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with USN '{clean_usn}' not found.",
        )
    return student


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _assert_session_ownership(
    current_user: AuthenticatedUser,
    session: Dict[str, Any],
    db: Optional[Session] = None,
) -> None:
    """Enforce faculty ownership of a session (N3).

    The policy itself lives in ``app.services.attendance_edits`` so that the
    direct API, the chat confirmation flow and the legacy UI commit all use
    exactly the same rule. Session age and lifecycle status are not part of
    the decision: there is no time-based editing lock (N5).
    """
    assert_session_edit_authorized(current_user, session, db)


def _verify_room_exists(db: Session, room_id: str) -> Dict[str, Any]:
    """Verify room exists in database; raise 404 if missing."""
    clean_id = room_id.strip()
    if clean_id.upper() == "UNALLOCATED":
        crud.ensure_unallocated_room(db)
        room = crud.get_room(db, room_id="UNALLOCATED")
        if room:
            return room
        return {"room_id": "UNALLOCATED", "name": "Unallocated Classroom"}
    room = crud.get_room(db, room_id=clean_id)
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room with ID '{clean_id}' not found.",
        )
    return room


def _verify_roster_references(db: Session, records: Sequence[Any]) -> None:
    """Validate every USN and room of a roster with a single query each.

    The per-record checks issued two remote round trips per student, which made
    a 45-student save take roughly half a minute against Supabase.
    """
    usns = {str(r.usn).strip().upper() for r in records}
    known_usns = crud.get_existing_student_usns(db, usns)
    missing_usns = sorted(usns - known_usns)
    if missing_usns:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with USN '{missing_usns[0]}' not found.",
        )

    crud.ensure_unallocated_room(db)
    raw_rooms = {
        str(r.room_id).strip()
        if getattr(r, "room_id", None) and str(r.room_id).strip()
        else "UNALLOCATED"
        for r in records
    }
    non_unallocated = {r for r in raw_rooms if r.upper() != "UNALLOCATED"}
    if non_unallocated:
        known_rooms = crud.get_existing_room_ids(db, non_unallocated)
        missing_rooms = sorted(non_unallocated - known_rooms)
        if missing_rooms:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Room with ID '{missing_rooms[0]}' not found.",
            )


# ==============================================================================
# 1. GET /api/v1/attendance/sessions/{session_id}
# ==============================================================================

@router.get(
    "/sessions/{session_id}",
    response_model=List[AttendanceDetailResponse],
    summary="Get attendance records for a session",
    description="Retrieve joined attendance records for a session including student and room metadata.",
    responses={
        404: {"description": "Session not found"},
    },
)
def get_session_attendance(
    session_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    session = _verify_session_exists(db, session_id)
    _assert_session_ownership(current_user, session, db)
    return crud.get_session_attendance_details(db, session_id=session_id)


# ==============================================================================
# 2. POST /api/v1/attendance/sessions/{session_id}/record
# ==============================================================================

@router.post(
    "/sessions/{session_id}/record",
    response_model=AttendanceResponse,
    summary="Record or update single attendance mark",
    description="Record attendance for a student in a session. Use ?upsert=true to update an existing record.",
    responses={
        201: {"description": "Record created"},
        200: {"description": "Record updated (when upsert=true)"},
        404: {"description": "Session, student, or room not found"},
        409: {"description": "Record already exists (and upsert=false)"},
    },
)
def record_attendance(
    session_id: str,
    payload: AttendanceCreate,
    response: Response,
    upsert: bool = Query(False, description="Whether to update if record already exists"),
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    session = _verify_session_exists(db, session_id)
    _assert_session_ownership(current_user, session, db)

    clean_usn = payload.usn.strip().upper()
    _verify_student_exists(db, clean_usn)
    _verify_room_exists(db, payload.room_id)

    if payload.session_id and payload.session_id.strip() != session_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path session_id '{session_id}' does not match body session_id '{payload.session_id}'.",
        )

    existing = crud.get_attendance_record(db, session_id, clean_usn)
    if existing and not upsert:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Attendance record for student '{clean_usn}' in session '{session_id}' already exists.",
        )

    try:
        record = crud.insert_attendance(
            db,
            session_id=session_id,
            usn=clean_usn,
            room_id=payload.room_id,
            status=payload.status,
            source=payload.source,
            confidence=payload.confidence,
            upsert=upsert,
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Attendance record for student '{clean_usn}' in session '{session_id}' conflicts.",
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception as exc:
        db.rollback()
        logger.error("Failed to record attendance: %s", exc)
        raise

    try:
        # Audit is part of the same transaction: an unauditable write is rejected.
        # The shared audit service is used for every write path, so the audit
        # shape (actor, role, session, student, old -> new status, UTC time)
        # is identical for single and bulk edits.
        actor_id, actor_role = actor_identity(current_user)
        write_attendance_audit(
            db,
            actor_id=actor_id,
            actor_role=actor_role,
            session_id=session_id,
            action="ATTENDANCE_UPSERT" if existing else "ATTENDANCE_RECORD",
            changes=[
                AttendanceChange(
                    usn=clean_usn,
                    old_status=existing.get("status") if existing else None,
                    new_status=record["status"],
                    attendance_id=record["attendance_id"],
                )
            ],
        )
        db.commit()
        response.status_code = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        return record
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Failed to write attendance audit entry: %s", exc)
        raise


# ==============================================================================
# 3. POST /api/v1/attendance/sessions/{session_id}/bulk
# ==============================================================================

@router.post(
    "/sessions/{session_id}/bulk",
    status_code=status.HTTP_201_CREATED,
    summary="Bulk record attendance marks",
    description="Atomically insert multiple attendance marks for a session.",
    responses={
        201: {"description": "Records inserted"},
        404: {"description": "Session, student, or room not found"},
        409: {"description": "Duplicate USNs in batch or database conflict"},
    },
)
def bulk_record_attendance(
    session_id: str,
    payload: AttendanceBulkCreate,
    upsert: bool = Query(False, description="Whether to update records if already existing"),
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    session = _verify_session_exists(db, session_id)
    _assert_session_ownership(current_user, session, db)

    # Check for duplicate USNs within the request payload
    usns = [r.usn.strip().upper() for r in payload.records]
    if len(usns) != len(set(usns)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bulk insert payload contains duplicate student USNs.",
        )

    # Validate foreign keys in two queries instead of two per record.
    _verify_roster_references(db, payload.records)
    for r in payload.records:
        if r.session_id and r.session_id.strip() != session_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Record session_id '{r.session_id}' does not match path '{session_id}'.",
            )

    # If not upsert, check for existing records in DB to reject before insertion
    if not upsert:
        existing_usns = crud.get_existing_attendance_usns(db, session_id, usns)
        if existing_usns:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Attendance record for student '{existing_usns[0]}' in session '{session_id}' already exists.",
            )

    formatted_records = [
        {
            "session_id": session_id.strip(),
            "usn": r.usn.strip().upper(),
            "room_id": r.room_id.strip() if getattr(r, "room_id", None) and str(r.room_id).strip() else "UNALLOCATED",
            "status": r.status,
            "source": r.source,
            "confidence": r.confidence,
        }
        for r in payload.records
    ]

    # Capture the previous status of every affected student before the write so
    # that every modification can be audited old -> new (N5).
    previous_statuses = capture_attendance_statuses(
        db, session_id, [r["usn"] for r in formatted_records]
    )

    try:
        count = crud.insert_attendance_bulk(db, records=formatted_records, upsert=upsert)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bulk insert failed due to duplicate or conflicting attendance records.",
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception as exc:
        db.rollback()
        logger.error("Error during bulk attendance insertion: %s", exc)
        raise

    try:
        actor_id, actor_role = actor_identity(current_user)
        write_attendance_audit(
            db,
            actor_id=actor_id,
            actor_role=actor_role,
            session_id=session_id,
            action="ATTENDANCE_BULK_UPSERT" if upsert else "ATTENDANCE_BULK",
            changes=[
                AttendanceChange(
                    usn=r["usn"],
                    old_status=previous_statuses.get(r["usn"]),
                    new_status=crud.normalize_attendance_status(r["status"]),
                )
                for r in formatted_records
            ],
        )
        db.commit()
        return {
            "inserted_count": count,
            "message": f"Successfully inserted {count} attendance records.",
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Failed to write attendance audit entry: %s", exc)
        raise


# ==============================================================================
# 4. PUT /api/v1/attendance/sessions/{session_id}
# ==============================================================================

@router.put(
    "/sessions/{session_id}",
    status_code=status.HTTP_200_OK,
    summary="Replace session attendance atomically",
    description="Cleanly replaces all attendance records for the given session with a new batch.",
    responses={
        200: {"description": "Attendance replaced"},
        404: {"description": "Session, student, or room not found"},
        409: {"description": "Duplicate USNs in payload"},
    },
)
def replace_attendance(
    session_id: str,
    payload: AttendanceBulkCreate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    session = _verify_session_exists(db, session_id)
    _assert_session_ownership(current_user, session, db)

    # Validate duplicates in payload
    usns = [r.usn.strip().upper() for r in payload.records]
    if len(usns) != len(set(usns)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payload contains duplicate student USNs.",
        )

    # Validate foreign keys in two queries instead of two per record.
    _verify_roster_references(db, payload.records)

    formatted_records = [
        {
            "session_id": session_id.strip(),
            "usn": r.usn.strip().upper(),
            "room_id": r.room_id.strip() if getattr(r, "room_id", None) and str(r.room_id).strip() else "UNALLOCATED",
            "status": r.status,
            "source": r.source,
            "confidence": r.confidence,
        }
        for r in payload.records
    ]

    # Previous status of every student currently on record for this session.
    previous_statuses = capture_attendance_statuses(db, session_id)

    try:
        replaced_count = crud.replace_session_attendance(
            db, session_id=session_id, records=formatted_records
        )
        actor_id, actor_role = actor_identity(current_user)
        # One old -> new audit record per affected student (added, changed or
        # removed by the replacement).
        new_by_usn = {
            r["usn"]: crud.normalize_attendance_status(r["status"])
            for r in formatted_records
        }
        # Audit only rows that actually changed (added, edited or removed).
        # Auditing untouched students wrote one INSERT per row - 45 extra
        # round trips on a full roster - and buried the real edits.
        changes: List[AttendanceChange] = [
            AttendanceChange(
                usn=usn,
                old_status=previous_statuses.get(usn),
                new_status=new_by_usn.get(usn),
            )
            for usn in sorted(set(previous_statuses) | set(new_by_usn))
            if previous_statuses.get(usn) != new_by_usn.get(usn)
        ]
        write_attendance_audit(
            db,
            actor_id=actor_id,
            actor_role=actor_role,
            session_id=session_id,
            action="ATTENDANCE_REPLACE",
            changes=changes,
        )
        db.commit()
        return {
            "replaced_count": replaced_count,
            "message": f"Successfully replaced attendance for session '{session_id}' with {replaced_count} records.",
        }
    except ValueError as exc:
        # Staged edits protect their attendance row: refuse instead of losing them.
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:
        db.rollback()
        logger.error("Failed to replace attendance: %s", exc)
        raise


# ==============================================================================
# 5. DELETE /api/v1/attendance/sessions/{session_id}
# ==============================================================================

@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete attendance records for a session",
    description="Deletes all attendance records for the specified session without deleting the session itself.",
    responses={
        200: {"description": "Attendance records deleted"},
        404: {"description": "Session not found"},
    },
)
def delete_attendance(
    session_id: str,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _verify_session_exists(db, session_id)
    # Previous status of every student on record, for a per-student audit trail.
    previous_statuses = capture_attendance_statuses(db, session_id)
    try:
        deleted_count = crud.delete_session_attendance(db, session_id=session_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    actor_id, actor_role = actor_identity(current_user)
    write_attendance_audit(
        db,
        actor_id=actor_id,
        actor_role=actor_role,
        session_id=session_id,
        action="ATTENDANCE_DELETE",
        changes=[
            AttendanceChange(usn=usn, old_status=status, new_status=None)
            for usn, status in sorted(previous_statuses.items())
        ],
    )
    db.commit()
    return {
        "deleted_count": deleted_count,
        "message": f"Deleted {deleted_count} attendance records for session '{session_id}'.",
    }


# ==============================================================================
# 6. GET /api/v1/attendance/students/{usn}
# ==============================================================================

@router.get(
    "/students/{usn}",
    response_model=List[AttendanceResponse],
    summary="Get attendance history for a student",
    description=(
        "Retrieve the historical attendance marks of a student. Only records from sessions "
        "inside the caller's authorization scope are returned, and a student outside that "
        "scope is reported as not found so the endpoint never confirms their existence."
    ),
    responses={
        404: {"description": "Student not found or not visible to the caller"},
    },
)
def get_student_attendance_history(
    usn: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    clean_usn = usn.strip().upper()
    scope = resolve_data_scope(db, current_user)
    if not scope.is_student_visible(db, clean_usn):
        # Same response as an unknown student: no existence disclosure.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with USN '{clean_usn}' not found.",
        )
    _verify_student_exists(db, clean_usn)
    if scope.unrestricted:
        return crud.get_attendance_by_student(db, usn=clean_usn)
    return crud.get_attendance_by_student(
        db, usn=clean_usn, session_ids=scope.visible_session_ids(db)
    )


# ==============================================================================
# 7. POST /api/v1/attendance/sessions/{session_id}/reconcile
# ==============================================================================

@router.post(
    "/sessions/{session_id}/reconcile",
    status_code=status.HTTP_200_OK,
    summary="Reconcile session attendance",
    description=(
        "Reconcile session attendance records. Supports two modes:\n"
        "1. Explicit manual resolutions (using 'resolutions' list of ReconcileRequest items).\n"
        "2. Roster reconciliation (using 'uploaded_records' against the student roster, "
        "preserving PENDING for missing sheets and UNREVIEWED for low confidence marks)."
    ),
    responses={
        200: {"description": "Reconciliation completed"},
        404: {"description": "Session or student not found"},
    },
)
def reconcile_attendance(
    session_id: str,
    payload: SessionReconcilePayload,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    session = _verify_session_exists(db, session_id)
    _assert_session_ownership(current_user, session, db)

    # ---------------------------------------------------------
    # Mode 1: Single or Bulk Manual Resolutions
    # ---------------------------------------------------------
    resolutions = payload.resolutions

    if resolutions is not None:
        updated_records = []
        resolved_usns = [res.usn.strip().upper() for res in resolutions]
        # Previous status per affected student, captured before the write.
        previous_statuses = capture_attendance_statuses(db, session_id, resolved_usns)
        for res in resolutions:
            clean_usn = res.usn.strip().upper()
            _verify_student_exists(db, clean_usn)

            # Prefer the room already on record, else the room the session
            # actually has. Never invent a room id.
            existing = crud.get_attendance_record(db, session_id, clean_usn)
            room_id = existing["room_id"] if existing else crud.resolve_session_room_id(
                db, session_id, clean_usn
            )
            if not room_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot reconcile '{clean_usn}': no room is known for session "
                        f"'{session_id}'. Supply allocation or attendance room data first."
                    ),
                )

            updated = crud.insert_attendance(
                db,
                session_id=session_id,
                usn=clean_usn,
                room_id=room_id,
                status=res.resolved_status,
                source=f"reconciled:{res.reconciled_by or 'user'}",
                confidence=res.confidence,
                upsert=True,
            )
            updated_records.append(updated)

        actor_id, actor_role = actor_identity(current_user)
        write_attendance_audit(
            db,
            actor_id=actor_id,
            actor_role=actor_role,
            session_id=session_id,
            action="ATTENDANCE_RECONCILE",
            changes=[
                AttendanceChange(
                    usn=rec["usn"],
                    old_status=previous_statuses.get(rec["usn"]),
                    new_status=rec["status"],
                )
                for rec in updated_records
            ],
        )
        db.commit()
        return {
            "reconciled_count": len(updated_records),
            "records": updated_records,
            "message": f"Successfully reconciled {len(updated_records)} attendance records.",
        }

    # ---------------------------------------------------------
    # Mode 2: Roster Reconciliation Algorithm
    # ---------------------------------------------------------
    if isinstance(payload, SessionReconcilePayload):
        if payload.uploaded_records is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either 'resolutions' or 'uploaded_records' must be provided for reconciliation.",
            )

        # Use custom roster if provided, otherwise fetch all registered students
        if payload.roster:
            roster = payload.roster
        else:
            students = crud.get_all_students(db)
            session_room = crud.resolve_session_room_id(db, session_id)
            roster = [
                {
                    "usn": s["usn"],
                    "room_id": crud.resolve_session_room_id(db, session_id, s["usn"])
                    or session_room
                    or "",
                }
                for s in students
            ]

        missing_rooms = set(payload.missing_room_ids or [])

        # Previous status per student, captured before the roster write.
        previous_statuses = capture_attendance_statuses(db, session_id)

        try:
            reconciled = crud.reconcile_session_roster(
                db,
                session_id=session_id,
                roster=roster,
                uploaded_records=payload.uploaded_records,
                missing_room_ids=missing_rooms,
                confidence_threshold=payload.confidence_threshold,
                persist=payload.persist,
            )
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

        if payload.persist:
            actor_id, actor_role = actor_identity(current_user)
            new_by_usn = {r["usn"]: r["status"] for r in reconciled}
            changes = [
                AttendanceChange(
                    usn=usn,
                    old_status=previous_statuses.get(usn),
                    new_status=new_by_usn.get(usn),
                )
                for usn in sorted(set(previous_statuses) | set(new_by_usn))
            ]
            write_attendance_audit(
                db,
                actor_id=actor_id,
                actor_role=actor_role,
                session_id=session_id,
                action="ATTENDANCE_RECONCILE",
                changes=changes,
            )
            db.commit()

        return {
            "reconciled_count": len(reconciled),
            "records": reconciled,
            "message": f"Successfully reconciled roster against session attendance with {len(reconciled)} records.",
        }

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid reconciliation payload.",
    )


# ==============================================================================
# 5. Fast-Path Attendance Correction & 60-Second Undo Endpoints
# ==============================================================================

@router.post(
    "/{record_id}/corrections",
    response_model=AttendanceCorrectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Fast-path single-student attendance correction with 60-second undo token",
)
def correct_single_attendance(
    record_id: str,
    payload: AttendanceCorrectionRequest,
    current_user: AuthenticatedUser = Depends(
        require_roles(Role.ADMIN, Role.FACULTY)
    ),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Instant execution for authorized single-student edits.

    Verifies teacher ownership of session, enforces optimistic concurrency,
    writes append-only audit entry, and returns an opaque 60-second HMAC undo token.
    """
    clean_id = record_id.strip()
    record = None
    if clean_id.isdigit():
        record = db.get(Attendance, int(clean_id))
    if record is None:
        record = db.query(Attendance).filter(Attendance.attendance_id == clean_id).first()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attendance record with ID '{clean_id}' not found.",
        )

    # Re-verify session exists & teacher is authorized
    session = crud.get_session(db, session_id=record.session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{record.session_id}' not found.",
        )
    assert_session_edit_authorized(current_user, session, db)

    current_ver = get_record_version(db, str(record.attendance_id), record.session_id, record.usn)
    if payload.expected_version is not None and payload.expected_version != current_ver:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Optimistic concurrency conflict: expected record version {payload.expected_version}, "
                f"but current version is {current_ver}. Record was modified concurrently."
            ),
        )

    old_status = record.status
    target_status = payload.new_status

    if old_status == target_status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Student '{record.usn}' is already marked as {target_status}.",
        )

    # Perform update
    record.status = target_status

    # Write audit log
    actor_id, actor_role = actor_identity(current_user)
    changes = [
        AttendanceChange(
            usn=record.usn,
            old_status=old_status,
            new_status=target_status,
            attendance_id=str(record.attendance_id),
        )
    ]
    write_attendance_audit(
        db,
        actor_id=actor_id,
        actor_role=actor_role,
        session_id=record.session_id,
        action="ATTENDANCE_CORRECTION",
        changes=changes,
        reason=payload.reason or "Single attendance fast-path correction",
    )
    db.commit()

    new_ver = get_record_version(db, str(record.attendance_id), record.session_id, record.usn)

    undo_tok, undo_exp = create_undo_token(
        actor_id=actor_id,
        record_id=str(record.attendance_id),
        session_id=record.session_id,
        usn=record.usn,
        previous_status=old_status,
        new_status=target_status,
        version=new_ver,
    )

    return {
        "record_id": str(record.attendance_id),
        "session_id": record.session_id,
        "usn": record.usn,
        "previous_status": old_status,
        "new_status": target_status,
        "new_version": new_ver,
        "undo_token": undo_tok,
        "undo_expires_at": undo_exp,
        "message": f"Successfully updated attendance for {record.usn} to {target_status}. Undo available for 60s.",
    }


@router.post(
    "/{record_id}/undo",
    response_model=AttendanceUndoResponse,
    status_code=status.HTTP_200_OK,
    summary="Compensating 60-second undo rollback for an attendance edit",
)
def undo_single_attendance_by_path(
    record_id: str,
    payload: AttendanceUndoRequest,
    current_user: AuthenticatedUser = Depends(
        require_roles(Role.ADMIN, Role.FACULTY)
    ),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Execute server-side compensating transaction within 60-second window."""
    actor_id, actor_role = actor_identity(current_user)
    return execute_undo(
        db,
        undo_token=payload.undo_token,
        actor_id=actor_id,
        actor_role=actor_role,
        expected_version=payload.expected_version,
        target_record_id=record_id.strip(),
    )


@router.post(
    "/undo",
    response_model=AttendanceUndoResponse,
    status_code=status.HTTP_200_OK,
    summary="Compensating 60-second undo rollback using token payload binding",
)
def undo_single_attendance_generic(
    payload: AttendanceUndoRequest,
    current_user: AuthenticatedUser = Depends(
        require_roles(Role.ADMIN, Role.FACULTY)
    ),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Execute server-side compensating transaction using token target binding."""
    actor_id, actor_role = actor_identity(current_user)
    return execute_undo(
        db,
        undo_token=payload.undo_token,
        actor_id=actor_id,
        actor_role=actor_role,
        expected_version=payload.expected_version,
    )

