"""Pydantic schemas for RollCall AI Exam Hall & Form-B Control Module."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ExamCreate(BaseModel):
    exam_id: str = Field(..., min_length=3, max_length=50, description="Unique exam identifier (e.g. DSCE-CIE3-NOV2026)")
    name: str = Field(..., min_length=3, max_length=200, description="Exam display name")
    exam_type: str = Field("THEORY_CIE", description="THEORY_CIE, LAB_CIE, LAB_EXTERNAL, or THEORY_SEE")
    semester: Optional[int] = Field(None, ge=1, le=8)
    department: Optional[str] = Field(None, max_length=100)
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Exam date in YYYY-MM-DD")
    start_time: str = Field(..., description="Start time (e.g. 10:00 or 10:00:00)")
    end_time: str = Field(..., description="End time (e.g. 11:30 or 11:30:00)")
    cutoff_minutes: int = Field(45, ge=5, le=180, description="Form-B submission deadline in minutes from start")
    subject_code: str = Field(..., min_length=2, max_length=30)
    subject_name: Optional[str] = Field(None, max_length=150)


class ExamOut(BaseModel):
    exam_id: str
    name: str
    exam_type: str
    semester: Optional[int]
    department: Optional[str]
    date: str
    start_time: str
    end_time: str
    cutoff_minutes: int
    subject_code: str
    subject_name: Optional[str]
    created_by: Optional[str]
    created_at: str

    model_config = {"from_attributes": True}


class RoomAssignPayload(BaseModel):
    room_no: str
    block_name: Optional[str] = None
    capacity: Optional[int] = 30
    invigilator_id: Optional[str] = None
    external_examiner_name: Optional[str] = None
    external_examiner_college: Optional[str] = None
    coordinator_id: Optional[str] = None


class RoomAssignmentOut(BaseModel):
    id: int
    exam_id: str
    room_no: str
    display_room_no: str
    is_masked: bool = False
    reveals_at: Optional[str] = None
    block_name: Optional[str]
    capacity: Optional[int]
    invigilator_id: Optional[str]
    external_examiner_name: Optional[str]
    external_examiner_college: Optional[str]
    coordinator_id: Optional[str]
    status: str
    submitted_at: Optional[str]
    submitted_by: Optional[str]

    model_config = {"from_attributes": True}


class ExamSeatingOut(BaseModel):
    id: int
    exam_id: str
    room_no: str
    sl_no: int
    usn: str
    name: str
    branch: str
    subject_code: str
    seat_no: Optional[str]
    status: str
    marked_by: Optional[str]
    marked_source: Optional[str]
    marked_at: Optional[str]

    model_config = {"from_attributes": True}


class StudentMarkItem(BaseModel):
    usn: str
    status: str = Field(..., pattern=r"^(PRESENT|ABSENT)$")


class BulkMarkPayload(BaseModel):
    marks: List[StudentMarkItem]
    marked_source: str = Field("MANUAL", description="MANUAL or AI_SCAN")


class AdminOverridePayload(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500, description="Mandatory reason for admin unlocking/editing")
    new_status: str = Field("OPEN", description="OPEN or SUBMITTED")


class RoomSummaryItem(BaseModel):
    room_no: str
    block_name: Optional[str]
    invigilator_id: Optional[str]
    invigilator_name: Optional[str]
    status: str
    submitted_at: Optional[str]
    total_students: int
    present_count: int
    absent_count: int
    attendance_percentage: float
    absentees: List[Dict[str, Any]]


class BranchSummaryItem(BaseModel):
    branch: str
    total_students: int
    present_count: int
    absent_count: int
    attendance_percentage: float
