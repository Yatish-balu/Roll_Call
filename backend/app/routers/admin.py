"""FastAPI router for administrative endpoints (N4: teacher-subject mapping management)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import uuid
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Role, get_current_user, require_roles
from app.db import crud
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser
from app.schemas.meta import (
    AuditLogPageResponse,
    SecurityDecoyCreate,
    TeacherSubjectAssignRequest,
    TeacherSubjectListResponse,
    TeacherSubjectMapping,
)
from app.security.decoys import (
    create_decoy,
    decoy_mode,
    decoys_enabled,
    list_decoys,
)

logger = logging.getLogger("rollcall.routers.admin")

router = APIRouter(prefix="/admin", tags=["Administration"])


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get(
    "/teacher-subjects",
    response_model=TeacherSubjectListResponse,
    summary="List teacher-subject mappings",
    description="ADMIN-only listing of all teacher-subject assignments, optionally filtered by user or subject code.",
)
def list_teacher_subjects(
    user_id: Optional[str] = Query(None, description="Filter mappings by teacher user ID"),
    subject_code: Optional[str] = Query(None, description="Filter mappings by subject code"),
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    mappings = crud.list_teacher_subject_mappings(
        db, user_id=user_id, subject_code=subject_code
    )
    for m in mappings:
        if isinstance(m, dict) and "teacher_id" not in m:
            m["teacher_id"] = m.get("user_id")
    return {"items": mappings, "total": len(mappings)}


@router.get(
    "/audit-logs",
    response_model=AuditLogPageResponse,
    summary="Read the append-only audit trail",
    description=(
        "ADMIN-only, paginated read of the persisted audit trail, newest first. "
        "Filters: actor, actor role, action/event type, session, USN and a UTC date range. "
        "Only audit columns are returned; the log never contains credentials."
    ),
    responses={
        400: {"description": "Invalid date filter"},
        403: {"description": "ADMIN role required"},
    },
)
def list_audit_logs(
    actor: Optional[str] = Query(None, description="Filter by actor user id"),
    actor_role: Optional[str] = Query(None, description="Filter by the actor role at the time of the action"),
    event_type: Optional[str] = Query(None, description="Filter by action/event type (e.g. ATTENDANCE_UPSERT)"),
    action: Optional[str] = Query(None, description="Filter by action name (alias of event_type)"),
    session_id: Optional[str] = Query(None, description="Filter by session id"),
    usn: Optional[str] = Query(None, description="Filter by student USN"),
    start_date: Optional[str] = Query(None, description="Inclusive start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Inclusive end date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip before returning"),
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    for label, value in (("start_date", start_date), ("end_date", end_date)):
        if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid {label} '{value}'. Expected the YYYY-MM-DD format.",
            )

    items, total = crud.list_audit_entries(
        db,
        actor_id=actor,
        actor_role=actor_role,
        action=(event_type or action),
        session_id=session_id,
        usn=usn,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/security/decoys",
    summary="List the registered honeypot (decoy) identifiers",
    description=(
        "ADMIN-only listing of the decoy identifiers. Decoys live in their own table and are "
        "never mixed with real student, attendance or session data. Decoy probing is only "
        "active when SECURITY_DECOY_MODE is enabled by the deployment."
    ),
)
def list_security_decoys(
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    items = list_decoys(db)
    return {
        "items": items,
        "total": len(items),
        "mode": decoy_mode(),
        "enabled": decoys_enabled(),
    }


@router.post(
    "/security/decoys",
    status_code=status.HTTP_201_CREATED,
    summary="Register a honeypot (decoy) identifier",
    description=(
        "ADMIN-only. Registers an identifier that looks like master data but exists only in "
        "the decoy table. Accessing it produces a security event; it never returns decoy "
        "content to the caller and never enters the real student or attendance tables."
    ),
)
def create_security_decoy(
    payload: SecurityDecoyCreate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        decoy = create_decoy(
            db,
            decoy_kind=payload.decoy_kind,
            decoy_value=payload.decoy_value,
            note=payload.note,
            created_by=current_user.user_id,
        )
        db.commit()
        return decoy
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        db.rollback()
        logger.error("Failed to create security decoy: %s", exc)
        raise


@router.post(
    "/teacher-subjects",
    response_model=TeacherSubjectMapping,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a subject to a teacher",
    description=(
        "ADMIN-only assignment of a subject code to an active FACULTY user. "
        "The assignment is recorded in the append-only audit log."
    ),
    responses={
        404: {"description": "Target teacher does not exist"},
        409: {"description": "The teacher already has this subject assigned"},
        422: {"description": "Target user is not an active FACULTY account"},
    },
)
def assign_teacher_subject(
    payload: TeacherSubjectAssignRequest,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    target = crud.get_user(db, user_id=payload.user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID '{payload.user_id}' not found.",
        )

    if str(target.get("role", "")).upper() != "FACULTY":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Subject assignments can only be created for FACULTY users.",
        )

    if not target.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Subject assignments cannot be created for deactivated users.",
        )

    try:
        mapping = crud.assign_teacher_subject(
            db, user_id=payload.user_id, subject_code=payload.subject_code
        )
        crud.create_audit_entry(
            db,
            actor_id=current_user.user_id,
            action="TEACHER_SUBJECT_ASSIGN",
            entity_type="teacher_subject",
            entity_id=f"{payload.user_id}:{payload.subject_code}",
            new_value=payload.subject_code,
            timestamp=_utcnow_iso(),
            actor_role=getattr(current_user.role, "value", str(current_user.role)),
        )
        db.commit()
        return mapping
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Teacher '{payload.user_id}' already has subject "
                f"'{payload.subject_code}' assigned."
            ),
        )
    except Exception as exc:
        db.rollback()
        logger.error("Failed to assign subject %s to %s: %s", payload.subject_code, payload.user_id, exc)
        raise


@router.delete(
    "/teacher-subjects",
    summary="Unassign a subject from a teacher",
    description="ADMIN-only removal of a teacher-subject assignment.",
)
def remove_teacher_subject(
    user_id: str = Query(..., description="Teacher user ID"),
    subject_code: str = Query(..., description="Subject code to unassign"),
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    removed = crud.remove_teacher_subject(db, user_id=user_id, subject_code=subject_code)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assignment for teacher '{user_id}' with subject '{subject_code}' not found.",
        )
    try:
        crud.create_audit_entry(
            db,
            actor_id=current_user.user_id,
            action="TEACHER_SUBJECT_UNASSIGN",
            entity_type="teacher_subject",
            entity_id=f"{user_id}:{subject_code}",
            old_value=subject_code,
            timestamp=_utcnow_iso(),
            actor_role=getattr(current_user.role, "value", str(current_user.role)),
        )
        db.commit()
    except Exception as exc:
        logger.warning("Audit logging failed on unassign: %s", exc)
        db.commit()

    return {
        "success": True,
        "message": f"Successfully unassigned subject '{subject_code}' from teacher '{user_id}'.",
    }


class TeacherNameUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=150, description="New official display name of the faculty member")


class PermissionRequestCreate(BaseModel):
    subject_code: Optional[str] = Field(None, max_length=50, description="Requested subject code")
    request_type: str = Field("SUBJECT_ASSIGNMENT", max_length=50, description="Type of permission requested")
    reason: str = Field(..., min_length=1, max_length=500, description="Justification for permission request")


class PermissionRequestReview(BaseModel):
    decision: str = Field(..., description="'APPROVE' or 'REJECT'")
    comment: Optional[str] = Field(None, max_length=500, description="Admin review feedback")


def _ensure_permission_requests_table(db: Session) -> None:
    ddl = text("""
        CREATE TABLE IF NOT EXISTS permission_requests (
            request_id VARCHAR PRIMARY KEY,
            user_id VARCHAR NOT NULL,
            teacher_name VARCHAR,
            request_type VARCHAR NOT NULL,
            subject_code VARCHAR,
            reason TEXT,
            status VARCHAR NOT NULL DEFAULT 'PENDING',
            created_at VARCHAR NOT NULL,
            reviewed_by VARCHAR,
            reviewed_at VARCHAR,
            admin_comment TEXT
        )
    """)
    db.execute(ddl)
    db.commit()


@router.get(
    "/teachers",
    summary="List all faculty teachers with assigned subjects, session stats, and complete profile details",
    description="ADMIN-only listing of all teacher accounts with assignments, contact info, qualifications, and session counts.",
)
def list_teachers(
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from app.db.models import Session as DbSession, TeacherSubject, User
    import json
    from app.routers.profile import _ensure_profile_table
    _ensure_profile_table(db)

    users = db.query(User).filter(User.role == "FACULTY").all()
    result = []
    for u in users:
        subjects = [
            ts.subject_code for ts in db.query(TeacherSubject).filter(TeacherSubject.user_id == u.user_id).all()
        ]
        s_count = db.query(func.count(DbSession.session_id)).filter(DbSession.teacher_id == u.user_id).scalar() or 0

        # Pull complete profile details if available
        prof_row = db.execute(
            text("""
                SELECT full_name, mobile, email, branch, designation, experience_years,
                       qualifications, specialization, expertise, mastered_subjects, photo_url
                FROM user_profiles WHERE user_id = :uid
            """),
            {"uid": u.user_id},
        ).fetchone()

        full_name = u.name or u.user_id
        mobile = ""
        prof_email = u.email
        branch = ""
        designation = "Faculty"
        experience_years = 0
        qualifications = ""
        specialization = ""
        expertise = []
        mastered_subjects = []
        photo_url = ""

        if prof_row:
            if prof_row[0]:
                full_name = prof_row[0]
            if prof_row[1]:
                mobile = prof_row[1]
            if prof_row[2]:
                prof_email = prof_row[2]
            if prof_row[3]:
                branch = prof_row[3]
            if prof_row[4]:
                designation = prof_row[4]
            if prof_row[5] is not None:
                experience_years = prof_row[5]
            if prof_row[6]:
                qualifications = prof_row[6]
            if prof_row[7]:
                specialization = prof_row[7]
            if prof_row[8]:
                try:
                    expertise = json.loads(prof_row[8]) if isinstance(prof_row[8], str) else prof_row[8]
                except Exception:
                    expertise = [prof_row[8]]
            if prof_row[9]:
                try:
                    mastered_subjects = json.loads(prof_row[9]) if isinstance(prof_row[9], str) else prof_row[9]
                except Exception:
                    mastered_subjects = [prof_row[9]]
            if prof_row[10]:
                photo_url = prof_row[10]

        result.append({
            "user_id": u.user_id,
            "teacher_id": u.user_id,
            "name": full_name,
            "email": u.email,
            "profile_email": prof_email,
            "mobile": mobile,
            "branch": branch,
            "designation": designation,
            "experience_years": experience_years,
            "qualifications": qualifications,
            "specialization": specialization,
            "expertise": expertise,
            "mastered_subjects": mastered_subjects,
            "photo_url": photo_url,
            "role": u.role,
            "is_active": u.is_active,
            "subject_codes": subjects,
            "session_count": s_count,
            "created_at": u.created_at,
        })
    return {"items": result, "total": len(result)}


@router.get(
    "/teachers/{user_id}/profile",
    summary="Get complete teacher profile details (Admin only)",
    description="ADMIN-only endpoint to inspect full profile details of a specific faculty member.",
)
def get_teacher_profile(
    user_id: str,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from app.db.models import User
    import json
    from app.routers.profile import _ensure_profile_table
    _ensure_profile_table(db)

    u = db.get(User, user_id.strip())
    if u is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Teacher '{user_id}' not found.",
        )

    prof_row = db.execute(
        text("""
            SELECT full_name, mobile, email, branch, designation, experience_years,
                   qualifications, specialization, expertise, mastered_subjects, photo_url, updated_at
            FROM user_profiles WHERE user_id = :uid
        """),
        {"uid": u.user_id},
    ).fetchone()

    expertise = []
    mastered_subjects = []
    if prof_row:
        if prof_row[8]:
            try:
                expertise = json.loads(prof_row[8]) if isinstance(prof_row[8], str) else prof_row[8]
            except Exception:
                expertise = [prof_row[8]]
        if prof_row[9]:
            try:
                mastered_subjects = json.loads(prof_row[9]) if isinstance(prof_row[9], str) else prof_row[9]
            except Exception:
                mastered_subjects = [prof_row[9]]

    return {
        "user_id": u.user_id,
        "name": u.name or u.user_id,
        "email": u.email,
        "role": u.role,
        "is_active": u.is_active,
        "fullName": prof_row[0] if prof_row and prof_row[0] else (u.name or u.user_id),
        "mobile": prof_row[1] if prof_row and prof_row[1] else "",
        "profileEmail": prof_row[2] if prof_row and prof_row[2] else u.email,
        "branch": prof_row[3] if prof_row and prof_row[3] else "",
        "designation": prof_row[4] if prof_row and prof_row[4] else "Faculty",
        "experienceYears": prof_row[5] if prof_row and prof_row[5] is not None else 0,
        "qualifications": prof_row[6] if prof_row and prof_row[6] else "",
        "specialization": prof_row[7] if prof_row and prof_row[7] else "",
        "expertise": expertise,
        "masteredSubjects": mastered_subjects,
        "photoUrl": prof_row[10] if prof_row and prof_row[10] else "",
        "updatedAt": prof_row[11] if prof_row and prof_row[11] else u.created_at,
    }


@router.patch(
    "/teachers/{user_id}/name",
    summary="Update teacher's official name (Admin only)",
    description="ADMIN-only feature: only administrator has permission to change a teacher's official name.",
)
def update_teacher_name(
    user_id: str,
    payload: TeacherNameUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from app.db.models import User
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Teacher with ID '{user_id}' not found.",
        )
    old_name = user.name or user_id
    new_name = payload.name.strip()
    user.name = new_name

    try:
        db.execute(
            text("UPDATE user_profiles SET full_name = :n WHERE user_id = :u"),
            {"n": new_name, "u": user_id},
        )
    except Exception:
        pass

    crud.create_audit_entry(
        db,
        actor_id=current_user.user_id,
        action="TEACHER_NAME_UPDATE",
        entity_type="user",
        entity_id=user_id,
        old_value=old_name,
        new_value=new_name,
        timestamp=_utcnow_iso(),
        actor_role="ADMIN",
    )
    db.commit()

    return {
        "success": True,
        "user_id": user_id,
        "name": new_name,
        "message": f"Successfully updated teacher '{user_id}' name to '{new_name}'.",
    }


@router.post(
    "/permission-requests",
    summary="Submit a teacher permission or subject request",
    description="Faculty members can submit a request for subject assignment or elevated permission requiring Admin approval.",
)
def submit_permission_request(
    payload: PermissionRequestCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ensure_permission_requests_table(db)
    from app.db.models import User
    user = db.query(User).filter(User.user_id == current_user.user_id).first()
    t_name = user.name if user else current_user.user_id
    req_id = f"REQ-{uuid.uuid4().hex[:8].upper()}"
    now_iso = _utcnow_iso()

    db.execute(
        text("""
            INSERT INTO permission_requests 
            (request_id, user_id, teacher_name, request_type, subject_code, reason, status, created_at)
            VALUES (:rid, :uid, :name, :rtype, :subj, :reason, 'PENDING', :cat)
        """),
        {
            "rid": req_id,
            "uid": current_user.user_id,
            "name": t_name,
            "rtype": payload.request_type,
            "subj": payload.subject_code.upper() if payload.subject_code else None,
            "reason": payload.reason.strip(),
            "cat": now_iso,
        },
    )
    crud.create_audit_entry(
        db,
        actor_id=current_user.user_id,
        action="PERMISSION_REQUEST_SUBMITTED",
        entity_type="permission_request",
        entity_id=req_id,
        new_value=payload.subject_code or payload.request_type,
        timestamp=now_iso,
        actor_role=getattr(current_user.role, "value", str(current_user.role)),
    )
    db.commit()

    return {
        "request_id": req_id,
        "user_id": current_user.user_id,
        "teacher_name": t_name,
        "request_type": payload.request_type,
        "subject_code": payload.subject_code,
        "reason": payload.reason,
        "status": "PENDING",
        "created_at": now_iso,
    }


@router.get(
    "/permission-requests",
    summary="List permission requests",
    description="Admin sees all pending and processed teacher permission requests. Faculty members see their own requests.",
)
def list_permission_requests(
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ensure_permission_requests_table(db)
    is_admin = current_user.role == Role.ADMIN

    query = "SELECT request_id, user_id, teacher_name, request_type, subject_code, reason, status, created_at, reviewed_by, reviewed_at, admin_comment FROM permission_requests WHERE 1=1"
    params: Dict[str, Any] = {}

    if not is_admin:
        query += " AND user_id = :uid"
        params["uid"] = current_user.user_id

    if status_filter:
        query += " AND status = :st"
        params["st"] = status_filter.upper()

    query += " ORDER BY created_at DESC LIMIT 100"

    rows = db.execute(text(query), params).fetchall()
    items = [
        {
            "request_id": r[0],
            "user_id": r[1],
            "teacher_name": r[2],
            "request_type": r[3],
            "subject_code": r[4],
            "reason": r[5],
            "status": r[6],
            "created_at": r[7],
            "reviewed_by": r[8],
            "reviewed_at": r[9],
            "admin_comment": r[10],
        }
        for r in rows
    ]
    return {"items": items, "total": len(items)}


@router.post(
    "/permission-requests/{request_id}/review",
    summary="Admin review of permission request (Approve/Reject)",
    description="ADMIN-only: approve or reject a teacher permission request. If approved for a subject, the subject is automatically assigned.",
)
def review_permission_request(
    request_id: str,
    payload: PermissionRequestReview,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ensure_permission_requests_table(db)
    row = db.execute(
        text("SELECT request_id, user_id, subject_code, status FROM permission_requests WHERE request_id = :rid"),
        {"rid": request_id},
    ).fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Permission request '{request_id}' not found.",
        )

    t_user_id = row[1]
    t_subj = row[2]
    decision = payload.decision.upper()
    if decision not in ("APPROVE", "REJECT"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Decision must be either 'APPROVE' or 'REJECT'.",
        )

    new_status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    now_iso = _utcnow_iso()

    db.execute(
        text("""
            UPDATE permission_requests
            SET status = :st, reviewed_by = :rb, reviewed_at = :rat, admin_comment = :com
            WHERE request_id = :rid
        """),
        {
            "st": new_status,
            "rb": current_user.user_id,
            "rat": now_iso,
            "com": payload.comment,
            "rid": request_id,
        },
    )

    if new_status == "APPROVED" and t_subj:
        try:
            crud.assign_teacher_subject(db, user_id=t_user_id, subject_code=t_subj)
        except Exception as exc:
            logger.warning("Auto subject assignment failed: %s", exc)

    crud.create_audit_entry(
        db,
        actor_id=current_user.user_id,
        action=f"PERMISSION_REQUEST_{new_status}",
        entity_type="permission_request",
        entity_id=request_id,
        new_value=new_status,
        timestamp=now_iso,
        actor_role="ADMIN",
    )
    db.commit()

    return {
        "success": True,
        "request_id": request_id,
        "status": new_status,
        "message": f"Request {request_id} has been {new_status.lower()}.",
    }


# ==============================================================================
# N8: GET /api/admin/overview — institution-wide branch/room attendance
# ==============================================================================

@router.get(
    "/overview",
    summary="Admin attendance overview by branch and room",
    description=(
        "ADMIN-only aggregate attendance metrics: present/absent/percent per branch "
        "and per room, plus institute-wide totals. Percentages are computed in the "
        "backend; the frontend never calculates them."
    ),
)
def admin_overview(
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from tools.summary_tool import summary_tool

    sessions = crud.get_all_sessions(db)
    records: list[Dict[str, Any]] = []
    for sess in sessions:
        records.extend(
            crud.get_session_attendance_details(db, session_id=sess["session_id"])
        )

    report = summary_tool(records)
    return {
        "room_wise": report.room_wise_records(),
        "branch_wise": report.branch_wise_records(),
        "overall": report.overall,
        "total_sessions": len(sessions),
        "total_records": len(records),
    }


# ==============================================================================
# N8: GET /api/admin/faculty-uploads — per-teacher upload activity
# ==============================================================================

@router.get(
    "/faculty-uploads",
    summary="Per-teacher upload/session activity",
    description=(
        "ADMIN-only per-teacher activity: last session (upload) time in UTC, "
        "sessions created in the last 7 days, and total sessions."
    ),
)
def admin_faculty_uploads(
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from app.db.models import Session as DbSession, User

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    teachers = db.query(User).filter(User.role == "FACULTY").all()
    items = []
    for teacher in teachers:
        base = db.query(DbSession).filter(DbSession.teacher_id == teacher.user_id)
        total = base.count()
        last_at = (
            db.query(func.max(DbSession.created_at))
            .filter(DbSession.teacher_id == teacher.user_id)
            .scalar()
        )
        recent = (
            db.query(func.count(DbSession.session_id))
            .filter(
                DbSession.teacher_id == teacher.user_id,
                DbSession.created_at.isnot(None),
                DbSession.created_at >= cutoff,
            )
            .scalar()
            or 0
        )
        items.append(
            {
                "user_id": teacher.user_id,
                "name": teacher.name or teacher.user_id,
                "email": teacher.email,
                "last_upload_at_utc": last_at,
                "sessions_last_7_days": int(recent),
                "total_sessions": int(total),
            }
        )

    items.sort(key=lambda row: (row["sessions_last_7_days"], row["total_sessions"]), reverse=True)
    return {"items": items, "total": len(items), "window_days": 7}


# ==============================================================================
# N11: GET /api/admin/defaulters.pdf — admin defaulter report
# ==============================================================================

@router.get(
    "/defaulters.pdf",
    summary="Export defaulter report as PDF",
    description=(
        "ADMIN-only PDF of students strictly below the attendance threshold. "
        "Writes one DEFAULTER_EXPORT row to the audit log."
    ),
    responses={
        200: {"description": "PDF file", "content": {"application/pdf": {}}},
        403: {"description": "Admin only"},
    },
)
def export_defaulters_pdf(
    subject: Optional[str] = Query(None, description="Filter by subject code"),
    branch: Optional[str] = Query(None, description="Filter by branch"),
    semester: Optional[str] = Query(None, description="Filter by semester"),
    threshold: float = Query(75.0, gt=0, lt=100, description="Defaulter threshold percent"),
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    from fastapi.responses import Response

    from tools.defaulter_pdf import generate_defaulter_pdf

    actor_role = str(
        current_user.role.value if hasattr(current_user.role, "value") else current_user.role
    ).upper()
    pdf_bytes = generate_defaulter_pdf(
        db=db,
        actor_id=current_user.user_id,
        actor_role=actor_role,
        subject_code=subject,
        branch=branch,
        semester=semester,
        threshold=threshold,
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="defaulter_report.pdf"',
            "Cache-Control": "no-cache",
        },
    )


# ==============================================================================
# Feature 2A: POST /api/admin/timetable/bulk-assign — master timetable ingestion
# ==============================================================================

class TimetableSlotInput(BaseModel):
    day: str = Field(..., description="Day of week, e.g. 'Monday'")
    start_time: str = Field(..., description="HH:MM")
    end_time: str = Field(..., description="HH:MM")
    subject_code: str = Field(..., description="Subject code to assign")
    room_id: Optional[str] = Field(None, description="Room ID (optional)")
    session_type: Optional[str] = Field("THEORY", description="THEORY or LAB")


class BulkAssignRequest(BaseModel):
    slots: list[TimetableSlotInput] = Field(..., description="List of timetable slots to distribute")


@router.post(
    "/timetable/bulk-assign",
    status_code=status.HTTP_200_OK,
    summary="Bulk-assign master timetable slots to all matching teachers",
    description=(
        "ADMIN-only. Accepts a list of timetable slots (day, times, subject_code) and "
        "distributes each slot as a TimetableEntry to every teacher currently assigned "
        "to that subject via the faculty_subjects mapping. "
        "This creates a 'master institutional timetable' propagated to all teachers at once."
    ),
    responses={
        200: {"description": "Slots processed and distributed"},
        403: {"description": "ADMIN role required"},
    },
)
def bulk_assign_timetable_slots(
    payload: BulkAssignRequest,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from app.db.models import FacultySubject, TimetableEntry, Timetable, User
    import uuid as _uuid

    processed_slots = 0
    teachers_updated: set[str] = set()
    subjects_found: set[str] = set()

    now_iso = _utcnow_iso()

    for slot in payload.slots:
        subject_code = slot.subject_code.strip().upper()
        subjects_found.add(subject_code)

        # Find all teachers assigned to this subject
        teacher_rows = (
            db.query(FacultySubject)
            .filter(FacultySubject.subject_code == subject_code)
            .all()
        )
        if not teacher_rows:
            logger.warning("bulk-assign: no teachers found for subject %s", subject_code)
            continue

        for fs in teacher_rows:
            teacher_id = fs.user_id

            # Find or create a "master" timetable for this teacher.
            # We store master slots in a lightweight raw table to avoid needing
            # full dept/semester/section FKs.  We use a dedicated table that we
            # create on-first-use if the ORM-managed timetables table doesn't apply.
            _ensure_master_timetable_slots_table(db)

            slot_id = str(_uuid.uuid4())
            try:
                db.execute(
                    text(
                        """
                        INSERT INTO master_timetable_slots
                            (slot_id, teacher_id, subject_code, day_of_week,
                             start_time, end_time, room_id, session_type, created_at, created_by)
                        VALUES
                            (:sid, :tid, :subj, :day,
                             :st, :et, :room, :stype, :cat, :cb)
                        """
                    ),
                    {
                        "sid": slot_id,
                        "tid": teacher_id,
                        "subj": subject_code,
                        "day": slot.day.strip(),
                        "st": slot.start_time.strip(),
                        "et": slot.end_time.strip(),
                        "room": slot.room_id,
                        "stype": (slot.session_type or "THEORY").upper(),
                        "cat": now_iso,
                        "cb": current_user.user_id,
                    },
                )
                teachers_updated.add(teacher_id)
                processed_slots += 1
            except Exception as exc:
                logger.warning(
                    "bulk-assign: failed to insert slot for teacher %s / subject %s: %s",
                    teacher_id,
                    subject_code,
                    exc,
                )
                db.rollback()

    try:
        crud.create_audit_entry(
            db,
            actor_id=current_user.user_id,
            action="MASTER_TIMETABLE_BULK_ASSIGN",
            entity_type="master_timetable",
            entity_id="bulk",
            new_value=f"slots={processed_slots};teachers={len(teachers_updated)}",
            timestamp=now_iso,
            actor_role="ADMIN",
        )
        db.commit()
    except Exception as exc:
        logger.warning("bulk-assign: audit/commit failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass

    return {
        "processed_slots": processed_slots,
        "teachers_updated": sorted(teachers_updated),
        "subjects_found": sorted(subjects_found),
    }


def _ensure_master_timetable_slots_table(db: Session) -> None:
    """Create the master_timetable_slots table if it does not exist."""
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS master_timetable_slots (
                slot_id      VARCHAR PRIMARY KEY,
                teacher_id   VARCHAR NOT NULL,
                subject_code VARCHAR NOT NULL,
                day_of_week  VARCHAR NOT NULL,
                start_time   VARCHAR NOT NULL,
                end_time     VARCHAR NOT NULL,
                room_id      VARCHAR,
                session_type VARCHAR NOT NULL DEFAULT 'THEORY',
                created_at   VARCHAR NOT NULL,
                created_by   VARCHAR NOT NULL
            )
            """
        )
    )
    db.commit()


