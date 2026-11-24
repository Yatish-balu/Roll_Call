"""FastAPI router for Session master data endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# The module is aliased so it does not shadow the ``datetime`` class above.
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Role, get_current_user, require_roles
from app.auth.session_scope import resolve_session_scope
from app.db import crud
from app.dependencies import get_db
from app.policy import editable_until, is_editable
from app.schemas.auth import AuthenticatedUser
from app.services.session_initialization import (
    initialize_sessions_for_date,
    initialization_status,
)
from app.schemas.session import (
    ClassDelegationCreate,
    ClassDelegationResponse,
    ExtraSessionCreate,
    SessionAttendanceEditRequest,
    SessionBulkCreate,
    SessionCreate,
    SessionPageResponse,
    SessionResponse,
    SessionUpdate,
)
from app.services.attendance_edit import update_attendance

logger = logging.getLogger("rollcall.routers.sessions")

router = APIRouter(prefix="/sessions", tags=["Sessions"])


def _attach_lock_fields(
    payload: Dict[str, Any], caller_role: str, now_iso: str
) -> None:
    """Attach ``editable``, ``editable_until_utc`` and ``locked`` to a session dict."""
    created_at = payload.get("created_at")
    payload["editable"] = is_editable(created_at, caller_role, now_iso)
    payload["editable_until_utc"] = editable_until(created_at)
    payload["locked"] = not payload["editable"]


def _annotate_delegations(
    db: Session,
    session_dicts: List[Dict[str, Any]],
    current_user: AuthenticatedUser,
) -> None:
    """Annotate session dictionaries with delegation/proxy metadata."""
    if not session_dicts:
        return
    try:
        from app.db.models import ClassDelegation, User
        from sqlalchemy import select

        s_ids = [str(s["session_id"]).strip() for s in session_dicts if "session_id" in s]
        if not s_ids:
            return
        del_rows = db.execute(
            select(ClassDelegation).where(
                ClassDelegation.session_id.in_(s_ids),
                ClassDelegation.status == "ACTIVE",
            )
        ).scalars().all()
        if not del_rows:
            for s in session_dicts:
                s["is_delegated"] = False
                s["delegation"] = None
            return

        del_map = {d.session_id: d for d in del_rows}
        user_ids = {d.original_faculty_id for d in del_rows} | {d.substitute_faculty_id for d in del_rows}
        users = {
            u.user_id: u
            for u in db.execute(select(User).where(User.user_id.in_(user_ids))).scalars().all()
        } if user_ids else {}

        for s in session_dicts:
            d = del_map.get(s.get("session_id"))
            if d:
                orig_u = users.get(d.original_faculty_id)
                sub_u = users.get(d.substitute_faculty_id)
                s["is_delegated"] = True
                s["delegation"] = {
                    "delegation_id": d.delegation_id,
                    "type": d.delegation_type,
                    "reason": d.reason,
                    "from_user_id": d.original_faculty_id,
                    "from_name": orig_u.name if orig_u and orig_u.name else (orig_u.email if orig_u else d.original_faculty_id),
                    "to_user_id": d.substitute_faculty_id,
                    "to_name": sub_u.name if sub_u and sub_u.name else (sub_u.email if sub_u else d.substitute_faculty_id),
                    "is_proxy_for_me": d.substitute_faculty_id == current_user.user_id,
                }
            else:
                s["is_delegated"] = False
                s["delegation"] = None
    except Exception as exc:
        logger.debug("Delegation annotation error (ignoring): %s", exc)


@router.get(
    "",
    response_model=SessionPageResponse,
    summary="List sessions visible to the caller",
    description=(
        "Retrieve paginated sessions, optionally filtered by date (YYYY-MM-DD) and search. "
        "Access is filtered server-side by role: ADMIN keeps institution-wide access, while "
        "every other role only sees sessions they own, coordinate, or are mapped to through "
        "an exact subject-code mapping. Pagination, date and search parameters never widen "
        "that scope."
    ),
)
def list_sessions(
    date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Filter sessions by date (YYYY-MM-DD)"),
    from_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Start of an inclusive date range"),
    to_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="End of an inclusive date range"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip before returning"),
    search: Optional[str] = Query(None, description="Search term matching session_id or subject"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    # Session initialisation is a multi-query write transaction. Only run it
    # when the requested day has no sessions at all - a page refresh should not
    # re-run the timetable import and commit for every list request.
    try:
        from sqlalchemy import select

        from app.db.models import Session as DbSession

        init_date = dt.date.fromisoformat(date) if date else dt.date.today()
        if not db.execute(
            select(DbSession.session_id)
            .where(DbSession.date == init_date.isoformat())
            .limit(1)
        ).first():
            initialize_sessions_for_date(db, init_date)
    except Exception as exc:
        logger.debug("Automatic session initialisation skipped: %s", exc)

    scope = resolve_session_scope(db, current_user)
    caller_role = str(
        current_user.role.value if hasattr(current_user.role, "value") else current_user.role
    ).upper()
    now_iso = _utcnow_iso()

    if (from_date or to_date) and not date:
        # Range queries are executed against the ORM so the calendar can load a
        # whole month in a single request. The visibility scope is still
        # applied server side before the count and the pagination.
        from sqlalchemy import select

        from app.db.models import Session as DbSession

        stmt = select(DbSession)
        if from_date:
            stmt = stmt.where(DbSession.date >= from_date)
        if to_date:
            stmt = stmt.where(DbSession.date <= to_date)
        rows = db.execute(stmt).scalars().all()

        visible = []
        for row in rows:
            payload = {
                "session_id": row.session_id,
                "date": row.date,
                "subject": row.subject,
                "subject_code": row.subject_code,
                "teacher_id": row.teacher_id,
                "created_at": row.created_at,
            }
            if not scope.allows(payload):
                continue
            if search and search.strip():
                term = search.strip().lower()
                if term not in (row.session_id or "").lower() and term not in (row.subject or "").lower():
                    continue
            _attach_lock_fields(payload, caller_role, now_iso)
            visible.append(payload)

        _annotate_delegations(db, visible, current_user)
        visible.sort(key=lambda item: (item.get("date") or "", item.get("session_id") or ""), reverse=True)
        total = len(visible)
        window = visible[offset : offset + limit]
        return {
            "items": window,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    items, total = crud.get_sessions_paginated_scoped(
        db,
        date=date,
        search=search,
        limit=limit,
        offset=offset,
        scope_user_id=scope.user_id,
        scope_subject_codes=sorted(scope.subject_codes),
        scope_delegated_session_ids=sorted(scope.delegated_session_ids),
        unrestricted=scope.unrestricted,
    )
    for item in items:
        _attach_lock_fields(item, caller_role, now_iso)
    _annotate_delegations(db, items, current_user)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ==============================================================================
# Session allocations (class slots: room, batch, time)
#
# NOTE: this route must stay declared *before* "/{session_id}" so the literal
# path is not captured by the path parameter.
# ==============================================================================

@router.get(
    "/allocations",
    summary="List scheduled class allocations",
    description=(
        "Returns the real class slots (room, batch, faculty and time window) of the "
        "sessions the caller may see. The session visibility scope is applied on the "
        "server, so the response never exposes another teacher's classes."
    ),
)
def list_session_allocations(
    date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Exact allocation date"),
    from_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Start of a date range"),
    to_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="End of a date range"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from sqlalchemy import select

    from app.db.models import Session as DbSession, SessionAllocation

    stmt = select(SessionAllocation, DbSession).join(
        DbSession, SessionAllocation.session_id == DbSession.session_id
    )

    if date:
        stmt = stmt.where(SessionAllocation.allocation_date == date)
    else:
        if from_date:
            stmt = stmt.where(SessionAllocation.allocation_date >= from_date)
        if to_date:
            stmt = stmt.where(SessionAllocation.allocation_date <= to_date)

    rows = db.execute(stmt).all()

    scope = resolve_session_scope(db, current_user)
    items = []
    for allocation, db_session in rows:
        session_payload = {
            "session_id": db_session.session_id,
            "date": db_session.date,
            "subject": db_session.subject,
            "subject_code": db_session.subject_code,
            "teacher_id": db_session.teacher_id,
            "created_at": db_session.created_at,
        }
        if not scope.allows(session_payload):
            continue
        items.append(
            {
                "allocation_id": allocation.allocation_id,
                "session_id": allocation.session_id,
                "date": allocation.allocation_date,
                "subject": db_session.subject,
                "subject_code": db_session.subject_code,
                "teacher_id": db_session.teacher_id,
                "faculty_id": allocation.faculty_id,
                "room_id": allocation.room_id,
                "batch_id": allocation.batch_id,
                "start_time": allocation.start_time,
                "end_time": allocation.end_time,
                "lifecycle_status": allocation.lifecycle_status,
            }
        )

    items.sort(key=lambda item: (item.get("date") or "", item.get("start_time") or ""))
    return {"items": items, "total": len(items)}


# ==============================================================================
# Faculty Colleagues for Class Delegation / Proxy
# ==============================================================================

@router.get(
    "/colleagues",
    summary="List faculty colleagues available for class delegation or proxy substitution",
)
def list_faculty_colleagues(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    from sqlalchemy import select
    from app.db.models import User

    users = db.execute(
        select(User).where(
            User.role.in_([Role.FACULTY, Role.ADMIN]),
            User.is_active == 1,
            User.user_id != current_user.user_id,
        )
    ).scalars().all()
    results = []
    for u in users:
        subj_codes = crud.get_teacher_subjects(db, user_id=u.user_id)
        results.append({
            "user_id": u.user_id,
            "name": u.name or u.email.split("@")[0].replace(".", " ").title(),
            "email": u.email,
            "role": str(getattr(u.role, "value", u.role)),
            "assigned_subjects": subj_codes,
        })
    return results


# ==============================================================================
# Extra / Emergency / Remedial Class Creation
# ==============================================================================

@router.post(
    "/extra",
    status_code=status.HTTP_201_CREATED,
    summary="Schedule an extra, remedial or emergency class and populate attendance roster",
)
def create_extra_session(
    payload: ExtraSessionCreate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from sqlalchemy import select
    from app.db.models import Student, Subject, Room, SessionAllocation, Attendance, Semester
    from app.schemas.timetable import validate_academic_window

    try:
        validate_academic_window(payload.start_time, payload.end_time)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(val_err),
        )

    # Room check
    clean_room = payload.room_id.strip()
    room = db.get(Room, clean_room)
    if room is None:
        crud.ensure_unallocated_room(db)
        room_check = crud.get_room(db, room_id=clean_room)
        if not room_check:
            new_room = Room(room_id=clean_room, name=f"Room {clean_room}")
            db.add(new_room)
            db.flush()

    # Subject check
    subj_code = payload.subject_code.strip().upper()
    if current_user.role != Role.ADMIN:
        assigned = crud.get_teacher_subjects(db, user_id=current_user.user_id)
        if subj_code not in assigned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Subject '{subj_code}' is not assigned to your account.",
            )

    subject_name = payload.subject_name
    if not subject_name:
        subj_obj = db.get(Subject, subj_code)
        subject_name = subj_obj.name if subj_obj and subj_obj.name else subj_code

    # Build unique session ID
    clean_date = payload.date.replace("-", "")
    clean_time = payload.start_time.replace(":", "")
    base_sid = f"EXTRA-{subj_code}-{clean_date}-{clean_time}"[:45]
    session_id = base_sid
    counter = 1
    while crud.get_session(db, session_id=session_id) is not None:
        session_id = f"{base_sid}-{counter}"[:50]
        counter += 1

    now_iso = _utcnow_iso()
    session = crud.insert_session(
        db,
        session_id=session_id,
        date=payload.date,
        subject=subject_name,
        teacher_id=current_user.user_id,
        subject_code=subj_code,
        created_at=now_iso,
    )

    # Allocation
    allocation_id = f"ALC-{session_id}"[:50]
    alloc = SessionAllocation(
        allocation_id=allocation_id,
        session_id=session_id,
        allocation_date=payload.date,
        room_id=clean_room,
        start_time=payload.start_time,
        end_time=payload.end_time,
        faculty_id=current_user.user_id,
        batch_id=payload.batch_id,
        lifecycle_status=payload.class_type,
    )
    db.add(alloc)

    # Find enrolled students
    stmt = select(Student)
    if payload.batch_id:
        stmt = stmt.where(Student.batch_id == payload.batch_id)
    elif payload.section_id:
        stmt = stmt.where(Student.section_id == payload.section_id)
    elif payload.semester_number:
        sem = db.execute(
            select(Semester).where(Semester.semester_number == payload.semester_number)
        ).scalar_one_or_none()
        if sem:
            stmt = stmt.where(Student.semester_id == sem.semester_id)
        if payload.dept_id:
            stmt = stmt.where(Student.dept_id == payload.dept_id)
    elif payload.dept_id:
        stmt = stmt.where(Student.dept_id == payload.dept_id)

    students = list(db.execute(stmt).scalars().all())
    # If no students match specific filter, fetch general student roster
    if not students:
        students = list(db.execute(select(Student).limit(60)).scalars().all())

    attendance_rows = 0
    for student in students:
        att = Attendance(
            attendance_id=f"ATT-{session_id}-{student.usn}"[:50],
            session_id=session_id,
            allocation_id=allocation_id,
            usn=student.usn,
            status="UNREVIEWED",
            room_id=clean_room,
            source="extra_class_roster",
            recorded_at=now_iso,
        )
        db.add(att)
        attendance_rows += 1

    crud.create_audit_entry(
        db,
        actor_id=current_user.user_id,
        action="SESSION_EXTRA_CREATE",
        entity_type="session",
        entity_id=session_id,
        new_value=f"{subj_code}|{payload.date}|{payload.start_time}-{payload.end_time}|{clean_room}|{attendance_rows}_students",
        timestamp=now_iso,
        actor_role=getattr(current_user.role, "value", str(current_user.role)),
    )
    db.commit()

    return {
        "session_id": session_id,
        "date": payload.date,
        "subject": subject_name,
        "subject_code": subj_code,
        "start_time": payload.start_time,
        "end_time": payload.end_time,
        "room_id": clean_room,
        "class_type": payload.class_type,
        "students_enrolled": attendance_rows,
        "message": f"Extra class '{subject_name}' scheduled successfully with {attendance_rows} students ready for attendance.",
    }


# ==============================================================================
# Class Delegation & Proxy Substitution System
# ==============================================================================

@router.post(
    "/delegations",
    status_code=status.HTTP_201_CREATED,
    response_model=ClassDelegationResponse,
    summary="Delegate or proxy a scheduled class slot to a colleague",
)
def create_class_delegation(
    payload: ClassDelegationCreate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from sqlalchemy import select
    from app.db.models import ClassDelegation, Session as DbSession, User, SessionAllocation

    session_row = db.get(DbSession, payload.session_id)
    if session_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{payload.session_id}' not found.",
        )

    # Permission check: must be owner or ADMIN
    if current_user.role != Role.ADMIN and session_row.teacher_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You can only delegate sessions you own.",
        )

    # Substitute teacher check
    sub_user = db.get(User, payload.substitute_faculty_id)
    if sub_user is None or not sub_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Substitute faculty '{payload.substitute_faculty_id}' not found.",
        )

    if sub_user.user_id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Cannot delegate a class to yourself.",
        )

    # If EXCHANGE, verify exchange session
    ex_session = None
    if payload.delegation_type.upper() == "EXCHANGE":
        if not payload.exchange_session_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Exchange session ID is required for EXCHANGE delegation type.",
            )
        ex_session = db.get(DbSession, payload.exchange_session_id)
        if ex_session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Exchange session '{payload.exchange_session_id}' not found.",
            )
        if current_user.role != Role.ADMIN and ex_session.teacher_id != sub_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Exchange session '{payload.exchange_session_id}' is not owned by substitute teacher '{sub_user.user_id}'.",
            )

    now_iso = _utcnow_iso()
    delegation_id = f"DEL-{uuid.uuid4().hex[:12].upper()}"

    # Deactivate existing active delegation on this session if any
    existing = db.execute(
        select(ClassDelegation).where(
            ClassDelegation.session_id == payload.session_id,
            ClassDelegation.status == "ACTIVE",
        )
    ).scalars().all()
    for ex in existing:
        ex.status = "CANCELLED"
        ex.updated_at = now_iso

    new_del = ClassDelegation(
        delegation_id=delegation_id,
        session_id=payload.session_id,
        original_faculty_id=session_row.teacher_id or current_user.user_id,
        substitute_faculty_id=payload.substitute_faculty_id,
        delegation_date=session_row.date,
        delegation_type=payload.delegation_type.upper(),
        exchange_session_id=payload.exchange_session_id,
        reason=payload.reason,
        status="ACTIVE",
        created_at=now_iso,
        updated_at=now_iso,
    )
    db.add(new_del)

    # If EXCHANGE, also create reciprocal delegation for the exchange session!
    if payload.delegation_type.upper() == "EXCHANGE" and payload.exchange_session_id and ex_session:
        recip_del = ClassDelegation(
            delegation_id=f"DEL-{uuid.uuid4().hex[:12].upper()}",
            session_id=payload.exchange_session_id,
            original_faculty_id=sub_user.user_id,
            substitute_faculty_id=session_row.teacher_id or current_user.user_id,
            delegation_date=ex_session.date,
            delegation_type="EXCHANGE",
            exchange_session_id=payload.session_id,
            reason=f"Reciprocal exchange for {session_row.subject_code or session_row.session_id}",
            status="ACTIVE",
            created_at=now_iso,
            updated_at=now_iso,
        )
        db.add(recip_del)

    crud.create_audit_entry(
        db,
        actor_id=current_user.user_id,
        action="CLASS_DELEGATION_CREATE",
        entity_type="session",
        entity_id=payload.session_id,
        new_value=f"to:{payload.substitute_faculty_id}|type:{payload.delegation_type}|reason:{payload.reason or ''}",
        timestamp=now_iso,
        actor_role=getattr(current_user.role, "value", str(current_user.role)),
    )
    db.commit()

    orig_user = db.get(User, new_del.original_faculty_id)
    alloc = db.execute(
        select(SessionAllocation).where(SessionAllocation.session_id == payload.session_id)
    ).scalars().first()

    return {
        "delegation_id": new_del.delegation_id,
        "session_id": new_del.session_id,
        "original_faculty_id": new_del.original_faculty_id,
        "original_faculty_name": orig_user.name if orig_user and orig_user.name else (orig_user.email if orig_user else new_del.original_faculty_id),
        "substitute_faculty_id": new_del.substitute_faculty_id,
        "substitute_faculty_name": sub_user.name if sub_user and sub_user.name else sub_user.email,
        "delegation_date": new_del.delegation_date,
        "delegation_type": new_del.delegation_type,
        "exchange_session_id": new_del.exchange_session_id,
        "reason": new_del.reason,
        "status": new_del.status,
        "subject_code": session_row.subject_code,
        "subject_name": session_row.subject,
        "start_time": alloc.start_time if alloc else None,
        "end_time": alloc.end_time if alloc else None,
        "room_id": alloc.room_id if alloc else None,
        "created_at": new_del.created_at,
        "updated_at": new_del.updated_at,
    }


@router.get(
    "/delegations/my",
    summary="List active class delegations received by or given by the current faculty member",
)
def get_my_class_delegations(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from sqlalchemy import select
    from app.db.models import ClassDelegation, Session as DbSession, User, SessionAllocation

    recv_rows = db.execute(
        select(ClassDelegation).where(
            ClassDelegation.substitute_faculty_id == current_user.user_id,
            ClassDelegation.status == "ACTIVE",
        ).order_by(ClassDelegation.created_at.desc())
    ).scalars().all()

    given_rows = db.execute(
        select(ClassDelegation).where(
            ClassDelegation.original_faculty_id == current_user.user_id,
            ClassDelegation.status == "ACTIVE",
        ).order_by(ClassDelegation.created_at.desc())
    ).scalars().all()

    def serialize(del_row):
        orig_user = db.get(User, del_row.original_faculty_id)
        sub_user = db.get(User, del_row.substitute_faculty_id)
        sess = db.get(DbSession, del_row.session_id)
        alloc = db.execute(
            select(SessionAllocation).where(SessionAllocation.session_id == del_row.session_id)
        ).scalars().first()
        return {
            "delegation_id": del_row.delegation_id,
            "session_id": del_row.session_id,
            "original_faculty_id": del_row.original_faculty_id,
            "original_faculty_name": orig_user.name if orig_user and orig_user.name else (orig_user.email if orig_user else del_row.original_faculty_id),
            "substitute_faculty_id": del_row.substitute_faculty_id,
            "substitute_faculty_name": sub_user.name if sub_user and sub_user.name else (sub_user.email if sub_user else del_row.substitute_faculty_id),
            "delegation_date": del_row.delegation_date,
            "delegation_type": del_row.delegation_type,
            "exchange_session_id": del_row.exchange_session_id,
            "reason": del_row.reason,
            "status": del_row.status,
            "subject_code": sess.subject_code if sess else None,
            "subject_name": sess.subject if sess else None,
            "start_time": alloc.start_time if alloc else None,
            "end_time": alloc.end_time if alloc else None,
            "room_id": alloc.room_id if alloc else None,
            "created_at": del_row.created_at,
            "updated_at": del_row.updated_at,
        }

    return {
        "received": [serialize(r) for r in recv_rows],
        "given": [serialize(g) for g in given_rows],
    }


@router.delete(
    "/delegations/{delegation_id}",
    summary="Cancel or revoke a class delegation",
)
def cancel_class_delegation(
    delegation_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from app.db.models import ClassDelegation

    del_row = db.get(ClassDelegation, delegation_id)
    if del_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delegation '{delegation_id}' not found.",
        )

    if (
        current_user.role != Role.ADMIN
        and del_row.original_faculty_id != current_user.user_id
        and del_row.substitute_faculty_id != current_user.user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You are not a party to this delegation.",
        )

    del_row.status = "CANCELLED"
    del_row.updated_at = _utcnow_iso()
    crud.create_audit_entry(
        db,
        actor_id=current_user.user_id,
        action="CLASS_DELEGATION_CANCEL",
        entity_type="session",
        entity_id=del_row.session_id,
        new_value=f"delegation_id:{delegation_id}",
        timestamp=del_row.updated_at,
        actor_role=getattr(current_user.role, "value", str(current_user.role)),
    )
    db.commit()
    return {"message": "Delegation cancelled successfully.", "delegation_id": delegation_id}


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Get session by ID",
    description=(
        "Retrieve a single session record by session_id. Non-administrator callers may only "
        "read sessions they own, coordinate, or are mapped to through an exact subject-code "
        "mapping; any other session is rejected with 403."
    ),
    responses={
        403: {"description": "Session is not visible to the current user"},
        404: {"description": "Session not found"},
    },
)
def get_session_by_id(
    session_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    session = crud.get_session(db, session_id=session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{session_id.strip()}' not found.",
        )
    scope = resolve_session_scope(db, current_user)
    scope.assert_allowed(session)
    now_iso = datetime.now(timezone.utc).isoformat()
    caller_role = str(current_user.role.value if hasattr(current_user.role, "value") else current_user.role).upper()
    _attach_lock_fields(session, caller_role, now_iso)
    _annotate_delegations(db, [session], current_user)
    return session


@router.patch(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Update session details",
    description="Update a session's date, subject, or assigned details.",
)
@router.put(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Update session details (PUT)",
)
def update_session_by_id(
    session_id: str,
    payload: SessionUpdate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from app.db.models import Session as DbSession
    clean_id = session_id.strip()
    session_row = db.get(DbSession, clean_id)
    if not session_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{clean_id}' not found.",
        )
    # Check permissions: owner or admin
    if current_user.role != Role.ADMIN and session_row.teacher_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You can only edit sessions you own.",
        )
    if payload.date:
        session_row.date = payload.date
    if payload.subject:
        session_row.subject = payload.subject

    db.commit()
    db.refresh(session_row)
    session_dict = crud.get_session(db, session_id=clean_id)
    if not session_dict:
        session_dict = {
            "session_id": session_row.session_id,
            "date": session_row.date,
            "subject": session_row.subject,
            "teacher_id": session_row.teacher_id,
            "subject_code": getattr(session_row, "subject_code", None),
        }
    now_iso = datetime.now(timezone.utc).isoformat()
    caller_role = str(current_user.role.value if hasattr(current_user.role, "value") else current_user.role).upper()
    _attach_lock_fields(session_dict, caller_role, now_iso)
    return session_dict


def _utcnow_iso() -> str:
    """Current UTC timestamp in canonical ISO 8601 Z format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create session",
    description=(
        "Add a new session record. FACULTY users may only create sessions for their assigned "
        "subject codes (teacher_id is always bound to the verified token subject). ADMIN users "
        "may create sessions for any subject and optionally attribute them to a teacher (N4)."
    ),
    responses={
        403: {"description": "Subject code not assigned to the current teacher"},
        404: {"description": "Target teacher does not exist"},
        409: {"description": "Session already exists with this session_id"},
        422: {"description": "Missing subject code for FACULTY, or target teacher is not a FACULTY user"},
    },
)
def create_session(
    payload: SessionCreate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    existing = crud.get_session(db, session_id=payload.session_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session with ID '{payload.session_id}' already exists.",
        )

    now_iso = _utcnow_iso()

    if current_user.role == Role.ADMIN:
        # ADMIN: unrestricted subject; optional attribution to an existing teacher.
        target_teacher = payload.teacher_id
        if target_teacher is not None:
            teacher = crud.get_user(db, user_id=target_teacher)
            if teacher is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Teacher with user ID '{target_teacher}' not found.",
                )
            if str(teacher.get("role", "")).upper() != "FACULTY":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Sessions can only be attributed to FACULTY users.",
                )
        subject_code = payload.subject_code
    else:
        # FACULTY: subject_code is mandatory and must be one of the teacher's assigned codes.
        if not payload.subject_code:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="subject_code is required for faculty session creation.",
            )
        assigned_codes = crud.get_teacher_subjects(db, user_id=current_user.user_id)
        if payload.subject_code not in assigned_codes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Subject code '{payload.subject_code}' is not assigned to you. "
                    "You can only create sessions for your own subjects."
                ),
            )
        # Never trust a client-supplied teacher_id: bind to the verified token subject.
        target_teacher = current_user.user_id
        subject_code = payload.subject_code

    try:
        created = crud.insert_session(
            db,
            session_id=payload.session_id,
            date=payload.date,
            subject=payload.subject,
            teacher_id=target_teacher,
            subject_code=subject_code,
            created_at=now_iso,
        )
        crud.create_audit_entry(
            db,
            actor_id=current_user.user_id,
            action="SESSION_CREATE",
            entity_type="session",
            entity_id=payload.session_id,
            new_value=subject_code,
            timestamp=now_iso,
            actor_role=getattr(current_user.role, "value", str(current_user.role)),
        )
        db.commit()
        caller_role = str(current_user.role.value if hasattr(current_user.role, "value") else current_user.role).upper()
        _attach_lock_fields(created, caller_role, now_iso)
        return created
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session with ID '{payload.session_id}' already exists.",
        )
    except Exception as exc:
        db.rollback()
        logger.error("Failed to create session %s: %s", payload.session_id, exc)
        raise


