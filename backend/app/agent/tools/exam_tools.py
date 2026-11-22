"""Agent tools for inspecting and querying exam hall attendance, Form-B records, and room statuses."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.registry import RiskTier, ToolDefinition
from app.db.connection import get_sync_session_factory
from app.db.models import Exam, ExamSeating, RoomAssignment

logger = logging.getLogger(__name__)


def _get_db() -> Session:
    factory = get_sync_session_factory()
    return factory()


def query_exam_status_handler(
    exam_id: Optional[str] = None,
    date_str: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Query live examination status across rooms, including Form-B submission states."""
    db = _get_db()
    try:
        stmt = select(Exam)
        if exam_id:
            stmt = stmt.where(Exam.exam_id == exam_id.strip())
        elif date_str:
            stmt = stmt.where(Exam.date == date_str.strip())
        else:
            stmt = stmt.order_by(Exam.date.desc())

        exams = list(db.scalars(stmt).all())
        if not exams:
            return {"status": "not_found", "message": "No examinations found matching query."}

        results = []
        for ex in exams:
            rooms = db.query(RoomAssignment).filter(RoomAssignment.exam_id == ex.exam_id).all()
            total_students = db.query(ExamSeating).filter(ExamSeating.exam_id == ex.exam_id).count()
            present_students = (
                db.query(ExamSeating)
                .filter(ExamSeating.exam_id == ex.exam_id, ExamSeating.status == "PRESENT")
                .count()
            )
            absent_students = total_students - present_students

            room_list = []
            for r in rooms:
                r_stds = db.query(ExamSeating).filter(ExamSeating.exam_id == ex.exam_id, ExamSeating.room_no == r.room_no).count()
                r_pres = db.query(ExamSeating).filter(ExamSeating.exam_id == ex.exam_id, ExamSeating.room_no == r.room_no, ExamSeating.status == "PRESENT").count()
                room_list.append({
                    "room_no": r.room_no,
                    "block": r.block_name,
                    "status": r.status,
                    "submitted_at": r.submitted_at,
                    "total": r_stds,
                    "present": r_pres,
                    "absent": r_stds - r_pres,
                })

            results.append({
                "exam_id": ex.exam_id,
                "name": ex.name,
                "exam_type": ex.exam_type,
                "date": ex.date,
                "time": f"{ex.start_time} - {ex.end_time}",
                "total_students": total_students,
                "present_count": present_students,
                "absent_count": absent_students,
                "attendance_percentage": round((present_students / total_students * 100), 1) if total_students > 0 else 0.0,
                "rooms": room_list,
            })

        return {"status": "success", "count": len(results), "exams": results}
    finally:
        db.close()


def query_exam_absentees_handler(
    exam_id: str,
    room_no: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Query absentees for an examination sitting, optionally filtered by room."""
    db = _get_db()
    try:
        ex = db.get(Exam, exam_id.strip())
        if not ex:
            return {"status": "not_found", "message": f"Exam '{exam_id}' not found."}

        stmt = select(ExamSeating).where(ExamSeating.exam_id == exam_id.strip(), ExamSeating.status == "ABSENT")
        if room_no:
            stmt = stmt.where(ExamSeating.room_no == room_no.strip().upper())
        stmt = stmt.order_by(ExamSeating.room_no.asc(), ExamSeating.sl_no.asc())

        absentees = list(db.scalars(stmt).all())
        out = [
            {
                "room_no": a.room_no,
                "sl_no": a.sl_no,
                "usn": a.usn,
                "name": a.name,
                "branch": a.branch,
                "seat_no": a.seat_no,
            }
            for a in absentees
        ]

        return {
            "status": "success",
            "exam_id": exam_id,
            "exam_name": ex.name,
            "room_filter": room_no,
            "total_absentees": len(out),
            "absentees": out,
        }
    finally:
        db.close()


def query_exam_branch_summary_handler(
    exam_id: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Query branch-wise attendance breakdown and percentages for an exam."""
    db = _get_db()
    try:
        ex = db.get(Exam, exam_id.strip())
        if not ex:
            return {"status": "not_found", "message": f"Exam '{exam_id}' not found."}

        seating = db.query(ExamSeating).filter(ExamSeating.exam_id == exam_id.strip()).all()
        branch_map: Dict[str, Dict[str, int]] = {}

        for s in seating:
            b = s.branch or "GEN"
            if b not in branch_map:
                branch_map[b] = {"total": 0, "present": 0, "absent": 0}
            branch_map[b]["total"] += 1
            if s.status == "PRESENT":
                branch_map[b]["present"] += 1
            else:
                branch_map[b]["absent"] += 1

        summary = []
        for branch, counts in sorted(branch_map.items()):
            tot = counts["total"]
            pres = counts["present"]
            pct = round((pres / tot * 100), 1) if tot > 0 else 0.0
            summary.append({
                "branch": branch,
                "total": tot,
                "present": pres,
                "absent": counts["absent"],
                "percentage": pct,
            })

        return {
            "status": "success",
            "exam_id": exam_id,
            "exam_name": ex.name,
            "branches": summary,
        }
    finally:
        db.close()


# Tool Definitions for Agent Catalog
QUERY_EXAM_STATUS_TOOL = ToolDefinition(
    name="query_exam_status",
    description="Query real-time status of examination sittings, room allocations, Form-B submission states, and total present/absent numbers.",
    parameters={
        "type": "object",
        "properties": {
            "exam_id": {"type": "string", "description": "Optional specific exam ID (e.g. DSCE-CIE3-NOV2026)"},
            "date_str": {"type": "string", "description": "Optional date in YYYY-MM-DD format"},
        },
    },
    risk_tier=RiskTier.READ_ONLY,
    capability_family="attendance",
    handler=query_exam_status_handler,
)

QUERY_EXAM_ABSENTEES_TOOL = ToolDefinition(
    name="query_exam_absentees",
    description="Get the detailed list of absent students (USN, name, room, branch) for an exam sitting or specific room.",
    parameters={
        "type": "object",
        "properties": {
            "exam_id": {"type": "string", "description": "Exam identifier (e.g. DSCE-CIE3-NOV2026)"},
            "room_no": {"type": "string", "description": "Optional room filter (e.g. CDS 105)"},
        },
        "required": ["exam_id"],
    },
    risk_tier=RiskTier.READ_ONLY,
    capability_family="attendance",
    handler=query_exam_absentees_handler,
)

QUERY_EXAM_BRANCH_SUMMARY_TOOL = ToolDefinition(
    name="query_exam_branch_summary",
    description="Get branch-wise student attendance numbers and percentage breakdown for an exam sitting.",
    parameters={
        "type": "object",
        "properties": {
            "exam_id": {"type": "string", "description": "Exam identifier (e.g. DSCE-CIE3-NOV2026)"},
        },
        "required": ["exam_id"],
    },
    risk_tier=RiskTier.READ_ONLY,
    capability_family="reports",
    handler=query_exam_branch_summary_handler,
)
