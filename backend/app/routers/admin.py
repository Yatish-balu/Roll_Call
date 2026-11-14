"""FastAPI router for administrative endpoints (N4: teacher-subject mapping management)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

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
    summary="List all faculty teachers with assigned subjects and session stats",
    description="ADMIN-only listing of all teacher accounts with assignments and session counts.",
)
def list_teachers(
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from app.db.models import Session as DbSession, TeacherSubject, User
    users = db.query(User).filter(User.role == "FACULTY").all()
    result = []
    for u in users:
        subjects = [
            ts.subject_code for ts in db.query(TeacherSubject).filter(TeacherSubject.user_id == u.user_id).all()
        ]
        s_count = db.query(func.count(DbSession.session_id)).filter(DbSession.teacher_id == u.user_id).scalar() or 0
        result.append({
            "user_id": u.user_id,
            "teacher_id": u.user_id,
            "name": u.name or u.user_id,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "subject_codes": subjects,
            "session_count": s_count,
            "created_at": u.created_at,
        })
    return {"items": result, "total": len(result)}


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

