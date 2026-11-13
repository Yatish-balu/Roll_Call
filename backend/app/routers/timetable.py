"""FastAPI router for timetable configuration and weekly teaching schedule.

Scope rules
-----------
* ADMIN may read and write every timetable.
* FACULTY may read the timetable of their own teaching slots (entries whose
  ``faculty_id`` is their user id or whose ``subject_code`` is mapped to them)
  and may create/update entries only for their own mapped subject codes.
* VIEWER is read-only.

All writes enforce the institutional 09:00 - 17:00 academic window and reject
overlapping allocations for the same room, faculty member or batch.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Role, get_current_user, require_roles
from app.auth.session_scope import resolve_session_scope
from app.db.models import (
    AcademicYear,
    Batch,
    Department,
    Room,
    Section,
    Semester,
    Subject,
    Timetable,
    TimetableEntry,
)
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser
from app.schemas.timetable import (
    DAYS_OF_WEEK,
    TimetableCreate,
    TimetableEntryCreate,
    TimetableEntryResponse,
    TimetableEntryUpdate,
    TimetableReferenceData,
    TimetableWeekResponse,
    parse_hhmm,
    validate_academic_window,
)

logger = logging.getLogger("rollcall.routers.timetable")

router = APIRouter(prefix="/timetable", tags=["Timetable"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry_to_response(entry: TimetableEntry, db: Session) -> TimetableEntryResponse:
    subject_name = None
    room_name = None
    batch_label = None
    faculty_name = None

    if entry.subject:
        subject_name = entry.subject.name
    if entry.room:
        room_name = entry.room.name

    if entry.batch_id:
        batch = db.get(Batch, entry.batch_id)
        if batch is not None:
            batch_label = batch.batch_label

    if entry.faculty_id:
        from app.db.models import User  # local import avoids a circular import

        user = db.get(User, entry.faculty_id)
        if user is not None:
            faculty_name = user.email

    return TimetableEntryResponse(
        entry_id=entry.entry_id,
        timetable_id=entry.timetable_id,
        day_of_week=entry.day_of_week,
        period_number=entry.period_number,
        start_time=entry.start_time,
        end_time=entry.end_time,
        subject_code=entry.subject_code,
        subject_name=subject_name,
        room_id=entry.room_id,
        room_name=room_name,
        faculty_id=entry.faculty_id,
        faculty_name=faculty_name,
        batch_id=entry.batch_id,
        batch_label=batch_label,
        duration_minutes=entry.duration_minutes,
    )


def _mapped_subject_codes(db: Session, current_user: AuthenticatedUser) -> List[str]:
    from app.db import crud

    return crud.get_teacher_subjects(db, user_id=current_user.user_id)


def _visible_entry_filter(db: Session, current_user: AuthenticatedUser):
    """Return a SQLAlchemy filter restricting entries to the caller's scope."""
    if current_user.role == Role.ADMIN:
        return None
    codes = _mapped_subject_codes(db, current_user)
    return TimetableEntry.faculty_id == current_user.user_id, codes


def _assert_subject_allowed(db: Session, current_user: AuthenticatedUser, subject_code: str) -> None:
    if current_user.role == Role.ADMIN:
        return
    codes = _mapped_subject_codes(db, current_user)
    if subject_code.upper() not in codes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Subject code '{subject_code}' is not assigned to you. "
                "You can only manage timetable entries for your own subjects."
            ),
        )


def _find_overlaps(
    db: Session,
    timetable_id: str,
    day_of_week: str,
    start_time: str,
    end_time: str,
    room_id: str,
    faculty_id: Optional[str],
    batch_id: Optional[str],
    exclude_entry_id: Optional[str] = None,
) -> List[TimetableEntry]:
    """Return entries that clash on room, faculty member or batch."""
    stmt = select(TimetableEntry).where(
        TimetableEntry.timetable_id == timetable_id,
        TimetableEntry.day_of_week == day_of_week,
    )
    if exclude_entry_id:
        stmt = stmt.where(TimetableEntry.entry_id != exclude_entry_id)

    conflicts: List[TimetableEntry] = []
    new_start = parse_hhmm(start_time)
    new_end = parse_hhmm(end_time)

    for entry in db.execute(stmt).scalars().all():
        try:
            existing_start = parse_hhmm(entry.start_time)
            existing_end = parse_hhmm(entry.end_time)
        except ValueError:
            continue
        if new_end <= existing_start or new_start >= existing_end:
            continue

        same_room = entry.room_id == room_id
        same_faculty = bool(faculty_id) and entry.faculty_id == faculty_id
        same_batch = bool(batch_id) and entry.batch_id == batch_id
        if same_room or same_faculty or same_batch:
            conflicts.append(entry)
    return conflicts


