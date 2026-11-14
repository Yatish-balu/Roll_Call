"""Pydantic v2 schemas for N4: teacher-subject mapping, session scoping, and meta config."""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    teacher_id: Optional[str] = Field(None, description="Alias for user_id for frontend backward compatibility")

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def populate_teacher_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "teacher_id" not in data or not data["teacher_id"]:
                data["teacher_id"] = data.get("user_id")
        elif hasattr(data, "user_id"):
            # ORM model
            if not getattr(data, "teacher_id", None):
                setattr(data, "teacher_id", getattr(data, "user_id", None))
        return data


class TeacherSubjectListResponse(BaseModel):
    """Paginated teacher-subject mapping list."""

    items: List[TeacherSubjectMapping] = Field(default_factory=list)
    total: int = Field(ge=0)


class SecurityDecoyCreate(BaseModel):
    """Payload registering a honeypot identifier."""

    decoy_kind: str = Field(
        ..., min_length=1, max_length=50, description="Kind of decoy (e.g. STUDENT, SESSION)"
    )
    decoy_value: str = Field(
        ..., min_length=1, max_length=100, description="The decoy identifier itself"
    )
    note: Optional[str] = Field(
        None, max_length=255, description="Optional operator note"
    )


class AuditLogEntry(BaseModel):
    """One append-only audit record."""

    id: Optional[int] = Field(None, description="Audit record identifier")
    log_id: Optional[int] = Field(None, description="Audit record identifier")
    timestamp: str = Field(..., description="UTC timestamp of the recorded action")
    event_type: str = Field(..., description="Action recorded (e.g. ATTENDANCE_UPSERT)")
    action: str = Field(..., description="Action recorded (same value as event_type)")
    actor_id: str = Field(..., description="User id of the actor")
    actor_role: Optional[str] = Field(
        None, description="Role of the actor at the time of the action (null for older records)"
    )
    session_id: Optional[str] = Field(None, description="Session the action belongs to")
    usn: Optional[str] = Field(None, description="Student the action belongs to")
    entity_type: Optional[str] = Field(None, description="Type of the affected entity")
    entity_id: Optional[str] = Field(None, description="Identifier of the affected entity")
    old_status: Optional[str] = Field(None, description="Previous attendance status")
    new_status: Optional[str] = Field(None, description="New attendance status")
    reason: Optional[str] = Field(None, description="Optional note recorded with the action")

    model_config = ConfigDict(from_attributes=True)


class AuditLogPageResponse(BaseModel):
    """Paginated audit trail."""

    items: List[AuditLogEntry] = Field(default_factory=list, description="Audit records, newest first")
    total: int = Field(ge=0, description="Total number of matching audit records")
    limit: int = Field(ge=1, le=200, description="Maximum records returned per page")
    offset: int = Field(ge=0, description="Starting offset index")

    model_config = ConfigDict(from_attributes=True)


class MetaConfigResponse(BaseModel):
    """
    Server-decided application configuration for frontend consumption (Golden Rule:
    every number comes from Python code or the database, never React).
    """

    edit_lock_hours: int = Field(
        ...,
        description=(
            "DEPRECATED (N5): hours after session creation until editing is locked. "
            "Attendance editing is UNLIMITED, so this value is never used for "
            "authorization or editing decisions. Kept only for API compatibility "
            "until the frontend removes its 24-hour lock display."
        ),
    )
    unlimited_attendance_editing: bool = Field(
        ...,
        description=(
            "True when attendance may be edited at any time by an authorized actor, "
            "regardless of session age or lifecycle status (N5)."
        ),
    )
    admin_override_allowed: bool = Field(..., description="Whether ADMIN may override an edit lock with a reason (D12)")
    defaulter_threshold_percent: float = Field(..., description="Attendance percentage strictly below which a student is a defaulter (N10)")
    defaulter_required_percent: float = Field(..., description="Attendance percentage required after attending extra classes (N10)")
    attendance_bands: dict = Field(..., description="Colour band boundaries for class health (D5)")
    upload_limits: dict = Field(..., description="Maximum upload sizes in bytes for each modality (N15)")
    chat_confirm_expiry_minutes: int = Field(..., description="Server-side confirmation expiry in minutes (D13)")
    access_token_ttl_minutes: int = Field(..., description="JWT access token lifetime in minutes")
    subject_codes: List[str] = Field(default_factory=list, description="Distinct subject codes known to the institution")
