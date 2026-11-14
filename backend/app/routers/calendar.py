"""FastAPI router for calendar export endpoints (iCalendar RFC 5545)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.auth import Role, get_current_user, require_roles
from app.auth.session_scope import resolve_data_scope
from app.db import crud
from app.db.models import AcademicEvent, Attendance, Session as DbSession, Student
from app.dependencies import get_db
from app.health import health_band
from app.schemas.auth import AuthenticatedUser

logger = logging.getLogger("rollcall.routers.calendar")

router = APIRouter(prefix="/calendar", tags=["Calendar"])


class AcademicEventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    event_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    event_type: str = Field(default="ACADEMIC")  # HOLIDAY | EXAM | CIE | ACADEMIC | MILESTONE | WORKSHOP
    description: Optional[str] = None
    target_dept: Optional[str] = "ALL"


class AcademicEventBulkCreate(BaseModel):
    events: List[AcademicEventCreate]


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

    # Query institutional academic events for this month
    ev_stmt = (
        select(AcademicEvent)
        .where(
            or_(
                AcademicEvent.event_date.like(f"{month}%"),
                and_(AcademicEvent.end_date.isnot(None), AcademicEvent.end_date.like(f"{month}%")),
            )
        )
        .order_by(AcademicEvent.event_date.asc())
    )
    month_events = db.execute(ev_stmt).scalars().all()

    return {
        "month": month,
        "subject": subject,
        "days": results,
        "events": [e.to_dict() for e in month_events],
    }


@router.get(
    "/day",
    summary="Calendar day detail",
    description=(
        "Return all sessions for a specific date with standard session fields and academic events. "
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

    # Academic events occurring on this date
    ev_stmt = (
        select(AcademicEvent)
        .where(
            or_(
                AcademicEvent.event_date == date,
                and_(
                    AcademicEvent.event_date <= date,
                    AcademicEvent.end_date.isnot(None),
                    AcademicEvent.end_date >= date,
                ),
            )
        )
        .order_by(AcademicEvent.event_date.asc())
    )
    day_events = db.execute(ev_stmt).scalars().all()

    return {
        "date": date,
        "subject": subject,
        "sessions": items,
        "events": [e.to_dict() for e in day_events],
    }


# ==============================================================================
# Academic Calendar Events Endpoints (Institutional Calendar of Events)
# ==============================================================================

@router.get(
    "/events",
    summary="List academic calendar events",
    description="Retrieve institutional calendar events (holidays, exams, CIEs, milestones).",
)
def list_academic_events(
    month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$", description="Month in YYYY-MM format"),
    event_type: Optional[str] = Query(None, description="Filter by event type (HOLIDAY, CIE, EXAM, ACADEMIC, MILESTONE)"),
    from_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    to_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    stmt = select(AcademicEvent)
    if month:
        stmt = stmt.where(
            or_(
                AcademicEvent.event_date.like(f"{month}%"),
                and_(AcademicEvent.end_date.isnot(None), AcademicEvent.end_date.like(f"{month}%")),
            )
        )
    if event_type:
        stmt = stmt.where(func.upper(AcademicEvent.event_type) == event_type.strip().upper())
    if from_date:
        stmt = stmt.where(AcademicEvent.event_date >= from_date)
    if to_date:
        stmt = stmt.where(AcademicEvent.event_date <= to_date)

    stmt = stmt.order_by(AcademicEvent.event_date.asc())
    events = db.execute(stmt).scalars().all()
    return {
        "events": [e.to_dict() for e in events],
        "total": len(events),
    }


@router.post(
    "/events",
    status_code=status.HTTP_201_CREATED,
    summary="Create academic calendar event(s)",
    description="Register one or more institutional calendar events (ADMIN only).",
)
def create_academic_events(
    payload: Dict[str, Any],
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    created = []
    items_to_add = []

    # Support single object or list of objects
    raw_list = payload.get("events") if "events" in payload else [payload]
    if not isinstance(raw_list, list):
        raw_list = [raw_list]

    for item in raw_list:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        event_date = str(item.get("event_date") or "").strip()
        if not title or not event_date:
            continue
        ev_id = f"EVT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        ev = AcademicEvent(
            event_id=ev_id,
            title=title,
            event_date=event_date,
            end_date=item.get("end_date") or None,
            event_type=str(item.get("event_type") or "ACADEMIC").upper(),
            description=item.get("description") or None,
            target_dept=item.get("target_dept") or "ALL",
        )
        db.add(ev)
        items_to_add.append(ev)

    db.commit()
    return {
        "message": f"Successfully registered {len(items_to_add)} calendar event(s).",
        "count": len(items_to_add),
        "events": [e.to_dict() for e in items_to_add],
    }


@router.delete(
    "/events/{event_id}",
    summary="Delete academic calendar event",
    description="Remove an institutional calendar event (ADMIN only).",
)
def delete_academic_event(
    event_id: str,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    ev = db.get(AcademicEvent, event_id)
    if not ev:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Event '{event_id}' not found.")
    db.delete(ev)
    db.commit()
    return {"message": f"Event '{event_id}' removed.", "event_id": event_id}


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

    # Also include academic events in export
    ev_query = db.query(AcademicEvent)
    if month:
        ev_query = ev_query.filter(AcademicEvent.event_date.like(f"{month}%"))
    for ev in ev_query.order_by(AcademicEvent.event_date.asc()).limit(200).all():
        date_clean = (ev.event_date or "").replace("-", "")
        if not date_clean or len(date_clean) != 8:
            continue
        dtstart = f"{date_clean}T000000Z"
        dtend = f"{date_clean}T235959Z"
        summary = f"[{ev.event_type}] {ev.title}"
        desc = ev.description or f"Institutional Academic Event: {ev.title}"
        uid = f"evt-{ev.event_id}@rollcall.ai"
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

