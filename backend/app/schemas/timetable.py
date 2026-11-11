"""Pydantic v2 schemas for timetable management (N-timewindow policy).

The institutional academic day is strictly 09:00 - 17:00. The policy is
enforced here so every writer (API and background initialisation) applies the
exact same rule.
"""

from __future__ import annotations

import datetime
import re
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Academic day window (inclusive bounds)
# ---------------------------------------------------------------------------
ACADEMIC_DAY_START = "09:00"
ACADEMIC_DAY_END = "17:00"

DAYS_OF_WEEK = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def parse_hhmm(value: str) -> int:
    """Convert an 'HH:MM' string into minutes since midnight."""
    match = _TIME_RE.match(value.strip())
    if not match:
        raise ValueError(f"Time '{value}' must use the 24-hour HH:MM format.")
    hours, minutes = int(match.group(1)), int(match.group(2))
    return hours * 60 + minutes


def format_hhmm(minutes: int) -> str:
    """Convert minutes since midnight back into an 'HH:MM' string."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def validate_academic_window(start_time: str, end_time: str) -> None:
    """Raise ValueError when the slot violates the 09:00 - 17:00 policy."""
    start = parse_hhmm(start_time)
    end = parse_hhmm(end_time)

    if end <= start:
        raise ValueError("End time must be later than start time.")
    if start < parse_hhmm(ACADEMIC_DAY_START):
        raise ValueError(
            f"Classes cannot start before {ACADEMIC_DAY_START}. Official academic "
            "sessions run between 09:00 and 17:00."
        )
    if end > parse_hhmm(ACADEMIC_DAY_END):
        raise ValueError(
            f"Classes cannot end after {ACADEMIC_DAY_END}. Official academic "
            "sessions run between 09:00 and 17:00."
        )


class TimetableEntryBase(BaseModel):
    timetable_id: str = Field(..., min_length=1, max_length=100, description="Owning timetable identifier")
    day_of_week: str = Field(..., description="Weekday name (Monday - Saturday)")
    period_number: int = Field(..., ge=1, le=12, description="Period number inside the academic day")
    start_time: str = Field(..., description="Slot start time in HH:MM (24-hour)")
    end_time: str = Field(..., description="Slot end time in HH:MM (24-hour)")
    subject_code: str = Field(..., min_length=1, max_length=50, description="Subject code")
    room_id: str = Field(..., min_length=1, max_length=50, description="Room identifier")
    faculty_id: Optional[str] = Field(None, max_length=100, description="Assigned faculty user id")
    batch_id: Optional[str] = Field(None, max_length=50, description="Assigned batch identifier")
    duration_minutes: Optional[int] = Field(None, ge=1, le=480, description="Derived slot duration")

    @field_validator("day_of_week")
    @classmethod
    def validate_day(cls, v: str) -> str:
        cleaned = v.strip().title()
        if cleaned not in DAYS_OF_WEEK:
            raise ValueError(
                f"day_of_week must be one of: {', '.join(DAYS_OF_WEEK)}."
            )
        return cleaned

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        cleaned = v.strip()
        if not _TIME_RE.match(cleaned):
            raise ValueError(f"Time '{cleaned}' must use the 24-hour HH:MM format.")
        return cleaned

    @field_validator("subject_code")
    @classmethod
    def validate_subject_code(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("Subject code cannot be empty.")
        return cleaned

    @field_validator("room_id", "timetable_id")
    @classmethod
    def validate_identifier(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Identifier cannot be empty.")
        return cleaned

    @field_validator("batch_id")
    @classmethod
    def validate_batch_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        cleaned = v.strip()
        return cleaned or None

    def enforce_academic_window(self) -> "TimetableEntryBase":
        validate_academic_window(self.start_time, self.end_time)
        if self.duration_minutes is None:
            self.duration_minutes = parse_hhmm(self.end_time) - parse_hhmm(self.start_time)
        return self


class TimetableEntryCreate(TimetableEntryBase):
    entry_id: Optional[str] = Field(None, max_length=100, description="Optional explicit entry id")


class TimetableEntryUpdate(BaseModel):
    day_of_week: Optional[str] = None
    period_number: Optional[int] = Field(None, ge=1, le=12)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    subject_code: Optional[str] = None
    room_id: Optional[str] = None
    faculty_id: Optional[str] = None
    batch_id: Optional[str] = None

    @field_validator("day_of_week")
    @classmethod
    def validate_day(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        cleaned = v.strip().title()
        if cleaned not in DAYS_OF_WEEK:
            raise ValueError(f"day_of_week must be one of: {', '.join(DAYS_OF_WEEK)}.")
        return cleaned

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        cleaned = v.strip()
        if not _TIME_RE.match(cleaned):
            raise ValueError(f"Time '{cleaned}' must use the 24-hour HH:MM format.")
        return cleaned

    @field_validator("subject_code")
    @classmethod
    def validate_subject_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("Subject code cannot be empty.")
        return cleaned


class TimetableEntryResponse(BaseModel):
    entry_id: str
    timetable_id: str
    day_of_week: str
    period_number: int
    start_time: str
    end_time: str
    subject_code: str
    subject_name: Optional[str] = None
    room_id: str
    room_name: Optional[str] = None
    faculty_id: Optional[str] = None
    faculty_name: Optional[str] = None
    batch_id: Optional[str] = None
    batch_label: Optional[str] = None
    duration_minutes: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class TimetableDayView(BaseModel):
    day_of_week: str
    date: Optional[str] = Field(None, description="Calendar date the day maps to (ISO)")
    entries: List[TimetableEntryResponse] = Field(default_factory=list)


class TimetableWeekResponse(BaseModel):
    """Weekly teaching schedule derived from the configured timetables."""

    week_start: str = Field(..., description="Monday of the requested week (YYYY-MM-DD)")
    days: List[TimetableDayView] = Field(default_factory=list)
    total_entries: int = 0
    timetable_count: int = 0
    has_timetable: bool = False
    message: Optional[str] = Field(
        None,
        description="Human readable explanation when no timetable is configured",
    )


class TimetableReferenceData(BaseModel):
    """Reference master data used to build timetable entry forms."""

    departments: List[dict] = Field(default_factory=list)
    semesters: List[dict] = Field(default_factory=list)
    academic_years: List[dict] = Field(default_factory=list)
    sections: List[dict] = Field(default_factory=list)
    batches: List[dict] = Field(default_factory=list)
    subjects: List[dict] = Field(default_factory=list)
    rooms: List[dict] = Field(default_factory=list)
    timetables: List[dict] = Field(default_factory=list)


class TimetableCreate(BaseModel):
    timetable_id: Optional[str] = Field(None, max_length=100)
    dept_id: str = Field(..., min_length=1, max_length=50)
    semester_id: str = Field(..., min_length=1, max_length=50)
    section_id: str = Field(..., min_length=1, max_length=50)
    year_id: str = Field(..., min_length=1, max_length=50)
    effective_from: str = Field(..., description="ISO date the timetable becomes effective")
    effective_to: Optional[str] = Field(None, description="ISO date the timetable expires")

    @field_validator("effective_from", "effective_to")
    @classmethod
    def validate_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        cleaned = v.strip()
        try:
            datetime.date.fromisoformat(cleaned)
        except ValueError:
            raise ValueError(f"Date '{cleaned}' must be a valid calendar date (YYYY-MM-DD).")
        return cleaned
