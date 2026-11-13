"""N10: Defaulter engine — per-student attendance percentage and recovery count.

Computes, for each student, their attendance percentage and the number of
additional classes they would need to attend to reach the required threshold.
A student is a defaulter only when their percentage is strictly below the
threshold (75.0 is NOT a defaulter).

Formula for threshold t:
    classes_needed = max(0, ceil((t * conducted - 100 * attended) / (100 - t)))
    For t=75: classes_needed = max(0, 3*conducted - 4*attended)

All math is done in Python from database query results.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import DEFAULTER_THRESHOLD_PERCENT, DEFAULTER_REQUIRED_PERCENT
from app.db import crud
from app.db.models import Attendance, Session as DbSession, Student


def classes_needed_for_threshold(
    attended: int, conducted: int, threshold: float = DEFAULTER_THRESHOLD_PERCENT
) -> int:
    """Return the number of additional PRESENT classes needed to reach *threshold*.

    Solves (attended + x) / (conducted + x) = threshold / 100 for x, rounded up.
    Returns 0 when already at or above threshold, or when conducted is 0.
    """
    if conducted <= 0:
        return 0
    pct = (attended / conducted) * 100
    if pct >= threshold:
        return 0
    # x = (threshold * conducted - 100 * attended) / (100 - threshold)
    numerator = threshold * conducted - 100 * attended
    denominator = 100 - threshold
    if denominator <= 0:
        return 0
    return max(0, math.ceil(numerator / denominator))


def classes_needed_for_75(attended: int, conducted: int) -> int:
    """Convenience wrapper for the 75% threshold: max(0, 3*conducted - 4*attended)."""
    return classes_needed_for_threshold(attended, conducted, 75.0)


def defaulters(
    db: Session,
    actor_id: str = "anonymous",
    actor_role: str = "FACULTY",
    assigned_subjects: Optional[List[str]] = None,
    subject_code: Optional[str] = None,
    branch: Optional[str] = None,
    semester: Optional[str] = None,
    threshold: float = DEFAULTER_THRESHOLD_PERCENT,
    required_percent: float = DEFAULTER_REQUIRED_PERCENT,
) -> Dict[str, Any]:
    """Return per-student defaulter analysis scoped to the caller's role.

    Teachers see only their assigned subjects; admins see all branches.
    Students with conducted == 0 are excluded (no division by zero).
    Results are sorted by percent, lowest first.

    Returns:
        {
            "status": "success",
            "threshold": float,
            "required_percent": float,
            "defaulter_count": int,
            "students": [
                {
                    "usn": str,
                    "name": str,
                    "branch": str,
                    "attended": int,
                    "conducted": int,
                    "percent": float,   # 1 decimal
                    "classes_needed": int,
                    "is_defaulter": bool,
                },
                ...
            ],
        }
    """
    user_subjects = assigned_subjects or []

    # Base query: join attendance with sessions for subject scoping
    q = (
        select(
            Student.usn,
            Student.name,
            Student.branch,
            func.count(Attendance.attendance_id).label("conducted"),
            func.sum(
                func.case((Attendance.status == "PRESENT", 1), else_=0)
            ).label("attended"),
        )
        .join(Attendance, Attendance.usn == Student.usn)
        .join(DbSession, Attendance.session_id == DbSession.session_id)
        .group_by(Student.usn, Student.name, Student.branch)
    )

    conditions: List[Any] = []
    if actor_role.upper() == "FACULTY" and user_subjects:
        conditions.append(DbSession.subject_code.in_(user_subjects))
    if subject_code:
        conditions.append(DbSession.subject_code == subject_code.upper())
    if branch:
        conditions.append(func.upper(Student.branch) == branch.upper())
    if semester:
        conditions.append(Student.semester_id == semester)

    if conditions:
        from sqlalchemy import and_

        q = q.where(and_(*conditions))

    # Exclude students with no attendance records (conducted == 0)
    q = q.having(func.count(Attendance.attendance_id) > 0)

    rows = db.execute(q).all()

    results: List[Dict[str, Any]] = []
    for r in rows:
        usn = r.usn
        name = r.name
        branch = r.branch
        conducted = int(r.conducted or 0)
        attended = int(r.attended or 0)
        pct = round((attended / conducted) * 100, 1) if conducted > 0 else 0.0
        needed = classes_needed_for_threshold(attended, conducted, threshold)
        is_defaulter = pct < threshold

        results.append(
            {
                "usn": usn,
                "name": name,
                "branch": branch,
                "attended": attended,
                "conducted": conducted,
                "percent": pct,
                "classes_needed": needed,
                "is_defaulter": is_defaulter,
            }
        )

    # Sort by percent, lowest first
    results.sort(key=lambda s: s["percent"])

    defaulter_count = sum(1 for s in results if s["is_defaulter"])

    return {
        "status": "success",
        "threshold": threshold,
        "required_percent": required_percent,
        "defaulter_count": defaulter_count,
        "total_students": len(results),
        "students": results,
    }


__all__ = [
    "defaulters",
    "classes_needed_for_threshold",
    "classes_needed_for_75",
]
