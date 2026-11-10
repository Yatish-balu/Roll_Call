"""Defaulter calculation engine and data retrieval (Prompt N10 / Rule D9 / T-DEF)."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.auth import Role
from app.db.models import Attendance, Session as DbSession, Student, TeacherSubject, User
from app.dependencies import get_session_factory

try:
    from config import DEFAULTER_THRESHOLD_DEFAULT
except ImportError:
    from app.config import DEFAULTER_THRESHOLD_DEFAULT


def calculate_classes_needed(conducted: int, attended: int, threshold: float = DEFAULTER_THRESHOLD_DEFAULT) -> int:
    """Calculate the minimum number of consecutive classes a student must attend to reach threshold.

    Formula (T-DEF):
    For 75%: max(0, 3*conducted - 4*attended)
    General t: max(0, ceil((t*conducted - 100*attended)/(100 - t)))
    If already >= threshold or conducted == 0: returns 0.
    """
    if conducted <= 0 or threshold >= 100.0:
        return 0

    pct = round((attended / conducted) * 100.0, 1)
    if pct >= threshold:
        return 0

    if abs(threshold - 75.0) < 1e-6:
        # Exact integer formula for 75%
        needed = 3 * conducted - 4 * attended
        return max(0, int(needed))

    num = (threshold * conducted) - (100.0 * attended)
    den = 100.0 - threshold
    needed = math.ceil(num / den)
    return max(0, int(needed))


def get_defaulters_data(
    user: Any,
    subject_code: Optional[str] = None,
    branch: Optional[str] = None,
    semester: Optional[int] = None,
    threshold: float = DEFAULTER_THRESHOLD_DEFAULT,
    *,
    db: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    """Query student attendance records, evaluate threshold strictly, and return defaulter list."""
    if isinstance(user, dict):
        actor_id = str(user.get("user_id") or "")
        role_val = user.get("role")
    else:
        actor_id = str(getattr(user, "user_id", "") or "")
        role_val = getattr(user, "role", None)

    if hasattr(role_val, "value"):
        actor_role = str(role_val.value).upper()
    else:
        actor_role = str(role_val or "").upper()
    if actor_role.endswith(".ADMIN") or actor_role == "ROLE.ADMIN":
        actor_role = "ADMIN"
    elif actor_role.endswith(".FACULTY") or actor_role == "ROLE.FACULTY":
        actor_role = "FACULTY"

    created_db = False
    if db is None:
        factory = get_session_factory()
        db = factory()
        created_db = True

    try:
        # Permission check: Teacher may only view their assigned subjects
        if actor_role != "ADMIN":
            ts_stmt = select(TeacherSubject.subject_code).where(TeacherSubject.user_id == actor_id)
            assigned_codes = [c.upper() for c in db.execute(ts_stmt).scalars().all()]

            if subject_code:
                if subject_code.upper() not in assigned_codes:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Faculty '{actor_id}' is not authorized to view defaulters for unassigned subject '{subject_code}'.",
                    )
                allowed_subjects = [subject_code.upper()]
            else:
                allowed_subjects = assigned_codes
        else:
            allowed_subjects = [subject_code.upper()] if subject_code else None

        # Build attendance aggregation query
        # Conducted = count(session_id), Attended = count(status in PRESENT, P)
        is_present_expr = func.sum(
            case(
                (Attendance.status.in_(["PRESENT", "P"]), 1),
                else_=0,
            )
        )

        stmt = (
            select(
                Student.usn,
                Student.name,
                Student.branch,
                func.count(Attendance.session_id).label("conducted"),
                is_present_expr.label("attended"),
            )
            .join(Student, Attendance.usn == Student.usn)
            .join(DbSession, Attendance.session_id == DbSession.session_id)
        )

        if allowed_subjects is not None:
            stmt = stmt.where(
                func.upper(func.coalesce(DbSession.subject_code, DbSession.subject)).in_(allowed_subjects)
            )

        if branch:
            stmt = stmt.where(func.upper(Student.branch) == branch.strip().upper())

        stmt = stmt.group_by(Student.usn, Student.name, Student.branch)
        rows = db.execute(stmt).all()

        results: List[Dict[str, Any]] = []
        for usn, name, s_branch, conducted, attended in rows:
            conducted_int = int(conducted or 0)
            attended_int = int(attended or 0)

            # Exclude conducted = 0
            if conducted_int == 0:
                continue

            pct = round((attended_int / conducted_int) * 100.0, 1)

            # Defaulter condition: strictly BELOW threshold
            if pct < threshold:
                needed = calculate_classes_needed(conducted_int, attended_int, threshold)
                results.append({
                    "usn": usn,
                    "name": name,
                    "branch": s_branch,
                    "attended": attended_int,
                    "conducted": conducted_int,
                    "percent": pct,
                    "classes_needed": needed,
                })

        # Sort by percent ascending (lowest first), then USN ascending
        results.sort(key=lambda r: (r["percent"], r["usn"]))
        return results

    finally:
        if created_db:
            db.close()
