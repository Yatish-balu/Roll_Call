"""Analytics and Attendance Summary Pydantic v2 schemas."""

from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class GroupSummaryBase(BaseModel):
    """Base metrics for room and branch summaries."""
    present: int = Field(ge=0, description="Count of confirmed PRESENT students")
    absent: int = Field(ge=0, description="Count of confirmed ABSENT students")
    pending: int = Field(ge=0, description="Count of PENDING marks awaiting resolution")
    unreviewed: int = Field(ge=0, description="Count of UNREVIEWED / ambiguous marks")
    unresolved: int = Field(ge=0, description="Total unresolved count (pending + unreviewed)")
    confirmed: int = Field(ge=0, description="Total confirmed count (present + absent)")
    total: int = Field(ge=0, description="Total records (confirmed + unresolved)")
    percentage: float = Field(ge=0.0, le=100.0, description="Confirmed percentage: present / confirmed * 100")
    unresolved_by_status: Optional[Dict[str, int]] = Field(
        default=None, description="Detailed counts for unresolved statuses"
    )

    model_config = ConfigDict(from_attributes=True)


class RoomWiseSummary(GroupSummaryBase):
    room_id: str = Field(..., description="Room identifier")


class BranchWiseSummary(GroupSummaryBase):
    branch: str = Field(..., description="Branch or department name")


class OverallSummary(GroupSummaryBase):
    confirmed_percentage: Optional[float] = Field(
        default=0.0, ge=0.0, le=100.0, description="Confirmed attendance percentage"
    )


class SummaryReportResponse(BaseModel):
    """Full attendance analytics summary report response."""
    room_wise: List[RoomWiseSummary] = Field(default_factory=list, description="Room-wise attendance aggregates")
    branch_wise: List[BranchWiseSummary] = Field(default_factory=list, description="Branch-wise attendance aggregates")
    overall: OverallSummary = Field(..., description="Overall attendance metrics")
    session_id: Optional[str] = Field(None, description="Target session if filtered by session")
    date: Optional[str] = Field(None, description="Session date if applicable")

    model_config = ConfigDict(from_attributes=True)


class ExportReportRequest(BaseModel):
    """Request payload for exporting attendance reports to Excel or PDF."""
    session_id: Optional[str] = Field(None, description="Optional target session ID to export")
    date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Optional session date to export (YYYY-MM-DD)")
    title: Optional[str] = Field("RollCall AI Attendance Report", description="Title for PDF report")
    include_branch_summary: bool = Field(True, description="Whether to include branch summary")

