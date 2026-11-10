"""Attendance Pydantic v2 schemas for API validation and serialization."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


# Canonical 4 attendance states
AttendanceStatusLiteral = Literal["PRESENT", "ABSENT", "PENDING", "UNREVIEWED"]
ALLOWED_STATUSES = {"PRESENT", "ABSENT", "PENDING", "UNREVIEWED"}


def _clean_status(v: str) -> str:
    cleaned = v.strip().upper()
    if cleaned not in ALLOWED_STATUSES:
        raise ValueError(
            f"Invalid attendance status '{v}'. Must be strictly one of: {sorted(list(ALLOWED_STATUSES))}. "
            "Note: PENDING and UNREVIEWED must never be coerced to ABSENT."
        )
    return cleaned


class AttendanceBase(BaseModel):
    session_id: Optional[str] = Field(None, max_length=50, description="Session identifier")
    usn: str = Field(..., min_length=1, max_length=50, description="Student USN")
    room_id: str = Field(..., min_length=1, max_length=50, description="Room identifier")
    status: AttendanceStatusLiteral = Field(..., description="Attendance status: PRESENT, ABSENT, PENDING, or UNREVIEWED")
    source: str = Field(default="manual", min_length=1, max_length=100, description="Data source (e.g. manual, csv, photo)")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Extraction or model confidence score between 0.0 and 1.0")

    @field_validator("usn", "room_id", "source")
    @classmethod
    def strip_and_validate_non_empty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace only")
        return cleaned

    @field_validator("session_id")
    @classmethod
    def strip_optional_session_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("session_id cannot be empty or whitespace only")
            return cleaned
        return v

    @field_validator("status", mode="before")
    @classmethod
    def validate_attendance_status(cls, v: str) -> str:
        return _clean_status(str(v))


class AttendanceCreate(AttendanceBase):
    """Schema for creating a new attendance record."""
    pass


class AttendanceUpdate(BaseModel):
    """Schema for updating an existing attendance record."""
    room_id: Optional[str] = Field(None, min_length=1, max_length=50)
    status: Optional[AttendanceStatusLiteral] = None
    source: Optional[str] = Field(None, min_length=1, max_length=100)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)

    @field_validator("room_id", "source")
    @classmethod
    def strip_optional(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Field cannot be empty or whitespace only")
            return cleaned
        return v

    @field_validator("status", mode="before")
    @classmethod
    def validate_optional_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _clean_status(str(v))
        return v


class AttendanceResponse(AttendanceBase):
    """Schema for returning an attendance record."""
    session_id: str = Field(..., description="Session identifier")
    model_config = ConfigDict(from_attributes=True)


class AttendanceDetailResponse(AttendanceResponse):
    """Joined attendance details including student, room, and session metadata."""
    session_date: Optional[str] = Field(None, description="Date of the attendance session")
    subject: Optional[str] = Field(None, description="Course or subject name")
    student_name: Optional[str] = Field(None, description="Student full name")
    branch: Optional[str] = Field(None, description="Student branch / department")
    room_name: Optional[str] = Field(None, description="Room display name")

    model_config = ConfigDict(from_attributes=True)


class AttendanceBulkCreate(BaseModel):
    """Schema for bulk creation or upsertion of attendance records."""
    records: List[AttendanceCreate] = Field(..., min_length=1, description="List of attendance records to record")


class ReconcileRequest(BaseModel):
    """Schema for manually reviewing and reconciling unresolved or flagged attendance marks."""
    session_id: Optional[str] = Field(None, max_length=50, description="Session identifier")
    usn: str = Field(..., min_length=1, max_length=50, description="Student USN")
    resolved_status: AttendanceStatusLiteral = Field(..., description="Target status: PRESENT, ABSENT, PENDING, or UNREVIEWED")
    reason: Optional[str] = Field(None, max_length=500, description="Audit reason for the reconciliation")
    reconciled_by: Optional[str] = Field(default="user", max_length=100, description="User or role reconciling")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Reconciled confidence score")

    @field_validator("usn")
    @classmethod
    def strip_usn(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("USN cannot be empty or whitespace only")
        return cleaned

    @field_validator("session_id")
    @classmethod
    def strip_session_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("session_id cannot be empty or whitespace only")
            return cleaned
        return v

    @field_validator("resolved_status", mode="before")
    @classmethod
    def validate_resolved_status(cls, v: str) -> str:
        return _clean_status(str(v))


class BulkReconcileRequest(BaseModel):
    """Schema for reconciling multiple attendance items in a batch."""
    resolutions: List[ReconcileRequest] = Field(..., min_length=1, description="List of reconciliation items")


class SessionReconcilePayload(BaseModel):
    """Payload for session reconciliation, supporting both roster reconciliation and explicit resolutions."""
    resolutions: Optional[List[ReconcileRequest]] = Field(None, description="Explicit manual resolutions")
    roster: Optional[List[Dict[str, Any]]] = Field(None, description="Optional custom student roster")
    uploaded_records: Optional[List[Dict[str, Any]]] = Field(None, description="Uploaded attendance marks to reconcile")
    missing_room_ids: Optional[List[str]] = Field(None, description="List of room IDs with missing sheets")
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="Confidence threshold below which status becomes UNREVIEWED")
    persist: bool = Field(default=True, description="Whether to persist reconciled records to the database")


AttendanceCreate.model_rebuild()
AttendanceResponse.model_rebuild()
AttendanceDetailResponse.model_rebuild()
AttendanceBulkCreate.model_rebuild()
ReconcileRequest.model_rebuild()
BulkReconcileRequest.model_rebuild()
SessionReconcilePayload.model_rebuild()

