"""N10: Defaulter analysis endpoints.

``GET /api/defaulters`` returns, per student, the attendance percentage, the
number of additional classes needed to reach the threshold, and the defaulter
flag. All numbers are computed in Python from database rows; the LLM and the
frontend never compute them.

A student is a defaulter only when the percentage is **strictly below** the
threshold (75.0 is NOT a defaulter). Teachers see their assigned subjects only;
admins see all branches.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import Role, get_current_user
from app.config import DEFAULTER_REQUIRED_PERCENT, DEFAULTER_THRESHOLD_PERCENT
from app.db import crud
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser
from tools.defaulter_tool import defaulters

router = APIRouter(prefix="/defaulters", tags=["Defaulters"])


def _role_str(user: AuthenticatedUser) -> str:
    role = getattr(user, "role", "")
    return str(role.value if hasattr(role, "value") else role).strip().upper()


@router.get(
    "",
    summary="Defaulter analysis per student",
    description=(
        "Per-student attendance percentage, classes needed to reach the threshold, "
        "and defaulter flag. A student is a defaulter only when percent is strictly "
        "below the threshold (75.0 is NOT a defaulter). Teachers see their assigned "
        "subjects only; admins see all."
    ),
    responses={
        200: {"description": "Defaulter analysis"},
        422: {"description": "Invalid threshold"},
    },
)
def get_defaulters(
    subject: Optional[str] = Query(None, description="Filter by subject code"),
    branch: Optional[str] = Query(None, description="Filter by branch"),
    semester: Optional[str] = Query(None, description="Filter by semester"),
    threshold: Optional[float] = Query(
        None, gt=0, lt=100, description="Defaulter threshold percent (default 75.0)"
    ),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    role_str = _role_str(current_user)

    assigned_subjects: List[str] = []
    if role_str != Role.ADMIN.value:
        assigned_subjects = crud.get_teacher_subjects(db, user_id=current_user.user_id) or []

    return defaulters(
        db=db,
        actor_id=current_user.user_id,
        actor_role=role_str,
        assigned_subjects=assigned_subjects,
        subject_code=subject,
        branch=branch,
        semester=semester,
        threshold=threshold if threshold is not None else DEFAULTER_THRESHOLD_PERCENT,
        required_percent=DEFAULTER_REQUIRED_PERCENT,
    )


__all__ = ["router"]
