"""FastAPI router for current-user profile endpoints (N4)."""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import crud
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser
from app.schemas.meta import SubjectCodesResponse

logger = logging.getLogger("rollcall.routers.me")

router = APIRouter(prefix="/me", tags=["Profile"])


@router.get(
    "/subjects",
    response_model=SubjectCodesResponse,
    summary="List assigned subject codes for the current user",
    description=(
        "Return the subject codes assigned to the authenticated teacher (proxy selector data, D8). "
        "The user identity comes exclusively from the verified token, never from the request body."
    ),
)
def get_my_subjects(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    subject_codes = crud.get_teacher_subjects(db, user_id=current_user.user_id)
    return {
        "user_id": current_user.user_id,
        "role": current_user.role.value,
        "subject_codes": subject_codes,
    }
