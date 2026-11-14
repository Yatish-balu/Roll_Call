"""Single atomic write function for attendance edits (N6).

This is the implementation behind ``PUT /api/sessions/{session_id}/attendance/{usn}``.
It reuses the project's one authorization policy
(:func:`app.services.attendance_edits.assert_session_edit_authorized`), the one
lock policy (:func:`app.services.attendance_edits.assert_session_edit_unlocked`
-> :func:`app.policy.is_editable`) and the append-only audit service, so a
direct API edit, a chat confirmation and a legacy UI commit cannot disagree.

Steps enforced by :func:`update_attendance`:
1. Session exists (else 404 NOT_FOUND).
2. Caller is authorized for the session (else 403 FORBIDDEN).
3. The 24-hour lock allows the edit (else 403 LOCKED). ADMIN is never locked.
4. The USN has an attendance row in that session (else 404 NOT_FOUND).
5. Status is PRESENT or ABSENT (else 422 VALIDATION).
6. An admin edit of a session older than the window carries a reason
   (else 422 VALIDATION) and is audited as ``ADMIN_OVERRIDE_EVENT``.
7. The status change and one audit row are committed in ONE transaction: an
   audit failure rolls the attendance change back.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth.roles import Role
from app.config import LOCK_HOURS
from app.db import crud
from app.services.attendance_edits import (
    AttendanceChange,
    actor_identity,
    assert_session_edit_authorized,
    assert_session_edit_unlocked,
    write_attendance_audit,
)

# Events recorded in audit_log
ATTENDANCE_EDIT = "ATTENDANCE_EDIT"
ADMIN_OVERRIDE_EVENT = "ADMIN_OVERRIDE_EVENT"

VALID_STATUSES = {"PRESENT", "ABSENT"}


def _session_age_hours(created_at_utc: Optional[str], now: datetime) -> float:
    """Age of a session in hours; ``inf`` when the timestamp is missing/broken."""
    if not created_at_utc:
        return float("inf")
    text = str(created_at_utc).strip()
    if not text:
        return float("inf")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        created = datetime.fromisoformat(text)
    except ValueError:
        return float("inf")
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (now - created).total_seconds() / 3600.0


def update_attendance(
    user: Any,
    session_id: str,
    usn: str,
    new_status: str,
    reason: Optional[str] = None,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """Atomically update one attendance record and write one audit row.

    Parameters
    ----------
    user:
        Authenticated user object with ``user_id`` and ``role`` attributes
        (role always from the verified token/database, never from the body).
    session_id:
        Target session identifier.
    usn:
        Student USN whose status changes.
    new_status:
        ``"PRESENT"`` or ``"ABSENT"`` only.
    reason:
        Optional reason text. Required for admin edits of sessions older than
        ``LOCK_HOURS``; recorded in the audit row.
    db:
        SQLAlchemy Session. A short-lived session is created when omitted.

    Returns
    -------
    dict with ``session_id``, ``usn``, ``old_status``, ``new_status``, ``event``.
    """
    own_session = db is None
    if db is None:
        from app.db.connection import get_sync_session_factory

        db = get_sync_session_factory()()

    try:
        clean_usn = (usn or "").strip().upper()

        # 1. Session exists
        session = crud.get_session(db, session_id=session_id.strip())
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session '{session_id}' not found.",
            )

        # 2. Authorization (single shared policy)
        assert_session_edit_authorized(user, session, db)

        # 3. 24-hour lock (ADMIN is never locked)
        assert_session_edit_unlocked(user, session)

        # 4. Attendance row exists
        existing = crud.get_attendance_record(db, session_id.strip(), clean_usn)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"USN '{clean_usn}' is not in session '{session_id}'.",
            )

        # 5. Status is valid
        clean_status = (new_status or "").strip().upper()
        if clean_status not in VALID_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Status must be 'PRESENT' or 'ABSENT', got '{new_status}'.",
            )

        actor_id, actor_role = actor_identity(user)
        if not actor_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="An authenticated actor is required to edit attendance.",
            )

        # 6. Admin override of an old session requires a reason
        now = datetime.now(timezone.utc)
        is_admin_override = (
            str(actor_role).strip().upper() == "ADMIN"
            and _session_age_hours(session.get("created_at"), now) > LOCK_HOURS
        )
        if is_admin_override and not (reason or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Admin override of a session older than {int(LOCK_HOURS)} hours "
                    "requires a reason."
                ),
            )

        old_status = existing.get("status")
        event = ADMIN_OVERRIDE_EVENT if is_admin_override else ATTENDANCE_EDIT

        # 7. Write change + audit in ONE transaction
        crud.insert_attendance(
            db,
            session_id=session_id.strip(),
            usn=clean_usn,
            room_id=existing.get("room_id") or "UNASSIGNED",
            status=clean_status,
            source=existing.get("source") or "manual",
            confidence=float(existing.get("confidence") or 1.0),
            upsert=True,
            attendance_id=existing.get("attendance_id"),
        )
        write_attendance_audit(
            db,
            actor_id=actor_id,
            actor_role=actor_role,
            session_id=session_id.strip(),
            action=event,
            changes=[
                AttendanceChange(
                    usn=clean_usn,
                    old_status=old_status,
                    new_status=clean_status,
                    attendance_id=existing.get("attendance_id"),
                )
            ],
            reason=(reason or "").strip() or None,
        )
        db.commit()

        return {
            "session_id": session_id.strip(),
            "usn": clean_usn,
            "old_status": old_status,
            "new_status": clean_status,
            "event": event,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        if own_session:
            db.close()


__all__ = [
    "update_attendance",
    "ATTENDANCE_EDIT",
    "ADMIN_OVERRIDE_EVENT",
    "VALID_STATUSES",
]
