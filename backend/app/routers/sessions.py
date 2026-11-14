"""FastAPI router for Session master data endpoints."""

from __future__ import annotations

import logging
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
    SessionBulkCreate,
    SessionCreate,
    SessionPageResponse,
    SessionResponse,
)

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
    scope = resolve_session_scope(db, current_user)

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
            visible.append(payload)

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
        unrestricted=scope.unrestricted,
    )
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
    return session


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

