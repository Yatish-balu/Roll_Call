"""FastAPI router for Student Defaulter endpoints (Prompt N10 / Rule D9 / T-DEF)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser
from tools.defaulter_tool import get_defaulters_data

router = APIRouter(prefix="/defaulters", tags=["Defaulters"])


@router.get(
    "",
    summary="List attendance defaulters strictly below threshold",
    description="Calculate student attendance percentages and recovery classes needed. Defaulters are sorted by percent lowest first.",
)
def list_defaulters(
    subject_code: Optional[str] = Query(None, description="Filter by subject code (teacher restricted to assigned)"),
    branch: Optional[str] = Query(None, description="Filter by student academic department/branch"),
    semester: Optional[int] = Query(None, description="Filter by student semester"),
    threshold: float = Query(75.0, ge=1.0, le=99.9, description="Defaulter threshold percentage (default 75.0)"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    # Normalize direct Python calls vs FastAPI Query objects
    actual_subj = subject_code if isinstance(subject_code, str) else None
    actual_branch = branch if isinstance(branch, str) else None
    actual_sem = semester if isinstance(semester, int) else None
    actual_thresh = threshold if isinstance(threshold, (int, float)) else 75.0

    return get_defaulters_data(
        user=current_user,
        subject_code=actual_subj,
        branch=actual_branch,
        semester=actual_sem,
        threshold=actual_thresh,
        db=db,
    )

