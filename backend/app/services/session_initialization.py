"""Backend-driven session initialisation from the configured timetable.

The academic backend prepares the day's sessions from the stored timetable
(``timetables`` -> ``timetable_entries``) instead of relying on the browser to
create records. The operation is:

* **Idempotent** - the generated ``session_id``/``allocation_id`` are
  deterministic, so a second run detects the existing rows and does nothing.
* **Concurrency safe** - inserts rely on primary-key uniqueness; a losing
  transaction rolls back to a savepoint and reports the slot as "already
  initialised" instead of failing the whole run.
* **Restricted to working academic days** - Saturdays and Sundays are skipped,
  and a date outside the semester / timetable validity window is treated as a
  holiday.
* **Limited to 09:00 - 17:00** - slots outside the institutional academic day
  are rejected and reported.
* **Never historical** - only the requested date is initialised, and the
  automatic daily job only ever prepares *today*.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Attendance,
    Batch,
    Section,
    Session as DbSession,
    SessionAllocation,
    Student,
    Subject,
    Timetable,
    TimetableEntry,
)
from app.schemas.timetable import (
    ACADEMIC_DAY_END,
    ACADEMIC_DAY_START,
    parse_hhmm,
    validate_academic_window,
)

logger = logging.getLogger("rollcall.services.session_initialization")

WEEKEND_DAYS = {"Saturday", "Sunday"}

STATUS_INITIALIZED = "INITIALIZED"
STATUS_NO_CLASSES = "NO_CLASSES"
STATUS_PENDING = "PENDING"
STATUS_FAILED = "FAILED"


def _sanitize(part: str, fallback: str = "X") -> str:
    cleaned = "".join(ch for ch in part.upper() if ch.isalnum() or ch in "-_")
    return cleaned[:24] or fallback


def build_session_id(target_date: datetime.date, entry: TimetableEntry) -> str:
    """Deterministic session identifier so re-runs stay idempotent."""
    return (
        f"AUTO-{target_date.strftime('%Y%m%d')}-"
        f"{_sanitize(entry.subject_code)}-{entry.period_number:02d}"
    )[:50]


def build_allocation_id(target_date: datetime.date, entry: TimetableEntry) -> str:
    """Deterministic allocation identifier so re-runs stay idempotent."""
    return (
        f"ALC-{target_date.strftime('%Y%m%d')}-"
        f"{_sanitize(entry.subject_code)}-{entry.period_number:02d}"
    )[:50]


def _active_timetables(db: Session, target_date: datetime.date) -> List[Timetable]:
    date_str = target_date.isoformat()
    stmt = select(Timetable).where(
        Timetable.is_active == 1,
        Timetable.effective_from <= date_str,
    )
    timetables = list(db.execute(stmt).scalars().all())
    return [t for t in timetables if not t.effective_to or t.effective_to >= date_str]


def _semester_window(db: Session, timetable: Timetable) -> Optional[tuple]:
    """Return the (start, end) semester window for a timetable, if known."""
    from app.db.models import Semester

    semester = db.get(Semester, timetable.semester_id)
    if semester is None:
        return None
    return (semester.start_date, semester.end_date)


def _entries_for_day(
    db: Session, timetable_ids: List[str], weekday: str
) -> List[TimetableEntry]:
    if not timetable_ids:
        return []
    stmt = select(TimetableEntry).where(
        TimetableEntry.timetable_id.in_(timetable_ids),
        TimetableEntry.day_of_week == weekday,
    )
    entries = list(db.execute(stmt).scalars().all())
    entries.sort(key=lambda e: (e.start_time or "", e.period_number or 0))
    return entries


def _subject_name(db: Session, subject_code: str) -> str:
    subject = db.get(Subject, subject_code)
    if subject is not None and subject.name:
        return subject.name
    return subject_code


def _students_for_entry(db: Session, entry: TimetableEntry) -> List[Student]:
    """Students covered by the slot (batch first, then section)."""
    stmt = select(Student)
    if entry.batch_id:
        stmt = stmt.where(Student.batch_id == entry.batch_id)
        students = list(db.execute(stmt).scalars().all())
        if students:
            return students
        stmt = select(Student)
    timetable = db.get(Timetable, entry.timetable_id)
    if timetable is None:
        return []
    stmt = stmt.where(Student.section_id == timetable.section_id)
    return list(db.execute(stmt).scalars().all())


def initialize_sessions_for_date(
    db: Session,
    target_date: datetime.date,
    actor_user_id: Optional[str] = None,
    actor_role: Optional[str] = None,
) -> Dict[str, Any]:
    """Prepare the sessions for ``target_date`` from the configured timetable."""
    result: Dict[str, Any] = {
        "date": target_date.isoformat(),
        "status": STATUS_NO_CLASSES,
        "scheduled_slots": 0,
        "created_sessions": [],
        "existing_sessions": [],
        "skipped_slots": [],
        "attendance_rows_prepared": 0,
        "timetable_count": 0,
        "message": "",
    }

    weekday = target_date.strftime("%A")
    if weekday in WEEKEND_DAYS:
        result["message"] = (
            f"{weekday} is not an academic working day, so no sessions were prepared."
        )
        return result

    timetables = _active_timetables(db, target_date)
    result["timetable_count"] = len(timetables)
    if not timetables:
        result["message"] = (
            "No active timetable is configured for this date, so there are no classes "
            "to initialise."
        )
        return result

    # Holiday awareness: a date outside the semester window is not a working day.
    for timetable in timetables:
        window = _semester_window(db, timetable)
        if window is None:
            continue
        start, end = window
        if not (start <= target_date.isoformat() <= end):
            result["message"] = (
                f"{target_date.isoformat()} falls outside the configured semester window "
                f"({start} - {end}); it is treated as a holiday."
            )
            result["status"] = STATUS_NO_CLASSES
            return result

    entries = _entries_for_day(db, [t.timetable_id for t in timetables], weekday)
    result["scheduled_slots"] = len(entries)
    if not entries:
        result["message"] = (
            f"No classes are scheduled for {weekday} {target_date.isoformat()} in the "
            "configured timetable."
        )
        return result

    for entry in entries:
        # Policy guard: only slots inside the institutional academic day.
        try:
            validate_academic_window(entry.start_time, entry.end_time)
        except ValueError as exc:
            result["skipped_slots"].append(
                {
                    "entry_id": entry.entry_id,
                    "subject_code": entry.subject_code,
                    "reason": str(exc),
                }
            )
            continue

        session_id = build_session_id(target_date, entry)
        allocation_id = build_allocation_id(target_date, entry)

        try:
            savepoint = db.begin_nested()
            existing = db.get(DbSession, session_id)
            if existing is not None:
                savepoint.rollback()
                result["existing_sessions"].append(
                    {
                        "session_id": session_id,
                        "subject_code": entry.subject_code,
                        "start_time": entry.start_time,
                        "end_time": entry.end_time,
                        "room_id": entry.room_id,
                    }
                )
                continue

            db_session = DbSession(
                session_id=session_id,
                date=target_date.isoformat(),
                subject=_subject_name(db, entry.subject_code),
                created_at=datetime.datetime.now(datetime.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                teacher_id=entry.faculty_id,
                subject_code=entry.subject_code,
                lifecycle_status="SCHEDULED",
            )
            db.add(db_session)

            allocation = SessionAllocation(
                allocation_id=allocation_id,
                session_id=session_id,
                timetable_entry_id=entry.entry_id,
                allocation_date=target_date.isoformat(),
                room_id=entry.room_id,
                start_time=entry.start_time,
                end_time=entry.end_time,
                batch_id=entry.batch_id,
                faculty_id=entry.faculty_id,
                lifecycle_status="SCHEDULED",
            )
            db.add(allocation)

            prepared = 0
            for student in _students_for_entry(db, entry):
                db.add(
                    Attendance(
                        attendance_id=str(uuid.uuid4()),
                        session_id=session_id,
                        allocation_id=allocation_id,
                        usn=student.usn,
                        room_id=entry.room_id,
                        status="UNREVIEWED",
                        source="timetable_auto_init",
                        confidence=1.0,
                    )
                )
                prepared += 1
            result["attendance_rows_prepared"] += prepared

            savepoint.commit()
            result["created_sessions"].append(
                {
                    "session_id": session_id,
                    "subject_code": entry.subject_code,
                    "subject": db_session.subject,
                    "start_time": entry.start_time,
                    "end_time": entry.end_time,
                    "room_id": entry.room_id,
                    "faculty_id": entry.faculty_id,
                    "batch_id": entry.batch_id,
                    "attendance_rows": prepared,
                }
            )
        except IntegrityError:
            # Another worker won the race for this slot: treat it as already initialised.
            db.rollback()
            result["existing_sessions"].append(
                {
                    "session_id": session_id,
                    "subject_code": entry.subject_code,
                    "start_time": entry.start_time,
                    "end_time": entry.end_time,
                    "room_id": entry.room_id,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            db.rollback()
            logger.exception("Session initialisation failed for entry %s", entry.entry_id)
            result["skipped_slots"].append(
                {
                    "entry_id": entry.entry_id,
                    "subject_code": entry.subject_code,
                    "reason": f"initialisation error: {exc}",
                }
            )

    db.commit()

    if result["created_sessions"]:
        result["status"] = STATUS_INITIALIZED
        result["message"] = (
            f"{len(result['created_sessions'])} session(s) initialised for "
            f"{target_date.isoformat()}."
        )
    elif result["existing_sessions"]:
        result["status"] = STATUS_INITIALIZED
        result["message"] = (
            f"All {len(result['existing_sessions'])} session(s) for "
            f"{target_date.isoformat()} were already initialised."
        )
    elif result["skipped_slots"]:
        result["status"] = STATUS_FAILED
        result["message"] = (
            "Every scheduled slot was rejected. Review the skipped slots and the "
            "09:00 - 17:00 academic window policy."
        )
    else:
        result["status"] = STATUS_NO_CLASSES
        result["message"] = "No sessions were prepared."

    return result


def run_daily_initialization(target_date: Optional[datetime.date] = None) -> Dict[str, Any]:
    """Entry point for the backend scheduler: initialise today's sessions.

    Opens its own database session so the background job never interferes with
    request scoped sessions. Errors are swallowed and logged: a failing job must
    never take the API down.
    """
    from app.db.connection import get_sync_session_factory

    SessionLocal = get_sync_session_factory()
    day = target_date or datetime.date.today()
    try:
        with SessionLocal() as db:
            result = initialize_sessions_for_date(db, day)
            logger.info(
                "Daily session initialisation for %s finished with status %s",
                day.isoformat(),
                result.get("status"),
            )
            return result
    except Exception:  # pragma: no cover - the scheduler must never crash the app
        logger.exception("Daily session initialisation failed for %s", day.isoformat())
        return {
            "date": day.isoformat(),
            "status": STATUS_FAILED,
            "message": "Session initialisation failed. The Sessions page shows the error.",
        }


def initialization_status(
    db: Session, target_date: datetime.date
) -> Dict[str, Any]:
    """Report the initialisation state of a date without writing anything."""
    weekday = target_date.strftime("%A")
    if weekday in WEEKEND_DAYS:
        return {
            "date": target_date.isoformat(),
            "status": STATUS_NO_CLASSES,
            "scheduled_slots": 0,
            "initialized_sessions": 0,
            "pending_sessions": 0,
            "message": f"{weekday} is not an academic working day.",
        }

    timetables = _active_timetables(db, target_date)
    entries = _entries_for_day(db, [t.timetable_id for t in timetables], weekday)
    expected = [build_session_id(target_date, e) for e in entries]

    initialized = 0
    pending = 0
    for session_id in expected:
        if db.get(DbSession, session_id) is not None:
            initialized += 1
        else:
            pending += 1

    if not entries:
        status = STATUS_NO_CLASSES
        message = (
            f"No classes are scheduled for {weekday} {target_date.isoformat()} in the "
            "configured timetable."
        )
    elif pending == 0:
        status = STATUS_INITIALIZED
        message = f"All {initialized} session(s) for {target_date.isoformat()} are initialised."
    else:
        status = STATUS_PENDING
        message = (
            f"{pending} of {len(expected)} session(s) for {target_date.isoformat()} are "
            "still pending initialisation."
        )

    return {
        "date": target_date.isoformat(),
        "status": status,
        "scheduled_slots": len(entries),
        "initialized_sessions": initialized,
        "pending_sessions": pending,
        "message": message,
    }