# ==============================================================================
# Feature 4B: GET /api/admin/reports/attendance-sheet.pdf
# ==============================================================================

@router.get(
    "/reports/attendance-sheet.pdf",
    summary="Consolidated multi-subject attendance sheet PDF",
    description=(
        "ADMIN-only. Generates a full attendance matrix: rows = students (USN, Name), "
        "columns = subjects, cells = attendance % for each subject. "
        "Cells strictly below the threshold are highlighted in red. "
        "Optional query params: semester, branch, threshold (default 75.0)."
    ),
    responses={
        200: {"description": "PDF file", "content": {"application/pdf": {}}},
        403: {"description": "Admin only"},
    },
)
def export_attendance_sheet_pdf(
    semester: Optional[str] = Query(None, description="Filter by semester label or number"),
    branch: Optional[str] = Query(None, description="Filter by student branch"),
    threshold: float = Query(75.0, gt=0, lt=100, description="Highlight threshold percent"),
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    from fastapi.responses import Response
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from app.db.models import Student, Attendance, Session as DbSession

    generated_at = _utcnow_iso()

    # ----- 1. Fetch students (optionally filtered by branch) ------------------
    student_q = db.query(Student)
    if branch:
        student_q = student_q.filter(Student.branch == branch.strip())
    students = student_q.order_by(Student.usn).all()

    # Optional semester filter: resolve semester_id from semester label/number
    sem_id: Optional[str] = None
    if semester:
        from sqlalchemy import text as _text
        sem_row = db.execute(
            _text(
                "SELECT semester_id FROM semesters WHERE semester_label = :sl OR CAST(semester_number AS TEXT) = :sn LIMIT 1"
            ),
            {"sl": semester.strip(), "sn": semester.strip()},
        ).fetchone()
        if sem_row:
            sem_id = sem_row[0]
        # Also filter students by semester_id if found
        if sem_id:
            students = [s for s in students if s.semester_id == sem_id]

    # ----- 2. Collect all subject_codes from sessions that have attendance ----
    rows_q = db.execute(
        text(
            """
            SELECT DISTINCT s.subject_code
            FROM sessions s
            JOIN attendance a ON a.session_id = s.session_id
            WHERE s.subject_code IS NOT NULL
            ORDER BY s.subject_code
            """
        )
    ).fetchall()
    all_subjects = [r[0] for r in rows_q if r[0]]

    if not all_subjects:
        all_subjects = []

    # ----- 3. Compute per-student per-subject attendance % -------------------
    # attendance_map[usn][subject_code] = (attended, conducted)
    attendance_map: Dict[str, Dict[str, list]] = {}
    for st in students:
        attendance_map[st.usn] = {}

    if all_subjects and students:
        usn_list = [s.usn for s in students]
        # Build a subquery: for each (usn, subject_code) pair count PRESENT vs total
        # We do this in one query for efficiency
        raw = db.execute(
            text(
                """
                SELECT a.usn, s.subject_code,
                       SUM(CASE WHEN a.status = 'PRESENT' THEN 1 ELSE 0 END) AS attended,
                       COUNT(a.attendance_id) AS conducted
                FROM attendance a
                JOIN sessions s ON s.session_id = a.session_id
                WHERE s.subject_code IS NOT NULL
                GROUP BY a.usn, s.subject_code
                """
            )
        ).fetchall()
        for row in raw:
            usn, subj, attended, conducted = row[0], row[1], row[2], row[3]
            if usn in attendance_map:
                attendance_map[usn][subj] = [int(attended), int(conducted)]

    # ----- 4. Build PDF -------------------------------------------------------
    buffer = BytesIO()
    # Use landscape A3 for wide tables
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A3),
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        title="RollCall AI - Attendance Sheet",
        author="RollCall AI",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Consolidated Attendance Sheet", styles["Title"]),
        Spacer(1, 0.1 * inch),
        Paragraph(f"Generated (UTC): {generated_at}", styles["Normal"]),
        Paragraph(
            f"Threshold: {threshold:.1f}%  |  Branch: {branch or 'All'}  |  Semester: {semester or 'All'}",
            styles["Normal"],
        ),
        Spacer(1, 0.15 * inch),
    ]

    if not students:
        story.append(Paragraph("No students match the selected filters.", styles["Normal"]))
    else:
        # Header row: USN, Name, then each subject
        header = ["USN", "Name"] + all_subjects
        table_data = [header]

        RED = colors.HexColor("#FF6B6B")
        LIGHT_RED = colors.HexColor("#FFE0E0")
        GREEN_OK = colors.HexColor("#D4EDDA")

        # Track red cell coordinates for styling
        red_cells = []

        for row_idx, st in enumerate(students, start=1):
            row = [st.usn, st.name or st.usn]
            for col_idx, subj in enumerate(all_subjects, start=2):
                pair = attendance_map.get(st.usn, {}).get(subj)
                if pair is None:
                    row.append("N/A")
                else:
                    attended, conducted = pair
                    if conducted == 0:
                        row.append("0/0")
                    else:
                        pct = (attended / conducted) * 100
                        cell_text = f"{pct:.1f}%\n({attended}/{conducted})"
                        row.append(cell_text)
                        if pct < threshold:
                            red_cells.append((col_idx, row_idx))
            table_data.append(row)

        # Dynamic column widths
        subj_col_w = max(0.65 * inch, min(1.1 * inch, 8.0 * inch / max(len(all_subjects), 1)))
        col_widths = [1.0 * inch, 1.4 * inch] + [subj_col_w] * len(all_subjects)

        tbl = Table(table_data, colWidths=col_widths, repeatRows=1)

        base_style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
            ("ALIGN", (2, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        # Apply red highlight to below-threshold cells
        for (col, row) in red_cells:
            base_style.append(("BACKGROUND", (col, row), (col, row), LIGHT_RED))
            base_style.append(("TEXTCOLOR", (col, row), (col, row), RED))

        tbl.setStyle(TableStyle(base_style))
        story.append(tbl)

    story.append(Spacer(1, 0.2 * inch))
    story.append(
        Paragraph(
            f"Cells highlighted in red are strictly below the {threshold:.1f}% threshold. "
            "RollCall AI - Attendance Sheet Report.",
            styles["Italic"],
        )
    )

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    # Audit log
    try:
        crud.create_audit_entry(
            db,
            actor_id=current_user.user_id,
            action="ATTENDANCE_SHEET_EXPORT",
            entity_type="attendance_sheet",
            entity_id=f"attendance_sheet_{generated_at}",
            new_value=f"students={len(students)};subjects={len(all_subjects)};threshold={threshold}",
            timestamp=generated_at,
            actor_role="ADMIN",
        )
        db.commit()
    except Exception as exc:
        logger.warning("attendance-sheet-pdf: audit failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="attendance_sheet.pdf"',
            "Cache-Control": "no-cache",
        },
    )


# ==============================================================================
# Feature 4C: GET /api/admin/reports/faculty-workload.pdf
# ==============================================================================

@router.get(
    "/reports/faculty-workload.pdf",
    summary="Faculty workload report PDF",
    description=(
        "ADMIN-only. Generates a PDF showing each teacher's: total sessions conducted "
        "vs expected from timetable, subjects taught, and average attendance rate. "
    ),
    responses={
        200: {"description": "PDF file", "content": {"application/pdf": {}}},
        403: {"description": "Admin only"},
    },
)
def export_faculty_workload_pdf(
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    from fastapi.responses import Response
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from app.db.models import User, FacultySubject, Session as DbSession, Attendance

    generated_at = _utcnow_iso()

    teachers = db.query(User).filter(User.role == "FACULTY").order_by(User.name).all()

    rows_data = []
    for teacher in teachers:
        teacher_id = teacher.user_id
        display_name = teacher.name or teacher_id

        # Subjects taught
        fs_rows = db.query(FacultySubject).filter(FacultySubject.user_id == teacher_id).all()
        subjects = [fs.subject_code for fs in fs_rows]

        # Sessions conducted
        sessions_conducted = (
            db.query(func.count(DbSession.session_id))
            .filter(DbSession.teacher_id == teacher_id)
            .scalar()
            or 0
        )

        # Expected sessions from master_timetable_slots (per week * ~16 weeks semester)
        # We use a simple count of unique slots as a proxy for "expected per week"
        try:
            _ensure_master_timetable_slots_table(db)
            expected_per_week = db.execute(
                text(
                    "SELECT COUNT(*) FROM master_timetable_slots WHERE teacher_id = :tid"
                ),
                {"tid": teacher_id},
            ).scalar() or 0
            expected_total = int(expected_per_week) * 16  # 16-week semester estimate
        except Exception:
            expected_total = 0

        # Average attendance rate across all their sessions
        avg_pct: Optional[float] = None
        try:
            stats = db.execute(
                text(
                    """
                    SELECT
                        SUM(CASE WHEN a.status = 'PRESENT' THEN 1 ELSE 0 END) AS total_present,
                        COUNT(a.attendance_id) AS total_records
                    FROM attendance a
                    JOIN sessions s ON s.session_id = a.session_id
                    WHERE s.teacher_id = :tid
                    """
                ),
                {"tid": teacher_id},
            ).fetchone()
            if stats and stats[1] and int(stats[1]) > 0:
                avg_pct = (int(stats[0]) / int(stats[1])) * 100
        except Exception:
            pass

        rows_data.append(
            (
                display_name,
                teacher_id,
                ", ".join(subjects) if subjects else "—",
                str(sessions_conducted),
                str(expected_total) if expected_total else "N/A",
                f"{avg_pct:.1f}%" if avg_pct is not None else "N/A",
            )
        )

    # Build PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title="RollCall AI - Faculty Workload Report",
        author="RollCall AI",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Faculty Workload Report", styles["Title"]),
        Spacer(1, 0.1 * inch),
        Paragraph(f"Generated (UTC): {generated_at}", styles["Normal"]),
        Spacer(1, 0.15 * inch),
    ]

    if not rows_data:
        story.append(Paragraph("No faculty members found.", styles["Normal"]))
    else:
        header = ["Name", "User ID", "Subjects", "Sessions\nConducted", "Sessions\nExpected", "Avg Attendance\nRate"]
        table_data = [header] + list(rows_data)
        col_widths = [1.3 * inch, 1.0 * inch, 2.1 * inch, 0.8 * inch, 0.8 * inch, 0.9 * inch]

        tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
                    ("ALIGN", (3, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("WORDWRAP", (2, 1), (2, -1), True),
                ]
            )
        )
        story.append(tbl)

    story.append(Spacer(1, 0.2 * inch))
    story.append(
        Paragraph(
            "Expected sessions = timetable slots per week × 16 weeks. RollCall AI - Faculty Workload Report.",
            styles["Italic"],
        )
    )

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    try:
        crud.create_audit_entry(
            db,
            actor_id=current_user.user_id,
            action="FACULTY_WORKLOAD_EXPORT",
            entity_type="faculty_workload_report",
            entity_id=f"workload_{generated_at}",
            new_value=f"teachers={len(rows_data)}",
            timestamp=generated_at,
            actor_role="ADMIN",
        )
        db.commit()
    except Exception as exc:
        logger.warning("faculty-workload-pdf: audit failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="faculty_workload.pdf"',
            "Cache-Control": "no-cache",
        },
    )


