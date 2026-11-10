"""FastAPI router for Calendar month heatmap data and day detail (Prompt N13)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user, Role
from app.db import crud
from app.db.models import Attendance, Session as DbSession, TeacherSubject
from app.dependencies import get_db
from app.health import health_band
from app.policy import is_editable, editable_until
from app.schemas.auth import AuthenticatedUser

router = APIRouter(prefix="/calendar", tags=["Calendar"])


def _check_subject_scope(
    user: AuthenticatedUser,
    subject: Optional[str],
    db: Session,
) -> Optional[List[str]]:
    """Verify teacher subject authorization and return allowed uppercase subject codes."""
    actual_subj = subject if isinstance(subject, str) else None
    role_str = str(user.role).upper()
    is_admin = role_str == "ADMIN" or role_str.endswith(".ADMIN")

    if is_admin:
        return [actual_subj.strip().upper()] if actual_subj else None

    # Teacher role: look up assigned subjects
    ts_stmt = select(TeacherSubject.subject_code).where(TeacherSubject.user_id == user.user_id)
    assigned = [c.upper() for c in db.execute(ts_stmt).scalars().all()]

    if actual_subj:
        clean_subj = actual_subj.strip().upper()
        if clean_subj not in assigned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Teacher '{user.user_id}' is not assigned to subject '{actual_subj}'.",
            )
        return [clean_subj]

    return assigned


@router.get(
    "",
    summary="Get calendar month attendance aggregation for heatmap",
    description="Returns aggregate attendance counts, percent, and health bands per active day.",
)
def get_calendar_month(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$", description="Month in YYYY-MM format"),
    subject: Optional[str] = Query(None, description="Optional subject code filter"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    # Validate month format
    if not re.match(r"^\d{4}-\d{2}$", month):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Month parameter must be in YYYY-MM format.",
        )

    allowed_subjects = _check_subject_scope(current_user, subject, db)

    # If teacher has zero assigned subjects, return empty
    if allowed_subjects is not None and len(allowed_subjects) == 0:
        return []

    # Query daily attendance totals
    month_pattern = f"{month}-%"
    stmt = (
        select(
            DbSession.date,
            func.count(func.distinct(DbSession.session_id)).label("sessions"),
            func.sum(
                case(
                    (Attendance.status.in_(["PRESENT", "P"]), 1),
                    else_=0,
                )
            ).label("present"),
            func.sum(
                case(
                    (Attendance.status.in_(["ABSENT", "A"]), 1),
                    else_=0,
                )
            ).label("absent"),
        )
        .join(Attendance, DbSession.session_id == Attendance.session_id)
        .where(DbSession.date.like(month_pattern))
    )

    if allowed_subjects is not None:
        stmt = stmt.where(
            func.upper(func.coalesce(DbSession.subject_code, DbSession.subject)).in_(allowed_subjects)
        )

    stmt = stmt.group_by(DbSession.date).order_by(DbSession.date.asc())
    rows = db.execute(stmt).all()

    days = []
    for d_date, sess_count, present_count, absent_count in rows:
        p = int(present_count or 0)
        a = int(absent_count or 0)
        tot = p + a
        pct = round((p / tot) * 100.0, 1) if tot > 0 else 0.0
        band = health_band(pct)

        days.append({
            "date": d_date,
            "sessions": int(sess_count or 0),
            "present": p,
            "absent": a,
            "percent": pct,
            "band": band,
        })

    return days


@router.get(
    "/day",
    summary="Get session details for a specific calendar date",
    description="Returns session records for that day with computed lock and editable flags.",
)
def get_calendar_day(
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Date in YYYY-MM-DD format"),
    subject: Optional[str] = Query(None, description="Optional subject code filter"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Date parameter must be in YYYY-MM-DD format.",
        )

    allowed_subjects = _check_subject_scope(current_user, subject, db)
    if allowed_subjects is not None and len(allowed_subjects) == 0:
        return []

    stmt = select(DbSession).where(DbSession.date == date)
    if allowed_subjects is not None:
        stmt = stmt.where(
            func.upper(func.coalesce(DbSession.subject_code, DbSession.subject)).in_(allowed_subjects)
        )

    stmt = stmt.order_by(DbSession.session_id.asc())
    sessions = db.execute(stmt).scalars().all()

    result = []
    for s in sessions:
        created_at = s.created_at
        editable = is_editable(created_at, current_user.role)
        until_iso = None
        if created_at:
            try:
                until_iso = editable_until(created_at).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                until_iso = None

        result.append({
            "session_id": s.session_id,
            "date": s.date,
            "subject": s.subject,
            "subject_code": s.subject_code,
            "teacher_id": s.teacher_id,
            "created_at_utc": created_at,
            "editable": editable,
            "locked": not editable,
            "editable_until_utc": until_iso,
        })

    return result
