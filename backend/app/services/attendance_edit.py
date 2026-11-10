"""The single safe write service for modifying attendance marks and recording audit entries."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.policy import is_editable
from app.db.models import Attendance, Session as DbSession, Student, AuditLog
from app.dependencies import get_session_factory

logger = logging.getLogger("rollcall.services.attendance_edit")

CANONICAL_STATUSES = {"PRESENT", "ABSENT"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def update_attendance(
    user: Any,
    session_id: str,
    usn: str,
    new_status: str,
    reason: Optional[str] = None,
    *,
    db: Optional[Session] = None,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Atomically update a student's attendance record and write an audit log entry.

    Steps enforced:
    1. Validate status is in ('PRESENT', 'ABSENT'); else 422.
    2. Session exists; else 404.
    3. USN is in session; else 404.
    4. Teacher may edit only own sessions; legacy sessions require ADMIN role; else 403.
    5. Check policy.is_editable (locked raises 403 LOCKED).
    6. Admin editing session older than 24h must supply a non-empty reason; else 422.
    7. Atomically apply update and insert audit_log row (action=ADMIN_OVERRIDE_EVENT or ATTENDANCE_EDIT).
       If audit write or DB update fails, transaction is rolled back completely.
    """
    clean_session_id = session_id.strip() if session_id else ""
    clean_usn = usn.strip().upper() if usn else ""

    # Status validation: strictly PRESENT or ABSENT
    if new_status not in CANONICAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Status '{new_status}' is invalid. Allowed statuses are 'PRESENT' or 'ABSENT'.",
        )

    # Extract caller identity and role
    if isinstance(user, dict):
        actor_id = str(user.get("user_id") or "")
        actor_role = str(user.get("role") or "").upper()
    else:
        actor_id = str(getattr(user, "user_id", "") or "")
        actor_role = str(getattr(user, "role", "") or "").upper()

    created_db = False
    if db is None:
        factory = get_session_factory()
        db = factory()
        created_db = True

    effective_now = now_utc or _utcnow()
    now_iso = effective_now.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        # Step 1: Session must exist
        sess = db.get(DbSession, clean_session_id)
        if not sess:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session with ID '{clean_session_id}' not found.",
            )

        # Step 2: Attendance record for this USN must exist in this session
        att_stmt = select(Attendance).where(
            Attendance.session_id == clean_session_id,
            Attendance.usn == clean_usn,
        )
        att = db.execute(att_stmt).scalar_one_or_none()
        if not att:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Student '{clean_usn}' not found in session '{clean_session_id}'.",
            )

        # Step 3: Authorization checks
        session_teacher = getattr(sess, "teacher_id", None)
        is_legacy = not session_teacher or session_teacher == "legacy"

        if actor_role != "ADMIN":
            if is_legacy:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Legacy session can only be edited by an administrator.",
                )
            if session_teacher != actor_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Teacher '{actor_id}' is not assigned to session '{clean_session_id}'.",
                )

        # Step 4: 24h Lock policy check
        session_created_at = getattr(sess, "created_at", None)
        if not is_editable(session_created_at, actor_role, now_utc=effective_now):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session is locked for edits (24h edit window expired).",
            )

        # Step 5: Admin override check (> 24h requires non-empty reason)
        is_admin_override = False
        if actor_role == "ADMIN":
            within_24h = is_editable(session_created_at, "FACULTY", now_utc=effective_now)
            if not within_24h:
                is_admin_override = True
                if not reason or not reason.strip():
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Admin edit after 24h lock requires a non-empty reason.",
                    )

        old_status = att.status
        action = "ADMIN_OVERRIDE_EVENT" if is_admin_override else "ATTENDANCE_EDIT"

        # Step 6: Atomic DB update + audit log insert
        att.status = new_status
        att.source = "MANUAL_EDIT"
        att.recorded_at = now_iso

        audit = AuditLog(
            actor_id=actor_id,
            action=action,
            session_id=clean_session_id,
            usn=clean_usn,
            entity_type="attendance",
            entity_id=att.attendance_id or f"{clean_session_id}:{clean_usn}",
            old_value=old_status,
            new_value=new_status,
            reason=reason.strip() if reason else None,
            timestamp=now_iso,
        )
        db.add(audit)
        db.flush()
        db.commit()

        return {
            "success": True,
            "session_id": clean_session_id,
            "usn": clean_usn,
            "old_status": old_status,
            "new_status": new_status,
            "updated_at": now_iso,
            "event": action,
            "audit_log_id": audit.log_id,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Failed atomic attendance edit: %s", exc)
        raise
    finally:
        if created_db:
            db.close()
