"""FastAPI router for current-user profile endpoints (N4).

``/api/v1/me/profile`` persists the Profile Settings UI: the descriptive
faculty profile lives in the 1:1 ``user_profiles`` table, while the identity
fields (display name ``users.name`` and ``users.email``) are mirrored onto
``users`` so they survive re-login and are authoritative for
``GET /api/v1/auth/me``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import crud
from app.db.models import User, UserProfile
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser
from app.schemas.meta import SubjectCodesResponse
from app.schemas.profile import UserProfileResponse, UserProfileUpdateRequest

logger = logging.getLogger("rollcall.routers.me")

router = APIRouter(prefix="/me", tags=["Profile"])


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json_list(raw: Optional[str]) -> list:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _profile_response(user: User, profile: Optional[UserProfile]) -> UserProfileResponse:
    return UserProfileResponse(
        fullName=(profile.full_name if profile and profile.full_name else None)
        or user.name
        or (user.email.split("@")[0] if user.email else user.user_id)
        or "",
        email=user.email or (profile.email if profile else "") or "",
        mobile=(profile.mobile if profile else "") or "",
        branch=(profile.branch if profile else "") or "",
        facultyId=user.user_id,
        designation=(profile.designation if profile else "") or "",
        experienceYears=profile.experience_years if profile else None,
        qualifications=(profile.qualifications if profile else "") or "",
        specialization=(profile.specialization if profile else "") or "",
        expertise=_load_json_list(profile.expertise if profile else None),
        masteredSubjects=_load_json_list(profile.mastered_subjects if profile else None),
        photoUrl=(profile.photo_url if profile else "") or "",
        updatedAt=profile.updated_at if profile else None,
    )


def _get_profile_row(db: Session, user_id: str) -> Optional[UserProfile]:
    return db.get(UserProfile, user_id)


@router.get(
    "/profile",
    response_model=UserProfileResponse,
    summary="Load the descriptive profile of the current user",
)
def get_my_profile(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    db_user = db.get(User, current_user.user_id)
    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "USER_NOT_FOUND", "message": "Account not found."}},
        )
    profile = _get_profile_row(db, current_user.user_id)
    return _profile_response(db_user, profile)


def _apply_profile_update(
    db: Session,
    db_user: User,
    payload: UserProfileUpdateRequest,
    *,
    partial: bool,
) -> UserProfile:
    """Apply PUT (full replace) or PATCH (only provided fields) semantics."""
    updates: Dict[str, Any] = payload.model_dump(exclude_unset=True)
    updates.pop("facultyId", None)  # identity field: never editable

    profile = _get_profile_row(db, db_user.user_id)
    if profile is None:
        if not partial and not updates:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": {"code": "EMPTY_PROFILE", "message": "No profile fields were provided."}},
            )
        profile = UserProfile(user_id=db_user.user_id)
        db.add(profile)

    # --- identity mirrors -------------------------------------------------
    full_name = updates.get("fullName")
    if full_name is not None:
        db_user.name = full_name
        profile.full_name = full_name
    elif not partial:
        # PUT semantics: absent name clears the stored display name.
        db_user.name = None
        profile.full_name = None

    new_email = updates.get("email")
    if new_email is not None and new_email != (db_user.email or "").lower():
        duplicate = db.execute(
            select(User.user_id).where(User.email == new_email, User.user_id != db_user.user_id)
        ).first()
        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": {
                        "code": "EMAIL_TAKEN",
                        "message": "That email address is already used by another account.",
                    }
                },
            )
        db_user.email = new_email
    profile.email = db_user.email

    # --- descriptive columns ---------------------------------------------
    for field in ("mobile", "branch", "designation", "qualifications", "specialization"):
        if field in updates:
            setattr(profile, field, updates[field])
        elif not partial:
            setattr(profile, field, None)

    if "experienceYears" in updates:
        profile.experience_years = updates["experienceYears"]
    elif not partial:
        profile.experience_years = None

    for field, column in (("expertise", "expertise"), ("masteredSubjects", "mastered_subjects")):
        if field in updates:
            setattr(profile, column, json.dumps(updates[field]) if updates[field] is not None else None)
        elif not partial:
            setattr(profile, column, None)

    if "photoUrl" in updates:
        profile.photo_url = updates["photoUrl"]
    elif not partial:
        profile.photo_url = None

    profile.updated_at = _utcnow_iso()
    return profile


@router.put(
    "/profile",
    response_model=UserProfileResponse,
    summary="Replace the full descriptive profile of the current user",
)
def replace_my_profile(
    payload: UserProfileUpdateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    db_user = db.get(User, current_user.user_id)
    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "USER_NOT_FOUND", "message": "Account not found."}},
        )
    profile = _apply_profile_update(db, db_user, payload, partial=False)
    db.commit()
    db.refresh(profile)
    db.refresh(db_user)
    logger.info("Profile replaced for user %s", db_user.user_id)
    return _profile_response(db_user, profile)


@router.patch(
    "/profile",
    response_model=UserProfileResponse,
    summary="Update only the provided profile fields of the current user",
)
def update_my_profile(
    payload: UserProfileUpdateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    db_user = db.get(User, current_user.user_id)
    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "USER_NOT_FOUND", "message": "Account not found."}},
        )
    profile = _apply_profile_update(db, db_user, payload, partial=True)
    db.commit()
    db.refresh(profile)
    db.refresh(db_user)
    logger.info("Profile updated for user %s", db_user.user_id)
    return _profile_response(db_user, profile)


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
