"""FastAPI router for server-decided application configuration (N4).

Golden Rule: every number shown by React comes from this endpoint (Python code),
never from frontend constants.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import crud
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser
from app.schemas.meta import MetaConfigResponse

logger = logging.getLogger("rollcall.routers.meta")

router = APIRouter(prefix="/meta", tags=["Configuration"])


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning("Ignoring invalid %s=%r, falling back to %s", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        logger.warning("Ignoring invalid %s=%r, falling back to %s", name, raw, default)
        return default


@router.get(
    "/config",
    response_model=MetaConfigResponse,
    summary="Retrieve server-decided application configuration",
    description=(
        "Single source of truth for edit-lock policy, defaulter thresholds, colour bands, "
        "upload limits and confirmation expiry so the frontend never computes them locally."
    ),
)
def get_meta_config(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    subject_codes = sorted(
        {m["subject_code"] for m in crud.list_teacher_subject_mappings(db)}
    )

    return {
        # DEPRECATED (N5): kept for API compatibility only. Attendance editing
        # is unlimited, so this value never gates an edit and is never consulted
        # by the backend authorization or editing logic.
        "edit_lock_hours": _env_int("EDIT_LOCK_HOURS", 24),
        "unlimited_attendance_editing": True,
        "admin_override_allowed": True,
        "defaulter_threshold_percent": _env_float("DEFAULTER_THRESHOLD_PERCENT", 75.0),
        "defaulter_required_percent": _env_float("DEFAULTER_REQUIRED_PERCENT", 75.0),
        "attendance_bands": {
            "green_above_percent": _env_float("BAND_GREEN_ABOVE_PERCENT", 85.0),
            "yellow_from_percent": _env_float("BAND_YELLOW_FROM_PERCENT", 70.0),
            "labels": {"green": "green", "yellow": "yellow", "red": "red"},
        },
        "upload_limits": {
            "image_max_bytes": _env_int("MAX_IMAGE_UPLOAD_BYTES", 10 * 1024 * 1024),
            "csv_max_bytes": _env_int("MAX_CSV_UPLOAD_BYTES", 5 * 1024 * 1024),
        },
        "chat_confirm_expiry_minutes": _env_int("CHAT_CONFIRM_EXPIRY_MINUTES", 5),
        "access_token_ttl_minutes": _env_int("ACCESS_TOKEN_TTL_MINUTES", 15),
        "subject_codes": subject_codes,
    }
