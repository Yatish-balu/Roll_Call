"""FastAPI router for Attendance Analytics endpoints."""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.auth.session_scope import resolve_data_scope, resolve_session_scope
from app.db import crud
from app.dependencies import get_db
from app.schemas.analytics import (
    DefaulterStudent,
    DefaultersResponse,
    OverallSummary,
    SummaryReportResponse,
)
from app.schemas.auth import AuthenticatedUser
from tools.summary_tool import summary_tool

logger = logging.getLogger("rollcall.routers.analytics")

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _validate_iso_date(date_str: str) -> str:
    """Validate calendar date in YYYY-MM-DD format."""
    cleaned = date_str.strip()
    try:
        datetime.date.fromisoformat(cleaned)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid ISO date '{date_str}'. Expected valid calendar date in YYYY-MM-DD format.",
        )
    return cleaned


# ==============================================================================
# 1. GET /api/v1/analytics/sessions/{session_id}/summary
# ==============================================================================

@router.get(
    "/sessions/{session_id}/summary",
    response_model=SummaryReportResponse,
    summary="Get session attendance summary",
    description="Calculate room-wise, branch-wise, and overall attendance metrics for a specific session.",
    responses={
        404: {"description": "Session not found"},
    },
)
def get_session_summary(
    session_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SummaryReportResponse:
    clean_id = session_id.strip()
    session = crud.get_session(db, session_id=clean_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{clean_id}' not found.",
        )

    # Session visibility is enforced server-side: a caller may only aggregate a
    # session they are authorized to see.
    scope = resolve_session_scope(db, current_user)
    scope.assert_allowed(session)

    records = crud.get_session_attendance_details(db, session_id=clean_id)
    report = summary_tool(records)

    return SummaryReportResponse(
        room_wise=report.room_wise_records(),
        branch_wise=report.branch_wise_records(),
        overall=OverallSummary(**report.overall),
        session_id=clean_id,
        date=session.get("date"),
    )


# ==============================================================================
# 2. GET /api/v1/analytics/date/{date}/summary
# ==============================================================================

@router.get(
    "/date/{date}/summary",
    response_model=SummaryReportResponse,
    summary="Get date attendance summary",
    description="Aggregate attendance metrics across all sessions conducted on a specified date (YYYY-MM-DD).",
    responses={
        422: {"description": "Invalid date format"},
    },
)
def get_date_summary(
    date: str = Path(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Session date in YYYY-MM-DD format"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SummaryReportResponse:
    clean_date = _validate_iso_date(date)
    sessions = crud.get_sessions_by_date(db, date=clean_date)
    scope = resolve_session_scope(db, current_user)
    sessions = [s for s in sessions if scope.allows(s)]

    if not sessions:
        # Gracefully handle dates with no sessions
        return SummaryReportResponse(
            room_wise=[],
            branch_wise=[],
            overall=OverallSummary(
                present=0,
                absent=0,
                pending=0,
                unreviewed=0,
                unresolved=0,
                confirmed=0,
                total=0,
                percentage=0.0,
                confirmed_percentage=0.0,
            ),
            date=clean_date,
        )

    all_records: List[Dict[str, Any]] = []
    for sess in sessions:
        recs = crud.get_session_attendance_details(db, session_id=sess["session_id"])
        all_records.extend(recs)

    report = summary_tool(all_records)

    return SummaryReportResponse(
        room_wise=report.room_wise_records(),
        branch_wise=report.branch_wise_records(),
        overall=OverallSummary(**report.overall),
        date=clean_date,
    )


# ==============================================================================
# 4. GET /api/v1/analytics/defaulters
# ==============================================================================

@router.get(
    "/defaulters",
    response_model=DefaultersResponse,
    summary="Students below the institutional attendance threshold",
    description=(
        "Computes the defaulter registry from the verified attendance records. The "
        "percentage is the confirmed attendance (PRESENT / (PRESENT + ABSENT) * 100). "
        "Only the students the caller is authorised to see are evaluated, and the "
        "branch / subject / semester filters are applied by the database query."
    ),
)
def get_defaulters(
    branch: Optional[str] = Query(None, description="Optional branch code filter"),
    subject: Optional[str] = Query(None, description="Optional subject code filter"),
    semester: Optional[int] = Query(None, ge=1, le=8, description="Optional semester filter (1 - 8)"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DefaultersResponse:
    import math
    import os

    from sqlalchemy import func, select

    from app.db.models import Attendance, Semester, Session as DbSession, Student

    threshold = float(os.getenv("DEFAULTER_THRESHOLD_PERCENT", "75.0"))
    required = float(os.getenv("DEFAULTER_REQUIRED_PERCENT", "75.0"))

    scope = resolve_data_scope(db, current_user)

    condition = scope.student_condition()
    stmt = (
        select(
            Attendance.usn,
            Student.name,
            Student.branch,
            Attendance.status,
        )
        .join(Student, Student.usn == Attendance.usn)
        .join(DbSession, DbSession.session_id == Attendance.session_id)
    )

    if condition is not None:
        stmt = stmt.where(condition)
    if not scope.unrestricted:
        # Only the sessions the caller may see contribute to the registry.
        visible_sessions = scope.visible_session_ids(db)
        stmt = stmt.where(Attendance.session_id.in_(sorted(visible_sessions)))
    if branch and branch.strip() and branch.strip().upper() != "ALL":
        stmt = stmt.where(func.upper(Student.branch) == branch.strip().upper())
    if subject and subject.strip() and subject.strip().upper() != "ALL":
        stmt = stmt.where(func.upper(DbSession.subject_code) == subject.strip().upper())
    if semester is not None:
        semester_ids = select(Semester.semester_id).where(Semester.semester_number == semester)
        stmt = stmt.where(Student.semester_id.in_(semester_ids))

    rows = db.execute(stmt).all()

    # Aggregate the confirmed marks per student.
    stats: Dict[str, Dict[str, Any]] = {}
    for usn, name, branch_code, status in rows:
        entry = stats.setdefault(
            usn,
            {
                "usn": usn,
                "name": name,
                "branch": branch_code,
                "present": 0,
                "absent": 0,
            },
        )
        status_value = str(status or "").upper()
        if status_value == "PRESENT":
            entry["present"] += 1
        elif status_value == "ABSENT":
            entry["absent"] += 1

    semester_numbers = {
        row.semester_id: row.semester_number
        for row in db.execute(select(Semester)).scalars().all()
    }
    semester_by_usn = {
        row.usn: semester_numbers.get(row.semester_id)
        for row in db.execute(select(Student)).scalars().all()
    }

    items: List[DefaulterStudent] = []
    evaluated = 0
    for entry in stats.values():
        conducted = entry["present"] + entry["absent"]
        if conducted <= 0:
            continue
        evaluated += 1
        percentage = round((entry["present"] / conducted) * 100, 2)
        if percentage >= threshold:
            continue
        needed = 0
        if conducted > 0 and required > 0:
            target = math.ceil((required / 100.0) * conducted)
            needed = max(0, target - entry["present"])
        items.append(
            DefaulterStudent(
                usn=entry["usn"],
                student_name=entry["name"],
                branch=entry["branch"],
                attended_classes=entry["present"],
                conducted_classes=conducted,
                attendance_percentage=percentage,
                classes_needed_to_recover=needed,
                semester=semester_by_usn.get(entry["usn"]),
            )
        )

    items.sort(key=lambda item: item.attendance_percentage)
    return DefaultersResponse(
        threshold_percent=threshold,
        required_percent=required,
        total_defaulters=len(items),
        items=items,
        evaluated_students=evaluated,
    )


# ==============================================================================
# 3. GET /api/v1/analytics/overview
# ==============================================================================

@router.get(
    "/overview",
    response_model=SummaryReportResponse,
    summary="Get institute-wide attendance overview",
    description="Calculate aggregate attendance metrics across all registered sessions and records in the system.",
)
def get_overall_overview(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SummaryReportResponse:
    sessions = crud.get_all_sessions(db)
    scope = resolve_session_scope(db, current_user)
    sessions = [s for s in sessions if scope.allows(s)]
    all_records: List[Dict[str, Any]] = []
    for sess in sessions:
        recs = crud.get_session_attendance_details(db, session_id=sess["session_id"])
        all_records.extend(recs)

    report = summary_tool(all_records)

    return SummaryReportResponse(
        room_wise=report.room_wise_records(),
        branch_wise=report.branch_wise_records(),
        overall=OverallSummary(**report.overall),
    )

