"""FastAPI router for calendar export endpoints (iCalendar RFC 5545)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db.models import Session as DbSession
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser

logger = logging.getLogger("rollcall.routers.calendar")

router = APIRouter(prefix="/calendar", tags=["Calendar"])


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

