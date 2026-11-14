"""Single atomic write function for attendance edits (N6).

This is the ONLY place that changes attendance. Every write path (direct API,
chat confirmation, legacy UI commit) goes through here so that authorization,
the 24-hour lock, and the audit trail are decided in exactly one location.

Steps enforced by :func:`update_attendance`:
1. Session exists (else 404 NOT_FOUND).
2. USN is in the session (else 404 NOT_FOUND).
3. Status is Present or Absent (else 422 VALIDATION).
4. Teacher may edit only their own session; legacy sessions are admin-only.
5. Call :func:`app.policy.is_editable` (locked gives 403 LOCKED).
6. Admin editing a session older than 24 h must give a reason (else 422 VALIDATION).
7. Write the change and one audit_log row in ONE transaction (audit failure
   rolls the attendance change back).
8. Event is ADMIN_OVERRIDE_EVENT when an admin edits a session older than 24 h,
   otherwise ATTENDANCE_EDIT.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth.roles import Role
from app.config import LOCK_HOURS
from app.db import crud
from app.db.models import Attendance, Session as DbSession
from app.errors import FORBIDDEN, LOCKED, NOT_FOUND, VALIDATION, error_response
from app.policy import is_editable

# Events recorded in audit_log
ATTENDANCE_EDIT = "ATTENDANCE_EDIT"
ADMIN_OVERRIDE_EVENT = "ADMIN_OVERRIDE_EVENT"

VALID_STATUSES = {"PRESENT", "ABSENT"}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _session_age_hours(created_at_utc: Optional[str], now: datetime) -> float:
    if not created_at_utc:
        return float("inf")
    text = created_at_utc.strip()
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
        (role from the verified token/database, never from request body).
    session_id:
        Target session identifier.
    usn:
        Student USN whose status changes.
    new_status:
        ``"PRESENT"`` or ``"ABSENT"`` only.
    reason:
        Optional reason text. Required for admin edits of sessions older than
        24 h.
    db:
        SQLAlchemy Session. Created internally when omitted.

    Returns
    -------
    dict with ``session_id``, ``usn``, ``old_status``, ``new_status``, ``event``.
    """
    own_session = db is not None
    if db is None:
        from app.db.connection import get_sync_session_factory

        db = get_sync_session_factory()()

    try:
        # 1. Session exists
        session = db.get(DbSession, session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_response(NOT_FOUND, f"Session '{session_id}' not found.")["error"]["message"],
            )

        # 2. USN is in the session
        attendance = (
            db.query(Attendance)
            .filter(Attendance.session_id == session_id, Attendance.usn == usn.strip().upper())
            .first()
        )
        if attendance is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_response(
                    NOT_FOUND, f"USN '{usn}' is not in session '{session_id}'."
                )["error"]["message"],
            )

        # 3. Status is valid
        clean_status = (new_status or "").strip().upper()
        if clean_status not in VALID_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_response(
                    VALIDATION, f"Status must be 'PRESENT' or 'ABSENT', got '{new_status}'."
                )["error"]["message"],
            )

        actor_id = str(getattr(user, "user_id", "")).strip()
        actor_role_raw = getattr(user, "role", Role.VIEWER)
        actor_role = actor_role_raw.value if hasattr(actor_role_raw, "value") else str(actor_role_raw)
        actor_role = actor_role.strip().upper()

        # 4. Ownership: teacher only own session; legacy sessions admin-only
        if actor_role != Role.ADMIN:
            session_teacher = str(session.teacher_id or "").strip()
            is_legacy = session_teacher == "legacy" or not session_teacher
            if is_legacy:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=error_response(
                        FORBIDDEN,
                        "Legacy sessions can only be edited by an administrator.",
                    )["error"]["message"],
                )
            if session_teacher != actor_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=error_response(
                        FORBIDDEN,
                        f"Session '{session_id}' is assigned to another faculty member.",
                    )["error"]["message"],
                )

        # 5. 24-hour lock via policy
        now = datetime.now(timezone.utc)
        age_hours = _session_age_hours(session.created_at, now)
        if not is_editable(session.created_at, actor_role, now.isoformat()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_response(
                    LOCKED,
                    f"Session '{session_id}' is locked (older than {LOCK_HOURS} hours). "
                    "Only an administrator can override.",
                )["error"]["message"],
            )

        # 6. Admin override reason for sessions older than 24 h
        is_admin_override = actor_role == Role.ADMIN and age_hours > LOCK_HOURS
        if is_admin_override and not (reason or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_response(
                    VALIDATION,
                    "Admin override of a session older than 24 hours requires a reason.",
                )["error"]["message"],
            )

        old_status = attendance.status
        event = ADMIN_OVERRIDE_EVENT if is_admin_override else ATTENDANCE_EDIT

        # 7. Write change + audit in ONE transaction
        attendance.status = clean_status
        db.add(attendance)

        crud.create_audit_entry(
            db,
            actor_id=actor_id,
            action=event,
            entity_type="attendance",
            entity_id=f"{session_id}:{usn.strip().upper()}",
            session_id=session_id,
            usn=usn.strip().upper(),
            old_value=old_status,
            new_value=clean_status,
            reason=(reason or "").strip() or None,
            timestamp=_utcnow_iso(),
            actor_role=actor_role,
        )
        db.commit()

        return {
            "session_id": session_id,
            "usn": usn.strip().upper(),
            "old_status": old_status,
            "new_status": clean_status,
            "event": event,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_response(VALIDATION, str(exc))["error"]["message"],
        )
    finally:
        if not own_session:
            db.close()


__all__ = [
    "update_attendance",
    "ATTENDANCE_EDIT",
    "ADMIN_OVERRIDE_EVENT",
    "VALID_STATUSES",
]