# ==============================================================================
# Feature 1A: POST /teachers/create — Create a new FACULTY account
# ==============================================================================

class CreateTeacherRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=100, description="Unique user ID for the new teacher")
    name: str = Field(..., min_length=1, max_length=150, description="Full name of the teacher")
    email: str = Field(..., min_length=3, max_length=200, description="Email address of the teacher")
    password: str = Field(..., min_length=6, description="Plain-text password (will be hashed server-side)")
    branch: Optional[str] = Field(None, max_length=100, description="Branch / department")
    designation: Optional[str] = Field(None, max_length=100, description="Job designation / title")
    department: Optional[str] = Field(None, max_length=100, description="Department name or ID")


@router.post(
    "/teachers/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new FACULTY teacher account",
    description=(
        "ADMIN-only. Creates a new user with role=FACULTY, hashes the supplied password with bcrypt, "
        "creates a default user_profiles row, and writes an audit log entry."
    ),
    responses={
        409: {"description": "A user with that user_id or email already exists"},
        403: {"description": "ADMIN role required"},
    },
)
def create_teacher(
    payload: CreateTeacherRequest,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    import bcrypt
    from app.routers.profile import _ensure_profile_table

    # Ensure user_profiles table exists
    _ensure_profile_table(db)

    clean_uid = payload.user_id.strip()
    clean_email = payload.email.strip().lower()

    # Hash the password using bcrypt (same as auth.py)
    hashed_pw = bcrypt.hashpw(payload.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    now_iso = _utcnow_iso()

    try:
        user = crud.create_user(
            db,
            user_id=clean_uid,
            email=clean_email,
            role="FACULTY",
            hashed_password=hashed_pw,
            is_active=1,
            created_at=now_iso,
        )
        # Set the name on the ORM object (create_user doesn't accept name param)
        from app.db.models import User as DbUser
        db_user = db.get(DbUser, clean_uid)
        if db_user is not None:
            db_user.name = payload.name.strip()

        # Create default user_profiles entry if not already present
        existing_profile = db.execute(
            text("SELECT 1 FROM user_profiles WHERE user_id = :uid"),
            {"uid": clean_uid},
        ).fetchone()
        if not existing_profile:
            db.execute(
                text("""
                    INSERT INTO user_profiles
                        (user_id, full_name, branch, designation, updated_at)
                    VALUES (:uid, :fname, :branch, :desig, :ts)
                """),
                {
                    "uid": clean_uid,
                    "fname": payload.name.strip(),
                    "branch": payload.branch or "",
                    "desig": payload.designation or "Faculty",
                    "ts": now_iso,
                },
            )

        crud.create_audit_entry(
            db,
            actor_id=current_user.user_id,
            action="TEACHER_CREATED",
            entity_type="user",
            entity_id=clean_uid,
            new_value=clean_email,
            timestamp=now_iso,
            actor_role=getattr(current_user.role, "value", str(current_user.role)),
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with user_id '{clean_uid}' or email '{clean_email}' already exists.",
        )
    except Exception as exc:
        db.rollback()
        logger.error("Failed to create teacher %s: %s", clean_uid, exc)
        raise

    return {
        "user_id": clean_uid,
        "name": payload.name.strip(),
        "email": clean_email,
        "role": "FACULTY",
        "is_active": 1,
        "branch": payload.branch,
        "designation": payload.designation,
        "department": payload.department,
        "created_at": now_iso,
    }


# ==============================================================================
# Feature 1B: PATCH /teachers/{user_id}/toggle-active — Toggle teacher active/inactive
# ==============================================================================

@router.patch(
    "/teachers/{user_id}/toggle-active",
    summary="Toggle a teacher's active/inactive status",
    description=(
        "ADMIN-only. Flips user.is_active between 0 and 1 and writes an audit log entry "
        "(TEACHER_ACTIVATED or TEACHER_DEACTIVATED)."
    ),
    responses={
        404: {"description": "Teacher not found"},
        403: {"description": "ADMIN role required"},
    },
)
def toggle_teacher_active(
    user_id: str,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from app.db.models import User as DbUser

    user = db.get(DbUser, user_id.strip())
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Teacher '{user_id}' not found.",
        )

    old_state = user.is_active
    new_state = 0 if old_state else 1
    user.is_active = new_state

    action = "TEACHER_ACTIVATED" if new_state else "TEACHER_DEACTIVATED"
    message = f"Teacher '{user_id}' has been {'activated' if new_state else 'deactivated'}."

    crud.create_audit_entry(
        db,
        actor_id=current_user.user_id,
        action=action,
        entity_type="user",
        entity_id=user_id.strip(),
        old_value=str(old_state),
        new_value=str(new_state),
        timestamp=_utcnow_iso(),
        actor_role=getattr(current_user.role, "value", str(current_user.role)),
    )
    db.commit()

    return {
        "user_id": user_id.strip(),
        "is_active": new_state,
        "message": message,
    }


# ==============================================================================
# Feature 3 (partial): POST /students/assign-proctor — Assign a proctor to students
# ==============================================================================

class AssignProctorRequest(BaseModel):
    student_usns: List[str] = Field(..., min_length=1, description="List of student USNs to assign the proctor to")
    proctor_user_id: str = Field(..., min_length=1, description="User ID of the FACULTY proctor")


def _ensure_proctor_column(db: Session) -> None:
    """Safely add proctor_id column to students table if it doesn't exist."""
    try:
        from sqlalchemy import inspect
        bind = db.get_bind()
        inspector = inspect(bind)
        col_names = {c["name"] for c in inspector.get_columns("students")}
        if "proctor_id" not in col_names:
            db.execute(
                text(
                    "ALTER TABLE students ADD COLUMN proctor_id TEXT REFERENCES users(user_id)"
                )
            )
            db.commit()
    except Exception as exc:
        logger.warning("Could not ensure proctor_id column: %s", exc)


@router.post(
    "/students/assign-proctor",
    status_code=status.HTTP_200_OK,
    summary="Assign a proctor teacher to one or more students",
    description=(
        "ADMIN-only. Verifies the proctor is an active FACULTY user, then bulk-updates "
        "proctor_id on each provided student USN. Adds the column if missing."
    ),
    responses={
        404: {"description": "Proctor teacher not found"},
        422: {"description": "Proctor is not an active FACULTY"},
        403: {"description": "ADMIN role required"},
    },
)
def assign_proctor(
    payload: AssignProctorRequest,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from app.db.models import User as DbUser

    proctor = db.get(DbUser, payload.proctor_user_id.strip())
    if proctor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{payload.proctor_user_id}' not found.",
        )
    if str(proctor.role).upper() != "FACULTY":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Proctor must be a FACULTY user.",
        )
    if not proctor.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Proctor must be an active user.",
        )

    _ensure_proctor_column(db)

    updated = 0
    now_iso = _utcnow_iso()
    for usn in payload.student_usns:
        clean_usn = usn.strip().upper()
        result = db.execute(
            text("UPDATE students SET proctor_id = :pid WHERE usn = :usn"),
            {"pid": payload.proctor_user_id.strip(), "usn": clean_usn},
        )
        updated += result.rowcount

    crud.create_audit_entry(
        db,
        actor_id=current_user.user_id,
        action="PROCTOR_ASSIGNED",
        entity_type="student",
        entity_id=payload.proctor_user_id.strip(),
        new_value=f"usns={','.join(payload.student_usns)}",
        timestamp=now_iso,
        actor_role=getattr(current_user.role, "value", str(current_user.role)),
    )
    db.commit()

    return {
        "updated": updated,
        "proctor_user_id": payload.proctor_user_id.strip(),
    }


