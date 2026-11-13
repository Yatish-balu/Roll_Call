"""FastAPI router for calendar export endpoints (iCalendar RFC 5545)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.auth import Role, get_current_user
from app.auth.session_scope import resolve_data_scope
from app.db import crud
from app.db.models import Attendance, Session as DbSession, Student
from app.dependencies import get_db
from app.health import health_band
from app.schemas.auth import AuthenticatedUser

logger = logging.getLogger("rollcall.routers.calendar")

router = APIRouter(prefix="/calendar", tags=["Calendar"])


@router.get(
    "",
    summary="Calendar month data",
    description=(
        "Return per-day calendar data for a month: date, sessions, present, absent, "
        "percent, and colour band. Days with no sessions are not returned. "
        "Teacher sees only their assigned subjects; admin sees any subject."
    ),
)
def get_calendar_month(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$", description="Month in YYYY-MM format"),
    subject: Optional[str] = Query(None, description="Filter by subject code"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    role_str = str(current_user.role.value if hasattr(current_user.role, "value") else current_user.role).upper()

    scope = resolve_data_scope(db, current_user)

    # Validate month
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid month format. Use YYYY-MM.",
        )

    q = (
        select(
            DbSession.date,
            func.count(DbSession.session_id).label("session_count"),
            func.count(Attendance.attendance_id).label("total_attendance"),
            func.sum(
                case((Attendance.status == "PRESENT", 1), else_=0)
            ).label("present_count"),
        )
        .outerjoin(Attendance, DbSession.session_id == Attendance.session_id)
        .where(DbSession.date.like(f"{month}%"))
        .group_by(DbSession.date)
    )

    condition = scope.session_condition()
    if condition is not None:
        q = q.where(condition)
    if subject:
        q = q.where(DbSession.subject_code == subject.upper())

    rows = db.execute(q).all()

    results: List[Dict[str, Any]] = []
    for r in rows:
        total = int(r.total_attendance or 0)
        present = int(r.present_count or 0)
        pct = round((present / total) * 100, 1) if total > 0 else 0.0

        results.append(
            {
                "date": r.date,
                "sessions": int(r.session_count or 0),
                "present": present,
                "absent": total - present,
                "percent": pct,
                "band": health_band(pct),
            }
        )

    # Sort by date
    results.sort(key=lambda x: x["date"])

    return {
        "month": month,
        "subject": subject,
        "days": results,
    }


@router.get(
    "/day",
    summary="Calendar day detail",
    description=(
        "Return all sessions for a specific date with standard session fields. "
        "Teacher sees only their assigned subjects; admin sees any subject."
    ),
)
def get_calendar_day(
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Date in YYYY-MM-DD format"),
    subject: Optional[str] = Query(None, description="Filter by subject code"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    scope = resolve_data_scope(db, current_user)

    q = select(DbSession).where(DbSession.date == date)

    condition = scope.session_condition()
    if condition is not None:
        q = q.where(condition)
    if subject:
        q = q.where(DbSession.subject_code == subject.upper())

    q = q.order_by(DbSession.session_id.asc())
    sessions = db.execute(q).scalars().all()

    items = []
    for s in sessions:
        items.append(
            {
                "session_id": s.session_id,
                "date": s.date,
                "subject": s.subject,
                "subject_code": s.subject_code,
                "teacher_id": s.teacher_id,
                "room_id": getattr(s, "room_id", None),
                "lifecycle_status": s.lifecycle_status or "SCHEDULED",
            }
        )

    return {
        "date": date,
        "subject": subject,
        "sessions": items,
    }


# ==============================================================================
# Existing: GET /api/v1/calendar/export.ics
# ==============================================================================

@router.get(
    "/export.ics",
    summary="Export sessions to standard iCalendar (.ics) format",
    description="Generate RFC 5545 iCalendar data for real database attendance sessions.",
)
def export_calendar_ics(
    month: Optional[str] = Query(None, description="Month filter in YYYY-MM format"),
    subject: Optional[str] = Query(None, description="Filter by subject code"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    query = db.query(DbSession)

    if month:
        query = query.filter(DbSession.date.like(f"{month}%"))
    if subject:
        query = query.filter(DbSession.subject_code == subject.upper())

    # Faculty users only see their own sessions unless admin
    if getattr(current_user.role, "value", str(current_user.role)).upper() != "ADMIN":
        query = query.filter(DbSession.teacher_id == current_user.user_id)

    sessions = query.order_by(DbSession.date.asc()).limit(500).all()

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//RollCall AI//Attendance System//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:RollCall AI Academic Schedule",
    ]

    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for s in sessions:
        date_clean = (s.date or "").replace("-", "")
        if not date_clean or len(date_clean) != 8:
            continue
        dtstart = f"{date_clean}T090000Z"
        dtend = f"{date_clean}T100000Z"
        summary = f"{s.subject_code or s.subject or 'Class'} - RollCall Session"
        desc = f"Session ID: {s.session_id} | Subject: {s.subject or s.subject_code}"
        uid = f"sess-{s.session_id}@rollcall.ai"

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_stamp}",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{desc}",
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR\r\n")
    ics_content = "\r\n".join(lines)

    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={
            "Content-Disposition": 'attachment; filename="rollcall-schedule.ics"',
            "Cache-Control": "no-cache",
        },
    )

