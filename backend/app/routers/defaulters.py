"""N10: Defaulter endpoints.

GET /api/defaulters — per-student attendance percentage with defaulter flag.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import Role, get_current_user, require_roles
from app.config import DEFAULTER_THRESHOLD_PERCENT, DEFAULTER_REQUIRED_PERCENT
from app.db import crud
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser
from tools.defaulter_tool import defaulters

router = APIRouter(prefix="/defaulters", tags=["Defaulters"])


@router.get(
    "",
    summary="Defaulter analysis per student",
    description=(
        "Return per-student attendance percentage, classes needed to reach "
        "the threshold, and defaulter flag. A student is a defaulter only "
        "when percent is strictly below the threshold (75.0 is NOT a "
        "defaulter). Teachers see their assigned subjects only; admins see "
        "all branches."
    ),
)
def get_defaulters(
    subject: Optional[str] = Query(None, description="Filter by subject code"),
    branch: Optional[str] = Query(None, description="Filter by branch"),
    semester: Optional[str] = Query(None, description="Filter by semester"),
    threshold: Optional[float] = Query(
        None,
        description="Defaulter threshold percent (default 75.0)",
    ),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    role_str = str(current_user.role.value if hasattr(current_user.role, "value") else current_user.role).upper()

    # Teachers can only query their assigned subjects
    assigned_subjects: List[str] = []
    if role_str != "ADMIN":
        try:
            assigned_subjects = crud.get_teacher_subjects(db, user_id=current_user.user_id) or []
        except Exception:
            assigned_subjects = []

    result = defaulters(
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
    return result


__all__ = ["router"]