def _describe_conflicts(conflicts: List[TimetableEntry]) -> str:
    parts: List[str] = []
    for entry in conflicts:
        reasons = []
        if entry.room_id:
            reasons.append(f"room {entry.room_id}")
        if entry.faculty_id:
            reasons.append(f"faculty {entry.faculty_id}")
        if entry.batch_id:
            reasons.append(f"batch {entry.batch_id}")
        parts.append(
            f"{entry.subject_code} ({entry.start_time}-{entry.end_time}, "
            f"{'/'.join(reasons) or 'same timetable'})"
        )
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# GET /api/v1/timetable/week
# ---------------------------------------------------------------------------

@router.get(
    "/week",
    response_model=TimetableWeekResponse,
    summary="Weekly teaching schedule derived from configured timetables",
)
def get_timetable_week(
    week_start: Optional[str] = Query(
        None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Any date inside the requested week (the Monday is used)",
    ),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    today = datetime.date.today()
    if week_start:
        anchor = datetime.date.fromisoformat(week_start)
    else:
        anchor = today
    monday = anchor - datetime.timedelta(days=anchor.weekday())

    timetable_rows = db.execute(select(Timetable).where(Timetable.is_active == 1)).scalars().all()
    timetable_ids = [t.timetable_id for t in timetable_rows]

    entries: List[TimetableEntry] = []
    if timetable_ids:
        stmt = select(TimetableEntry).where(TimetableEntry.timetable_id.in_(timetable_ids))
        if current_user.role != Role.ADMIN:
            codes = _mapped_subject_codes(db, current_user)
            stmt = stmt.where(
                (TimetableEntry.faculty_id == current_user.user_id)
                | (TimetableEntry.subject_code.in_(codes) if codes else TimetableEntry.faculty_id.is_(None))
            )
        entries = list(db.execute(stmt).scalars().all())

    days = []
    total = 0
    for index, day_name in enumerate(DAYS_OF_WEEK):
        day_date = monday + datetime.timedelta(days=index)
        day_entries = [e for e in entries if (e.day_of_week or "").title() == day_name]
        day_entries.sort(key=lambda e: (e.start_time or "", e.period_number or 0))
        total += len(day_entries)
        days.append(
            {
                "day_of_week": day_name,
                "date": day_date.isoformat(),
                "entries": [_entry_to_response(e, db).model_dump() for e in day_entries],
            }
        )

    message = None
    if not timetable_rows:
        message = (
            "No active timetable is configured on the server. Configure a timetable "
            "(department, semester, section and academic year) to publish a weekly schedule."
        )
    elif not entries:
        message = "The configured timetable has no entries visible to your account yet."

    return {
        "week_start": monday.isoformat(),
        "days": days,
        "total_entries": total,
        "timetable_count": len(timetable_rows),
        "has_timetable": bool(timetable_rows),
        "message": message,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/timetable/entries
# ---------------------------------------------------------------------------

@router.get(
    "/entries",
    response_model=List[TimetableEntryResponse],
    summary="List timetable entries",
)
def list_timetable_entries(
    timetable_id: Optional[str] = Query(None, description="Restrict to a single timetable"),
    day_of_week: Optional[str] = Query(None, description="Restrict to a weekday name"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    stmt = select(TimetableEntry)
    if timetable_id:
        stmt = stmt.where(TimetableEntry.timetable_id == timetable_id)
    if day_of_week:
        stmt = stmt.where(TimetableEntry.day_of_week == day_of_week.strip().title())
    if current_user.role != Role.ADMIN:
        codes = _mapped_subject_codes(db, current_user)
        stmt = stmt.where(
            (TimetableEntry.faculty_id == current_user.user_id)
            | (TimetableEntry.subject_code.in_(codes) if codes else TimetableEntry.faculty_id.is_(None))
        )
    entries = list(db.execute(stmt).scalars().all())
    entries.sort(key=lambda e: (e.day_of_week or "", e.start_time or ""))
    return [_entry_to_response(e, db).model_dump() for e in entries]


# ---------------------------------------------------------------------------
# GET /api/v1/timetable/reference
# ---------------------------------------------------------------------------

@router.get(
    "/reference",
    response_model=TimetableReferenceData,
    summary="Reference master data for timetable configuration",
)
def get_timetable_reference(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    departments = [
        {"dept_id": d.dept_id, "name": d.name}
        for d in db.execute(select(Department)).scalars().all()
    ]
    semesters = [
        {
            "semester_id": s.semester_id,
            "semester_number": s.semester_number,
            "semester_label": s.semester_label,
            "year_id": s.year_id,
        }
        for s in db.execute(select(Semester)).scalars().all()
    ]
    years = [
        {"year_id": y.year_id, "label": getattr(y, "year_label", None) or y.year_id}
        for y in db.execute(select(AcademicYear)).scalars().all()
    ]
    sections = [
        {"section_id": s.section_id, "section_label": s.section_label, "dept_id": s.dept_id}
        for s in db.execute(select(Section)).scalars().all()
    ]
    batches = [
        {
            "batch_id": b.batch_id,
            "batch_label": b.batch_label,
            "batch_type": b.batch_type,
            "section_id": b.section_id,
        }
        for b in db.execute(select(Batch)).scalars().all()
    ]
    subjects = [
        {
            "subject_code": s.subject_code,
            "name": s.name,
            "subject_type": s.subject_type,
            "dept_id": s.dept_id,
        }
        for s in db.execute(select(Subject)).scalars().all()
    ]
    rooms = [
        {
            "room_id": r.room_id,
            "name": r.name,
            "room_type": getattr(r, "room_type", None),
            "capacity": getattr(r, "capacity", None),
        }
        for r in db.execute(select(Room)).scalars().all()
    ]
    timetables = [
        {
            "timetable_id": t.timetable_id,
            "dept_id": t.dept_id,
            "semester_id": t.semester_id,
            "section_id": t.section_id,
            "year_id": t.year_id,
            "effective_from": t.effective_from,
            "effective_to": t.effective_to,
            "is_active": t.is_active,
        }
        for t in db.execute(select(Timetable)).scalars().all()
    ]
    return {
        "departments": departments,
        "semesters": semesters,
        "academic_years": years,
        "sections": sections,
        "batches": batches,
        "subjects": subjects,
        "rooms": rooms,
        "timetables": timetables,
    }


# ---------------------------------------------------------------------------
# POST /api/v1/timetable/entries
# ---------------------------------------------------------------------------

@router.post(
    "/entries",
    response_model=TimetableEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a timetable entry",
    responses={
        403: {"description": "Subject code is not assigned to the caller"},
        409: {"description": "Overlapping allocation for room, faculty or batch"},
        422: {"description": "Invalid time window (must be within 09:00 - 17:00)"},
    },
)
def create_timetable_entry(
    payload: TimetableEntryCreate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _assert_subject_allowed(db, current_user, payload.subject_code)

    try:
        validate_academic_window(payload.start_time, payload.end_time)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )

    if db.get(Timetable, payload.timetable_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Timetable '{payload.timetable_id}' was not found.",
        )

    # Faculty always create entries for themselves; only an admin may assign an
    # entry to another faculty member. Using the effective value for the clash
    # check also prevents double-booking by passing a different faculty_id.
    effective_faculty_id = (
        payload.faculty_id if current_user.role == Role.ADMIN else current_user.user_id
    )

    conflicts = _find_overlaps(
        db,
        timetable_id=payload.timetable_id,
        day_of_week=payload.day_of_week,
        start_time=payload.start_time,
        end_time=payload.end_time,
        room_id=payload.room_id,
        faculty_id=effective_faculty_id,
        batch_id=payload.batch_id,
    )
    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The slot overlaps an existing allocation: "
                f"{_describe_conflicts(conflicts)}."
            ),
        )

    entry_id = payload.entry_id or f"TT-{uuid.uuid4().hex[:12].upper()}"
    duration = parse_hhmm(payload.end_time) - parse_hhmm(payload.start_time)

    entry = TimetableEntry(
        entry_id=entry_id,
        timetable_id=payload.timetable_id,
        day_of_week=payload.day_of_week,
        period_number=payload.period_number,
        start_time=payload.start_time,
        end_time=payload.end_time,
        subject_code=payload.subject_code,
        room_id=payload.room_id,
        faculty_id=effective_faculty_id,
        batch_id=payload.batch_id,
        duration_minutes=duration,
    )

    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A timetable entry with id '{entry_id}' already exists.",
        )
    db.refresh(entry)
    return _entry_to_response(entry, db).model_dump()


# ---------------------------------------------------------------------------
# PUT /api/v1/timetable/entries/{entry_id}
# ---------------------------------------------------------------------------

@router.put(
    "/entries/{entry_id}",
    response_model=TimetableEntryResponse,
    summary="Update a timetable entry",
    responses={
        404: {"description": "Entry not found"},
        409: {"description": "Overlapping allocation for room, faculty or batch"},
        422: {"description": "Invalid time window (must be within 09:00 - 17:00)"},
    },
)
def update_timetable_entry(
    entry_id: str,
    payload: TimetableEntryUpdate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    entry = db.get(TimetableEntry, entry_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Timetable entry '{entry_id}' was not found.",
        )

    requested_subject = payload.subject_code.upper() if payload.subject_code else entry.subject_code

    if current_user.role == Role.ADMIN:
        effective_faculty_id = (
            payload.faculty_id if payload.faculty_id is not None else entry.faculty_id
        )
    else:
        # Faculty may only edit entries they own (or an unassigned entry for a
        # subject mapped to them), may never hand an entry to another user, and
        # must keep the resulting subject inside their own mapping. The previous
        # code skipped the subject check whenever the caller owned the entry,
        # which allowed moving it to any subject.
        if entry.faculty_id not in (None, current_user.user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only modify your own timetable entries.",
            )
        _assert_subject_allowed(db, current_user, requested_subject)
        if payload.faculty_id is not None and payload.faculty_id != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot assign a timetable entry to another faculty member.",
            )
        effective_faculty_id = entry.faculty_id or current_user.user_id

    updated = {
        "day_of_week": payload.day_of_week if payload.day_of_week is not None else entry.day_of_week,
        "period_number": payload.period_number if payload.period_number is not None else entry.period_number,
        "start_time": payload.start_time if payload.start_time is not None else entry.start_time,
        "end_time": payload.end_time if payload.end_time is not None else entry.end_time,
        "subject_code": requested_subject,
        "room_id": payload.room_id if payload.room_id else entry.room_id,
        "faculty_id": effective_faculty_id,
        "batch_id": payload.batch_id if payload.batch_id is not None else entry.batch_id,
    }

    try:
        validate_academic_window(updated["start_time"], updated["end_time"])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )

    conflicts = _find_overlaps(
        db,
        timetable_id=entry.timetable_id,
        day_of_week=updated["day_of_week"],
        start_time=updated["start_time"],
        end_time=updated["end_time"],
        room_id=updated["room_id"],
        faculty_id=updated["faculty_id"],
        batch_id=updated["batch_id"],
        exclude_entry_id=entry.entry_id,
    )
    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The updated slot overlaps an existing allocation: "
                f"{_describe_conflicts(conflicts)}."
            ),
        )

    for key, value in updated.items():
        setattr(entry, key, value)
    entry.duration_minutes = parse_hhmm(entry.end_time) - parse_hhmm(entry.start_time)

    db.commit()
    db.refresh(entry)
    return _entry_to_response(entry, db).model_dump()


