"""Attendance & Document Intake Agent Tools for RollCall AI.

Provides:
- 6 Wrapped Core Legacy Tools: read_csv, read_photo, validate_attendance,
  generate_summary, query_attendance, export_attendance (preserved, never deleted).
- single_attendance_correction: Fast-path instant single-student edit with 60-second undo token.
- bulk_attendance_proposal: SENSITIVE_WRITE proposal preparation requiring explicit confirmation.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agent.registry import RiskTier, ToolDefinition
from app.db import crud
from app.db.connection import get_sync_session_factory
from app.db.models import Attendance
from app.schemas.auth import AuthenticatedUser, Role
from app.services.attendance_edits import (
    AttendanceChange,
    assert_session_edit_authorized,
    write_attendance_audit,
)
from app.services.image_pipeline import process_mobile_attendance_sheet
from app.services.undo_service import create_undo_token, get_record_version
from tools.export_tool import export_tool
from tools.query_tool import query_tool
from tools.read_csv_tool import read_csv_tool
from tools.read_photo_tool import read_photo_tool
from tools.summary_tool import summary_tool
from tools.validate_tool import validate_tool

logger = logging.getLogger("rollcall.agent.tools.attendance")


def _get_db() -> Session:
    factory = get_sync_session_factory()
    return factory()


# ------------------------------------------------------------------------------
# 1. Wrapped Core Legacy Tools (Strictly preserved, never removed)
# ------------------------------------------------------------------------------

def read_csv_handler(
    file_path: Optional[str] = None,
    csv_content: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Parse CSV attendance sheet records."""
    return read_csv_tool(file_path=file_path, csv_content=csv_content)