# ==============================================================================
# Feature 3 (partial D): PATCH /students/{usn} — Edit student profile fields
# ==============================================================================

class StudentProfileEditRequest(BaseModel):
    phone: Optional[str] = Field(None, max_length=20, description="Student phone number")
    personal_email: Optional[str] = Field(None, max_length=200, description="Personal email address")
    parent_phone: Optional[str] = Field(None, max_length=20, description="Parent / guardian phone")
    semester: Optional[str] = Field(None, max_length=20, description="Semester label or number")


def _ensure_student_extra_columns(db: Session) -> None:
    """Add phone, personal_email, parent_phone columns to students if they don't exist."""
    try:
        from sqlalchemy import inspect
        bind = db.get_bind()
        inspector = inspect(bind)
        col_names = {c["name"] for c in inspector.get_columns("students")}
        for col_def in [
            ("phone", "TEXT"),
            ("personal_email", "TEXT"),
            ("parent_phone", "TEXT"),
        ]:
            if col_def[0] not in col_names:
                db.execute(
                    text(f"ALTER TABLE students ADD COLUMN {col_def[0]} {col_def[1]}")
                )
        db.commit()
    except Exception as exc:
        logger.warning("Could not ensure student extra columns: %s", exc)


@router.patch(
    "/students/{usn}",
    summary="Edit student profile fields",
    description=(
        "ADMIN-only. Updates optional student fields (phone, personal_email, parent_phone, semester). "
        "Only provided (non-None) fields are written. Writes an audit log entry."
    ),
    responses={
        404: {"description": "Student not found"},
        403: {"description": "ADMIN role required"},
    },
)
def edit_student_profile(
    usn: str,
    payload: StudentProfileEditRequest,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from app.db.models import Student as DbStudent

    clean_usn = usn.strip().upper()

    student = db.query(DbStudent).filter(DbStudent.usn == clean_usn).first()
    if student is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student '{clean_usn}' not found.",
        )

    _ensure_student_extra_columns(db)

    updates: Dict[str, Any] = {}
    if payload.phone is not None:
        updates["phone"] = payload.phone.strip()
    if payload.personal_email is not None:
        updates["personal_email"] = payload.personal_email.strip().lower()
    if payload.parent_phone is not None:
        updates["parent_phone"] = payload.parent_phone.strip()
    if payload.semester is not None:
        updates["semester"] = payload.semester.strip()

    if updates:
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["_usn"] = clean_usn
        db.execute(
            text(f"UPDATE students SET {set_clause} WHERE usn = :_usn"),  # nosec B608 - allowlisted columns, bound values
            updates,
        )

    now_iso = _utcnow_iso()
    crud.create_audit_entry(
        db,
        actor_id=current_user.user_id,
        action="STUDENT_PROFILE_EDIT",
        entity_type="student",
        entity_id=clean_usn,
        new_value=str(updates),
        timestamp=now_iso,
        actor_role=getattr(current_user.role, "value", str(current_user.role)),
    )
    db.commit()

    # Re-fetch to return fresh data
    row = db.execute(
        text("SELECT * FROM students WHERE usn = :usn"),
        {"usn": clean_usn},
    ).fetchone()

    student_dict: Dict[str, Any] = {"usn": clean_usn}
    if row is not None:
        # _mapping gives column->value
        try:
            student_dict = dict(row._mapping)
        except AttributeError:
            student_dict = dict(zip(row.keys(), row))

    return student_dict

