"""FastAPI router for administrative endpoints (N4: teacher-subject mapping management)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
