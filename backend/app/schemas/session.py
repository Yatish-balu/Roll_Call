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

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Session ID cannot be empty or whitespace only")
        return cleaned


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

    model_config = ConfigDict(from_attributes=True)


class SessionPageResponse(BaseModel):
    items: List[SessionResponse] = Field(default_factory=list, description="Paginated session records")
    total: int = Field(ge=0, description="Total matching session records")
    limit: int = Field(ge=1, le=200, description="Maximum records returned per page")
    offset: int = Field(ge=0, description="Starting offset index")

    model_config = ConfigDict(from_attributes=True)


class SessionBulkCreate(BaseModel):
    sessions: List[SessionCreate] = Field(..., min_length=1, description="List of sessions to create")