# ==============================================================================
# Session initialisation from the configured timetable
# ==============================================================================

def _parse_target_date(raw: Optional[str]) -> dt.date:
    if not raw:
        return dt.date.today()
    try:
        return dt.date.fromisoformat(raw.strip())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid date '{raw}'. Expected a valid calendar date in YYYY-MM-DD format.",
        )


@router.get(
    "/initialization/today",
    summary="Initialisation state of the academic day",
    description=(
        "Reports whether the sessions of the requested academic day (today by default) "
        "have been initialised from the configured timetable. The endpoint never writes "
        "and never initialises historical dates."
    ),
)
def get_initialization_status(
    date: Optional[str] = Query(
        None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Academic day to report on (defaults to today)",
    ),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    target = _parse_target_date(date)
    return initialization_status(db, target)


@router.post(
    "/initialize",
    summary="Initialise the academic day's sessions from the timetable",
    description=(
        "Creates the sessions and session allocations for the requested academic day from "
        "the configured timetable. The operation is idempotent (deterministic identifiers), "
        "safe under concurrent execution (primary key uniqueness), restricted to working "
        "academic days and to the 09:00 - 17:00 academic window. Historical dates are "
        "rejected."
    ),
    responses={
        409: {"description": "Concurrent initialisation conflict"},
        422: {"description": "Invalid date"},
    },
)
def initialize_sessions(
    date: Optional[str] = Query(
        None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Academic day to initialise (defaults to today)",
    ),
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    target = _parse_target_date(date)
    today = dt.date.today()
    if target < today:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Historical sessions are never initialised automatically. "
                "Only today (or a future academic day) can be initialised."
            ),
        )

    result = initialize_sessions_for_date(
        db,
        target,
        actor_user_id=current_user.user_id,
        actor_role=getattr(current_user.role, "value", str(current_user.role)),
    )

    if result["created_sessions"]:
        for created in result["created_sessions"]:
            try:
                crud.create_audit_entry(
                    db,
                    actor_id=current_user.user_id,
                    action="SESSION_AUTO_INIT",
                    entity_type="session",
                    entity_id=created["session_id"],
                    new_value=created.get("subject_code"),
                    timestamp=_utcnow_iso(),
                    actor_role=getattr(current_user.role, "value", str(current_user.role)),
                )
            except Exception:  # pragma: no cover - auditing must not block init
                logger.warning("Failed to audit auto-initialised session %s", created.get("session_id"))
        db.commit()

    return result


