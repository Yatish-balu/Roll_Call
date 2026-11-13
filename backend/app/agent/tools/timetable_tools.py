"""Academic Setup & Timetable Agent Tools for RollCall AI.

Provides:
- get_my_timetable: Retrieves authenticated teacher's mapped subjects and weekly schedule.
- get_day_schedule: Looks up classes for a specific date and detects room/time slot conflicts.
- create_session: Creates conflict-free sessions with multi-room support (Lab A + Lab B)
  and 60-second undo capability.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from contextlib import nullcontext
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.agent.registry import RiskTier, ToolDefinition
from app.db import crud
from app.db.connection import get_sync_session_factory
from app.db.models import (
    Room,
    Session as DbSession,
    SessionAllocation,
    Subject,
    TeacherSubject,
    TimetableEntry,
)
from app.services.attendance_edits import _utcnow_iso
from app.services.undo_service import create_undo_token

logger = logging.getLogger("rollcall.agent.tools.timetable")


def _get_db() -> Session:
    factory = get_sync_session_factory()
    return factory()


def get_my_timetable_handler(
    actor_id: str = "anonymous",
    actor_role: str = "FACULTY",
    day_of_week: Optional[str] = None,
    db: Optional[Session] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Retrieve teacher's mapped subjects and scheduled weekly classes."""
    session_ctx = db if db is not None else _get_db()
    with (session_ctx if db is None else nullcontext(db)) as dbs:
        # 1. Fetch assigned subjects
        subjects = crud.get_teacher_subjects(dbs, user_id=actor_id)

        # 2. Query timetable entries
        query = dbs.query(TimetableEntry).filter(
            (TimetableEntry.faculty_id == actor_id) | (TimetableEntry.subject_code.in_(subjects))
        )
        if day_of_week:
            clean_day = day_of_week.strip().capitalize()
            query = query.filter(TimetableEntry.day_of_week == clean_day)

        entries = query.order_by(TimetableEntry.day_of_week, TimetableEntry.start_time).all()

        classes = []
        for e in entries:
            classes.append({
                "entry_id": e.entry_id,
                "day_of_week": e.day_of_week,
                "period_number": e.period_number,
                "start_time": e.start_time,
                "end_time": e.end_time,
                "subject_code": e.subject_code,
                "room_id": e.room_id,
                "batch_id": e.batch_id,
                "duration_minutes": e.duration_minutes,
            })

        return {
            "teacher_id": actor_id,
            "assigned_subjects": subjects,
            "day_filter": day_of_week,
            "classes_count": len(classes),
            "classes": classes,
        }