# ---------------------------------------------------------------------------
# DELETE /api/v1/timetable/entries/{entry_id}
# ---------------------------------------------------------------------------

@router.delete(
    "/entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a timetable entry",
)
def delete_timetable_entry(
    entry_id: str,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> None:
    entry = db.get(TimetableEntry, entry_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Timetable entry '{entry_id}' was not found.",
        )
    if current_user.role != Role.ADMIN and entry.faculty_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only remove your own timetable entries.",
        )
    db.delete(entry)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# POST /api/v1/timetable (create the timetable container)
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=Dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="Create a timetable container",
)
def create_timetable(
    payload: TimetableCreate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    timetable_id = payload.timetable_id or f"TTM-{uuid.uuid4().hex[:10].upper()}"
    existing = db.get(Timetable, timetable_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Timetable '{timetable_id}' already exists.",
        )

    timetable = Timetable(
        timetable_id=timetable_id,
        dept_id=payload.dept_id,
        semester_id=payload.semester_id,
        section_id=payload.section_id,
        year_id=payload.year_id,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        revision_number=1,
        is_active=1,
    )
    db.add(timetable)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A timetable with the same department, semester, section and year already exists.",
        )
    db.refresh(timetable)
    return {
        "timetable_id": timetable.timetable_id,
        "dept_id": timetable.dept_id,
        "semester_id": timetable.semester_id,
        "section_id": timetable.section_id,
        "year_id": timetable.year_id,
        "effective_from": timetable.effective_from,
        "effective_to": timetable.effective_to,
        "is_active": timetable.is_active,
    }