def read_photo_handler(
    image_path: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    session_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Process mobile photo or image path through orientation, downscale, and OCR."""
    if image_bytes is not None:
        with _get_db() as db:
            return process_mobile_attendance_sheet(
                image_bytes=image_bytes,
                session_id=session_id,
                db=db,
            )
    if image_path:
        with open(image_path, "rb") as f:
            raw_b = f.read()
        with _get_db() as db:
            return process_mobile_attendance_sheet(
                image_bytes=raw_b,
                session_id=session_id,
                db=db,
            )
    return {"success": False, "error": "No image_path or image_bytes provided."}


def validate_attendance_handler(
    records: List[Dict[str, Any]],
    session_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Validate attendance records against roster and schema rules."""
    return validate_tool(records=records, session_id=session_id)


def generate_summary_handler(
    session_id: Optional[str] = None,
    date: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Generate attendance summary metrics and percentages."""
    return summary_tool(session_id=session_id, date=date)


def query_attendance_handler(
    query_type: str = "attendance",
    session_id: Optional[str] = None,
    usn: Optional[str] = None,
    date: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Deterministic read-only querying of attendance and sessions."""
    return query_tool(
        query_type=query_type,
        session_id=session_id,
        usn=usn,
        date=date,
    )


def export_attendance_handler(
    export_format: str = "pdf",
    session_id: Optional[str] = None,
    date: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Export attendance reports to PDF or Excel formats."""
    return export_tool(export_format=export_format, session_id=session_id, date=date)


# ------------------------------------------------------------------------------
# 2. Risk-Tiered Single Attendance Correction (Fast-Path with 60s Undo)
# ------------------------------------------------------------------------------

def single_attendance_correction_handler(
    session_id: str,
    usn: str,
    new_status: str,
    actor_id: str = "anonymous",
    actor_role: str = "FACULTY",
    reason: Optional[str] = "Teacher correction",
    expected_version: Optional[int] = None,
    db: Optional[Session] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Fast-path authorized single-student edit returning an opaque 60s undo token."""
    clean_session = session_id.strip()
    clean_usn = usn.strip().upper()
    target_status = new_status.strip().upper()

    session_ctx = db if db is not None else _get_db()
    with (session_ctx if db is None else nullcontext(db)) as dbs:
        # Verify session
        session_dict = crud.get_session(dbs, session_id=clean_session)
        if not session_dict:
            return {"success": False, "error": f"Session '{clean_session}' not found."}

        # Check authorization
        role_enum = Role.ADMIN if "ADMIN" in actor_role.upper() else Role.FACULTY
        auth_user = AuthenticatedUser(
            user_id=actor_id,
            email=f"{actor_id}@rollcall.internal",
            role=role_enum,
        )
        assert_session_edit_authorized(auth_user, session_dict, dbs)

        # Retrieve attendance record (case-insensitive USN matching)
        record = (
            dbs.query(Attendance)
            .filter(
                Attendance.session_id == clean_session,
                func.upper(Attendance.usn) == clean_usn,
            )
            .first()
        )
        if not record:
            return {
                "success": False,
                "error": f"No attendance record found for student '{clean_usn}' in session '{clean_session}'.",
            }

        curr_ver = get_record_version(dbs, str(record.attendance_id), clean_session, clean_usn)
        if expected_version is not None and expected_version != curr_ver:
            return {
                "success": False,
                "error": f"Concurrency conflict: expected version {expected_version}, but found {curr_ver}.",
            }

        old_status = record.status
        if old_status == target_status:
            return {
                "success": True,
                "message": f"Student '{clean_usn}' is already marked {target_status}.",
                "record_id": str(record.attendance_id),
                "status": target_status,
            }

        record.status = target_status

        # Append-only audit
        changes = [
            AttendanceChange(
                usn=clean_usn,
                old_status=old_status,
                new_status=target_status,
                attendance_id=str(record.attendance_id),
            )
        ]
        write_attendance_audit(
            dbs,
            actor_id=actor_id,
            actor_role=actor_role,
            session_id=clean_session,
            action="ATTENDANCE_CORRECTION",
            changes=changes,
            reason=reason or "Agent single attendance correction",
        )
        dbs.commit()

        new_ver = get_record_version(dbs, str(record.attendance_id), clean_session, clean_usn)
        undo_tok, undo_exp = create_undo_token(
            actor_id=actor_id,
            record_id=str(record.attendance_id),
            session_id=clean_session,
            usn=clean_usn,
            previous_status=old_status,
            new_status=target_status,
            version=new_ver,
        )

        return {
            "success": True,
            "record_id": str(record.attendance_id),
            "session_id": clean_session,
            "usn": clean_usn,
            "previous_status": old_status,
            "new_status": target_status,
            "new_version": new_ver,
            "undo_token": undo_tok,
            "undo_expires_at": undo_exp,
            "message": f"Updated attendance for {clean_usn} to {target_status}. Undo available for 60 seconds.",
        }


# ------------------------------------------------------------------------------
# 3. Sensitive Bulk Proposal Tool (CONFIRM_REQUIRED)
# ------------------------------------------------------------------------------

def bulk_attendance_proposal_handler(
    session_id: str,
    records: List[Dict[str, Any]],
    actor_id: str = "anonymous",
    actor_role: str = "FACULTY",
    db: Optional[Session] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Prepare a proposal card for bulk changes without applying them automatically."""
    clean_session = session_id.strip()
    session_ctx = db if db is not None else _get_db()
    with (session_ctx if db is None else nullcontext(db)) as dbs:
        session_dict = crud.get_session(dbs, session_id=clean_session)
        if not session_dict:
            return {"success": False, "error": f"Session '{clean_session}' not found."}

        # Check authorization
        role_enum = Role.ADMIN if "ADMIN" in actor_role.upper() else Role.FACULTY
        auth_user = AuthenticatedUser(
            user_id=actor_id,
            email=f"{actor_id}@rollcall.internal",
            role=role_enum,
        )
        assert_session_edit_authorized(auth_user, session_dict, dbs)

        present = sum(1 for r in records if str(r.get("status", "")).upper() == "PRESENT")
        absent = sum(1 for r in records if str(r.get("status", "")).upper() == "ABSENT")
        unreviewed = sum(1 for r in records if str(r.get("status", "")).upper() in ("UNREVIEWED", "PENDING"))

        return {
            "proposal_type": "bulk_attendance_update",
            "session_id": clean_session,
            "subject": session_dict.get("subject"),
            "date": session_dict.get("date"),
            "total_records": len(records),
            "present_count": present,
            "absent_count": absent,
            "unreviewed_count": unreviewed,
            "records": records,
            "requires_confirmation": True,
        }


# Tool Definitions
READ_CSV_TOOL = ToolDefinition(
    name="read_csv",
    description="Parse student attendance records from a CSV file or CSV string.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute or relative path to CSV file"},
            "csv_content": {"type": "string", "description": "Raw CSV string data"},
        },
    },
    capability_family="attendance",
    risk_tier=RiskTier.READ,
    allowed_roles={"FACULTY", "ADMIN"},
    handler=read_csv_handler,
)

READ_PHOTO_TOOL = ToolDefinition(
    name="read_photo",
    description="Extract attendance records from a mobile photo with automatic orientation normalisation, downscale, and OCR.",
    parameters={
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "Path to photo on disk"},
            "session_id": {"type": "string", "description": "Optional session ID to reconcile against roster"},
        },
    },
    capability_family="attendance",
    risk_tier=RiskTier.READ,
    allowed_roles={"FACULTY", "ADMIN"},
    handler=read_photo_handler,
)

VALIDATE_ATTENDANCE_TOOL = ToolDefinition(
    name="validate_attendance",
    description="Validate attendance marks against enrolled student rosters and verify status tags.",
    parameters={
        "type": "object",
        "properties": {
            "records": {
                "type": "array",
                "items": {"type": "object"},
                "description": "List of attendance records with usn and status",
            },
            "session_id": {"type": "string", "description": "Optional session ID"},
        },
        "required": ["records"],
    },
    capability_family="attendance",
    risk_tier=RiskTier.READ,
    allowed_roles={"FACULTY", "ADMIN"},
    handler=validate_attendance_handler,
)

GENERATE_SUMMARY_TOOL = ToolDefinition(
    name="generate_summary",
    description="Calculate aggregate attendance percentages, counts, and absentees.",
    parameters={
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Session ID to summarize"},
            "date": {"type": "string", "description": "Date to summarize"},
        },
    },
    capability_family="attendance",
    risk_tier=RiskTier.READ,
    allowed_roles={"FACULTY", "ADMIN"},
    handler=generate_summary_handler,
)

QUERY_ATTENDANCE_TOOL = ToolDefinition(
    name="query_attendance",
    description="Search attendance marks, students, absentees, and session statistics.",
    parameters={
        "type": "object",
        "properties": {
            "query_type": {
                "type": "string",
                "enum": ["attendance", "session_stats", "absentees", "students"],
                "description": "Type of query to perform",
            },
            "session_id": {"type": "string", "description": "Target session ID"},
            "usn": {"type": "string", "description": "Target student USN"},
            "date": {"type": "string", "description": "Date in YYYY-MM-DD"},
        },
    },
    capability_family="attendance",
    risk_tier=RiskTier.READ,
    allowed_roles={"FACULTY", "ADMIN"},
    handler=query_attendance_handler,
)

EXPORT_ATTENDANCE_TOOL = ToolDefinition(
    name="export_attendance",
    description="Export verified session attendance to official PDF or Excel report formats.",
    parameters={
        "type": "object",
        "properties": {
            "export_format": {"type": "string", "enum": ["pdf", "excel"]},
            "session_id": {"type": "string", "description": "Target session ID"},
            "date": {"type": "string", "description": "Target date"},
        },
    },
    capability_family="reports",
    risk_tier=RiskTier.READ,
    allowed_roles={"FACULTY", "ADMIN"},
    handler=export_attendance_handler,
)

SINGLE_ATTENDANCE_CORRECTION_TOOL = ToolDefinition(
    name="single_attendance_correction",
    description="Instant single-student attendance status correction with automatic 60-second undo token.",
    parameters={
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Session ID"},
            "usn": {"type": "string", "description": "Student USN"},
            "new_status": {
                "type": "string",
                "enum": ["PRESENT", "ABSENT", "PENDING", "UNREVIEWED"],
                "description": "New attendance status",
            },
            "reason": {"type": "string", "description": "Reason for edit"},
            "expected_version": {"type": "integer", "description": "Optimistic concurrency version"},
        },
        "required": ["session_id", "usn", "new_status"],
    },
    capability_family="attendance",
    risk_tier=RiskTier.LOW_RISK_WRITE,
    allowed_roles={"FACULTY", "ADMIN"},
    handler=single_attendance_correction_handler,
)

BULK_ATTENDANCE_PROPOSAL_TOOL = ToolDefinition(
    name="bulk_attendance_proposal",
    description="Draft a batch attendance proposal card for multiple students requiring explicit approval before commit.",
    parameters={
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Session ID"},
            "records": {
                "type": "array",
                "items": {"type": "object"},
                "description": "List of attendance changes with usn and status",
            },
        },
        "required": ["session_id", "records"],
    },
    capability_family="attendance",
    risk_tier=RiskTier.CONFIRM_REQUIRED,
    allowed_roles={"FACULTY", "ADMIN"},
    handler=bulk_attendance_proposal_handler,
)
