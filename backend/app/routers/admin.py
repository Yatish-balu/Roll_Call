"""FastAPI router for administrative endpoints (N4: teacher-subject mapping management)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select, desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Role, get_current_user, require_roles
from app.db import crud
from app.db.models import Attendance, AuditLog, Session as DbSession, Student, TeacherSubject, User
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser
from app.schemas.meta import (
    TeacherSubjectAssignRequest,
    TeacherSubjectListResponse,
    TeacherSubjectMapping,
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Subject assignments can only be created for FACULTY users.",
        )

    if not target.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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


@router.delete(
    "/teacher-subjects/{mapping_id}",
    summary="Delete a teacher-subject mapping",
    description="ADMIN-only removal of a teacher-subject assignment.",
)
def delete_teacher_subject(
    mapping_id: int,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    mapping = db.get(TeacherSubject, mapping_id)
    if not mapping:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mapping with ID {mapping_id} not found.",
        )
    teacher_id = mapping.user_id
    subject_code = mapping.subject_code
    db.delete(mapping)
    crud.create_audit_entry(
        db,
        actor_id=current_user.user_id,
        action="TEACHER_SUBJECT_DELETE",
        entity_type="teacher_subject",
        entity_id=str(mapping_id),
        old_value=f"{teacher_id}:{subject_code}",
        timestamp=_utcnow_iso(),
    )
    db.commit()
    return {"success": True, "message": f"Mapping {mapping_id} deleted."}


@router.get(
    "/users",
    summary="List users by role (admin only)",
)
def list_admin_users(
    role: Optional[str] = Query(None, description="Optional role filter ('teacher' or 'admin')"),
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    stmt = select(User)
    if role:
        norm_role = "FACULTY" if role.lower() in ("teacher", "faculty") else role.upper()
        stmt = stmt.where(User.role == norm_role)
    users = db.execute(stmt).scalars().all()
    res = []
    for u in users:
        res.append({
            "user_id": u.user_id,
            "name": u.user_id.replace("_", " ").title(),
            "email": u.email,
            "role": u.role,
            "is_active": bool(u.is_active),
        })
    return res


@router.get(
    "/overview",
    summary="Institution attendance overview across all branches and rooms",
    description="Provides aggregate attendance totals, overall percentage, branch-wise and room-wise breakdowns.",
)
def get_admin_overview(
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    # Branch wise
    stmt_branch = (
        select(
            Student.branch,
            Attendance.status,
            func.count(Attendance.usn),
        )
        .join(Student, Attendance.usn == Student.usn)
        .group_by(Student.branch, Attendance.status)
    )
    rows_branch = db.execute(stmt_branch).all()
    branch_map: Dict[str, Dict[str, int]] = {}
    for branch, att_status, count in rows_branch:
        if branch not in branch_map:
            branch_map[branch] = {"present": 0, "absent": 0}
        norm_status = str(att_status).upper()
        if norm_status in ("PRESENT", "P"):
            branch_map[branch]["present"] += count
        else:
            branch_map[branch]["absent"] += count

    branch_wise = []
    for branch, counts in sorted(branch_map.items()):
        p = counts["present"]
        a = counts["absent"]
        tot = p + a
        pct = round((p / tot) * 100.0, 1) if tot > 0 else 0.0
        branch_wise.append({
            "branch": branch,
            "present": p,
            "absent": a,
            "percentage": pct,
        })

    # Room wise
    stmt_room = (
        select(
            Attendance.room_id,
            Attendance.status,
            func.count(Attendance.usn),
        )
        .group_by(Attendance.room_id, Attendance.status)
    )
    rows_room = db.execute(stmt_room).all()
    room_map: Dict[str, Dict[str, int]] = {}
    for r_id, att_status, count in rows_room:
        if r_id not in room_map:
            room_map[r_id] = {"present": 0, "absent": 0}
        norm_status = str(att_status).upper()
        if norm_status in ("PRESENT", "P"):
            room_map[r_id]["present"] += count
        else:
            room_map[r_id]["absent"] += count

    room_wise = []
    for r_id, counts in sorted(room_map.items()):
        p = counts["present"]
        a = counts["absent"]
        tot = p + a
        pct = round((p / tot) * 100.0, 1) if tot > 0 else 0.0
        room_wise.append({
            "room_id": r_id,
            "present": p,
            "absent": a,
            "percentage": pct,
        })

    # Global totals
    tot_present = sum(b["present"] for b in branch_wise)
    tot_absent = sum(b["absent"] for b in branch_wise)
    total_records = tot_present + tot_absent
    percentage = round((tot_present / total_records) * 100.0, 1) if total_records > 0 else 0.0

    return {
        "total_records": total_records,
        "present": tot_present,
        "absent": tot_absent,
        "percentage": percentage,
        "branch_wise": branch_wise,
        "room_wise": room_wise,
    }


@router.get(
    "/faculty-uploads",
    summary="Teacher upload activity summary",
    description="Lists all faculty members with last upload time and session counts.",
)
def get_faculty_uploads(
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    # Get all faculty users
    teachers = db.execute(
        select(User).where(User.role == "FACULTY").order_by(User.user_id.asc())
    ).scalars().all()

    now = datetime.now(timezone.utc)
    seven_days_ago_iso = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    res = []
    for t in teachers:
        # All sessions for this teacher
        t_sessions = db.execute(
            select(DbSession).where(DbSession.teacher_id == t.user_id)
        ).scalars().all()

        last_upload = None
        s_7d = 0
        s_sem = len(t_sessions)
        for s in t_sessions:
            created = s.created_at
            if created:
                if not last_upload or created > last_upload:
                    last_upload = created
                if created >= seven_days_ago_iso:
                    s_7d += 1

        res.append({
            "teacher_id": t.user_id,
            "name": t.user_id.replace("_", " ").title(),
            "email": t.email,
            "last_upload_utc": last_upload,
            "sessions_last_7_days": s_7d,
            "sessions_this_semester": s_sem,
        })

    return res


@router.get(
    "/audit-log",
    summary="Paginated immutable audit log reader (admin only)",
    description="Read-only view of audit trail ordered newest first. Filterable by event, actor, date range.",
)
def get_audit_log(
    event: Optional[str] = Query(None, description="Filter by event action (e.g. ATTENDANCE_EDIT, ADMIN_OVERRIDE_EVENT)"),
    actor: Optional[str] = Query(None, description="Filter by actor user ID"),
    from_date: Optional[str] = Query(None, alias="from", description="Earliest timestamp ISO or date"),
    to_date: Optional[str] = Query(None, alias="to", description="Latest timestamp ISO or date"),
    page: int = Query(1, ge=1, description="Page number starting at 1"),
    page_size: int = Query(50, ge=1, le=50, description="Records per page (max 50)"),
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    # Normalize direct Python calls vs FastAPI Query objects
    actual_event = event if isinstance(event, str) else None
    actual_actor = actor if isinstance(actor, str) else None
    actual_from = from_date if isinstance(from_date, str) else None
    actual_to = to_date if isinstance(to_date, str) else None

    stmt = select(AuditLog)

    if actual_event:
        stmt = stmt.where(AuditLog.action == actual_event)
    if actual_actor:
        stmt = stmt.where(AuditLog.actor_id == actual_actor)
    if actual_from:
        stmt = stmt.where(AuditLog.timestamp >= actual_from)
    if actual_to:
        upper_bound = f"{actual_to}T23:59:59Z" if len(actual_to) == 10 else actual_to
        stmt = stmt.where(AuditLog.timestamp <= upper_bound)

    # Count total matching rows
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.execute(count_stmt).scalar() or 0

    # Paginate and order newest first
    offset = (page - 1) * page_size
    stmt = stmt.order_by(AuditLog.log_id.desc()).offset(offset).limit(page_size)
    rows = db.execute(stmt).scalars().all()

    items = []
    for r in rows:
        items.append({
            "log_id": r.log_id,
            "event": r.action,
            "actor_id": r.actor_id,
            "session_id": r.session_id,
            "usn": r.usn,
            "old_value": r.old_value,
            "new_value": r.new_value,
            "reason": r.reason,
            "timestamp": r.timestamp,
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@router.get(
    "/defaulters.pdf",
    summary="Export official defaulter list notice board PDF (admin only)",
    description="Generates styled notice board PDF grouped by academic branch and records audit log export event.",
)
def export_defaulters_pdf(
    threshold: float = Query(75.0, ge=1.0, le=99.9, description="Defaulter threshold percentage"),
    branch: Optional[str] = Query(None, description="Optional branch filter"),
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Response:
    from tools.defaulter_tool import get_defaulters_data
    from tools.defaulter_pdf import generate_defaulter_pdf

    actual_thresh = threshold if isinstance(threshold, (int, float)) else 75.0
    actual_branch = branch if isinstance(branch, str) else None

    defaulters = get_defaulters_data(
        user=current_user,
        branch=actual_branch,
        threshold=actual_thresh,
        db=db,
    )

    pdf_bytes = generate_defaulter_pdf(
        defaulters=defaulters,
        admin_id=current_user.user_id,
        threshold=actual_thresh,
    )

    # Write audit log row: DEFAULTER_EXPORT
    crud.create_audit_entry(
        db,
        actor_id=current_user.user_id,
        action="DEFAULTER_EXPORT",
        entity_type="report",
        entity_id=f"defaulters_pdf_{actual_thresh}",
        new_value=f"count={len(defaulters)};threshold={actual_thresh}",
        timestamp=_utcnow_iso(),
    )
    db.commit()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=defaulters_list_{actual_thresh}.pdf"},
    )
