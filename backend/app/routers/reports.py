"""FastAPI router for Report Export endpoints (Excel & PDF)."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, rate_limit_reports
from app.auth.session_scope import SessionScope, resolve_data_scope, resolve_session_scope
from app.db import crud
from app.db.models import Batch, Department, Semester, Section
from app.dependencies import get_db
from app.schemas.analytics import ExportReportRequest
from app.schemas.auth import AuthenticatedUser
from app.services.student_pdf import (
    VALID_SEMESTERS,
    build_student_query,
    describe_filters,
    export_students_pdf,
    normalise_semester,
)
from tools.export_tool import export_to_excel, export_to_pdf

logger = logging.getLogger("rollcall.routers.reports")

router = APIRouter(prefix="/reports", tags=["Reports"])

EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MEDIA_TYPE = "application/pdf"


def _gather_export_records(
    db: Session,
    scope: SessionScope,
    session_id: str | None = None,
    date: str | None = None,
) -> tuple[List[Dict[str, Any]], str]:
    """
    Fetch verified attendance records from the database based on session_id or date filter.
    Returns (records, base_filename).

    The export is restricted to sessions the caller may see, so a report can
    never become a bypass of the session visibility scope.
    """
    if session_id:
        clean_id = session_id.strip()
        sess = crud.get_session(db, session_id=clean_id)
        if not sess:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session with ID '{clean_id}' not found.",
            )
        scope.assert_allowed(sess)
        records = crud.get_session_attendance_details(db, session_id=clean_id)
        return records, f"attendance_report_{clean_id}"

    if date:
        clean_date = date.strip()
        sessions = crud.get_sessions_by_date(db, date=clean_date)
        all_records: List[Dict[str, Any]] = []
        for s in sessions:
            if not scope.allows(s):
                continue
            all_records.extend(crud.get_session_attendance_details(db, session_id=s["session_id"]))
        return all_records, f"attendance_report_{clean_date}"

    # Default: gather all session attendance the caller is allowed to see.
    all_sessions = crud.get_all_sessions(db)
    all_records: List[Dict[str, Any]] = []
    for s in all_sessions:
        if not scope.allows(s):
            continue
        all_records.extend(crud.get_session_attendance_details(db, session_id=s["session_id"]))
    return all_records, "attendance_report_all"


# ==============================================================================
# 3. Student roster export (branch + semester filters applied server-side)
# ==============================================================================

class StudentRosterExportRequest(BaseModel):
    """Filters for the student roster PDF. All filters are optional."""

    branch: Optional[str] = Field(
        None,
        max_length=50,
        description="Branch code filter (e.g. CSE). 'ALL' or null exports every branch.",
    )
    semester: Optional[int] = Field(
        None,
        ge=1,
        le=8,
        description="Semester number filter (1 - 8). Null exports every semester.",
    )
    title: Optional[str] = Field(
        None,
        max_length=120,
        description="Document title shown in the PDF header",
    )


@router.get(
    "/students/filters",
    summary="Available branch and semester filters for the student roster",
    description=(
        "Returns the branches the caller may filter by and the semesters that are "
        "configured on the server. The list is derived from the data the caller is "
        "authorised to see."
    ),
)
def get_student_roster_filters(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from sqlalchemy import distinct, select

    from app.db.models import Student

    scope = resolve_data_scope(db, current_user)
    condition = scope.student_condition()

    branch_stmt = select(distinct(Student.branch))
    if condition is not None:
        branch_stmt = branch_stmt.where(condition)
    branches = sorted({row[0] for row in db.execute(branch_stmt).all() if row[0]})

    dept_stmt = select(distinct(Department.dept_id), Department.name)
    departments = [
        {"dept_id": dept_id, "name": name}
        for dept_id, name in db.execute(dept_stmt).all()
    ]

    semester_rows = db.execute(
        select(Semester.semester_number, Semester.semester_label).order_by(
            Semester.semester_number
        )
    ).all()
    configured_semesters = sorted({int(row[0]) for row in semester_rows if row[0] is not None})

    return {
        "branches": branches,
        "departments": departments,
        "semesters": list(VALID_SEMESTERS),
        "configured_semesters": configured_semesters,
    }


@router.post(
    "/students/pdf",
    summary="Export the student roster as a filtered PDF",
    description=(
        "Generates a PDF student roster. The branch and semester filters are applied "
        "by the database query before the document is rendered, so the PDF content and "
        "the reported student count always describe the same population."
    ),
    dependencies=[Depends(rate_limit_reports)],
    responses={
        200: {
            "content": {PDF_MEDIA_TYPE: {}},
            "description": "Downloadable student roster PDF",
        },
        422: {"description": "Invalid branch or semester filter"},
        429: {"description": "Rate limit exceeded"},
    },
)
def export_student_roster_pdf(
    payload: StudentRosterExportRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    try:
        semester = normalise_semester(payload.semester)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )

    branch = (payload.branch or "").strip().upper() or None
    if branch == "ALL":
        branch = None

    scope = resolve_data_scope(db, current_user)
    stmt = build_student_query(
        scope_condition=scope.student_condition(),
        branch=branch,
        semester=semester,
    )

    students = db.execute(stmt).scalars().all()
    section_labels = {
        row.section_id: row.section_label
        for row in db.execute(select(Section)).scalars().all()
    }
    batch_labels = {
        row.batch_id: row.batch_label
        for row in db.execute(select(Batch)).scalars().all()
    }
    semester_numbers = {
        row.semester_id: row.semester_number
        for row in db.execute(select(Semester)).scalars().all()
    }

    rows: List[Dict[str, Any]] = []
    for student in students:
        rows.append(
            {
                "usn": student.usn,
                "name": student.name,
                "branch": student.branch,
                "dept_id": student.dept_id,
                "semester_id": student.semester_id,
                "semester_number": semester_numbers.get(student.semester_id),
                "section_id": student.section_id,
                "section_label": section_labels.get(student.section_id),
                "batch_id": student.batch_id,
                "batch_label": batch_labels.get(student.batch_id),
            }
        )

    title = payload.title or "RollCall AI Student Roster"
    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        export_students_pdf(
            students=rows,
            output_path=temp_path,
            title=title,
            branch=branch,
            semester=semester,
        )
        with open(temp_path, "rb") as handle:
            file_bytes = handle.read()

        filename = "student_roster.pdf"
        return Response(
            content=file_bytes,
            media_type=PDF_MEDIA_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(file_bytes)),
                "X-Student-Count": str(len(rows)),
                "X-Applied-Filters": describe_filters(branch, semester),
            },
        )
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception as exc:
            logger.warning("Failed to remove temporary student roster file %s: %s", temp_path, exc)


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
        db,
        resolve_session_scope(db, current_user),
        session_id=payload.session_id,
        date=payload.date,
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
        db,
        resolve_session_scope(db, current_user),
        session_id=payload.session_id,
        date=payload.date,
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

