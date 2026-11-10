"""FastAPI router for Attendance and Reconciliation endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Role, get_current_user, require_roles
from app.db import crud
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser
from app.schemas.attendance import (
    AttendanceBulkCreate,
    AttendanceCreate,
    AttendanceDetailResponse,
    AttendanceResponse,
    BulkReconcileRequest,
    ReconcileRequest,
    SessionReconcilePayload,
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

    ADMIN keeps institutional access to every session. FACULTY access is allowed
    only when one of these holds:
      * the session is attributed to that faculty member,
      * the session is attributed to nobody / the legacy sentinel AND the
        faculty is mapped to the session's subject code (``teacher_subjects``)
        or is the session coordinator.

    Legacy sessions are never assigned to anybody, but they are no longer
    world-readable by every faculty account: an unmapped faculty member is
    denied, and an authorized administrator can grant access by adding the
    subject-code mapping. Historical attendance data is not modified.
    """
    if current_user.role == Role.ADMIN:
        return
    # Every non-admin role is authorized the same way (ownership / coordinator /
    # subject mapping); write endpoints are separately role-gated.
    owner = session.get("teacher_id")
    owned = owner is not None and str(owner).strip() not in ("", "legacy")

    if owned:
        if str(owner).strip() == current_user.user_id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Forbidden: session '{session.get('session_id')}' is assigned to another "
                "faculty member. You can only access your own sessions."
            ),
        )

    # Unowned / legacy session: authorize by subject mapping, never by guesswork.
    coordinator = session.get("coordinator_faculty_id")
    if coordinator and str(coordinator).strip() == current_user.user_id:
        return

    subject_code = str(session.get("subject_code") or "").strip()
    if subject_code and db is not None and crud.is_teacher_assigned_to_subject(
        db, current_user.user_id, subject_code
    ):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            f"Forbidden: session '{session.get('session_id')}' has no faculty owner and "
            + (
                f"subject code '{subject_code}' is not mapped to your account."
                if subject_code
                else "no subject code, so access requires an administrator."
            )
        ),
    )


def _verify_room_exists(db: Session, room_id: str) -> Dict[str, Any]:
    """Verify room exists in database; raise 404 if missing."""
    clean_id = room_id.strip()
    room = crud.get_room(db, room_id=clean_id)
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room with ID '{clean_id}' not found.",
        )
    return room


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
    except Exception as exc:
        db.rollback()
        logger.error("Failed to record attendance: %s", exc)
        raise

    try:
        # Audit is part of the same transaction: an unauditable write is rejected.
        crud.create_audit_entry(
            db,
            actor_id=current_user.user_id,
            action="ATTENDANCE_UPSERT" if existing else "ATTENDANCE_RECORD",
            entity_type="attendance",
            entity_id=record["attendance_id"],
            session_id=session_id,
            usn=clean_usn,
            old_value=existing.get("status") if existing else None,
            new_value=record["status"],
            timestamp=_utcnow_iso(),
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

    # Validate foreign keys
    for r in payload.records:
        clean_usn = r.usn.strip().upper()
        _verify_student_exists(db, clean_usn)
        _verify_room_exists(db, r.room_id)
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
            "room_id": r.room_id.strip(),
            "status": r.status,
            "source": r.source,
            "confidence": r.confidence,
        }
        for r in payload.records
    ]

    try:
        count = crud.insert_attendance_bulk(db, records=formatted_records, upsert=upsert)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bulk insert failed due to duplicate or conflicting attendance records.",
        )
    except Exception as exc:
        db.rollback()
        logger.error("Error during bulk attendance insertion: %s", exc)
        raise

    try:
        crud.create_audit_entry(
            db,
            actor_id=current_user.user_id,
            action="ATTENDANCE_BULK_UPSERT" if upsert else "ATTENDANCE_BULK",
            entity_type="attendance",
            entity_id=session_id,
            session_id=session_id,
            new_value=f"{count} records",
            timestamp=_utcnow_iso(),
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

    # Validate foreign keys
    for r in payload.records:
        clean_usn = r.usn.strip().upper()
        _verify_student_exists(db, clean_usn)
        _verify_room_exists(db, r.room_id)

    formatted_records = [
        {
            "session_id": session_id.strip(),
            "usn": r.usn.strip().upper(),
            "room_id": r.room_id.strip(),
            "status": r.status,
            "source": r.source,
            "confidence": r.confidence,
        }
        for r in payload.records
    ]

    try:
        replaced_count = crud.replace_session_attendance(
            db, session_id=session_id, records=formatted_records
        )
        crud.create_audit_entry(
            db,
            actor_id=current_user.user_id,
            action="ATTENDANCE_REPLACE",
            entity_type="attendance",
            entity_id=session_id,
            session_id=session_id,
            new_value=f"{replaced_count} records",
            timestamp=_utcnow_iso(),
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
    try:
        deleted_count = crud.delete_session_attendance(db, session_id=session_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    crud.create_audit_entry(
        db,
        actor_id=current_user.user_id,
        action="ATTENDANCE_DELETE",
        entity_type="attendance",
        entity_id=session_id,
        session_id=session_id,
        old_value=f"{deleted_count} records",
        timestamp=_utcnow_iso(),
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
    description="Retrieve all historical attendance marks for a given student.",
    responses={
        404: {"description": "Student not found"},
    },
)
def get_student_attendance_history(
    usn: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    clean_usn = usn.strip().upper()
    _verify_student_exists(db, clean_usn)
    return crud.get_attendance_by_student(db, usn=clean_usn)


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

        crud.create_audit_entry(
            db,
            actor_id=current_user.user_id,
            action="ATTENDANCE_RECONCILE",
            entity_type="attendance",
            entity_id=session_id,
            session_id=session_id,
            new_value=f"{len(updated_records)} resolutions",
            timestamp=_utcnow_iso(),
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
            crud.create_audit_entry(
                db,
                actor_id=current_user.user_id,
                action="ATTENDANCE_RECONCILE",
                entity_type="attendance",
                entity_id=session_id,
                session_id=session_id,
                new_value=f"{len(reconciled)} reconciled records",
                timestamp=_utcnow_iso(),
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
