"""Pydantic schemas for the Profile Settings endpoints (/api/v1/me/profile).

Field names intentionally use the frontend's camelCase ``FacultyProfile``
contract so the client can send and receive the same object shape.
"""

from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MAX_PHOTO_URL_CHARS = 3_000_000  # ~2 MB image as a base64 data URL


class UserProfileResponse(BaseModel):
    """Server-authoritative descriptive profile for the authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    fullName: str = ""
    email: str = ""
    mobile: str = ""
    branch: str = ""
    facultyId: str = ""
    designation: str = ""
    experienceYears: Optional[int] = None
    qualifications: str = ""
    specialization: str = ""
    expertise: List[str] = Field(default_factory=list)
    masteredSubjects: List[str] = Field(default_factory=list)
    photoUrl: str = ""
    updatedAt: Optional[str] = None


class UserProfileUpdateRequest(BaseModel):
    """Editable profile fields. ``facultyId`` is identity, never editable."""

    fullName: Optional[str] = Field(None, max_length=120)
    email: Optional[str] = Field(None, max_length=254)
    mobile: Optional[str] = Field(None, max_length=32)
    branch: Optional[str] = Field(None, max_length=64)
    designation: Optional[str] = Field(None, max_length=64)
    experienceYears: Optional[int] = Field(None, ge=0, le=60)
    qualifications: Optional[str] = Field(None, max_length=200)
    specialization: Optional[str] = Field(None, max_length=200)
    expertise: Optional[List[str]] = Field(None, max_length=25)
    masteredSubjects: Optional[List[str]] = Field(None, max_length=25)
    photoUrl: Optional[str] = Field(None, max_length=MAX_PHOTO_URL_CHARS)

    @field_validator("fullName", "mobile", "branch", "designation", "qualifications", "specialization")
    @classmethod
    def _strip_strings(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if cleaned and not _EMAIL_RE.match(cleaned):
            raise ValueError("Invalid email address format.")
        return cleaned or None

    @field_validator("expertise", "masteredSubjects")
    @classmethod
    def _clean_tags(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        cleaned = [tag.strip() for tag in value if tag and tag.strip()]
        if len({tag.lower() for tag in cleaned}) != len(cleaned):
            raise ValueError("Duplicate tags are not allowed.")
        return cleaned
