"""Pydantic v2 schemas for N4: teacher-subject mapping, session scoping, and meta config."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SubjectCodesResponse(BaseModel):
    """Assigned subject codes for the currently authenticated user (proxy selector data, D8)."""

    user_id: str = Field(..., description="Authenticated user identifier")
    role: str = Field(..., description="Authoritative role of the user")
    subject_codes: List[str] = Field(default_factory=list, description="Assigned subject codes")


class TeacherSubjectAssignRequest(BaseModel):
    """Admin payload assigning a subject code to a teacher."""

    user_id: str = Field(..., min_length=1, max_length=100, description="Teacher user identifier")
    subject_code: str = Field(..., min_length=1, max_length=50, description="Subject code to assign")

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("User ID cannot be empty or whitespace only")
        return cleaned

    @field_validator("subject_code")
    @classmethod
    def validate_subject_code(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("Subject code cannot be empty or whitespace only")
        return cleaned


class TeacherSubjectMapping(BaseModel):
    """A single teacher-subject mapping record."""

    id: int = Field(..., description="Mapping row identifier")
    user_id: str = Field(..., description="Teacher user identifier")
    subject_code: str = Field(..., description="Assigned subject code")

    model_config = ConfigDict(from_attributes=True)


class TeacherSubjectListResponse(BaseModel):
    """Paginated teacher-subject mapping list."""

    items: List[TeacherSubjectMapping] = Field(default_factory=list)
    total: int = Field(ge=0)


class MetaConfigResponse(BaseModel):
    """
    Server-decided application configuration for frontend consumption (Golden Rule:
    every number comes from Python code or the database, never React).
    """

    edit_lock_hours: int = Field(..., description="Hours after session creation until editing is locked (N5)")
    admin_override_allowed: bool = Field(..., description="Whether ADMIN may override an edit lock with a reason (D12)")
    defaulter_threshold_percent: float = Field(..., description="Attendance percentage strictly below which a student is a defaulter (N10)")
    defaulter_required_percent: float = Field(..., description="Attendance percentage required after attending extra classes (N10)")
    attendance_bands: dict = Field(..., description="Colour band boundaries for class health (D5)")
    upload_limits: dict = Field(..., description="Maximum upload sizes in bytes for each modality (N15)")
    chat_confirm_expiry_minutes: int = Field(..., description="Server-side confirmation expiry in minutes (D13)")
    access_token_ttl_minutes: int = Field(..., description="JWT access token lifetime in minutes")
    subject_codes: List[str] = Field(default_factory=list, description="Distinct subject codes known to the institution")