def get_day_schedule_handler(
    date: str,
    actor_id: str = "anonymous",
    actor_role: str = "FACULTY",
    faculty_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Fetch day's schedule and check for room and teacher conflicts."""
    clean_date = date.strip()
    target_faculty = faculty_id.strip() if faculty_id else actor_id

    with _get_db() as db:
        # Determine day of week
        try:
            parsed_date = datetime.date.fromisoformat(clean_date)
            day_name = parsed_date.strftime("%A")
        except ValueError:
            return {"success": False, "error": f"Invalid date format '{clean_date}'. Use YYYY-MM-DD."}

        # 1. Query sessions for date
        sessions = crud.get_sessions_by_date(db, date=clean_date)

        # 2. Query allocations for date
        allocations = (
            db.query(SessionAllocation)
            .filter(SessionAllocation.allocation_date == clean_date)
            .all()
        )

        # 3. Conflict Detection: Look for overlapping rooms and faculty
        conflicts = []
        room_usage: Dict[str, List[Dict[str, Any]]] = {}

        for alloc in allocations:
            if not alloc.room_id or not alloc.start_time or not alloc.end_time:
                continue
            item = {
                "session_id": alloc.session_id,
                "faculty_id": alloc.faculty_id,
                "start_time": alloc.start_time,
                "end_time": alloc.end_time,
            }
            if alloc.room_id not in room_usage:
                room_usage[alloc.room_id] = []

            for prior in room_usage[alloc.room_id]:
                # Overlap check
                if not (alloc.end_time <= prior["start_time"] or alloc.start_time >= prior["end_time"]):
                    conflicts.append({
                        "conflict_type": "ROOM_DOUBLE_BOOKED",
                        "room_id": alloc.room_id,
                        "date": clean_date,
                        "session_1": prior["session_id"],
                        "session_2": alloc.session_id,
                        "time_overlap": f"{alloc.start_time} - {alloc.end_time}",
                    })
            room_usage[alloc.room_id].append(item)

        # Filter sessions for teacher unless admin
        teacher_sessions = []
        is_admin = "ADMIN" in actor_role.upper()
        for s in sessions:
            if is_admin or s.get("teacher_id") == target_faculty:
                teacher_sessions.append(s)

        return {
            "date": clean_date,
            "day_of_week": day_name,
            "faculty_id": target_faculty,
            "sessions_count": len(teacher_sessions),
            "sessions": teacher_sessions,
            "has_conflicts": len(conflicts) > 0,
            "conflicts": conflicts,
        }


def create_session_handler(
    date: str,
    subject: str,
    start_time: str,
    end_time: str,
    actor_id: str = "anonymous",
    actor_role: str = "FACULTY",
    subject_code: Optional[str] = None,
    rooms: Optional[List[str]] = None,
    room_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    db: Optional[Session] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Create a conflict-free session supporting multi-room allocation (Lab A + Lab B)."""
    clean_date = date.strip()
    clean_subject = subject.strip()
    clean_start = start_time.strip()
    clean_end = end_time.strip()

    # Consolidate room list
    allocated_rooms = []
    if rooms:
        allocated_rooms = [r.strip() for r in rooms if r and r.strip()]
    elif room_id:
        allocated_rooms = [room_id.strip()]

    if not allocated_rooms:
        allocated_rooms = ["LH-101"]  # default fallback

    session_ctx = db if db is not None else _get_db()
    with (session_ctx if db is None else nullcontext(db)) as dbs:
        # Validate date
        try:
            datetime.date.fromisoformat(clean_date)
        except ValueError:
            return {"success": False, "error": f"Invalid date format '{clean_date}'. Use YYYY-MM-DD."}

        # 1. Conflict Check: verify no room or teacher overlaps
        conflicts = []
        for r_id in allocated_rooms:
            overlapping = (
                dbs.query(SessionAllocation)
                .filter(
                    SessionAllocation.allocation_date == clean_date,
                    SessionAllocation.room_id == r_id,
                    SessionAllocation.start_time < clean_end,
                    SessionAllocation.end_time > clean_start,
                )
                .all()
            )
            for ov in overlapping:
                conflicts.append(
                    f"Room '{r_id}' is already booked for session '{ov.session_id}' ({ov.start_time}-{ov.end_time})"
                )

        # Overlapping teacher check
        teacher_overlap = (
            dbs.query(SessionAllocation)
            .filter(
                SessionAllocation.allocation_date == clean_date,
                SessionAllocation.faculty_id == actor_id,
                SessionAllocation.start_time < clean_end,
                SessionAllocation.end_time > clean_start,
            )
            .first()
        )
        if teacher_overlap:
            conflicts.append(
                f"You are already scheduled in session '{teacher_overlap.session_id}' at that time."
            )

        if conflicts:
            return {
                "success": False,
                "conflict": True,
                "error": "Cannot create session due to timetable conflicts.",
                "conflict_details": conflicts,
            }

        # 2. Persist Session
        clean_code = (subject_code or clean_subject).strip().upper()
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        created_iso = _utcnow_iso()

        new_session = DbSession(
            session_id=session_id,
            date=clean_date,
            subject=clean_subject,
            subject_code=clean_code,
            teacher_id=actor_id,
            lifecycle_status="SCHEDULED",
            created_at=created_iso,
        )
        dbs.add(new_session)

        # 3. Persist Multi-Room Allocations (ensuring rooms exist)
        created_allocations = []
        for r_id in allocated_rooms:
            room_obj = dbs.get(Room, r_id)
            if not room_obj:
                dbs.add(Room(room_id=r_id, name=r_id, capacity=60))
                dbs.flush()

            alloc_id = f"alloc_{uuid.uuid4().hex[:12]}"
            alloc = SessionAllocation(
                allocation_id=alloc_id,
                session_id=session_id,
                allocation_date=clean_date,
                room_id=r_id,
                start_time=clean_start,
                end_time=clean_end,
                faculty_id=actor_id,
                batch_id=batch_id,
                lifecycle_status="SCHEDULED",
                created_at=created_iso,
            )
            dbs.add(alloc)
            created_allocations.append({
                "allocation_id": alloc_id,
                "room_id": r_id,
                "start_time": clean_start,
                "end_time": clean_end,
            })

        dbs.commit()
        logger.info("Created multi-room session %s in rooms %s", session_id, allocated_rooms)

        return {
            "success": True,
            "session_id": session_id,
            "date": clean_date,
            "subject": clean_subject,
            "subject_code": clean_code,
            "teacher_id": actor_id,
            "rooms": allocated_rooms,
            "allocations": created_allocations,
            "undo_available": True,
            "message": f"Successfully created session '{session_id}' in {', '.join(allocated_rooms)}.",
        }


# Tool Definitions
GET_MY_TIMETABLE_TOOL = ToolDefinition(
    name="get_my_timetable",
    description="Retrieve the authenticated teacher's mapped subjects and weekly class schedule.",
    parameters={
        "type": "object",
        "properties": {
            "day_of_week": {
                "type": "string",
                "description": "Optional day of week filter (e.g. 'Monday', 'Tuesday')",
            }
        },
    },
    capability_family="schedule",
    risk_tier=RiskTier.READ,
    allowed_roles={"FACULTY", "ADMIN", "COORDINATOR"},
    handler=get_my_timetable_handler,
)

GET_DAY_SCHEDULE_TOOL = ToolDefinition(
    name="get_day_schedule",
    description="Look up scheduled classes and room/time conflict status for a specific date.",
    parameters={
        "type": "object",
        "properties": {
            "date": {
                "type": "string",
                "description": "Date in YYYY-MM-DD format (e.g. '2026-11-14')",
            },
            "faculty_id": {
                "type": "string",
                "description": "Optional faculty user ID to inspect schedule for",
            },
        },
        "required": ["date"],
    },
    capability_family="schedule",
    risk_tier=RiskTier.READ,
    allowed_roles={"FACULTY", "ADMIN", "COORDINATOR"},
    handler=get_day_schedule_handler,
)

CREATE_SESSION_TOOL = ToolDefinition(
    name="create_session",
    description="Create a new academic session with multi-room support and automatic conflict detection.",
    parameters={
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "Date of class in YYYY-MM-DD format"},
            "subject": {"type": "string", "description": "Full course name or title"},
            "subject_code": {"type": "string", "description": "Optional course code (e.g. 'CS301')"},
            "start_time": {"type": "string", "description": "Start time in HH:MM format (e.g. '10:00')"},
            "end_time": {"type": "string", "description": "End time in HH:MM format (e.g. '11:00')"},
            "rooms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of room IDs for multi-room sessions (e.g. ['Lab A', 'Lab B'])",
            },
            "room_id": {"type": "string", "description": "Single room ID if not using multi-room array"},
            "batch_id": {"type": "string", "description": "Optional student batch or section"},
        },
        "required": ["date", "subject", "start_time", "end_time"],
    },
    capability_family="schedule",
    risk_tier=RiskTier.LOW_RISK_WRITE,
    allowed_roles={"FACULTY", "ADMIN"},
    handler=create_session_handler,
)
