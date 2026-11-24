"""Student Pydantic v2 schemas for API validation and serialization."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StudentBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Student full name")
    branch: str = Field(..., min_length=1, max_length=50, description="Department or branch code (e.g. CSE, ECE)")

    @field_validator("name", "branch")
    @classmethod
    def strip_and_validate_non_empty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace only")
        return cleaned


class StudentCreate(StudentBase):
    usn: str = Field(..., min_length=1, max_length=50, description="Unique Student Number / identifier")

    @field_validator("usn")
    @classmethod
    def validate_usn(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("USN cannot be empty or whitespace only")
        return cleaned


class StudentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Updated student name")
    branch: Optional[str] = Field(None, min_length=1, max_length=50, description="Updated department code")

    @field_validator("name", "branch")
    @classmethod
    def strip_optional(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Field cannot be empty or whitespace only")
            return cleaned
        return v


class StudentResponse(StudentBase):
    usn: str = Field(..., description="Unique Student Number")
    semester: Optional[int] = Field(None, description="Semester number (1-8)")
    semester_id: Optional[str] = Field(None, description="Semester ID (e.g. SEM-5)")
    section: Optional[str] = Field(None, description="Section label")
    section_id: Optional[str] = Field(None, description="Section ID")
    batch: Optional[str] = Field(None, description="Batch label")
    batch_id: Optional[str] = Field(None, description="Batch ID")
    roll_no: Optional[str] = Field(None, description="Roll number")
    dept_id: Optional[str] = Field(None, description="Department ID")
    proctor_id: Optional[str] = Field(None, description="Proctor user ID")

    model_config = ConfigDict(from_attributes=True)


class StudentPageResponse(BaseModel):
    items: List[StudentResponse] = Field(default_factory=list, description="Paginated student records")
    total: int = Field(ge=0, description="Total matching student records")
    limit: int = Field(ge=1, le=200, description="Maximum records returned per page")
    offset: int = Field(ge=0, description="Starting offset index")

    model_config = ConfigDict(from_attributes=True)


class StudentBulkCreate(BaseModel):
    students: List[StudentCreate] = Field(..., min_length=1, description="List of students to create")

