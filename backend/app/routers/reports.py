"""FastAPI router for Report Export endpoints (Excel & PDF)."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth import get_current_user, rate_limit_reports
from app.db import crud
from app.dependencies import get_db
from app.schemas.analytics import ExportReportRequest
from app.schemas.auth import AuthenticatedUser
from tools.export_tool import export_to_excel, export_to_pdf

logger = logging.getLogger("rollcall.routers.reports")

router = APIRouter(prefix="/reports", tags=["Reports"])

EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MEDIA_TYPE = "application/pdf"


def _gather_export_records(
    db: Session,
    session_id: str | None = None,
    date: str | None = None,
) -> tuple[List[Dict[str, Any]], str]:
    """
    Fetch verified attendance records from the database based on session_id or date filter.
    Returns (records, base_filename).
    """
    if session_id:
        clean_id = session_id.strip()
        sess = crud.get_session(db, session_id=clean_id)
        if not sess:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session with ID '{clean_id}' not found.",
            )
        records = crud.get_session_attendance_details(db, session_id=clean_id)
        return records, f"attendance_report_{clean_id}"

    if date:
        clean_date = date.strip()
        sessions = crud.get_sessions_by_date(db, date=clean_date)
        all_records: List[Dict[str, Any]] = []
        for s in sessions:
            all_records.extend(crud.get_session_attendance_details(db, session_id=s["session_id"]))
        return all_records, f"attendance_report_{clean_date}"

    # Default: gather all session attendance
    all_sessions = crud.get_all_sessions(db)
    all_records: List[Dict[str, Any]] = []
    for s in all_sessions:
        all_records.extend(crud.get_session_attendance_details(db, session_id=s["session_id"]))
    return all_records, "attendance_report_all"


# ==============================================================================
# 1. POST /api/v1/reports/export/excel
# ==============================================================================

@router.post(
    "/export/excel",
    summary="Export attendance report to Excel",
    description="Generate a downloadable multi-sheet Excel (.xlsx) report containing room summaries, branch summaries, and attendance details.",
    dependencies=[Depends(rate_limit_reports)],
    responses={
        200: {
            "content": {EXCEL_MEDIA_TYPE: {}},
            "description": "Downloadable Excel workbook",
        },
        404: {"description": "Session not found"},
        429: {"description": "Rate limit exceeded"},
    },
)
def export_excel_report(
    payload: ExportReportRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    records, base_filename = _gather_export_records(
        db, session_id=payload.session_id, date=payload.date
    )

    filename = f"{base_filename}.xlsx"

    # Use a secure temporary file, read bytes, and immediately unlink to avoid lingering disk files
    fd, temp_path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    try:
        export_to_excel(
            data=records,
            output_path=temp_path,
            overwrite=True,
            include_branch_summary=payload.include_branch_summary,
        )

        with open(temp_path, "rb") as f:
            file_bytes = f.read()

        return Response(
            content=file_bytes,
            media_type=EXCEL_MEDIA_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(file_bytes)),
            },
        )
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception as exc:
            logger.warning("Failed to remove temporary export file %s: %s", temp_path, exc)


# ==============================================================================
# 2. POST /api/v1/reports/export/pdf
# ==============================================================================

@router.post(
    "/export/pdf",
    summary="Export attendance report to PDF",
    description="Generate a downloadable professional PDF (.pdf) report using ReportLab with summary tables and detailed listings.",
    dependencies=[Depends(rate_limit_reports)],
    responses={
        200: {
            "content": {PDF_MEDIA_TYPE: {}},
            "description": "Downloadable PDF report",
        },
        404: {"description": "Session not found"},
        429: {"description": "Rate limit exceeded"},
    },
)
def export_pdf_report(
    payload: ExportReportRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    records, base_filename = _gather_export_records(
        db, session_id=payload.session_id, date=payload.date
    )

    filename = f"{base_filename}.pdf"

    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        report_title = payload.title or "RollCall AI Attendance Report"
        if payload.session_id:
            report_title = f"{report_title} - Session {payload.session_id}"
        elif payload.date:
            report_title = f"{report_title} - {payload.date}"

        export_to_pdf(
            data=records,
            output_path=temp_path,
            title=report_title,
            overwrite=True,
        )

        with open(temp_path, "rb") as f:
            file_bytes = f.read()

        return Response(
            content=file_bytes,
            media_type=PDF_MEDIA_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(file_bytes)),
            },
        )
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception as exc:
            logger.warning("Failed to remove temporary export file %s: %s", temp_path, exc)

