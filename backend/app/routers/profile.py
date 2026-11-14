"""FastAPI router for user faculty profile endpoints.

Provides GET and PUT /profile with database persistence in Supabase (PostgreSQL)
and SQLite, ensuring multi-instance synchronization without schema drift.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import crud
from app.db.models import DepartmentStaff, FacultySubject, User
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser

logger = logging.getLogger("rollcall.routers.profile")

router = APIRouter(prefix="/profile", tags=["Profile"])


def _ensure_profile_table(db: Session) -> None:
    """Ensure the user_profiles table exists in the active database."""
    ddl = text("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id VARCHAR PRIMARY KEY,
            full_name VARCHAR,
            mobile VARCHAR,
            email VARCHAR,
            branch VARCHAR,
            designation VARCHAR,
            experience_years INTEGER,
            qualifications VARCHAR,
            specialization VARCHAR,
            expertise TEXT,
            mastered_subjects TEXT,
            photo_url TEXT,
            updated_at VARCHAR
        )
    """)
    db.execute(ddl)
    db.commit()


class FacultyProfileSchema(BaseModel):
    fullName: Optional[str] = ""
    mobile: Optional[str] = ""
    email: Optional[str] = ""
    branch: Optional[str] = ""
    facultyId: Optional[str] = ""
    designation: Optional[str] = ""
    experienceYears: Optional[int] = 0
    qualifications: Optional[str] = ""
    specialization: Optional[str] = ""
    expertise: List[str] = Field(default_factory=list)
    masteredSubjects: List[str] = Field(default_factory=list)
    photoUrl: Optional[str] = ""


