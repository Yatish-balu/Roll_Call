"""College Pydantic v2 schemas for API validation and serialization."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CollegeBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="College name")
    code: str = Field(..., min_length=2, max_length=20, description="College code")
    address: Optional[str] = Field(None, max_length=500, description="College address")

    @field_validator("name", "code")
    @classmethod
    def strip_and_validate_non_empty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace only")
        return cleaned


class CollegeCreate(CollegeBase):
    pass


class CollegeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    code: Optional[str] = Field(None, min_length=2, max_length=20)
    address: Optional[str] = Field(None, max_length=500)

    @field_validator("name", "code")
    @classmethod
    def strip_optional(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Field cannot be empty or whitespace only")
            return cleaned
        return v


class CollegeResponse(CollegeBase):
    college_id: str = Field(..., description="College identifier")
    created_at: str = Field(..., description="Creation timestamp (UTC ISO 8601)")

    model_config = ConfigDict(from_attributes=True)


class CollegePageResponse(BaseModel):
    items: List[CollegeResponse] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)

    model_config = ConfigDict(from_attributes=True)
