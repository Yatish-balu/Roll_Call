"""Session Pydantic v2 schemas for API validation and serialization."""

from __future__ import annotations

import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SessionBase(BaseModel):
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Session date in YYYY-MM-DD ISO format")
    subject: str = Field(..., min_length=1, max_length=255, description="Subject or course name")

    @field_validator("date")
    @classmethod
    def validate_iso_date(cls, v: str) -> str:
        cleaned = v.strip()
        try:
            datetime.date.fromisoformat(cleaned)
        except ValueError:
            raise ValueError(f"Date '{cleaned}' is not a valid ISO calendar date (YYYY-MM-DD)")
        return cleaned

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Subject cannot be empty or whitespace only")
        return cleaned


class SessionCreate(SessionBase):
    session_id: str = Field(..., min_length=1, max_length=50, description="Unique Session identifier (e.g. SESS-001)")
    subject_code: Optional[str] = Field(
        None,
        max_length=50,
        description="Subject code this session belongs to. FACULTY must supply one of their assigned codes (N4).",
    )
    teacher_id: Optional[str] = Field(
        None,
        max_length=100,
        description="Owning teacher user ID. ADMIN-only field; FACULTY sessions are always bound to the token subject.",
    )

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Session ID cannot be empty or whitespace only")
        return cleaned

    @field_validator("subject_code")
    @classmethod
    def validate_subject_code(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            cleaned = v.strip().upper()
            if not cleaned:
                raise ValueError("Subject code cannot be empty or whitespace only")
            return cleaned
        return v

    @field_validator("teacher_id")
    @classmethod
    def validate_teacher_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Teacher ID cannot be empty or whitespace only")
            return cleaned
        return v


class SessionUpdate(BaseModel):
    date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Updated session date")
    subject: Optional[str] = Field(None, min_length=1, max_length=255, description="Updated subject name")

    @field_validator("date")
    @classmethod
    def validate_optional_iso_date(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            cleaned = v.strip()
            try:
                datetime.date.fromisoformat(cleaned)
            except ValueError:
                raise ValueError(f"Date '{cleaned}' is not a valid ISO calendar date (YYYY-MM-DD)")
            return cleaned
        return v

    @field_validator("subject")
    @classmethod
    def validate_optional_subject(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Subject cannot be empty or whitespace only")
            return cleaned
        return v


class SessionResponse(SessionBase):
    session_id: str = Field(..., description="Unique Session identifier")
    created_at: Optional[str] = Field(None, description="Session creation timestamp (UTC ISO 8601)")
    created_at_utc: Optional[str] = Field(None, description="Session creation timestamp alias")
    teacher_id: Optional[str] = Field(None, description="Owning teacher user identifier")
    subject_code: Optional[str] = Field(None, description="Normalized subject code of the session")
    subject_name: Optional[str] = Field(None, description="Subject display name")
    editable: Optional[bool] = Field(None, description="Whether session is editable by caller")
    editable_until_utc: Optional[str] = Field(None, description="UTC timestamp until which session is editable")
    locked: Optional[bool] = Field(None, description="Whether 24h edit window has expired for caller")

    model_config = ConfigDict(from_attributes=True)


class AttendanceEditRequest(BaseModel):
    status: str = Field(..., description="Target attendance status ('PRESENT' or 'ABSENT')")
    reason: Optional[str] = Field(None, description="Reason for modification (required for admin > 24h)")


class AttendanceEditResponse(BaseModel):
    success: bool = Field(True, description="Whether the edit succeeded")
    session_id: str = Field(..., description="Session identifier")
    usn: str = Field(..., description="Student USN")
    old_status: str = Field(..., description="Previous attendance status")
    new_status: str = Field(..., description="Updated attendance status")
    updated_at: str = Field(..., description="UTC timestamp of the modification")
    event: Optional[str] = Field(None, description="Audit action event recorded")
    audit_log_id: Optional[int] = Field(None, description="Audit log entry ID")


class SessionAttendanceRecord(BaseModel):
    usn: str = Field(..., description="Student USN")
    name: Optional[str] = Field(None, description="Student name")
    status: str = Field(..., description="Attendance status")
    source: Optional[str] = Field(None, description="Attendance source")
    confidence: Optional[float] = Field(1.0, description="Confidence score")


class SessionAttendanceDetailResponse(BaseModel):
    session: SessionResponse = Field(..., description="Session header and lock metadata")
    records: List[SessionAttendanceRecord] = Field(default_factory=list, description="Attendance mark records")


class SessionPageResponse(BaseModel):
    items: List[SessionResponse] = Field(default_factory=list, description="Paginated session records")
    total: int = Field(ge=0, description="Total matching session records")
    limit: int = Field(ge=1, le=200, description="Maximum records returned per page")
    offset: int = Field(ge=0, description="Starting offset index")

    model_config = ConfigDict(from_attributes=True)


class SessionBulkCreate(BaseModel):
    sessions: List[SessionCreate] = Field(..., min_length=1, description="List of sessions to create")