@router.get(
    "",
    response_model=FacultyProfileSchema,
    summary="Get profile of the currently authenticated user",
)
def get_profile(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve the faculty profile from the persistent database store."""
    _ensure_profile_table(db)

    # 1. Query stored profile
    stmt = text("""
        SELECT full_name, mobile, email, branch, designation, experience_years,
               qualifications, specialization, expertise, mastered_subjects, photo_url
        FROM user_profiles WHERE user_id = :uid
    """)
    row = db.execute(stmt, {"uid": current_user.user_id}).fetchone()

    # 2. Get user defaults from user model & assignments
    user_record = db.get(User, current_user.user_id)
    assigned_subjects = crud.get_teacher_subjects(db, user_id=current_user.user_id)

    # Try resolving branch from department staff or faculty subjects
    branch_val = ""
    staff = db.query(DepartmentStaff).filter(DepartmentStaff.user_id == current_user.user_id).first()
    if staff and staff.dept_id:
        branch_val = staff.dept_id
    else:
        fs = db.query(FacultySubject).filter(FacultySubject.user_id == current_user.user_id).first()
        if fs and fs.dept_id:
            branch_val = fs.dept_id

    if row:
        expertise_list: List[str] = []
        mastered_list: List[str] = []
        try:
            expertise_list = json.loads(row[8] or "[]")
        except Exception:
            expertise_list = []
        try:
            mastered_list = json.loads(row[9] or "[]")
        except Exception:
            mastered_list = []

        if not mastered_list and assigned_subjects:
            mastered_list = assigned_subjects

        return {
            "fullName": row[0] or (user_record.name if user_record and user_record.name else current_user.user_id),
            "mobile": row[1] or "",
            "email": row[2] or (user_record.email if user_record else ""),
            "branch": row[3] or branch_val,
            "facultyId": current_user.user_id,
            "designation": row[4] or "",
            "experienceYears": row[5] if row[5] is not None else 0,
            "qualifications": row[6] or "",
            "specialization": row[7] or "",
            "expertise": expertise_list,
            "masteredSubjects": mastered_list,
            "photoUrl": row[10] or "",
        }

    # Default profile when not yet customized
    return {
        "fullName": user_record.name if (user_record and user_record.name) else current_user.user_id,
        "mobile": "",
        "email": user_record.email if user_record else "",
        "branch": branch_val,
        "facultyId": current_user.user_id,
        "designation": "",
        "experienceYears": 0,
        "qualifications": "",
        "specialization": "",
        "expertise": [],
        "masteredSubjects": assigned_subjects,
        "photoUrl": "",
    }


@router.put(
    "",
    response_model=FacultyProfileSchema,
    summary="Save profile of the currently authenticated user to the database",
)
def update_profile(
    payload: FacultyProfileSchema,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Persist the faculty profile into the database and sync user table metadata."""
    _ensure_profile_table(db)

    now_iso = datetime.now(timezone.utc).isoformat()
    expertise_json = json.dumps(payload.expertise or [])
    mastered_json = json.dumps(payload.masteredSubjects or [])

    upsert_sql = text("""
        INSERT INTO user_profiles (
            user_id, full_name, mobile, email, branch, designation,
            experience_years, qualifications, specialization, expertise,
            mastered_subjects, photo_url, updated_at
        ) VALUES (
            :uid, :full_name, :mobile, :email, :branch, :designation,
            :experience_years, :qualifications, :specialization, :expertise,
            :mastered_subjects, :photo_url, :updated_at
        )
        ON CONFLICT(user_id) DO UPDATE SET
            full_name = EXCLUDED.full_name,
            mobile = EXCLUDED.mobile,
            email = EXCLUDED.email,
            branch = EXCLUDED.branch,
            designation = EXCLUDED.designation,
            experience_years = EXCLUDED.experience_years,
            qualifications = EXCLUDED.qualifications,
            specialization = EXCLUDED.specialization,
            expertise = EXCLUDED.expertise,
            mastered_subjects = EXCLUDED.mastered_subjects,
            photo_url = EXCLUDED.photo_url,
            updated_at = EXCLUDED.updated_at
    """)

    db.execute(
        upsert_sql,
        {
            "uid": current_user.user_id,
            "full_name": payload.fullName or "",
            "mobile": payload.mobile or "",
            "email": payload.email or "",
            "branch": payload.branch or "",
            "designation": payload.designation or "",
            "experience_years": payload.experienceYears or 0,
            "qualifications": payload.qualifications or "",
            "specialization": payload.specialization or "",
            "expertise": expertise_json,
            "mastered_subjects": mastered_json,
            "photo_url": payload.photoUrl or "",
            "updated_at": now_iso,
        },
    )

    # Synchronize users table display name and email if valid
    user_record = db.get(User, current_user.user_id)
    if user_record:
        # Only ADMIN has permission to alter official faculty name in users table
        from app.schemas.auth import Role
        if payload.fullName and current_user.role == Role.ADMIN:
            user_record.name = payload.fullName.strip()
        if payload.email and "@" in payload.email:
            clean_email = payload.email.strip().lower()
            conflict = db.query(User).filter(User.email == clean_email, User.user_id != current_user.user_id).first()
            if not conflict:
                user_record.email = clean_email

    # Log to append-only audit log
    try:
        crud.create_audit_entry(
            db,
            actor_id=current_user.user_id,
            action="PROFILE_UPDATE",
            entity_type="user_profile",
            entity_id=current_user.user_id,
            new_value=json.dumps({"fullName": payload.fullName, "designation": payload.designation}),
            timestamp=now_iso,
            actor_role=getattr(current_user.role, "value", str(current_user.role)),
        )
    except Exception as exc:
        logger.warning("Could not write audit log for profile update: %s", exc)

    db.commit()

    return {
        "fullName": payload.fullName or (user_record.name if user_record else current_user.user_id),
        "mobile": payload.mobile or "",
        "email": payload.email or (user_record.email if user_record else ""),
        "branch": payload.branch or "",
        "facultyId": current_user.user_id,
        "designation": payload.designation or "",
        "experienceYears": payload.experienceYears or 0,
        "qualifications": payload.qualifications or "",
        "specialization": payload.specialization or "",
        "expertise": payload.expertise or [],
        "masteredSubjects": payload.masteredSubjects or [],
        "photoUrl": payload.photoUrl or "",
    }

