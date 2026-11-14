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
    teacher_id: Optional[str] = Field(None, description="Owning teacher user identifier")
    subject_code: Optional[str] = Field(None, description="Normalized subject code of the session")
    editable: bool = Field(
        True,
        description="Whether the calling role may still edit this session (N5 24-hour lock; ADMIN always true)",
    )
    editable_until_utc: Optional[str] = Field(
        None,
        description="UTC timestamp when the edit window closes (created_at + lock hours), or null if unknown",
    )
    locked: bool = Field(
        False,
        description="True exactly when editable is false (kept explicit so the UI never computes it)",
    )
    is_delegated: Optional[bool] = Field(None, description="Whether this session has an active proxy delegation")
    delegation: Optional[dict] = Field(None, description="Delegation metadata (proxy faculty, reason, etc.)")

    model_config = ConfigDict(from_attributes=True)


class SessionAttendanceEditRequest(BaseModel):
    """Body of ``PUT /api/sessions/{id}/attendance/{usn}`` (N6)."""

    status: str = Field(..., description="New status: PRESENT or ABSENT")
    reason: Optional[str] = Field(
        None,
        max_length=1000,
        description="Required when an ADMIN edits a session older than the lock window",
    )

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        cleaned = (v or "").strip().upper()
        if cleaned not in {"PRESENT", "ABSENT"}:
            raise ValueError("status must be 'PRESENT' or 'ABSENT'")
        return cleaned


class SessionPageResponse(BaseModel):
    items: List[SessionResponse] = Field(default_factory=list, description="Paginated session records")
    total: int = Field(ge=0, description="Total matching session records")
    limit: int = Field(ge=1, le=200, description="Maximum records returned per page")
    offset: int = Field(ge=0, description="Starting offset index")

    model_config = ConfigDict(from_attributes=True)


class SessionBulkCreate(BaseModel):
    sessions: List[SessionCreate] = Field(..., min_length=1, description="List of sessions to create")


class ExtraSessionCreate(BaseModel):
    subject_code: str = Field(..., min_length=1, max_length=50, description="Subject code (e.g. CN)")
    subject_name: Optional[str] = Field(None, max_length=255, description="Subject name")
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Class date YYYY-MM-DD")
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="Start time HH:MM")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="End time HH:MM")
    room_id: str = Field(..., min_length=1, max_length=50, description="Room ID (e.g. CDS10-105)")
    dept_id: Optional[str] = Field(None, max_length=50, description="Department code (e.g. CSE-CY)")
    semester_number: Optional[int] = Field(None, ge=1, le=8, description="Semester 1 - 8")
    section_id: Optional[str] = Field(None, max_length=50, description="Section ID")
    batch_id: Optional[str] = Field(None, max_length=50, description="Batch ID")
    class_type: str = Field(default="EXTRA", description="Type: EXTRA, REMEDIAL, EMERGENCY")


class ClassDelegationCreate(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=50, description="Session to delegate")
    substitute_faculty_id: str = Field(..., min_length=1, max_length=64, description="Substitute faculty ID")
    delegation_type: str = Field(default="PROXY", description="PROXY or EXCHANGE")
    exchange_session_id: Optional[str] = Field(None, max_length=50, description="Exchange session ID if type is EXCHANGE")
    reason: Optional[str] = Field(None, max_length=255, description="Reason for delegation (e.g. Leave)")


class ClassDelegationResponse(BaseModel):
    delegation_id: str
    session_id: str
    original_faculty_id: str
    original_faculty_name: Optional[str] = None
    substitute_faculty_id: str
    substitute_faculty_name: Optional[str] = None
    delegation_date: str
    delegation_type: str
    exchange_session_id: Optional[str] = None
    reason: Optional[str] = None
    status: str
    subject_code: Optional[str] = None
    subject_name: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    room_id: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


