"""Profile & Analytics Agent Tools for RollCall AI.

Provides:
- get_my_profile: Retrieve faculty profile details and mapped subjects.
- get_defaulters_analysis: Identify students with attendance below configured threshold (e.g. 75%).
"""

from __future__ import annotations

import json
import logging
from contextlib import nullcontext
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.registry import RiskTier, ToolDefinition
from app.db import crud
from app.db.connection import get_sync_session_factory
from app.db.models import Attendance, Session as DbSession, Student

logger = logging.getLogger("rollcall.agent.tools.profile_analytics")


def _get_db() -> Session:
    factory = get_sync_session_factory()
    return factory()


def get_my_profile_handler(
    actor_id: str = "anonymous",
    actor_role: str = "FACULTY",
    db: Optional[Session] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Retrieve teacher's profile details and mapped subject assignments."""
    from app.routers.profile import _ensure_profile_table

    session_ctx = db if db is not None else _get_db()
    with (session_ctx if db is None else nullcontext(db)) as dbs:
        try:
            _ensure_profile_table(dbs)
        except Exception:
            pass
        # 1. Fetch profile
        stmt = text("""
            SELECT full_name, mobile, email, branch, designation, experience_years,
                   qualifications, specialization, expertise, mastered_subjects, photo_url
            FROM user_profiles
            WHERE user_id = :uid
            LIMIT 1
        """)
        row = dbs.execute(stmt, {"uid": actor_id}).fetchone()

        # 2. Fetch assigned subjects
        subjects = crud.get_teacher_subjects(dbs, user_id=actor_id)

        profile_data = {}
        if row:
            profile_data = {
                "user_id": actor_id,
                "full_name": row[0],
                "mobile": row[1],
                "email": row[2],
                "branch": row[3],
                "designation": row[4],
                "experience_years": row[5],
                "qualifications": row[6],
                "specialization": row[7],
                "photo_url": row[10],
            }
        else:
            profile_data = {
                "user_id": actor_id,
                "full_name": actor_id,
                "email": f"{actor_id}@rollcall.internal",
                "role": actor_role,
            }

        profile_data["assigned_subjects"] = subjects
        return {
            "success": True,
            "profile": profile_data,
        }


def get_defaulters_analysis_handler(
    actor_id: str = "anonymous",
    actor_role: str = "FACULTY",
    subject_code: Optional[str] = None,
    threshold: float = 75.0,
    db: Optional[Session] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Identify students whose attendance is below the institutional threshold."""
    session_ctx = db if db is not None else _get_db()
    with (session_ctx if db is None else nullcontext(db)) as dbs:
        # Determine subjects to analyze
        assigned = crud.get_teacher_subjects(dbs, user_id=actor_id)
        if subject_code:
            clean_sub = subject_code.strip().upper()
            if "ADMIN" not in actor_role.upper() and clean_sub not in assigned and assigned:
                return {
                    "success": False,
                    "error": f"You are not assigned to subject code '{clean_sub}'.",
                }
            target_subjects = [clean_sub]
        else:
            target_subjects = assigned

        if not target_subjects:
            return {
                "success": True,
                "message": "No subjects assigned to evaluate for attendance defaulters.",
                "defaulters_count": 0,
                "defaulters": [],
            }

        # Query sessions for these subjects
        sessions = (
            db.query(DbSession)
            .filter(DbSession.subject_code.in_(target_subjects))
            .all()
        )
        session_ids = [s.session_id for s in sessions]
        if not session_ids:
            return {
                "success": True,
                "message": f"No sessions recorded yet for subjects: {', '.join(target_subjects)}.",
                "defaulters_count": 0,
                "defaulters": [],
            }

        # Query all attendance records for these sessions
        records = (
            db.query(Attendance)
            .filter(Attendance.session_id.in_(session_ids))
            .all()
        )

        student_stats: Dict[str, Dict[str, int]] = {}
        for r in records:
            usn = r.usn.upper()
            if usn not in student_stats:
                student_stats[usn] = {"total": 0, "present": 0}
            student_stats[usn]["total"] += 1
            if r.status == "PRESENT":
                student_stats[usn]["present"] += 1

        defaulters = []
        for usn, stats in student_stats.items():
            if stats["total"] == 0:
                continue
            pct = round((stats["present"] / stats["total"]) * 100.0, 1)
            if pct < threshold:
                student = crud.get_student(db, usn=usn)
                defaulters.append({
                    "usn": usn,
                    "name": student.get("name") if student else usn,
                    "branch": student.get("branch") if student else None,
                    "attended_classes": stats["present"],
                    "total_classes": stats["total"],
                    "attendance_percentage": pct,
                    "shortage_percentage": round(threshold - pct, 1),
                })

        # Sort defaulters by lowest attendance first
        defaulters.sort(key=lambda x: x["attendance_percentage"])

        return {
            "success": True,
            "threshold_percentage": threshold,
            "subjects_analyzed": target_subjects,
            "total_sessions_analyzed": len(session_ids),
            "total_students_evaluated": len(student_stats),
            "defaulters_count": len(defaulters),
            "defaulters": defaulters,
        }


# Tool Definitions
GET_MY_PROFILE_TOOL = ToolDefinition(
    name="get_my_profile",
    description="Retrieve the authenticated teacher's profile details and assigned subject codes.",
    parameters={"type": "object", "properties": {}},
    capability_family="profile",
    risk_tier=RiskTier.READ,
    allowed_roles={"FACULTY", "ADMIN", "COORDINATOR"},
    handler=get_my_profile_handler,
)

GET_DEFAULTERS_ANALYSIS_TOOL = ToolDefinition(
    name="get_defaulters_analysis",
    description="Calculate student attendance percentages and list all defaulters below the required threshold (default 75%).",
    parameters={
        "type": "object",
        "properties": {
            "subject_code": {
                "type": "string",
                "description": "Optional course code to filter (e.g. 'CS101')",
            },
            "threshold": {
                "type": "number",
                "description": "Attendance percentage threshold (default: 75.0)",
            },
        },
    },
    capability_family="reports",
    risk_tier=RiskTier.READ,
    allowed_roles={"FACULTY", "ADMIN"},
    handler=get_defaulters_analysis_handler,
)