@router.post(
    "/bulk",
    status_code=status.HTTP_201_CREATED,
    summary="Bulk create sessions",
    description="Atomically insert multiple session records. If any duplicate or conflict occurs, the entire batch is rolled back.",
    responses={
        409: {"description": "Conflict or duplicate records detected in batch or database"},
    },
)
def bulk_create_sessions(
    payload: SessionBulkCreate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    raw_sessions = [s.model_dump() for s in payload.sessions]

    # Check for duplicate session_ids within the payload itself
    session_ids = [s["session_id"] for s in raw_sessions]
    if len(session_ids) != len(set(session_ids)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bulk insert payload contains duplicate session IDs.",
        )

    # Check for existing records in database to ensure clean 409 error
    for s in raw_sessions:
        if crud.get_session(db, session_id=s["session_id"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Session with ID '{s['session_id']}' already exists.",
            )

    try:
        inserted_count = crud.insert_sessions_bulk(db, sessions=raw_sessions)
        db.commit()
        return {
            "inserted_count": inserted_count,
            "message": f"Successfully created {inserted_count} sessions.",
        }
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bulk insert failed due to duplicate or conflicting records.",
        )
    except Exception as exc:
        db.rollback()
        logger.error("Error during bulk session creation: %s", exc)
        raise


# ==============================================================================
# N6: PUT /api/sessions/{session_id}/attendance/{usn}
# ==============================================================================

@router.put(
    "/{session_id}/attendance/{usn}",
    summary="Edit one attendance record atomically (N6)",
    description=(
        "Change one student's status in a session. Authorization, the N5 24-hour "
        "lock and the audit row are all decided server-side in one transaction. "
        "FACULTY may edit their own session within the lock window; ADMIN is never "
        "locked but must supply a reason when the session is older than the window."
    ),
    responses={
        200: {"description": "Change applied and audited"},
        403: {"description": "FORBIDDEN or LOCKED"},
        404: {"description": "Session or attendance row not found"},
        422: {"description": "Invalid status, or missing admin override reason"},
    },
)
def edit_session_attendance(
    session_id: str,
    usn: str,
    payload: SessionAttendanceEditRequest,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return update_attendance(
        current_user,
        session_id=session_id,
        usn=usn,
        new_status=payload.status,
        reason=payload.reason,
        db=db,
    )

