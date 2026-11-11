"""FastAPI router for Attendance Analytics endpoints."""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.auth.session_scope import resolve_session_scope
from app.db import crud
from app.dependencies import get_db
from app.schemas.analytics import OverallSummary, SummaryReportResponse
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

