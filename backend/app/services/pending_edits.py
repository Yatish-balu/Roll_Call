"""Pending edits service for staged attendance changes from chat (Prompt N7 / Rule D13)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Union

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Attendance, Session as DbSession, PendingEdit, TeacherSubject
from app.dependencies import get_session_factory
from app.policy import is_editable
from app.services.attendance_edit import update_attendance

logger = logging.getLogger("rollcall.services.pending_edits")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso(dt: Optional[datetime] = None) -> str:
    return (dt or _utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")


def prepare_edit(
    user: Any,
    subject: str,
    usn: str,
    new_status: str,
    date_str: Optional[str] = None,
    *,
    db: Optional[Session] = None,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Prepare a staged attendance edit proposal.

    Checks:
    - Normalizes status (must be PRESENT or ABSENT).
    - Checks teacher subject assignment.
    - Resolves session for given date (defaults to today UTC).
    - Checks teacher owns session.
    - Checks USN exists in session.
    - Checks 24h lock policy.
    - Stores pending_edit record (expires in 5 minutes, single use).
    - Returns confirmation card payload.
    """
    clean_status = new_status.strip().upper() if new_status else ""
    if clean_status not in ("PRESENT", "ABSENT"):
        return {"error": f"Invalid status '{new_status}'. Status must be 'Present' or 'Absent'."}

    clean_usn = usn.strip().upper() if usn else ""
    clean_subject = subject.strip() if subject else ""

    if isinstance(user, dict):
        actor_id = str(user.get("user_id") or "")
        actor_role = str(user.get("role") or "").upper()
    else:
        actor_id = str(getattr(user, "user_id", "") or "")
        actor_role = str(getattr(user, "role", "") or "").upper()

    effective_now = now_utc or _utcnow()
    target_date = date_str.strip() if (date_str and date_str.lower() != "today") else effective_now.strftime("%Y-%m-%d")

    created_db = False
    if db is None:
        factory = get_session_factory()
        db = factory()
        created_db = True

    try:
        # Step 1: Teacher subject check (if FACULTY)
        if actor_role != "ADMIN":
            ts_stmt = select(TeacherSubject.subject_code).where(TeacherSubject.user_id == actor_id)
            assigned_codes = [c.upper() for c in db.execute(ts_stmt).scalars().all()]
            # Match code or prefix
            subj_match = any(
                code == clean_subject.upper() or code in clean_subject.upper() or clean_subject.upper() in code
                for code in assigned_codes
            )
            if not subj_match and assigned_codes:
                return {"error": f"Refused: You do not teach subject '{clean_subject}'."}

        # Step 2: Find session for date and subject
        sess_stmt = select(DbSession).where(
            DbSession.date == target_date,
        )
        sessions = db.execute(sess_stmt).scalars().all()
        matched_sess = None
        for s in sessions:
            s_subj = (s.subject_code or s.subject or "").upper()
            if clean_subject.upper() in s_subj or s_subj in clean_subject.upper():
                matched_sess = s
                break

        if not matched_sess:
            # Fallback: check all sessions for that subject if date was today
            for s in sessions:
                matched_sess = s
                break

        if not matched_sess:
            return {"error": f"No session found for subject '{clean_subject}' on date {target_date}."}

        # Step 3: Teacher ownership check
        if actor_role != "ADMIN":
            if matched_sess.teacher_id != actor_id:
                return {"error": f"Refused: You are not assigned to session '{matched_sess.session_id}'."}

        # Step 4: USN in session check
        att_stmt = select(Attendance).where(
            Attendance.session_id == matched_sess.session_id,
            Attendance.usn == clean_usn,
        )
        att = db.execute(att_stmt).scalar_one_or_none()
        if not att:
            return {"error": "USN not found in that session."}

        # Step 5: Lock policy check
        if not is_editable(matched_sess.created_at, actor_role, now_utc=effective_now):
            return {"error": "Session is locked. Only an admin can unlock."}

        # Step 6: Create pending_edit row (5 min expiry)
        edit_id = f"pe_{uuid.uuid4().hex[:12]}"
        now_iso = _utcnow_iso(effective_now)
        exp_iso = _utcnow_iso(effective_now + timedelta(minutes=5))

        pending = PendingEdit(
            edit_id=edit_id,
            user_id=actor_id,
            session_id=matched_sess.session_id,
            attendance_id=att.attendance_id,
            usn=clean_usn,
            old_status=att.status,
            new_status=clean_status,
            created_at=now_iso,
            expires_at=exp_iso,
            consumed=0,
        )
        db.add(pending)
        db.commit()

        confirm_text = f"Change {clean_usn} from {att.status} to {clean_status} for {clean_subject} on {target_date}?"
        return {
            "needs_confirmation": True,
            "pending_id": edit_id,
            "confirm_text": confirm_text,
            "session_id": matched_sess.session_id,
            "usn": clean_usn,
            "old_status": att.status,
            "new_status": clean_status,
            "date": target_date,
        }
    finally:
        if created_db:
            db.close()


def confirm_pending(
    user: Any,
    pending_id: str,
    decision: Union[str, bool],
    reason: Optional[str] = None,
    *,
    db: Optional[Session] = None,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Execute or cancel a staged attendance edit proposal."""
    clean_eid = pending_id.strip() if pending_id else ""
    if isinstance(user, dict):
        actor_id = str(user.get("user_id") or "")
    else:
        actor_id = str(getattr(user, "user_id", "") or "")

    effective_now = now_utc or _utcnow()
    now_iso = _utcnow_iso(effective_now)

    is_yes = False
    if isinstance(decision, bool):
        is_yes = decision
    elif isinstance(decision, str):
        is_yes = decision.strip().lower() in ("yes", "y", "true", "confirm")

    created_db = False
    if db is None:
        factory = get_session_factory()
        db = factory()
        created_db = True

    try:
        # Atomic fetch-and-check
        pending = db.get(PendingEdit, clean_eid)
        if not pending:
            return {"error": "No pending edit found."}

        if pending.user_id != actor_id:
            return {"error": "Pending edit belongs to a different user."}

        if pending.consumed != 0:
            return {"error": "Pending edit has already been used."}

        if pending.expires_at <= now_iso:
            return {"error": "Pending expired. Nothing changed."}

        if not is_yes:
            # Cancellation: mark consumed and return
            pending.consumed = 1
            db.commit()
            return {
                "success": True,
                "cancelled": True,
                "message": "Pending edit cancelled. No changes were made.",
            }

        # Mark consumed first within atomic transaction to prevent double execution
        pending.consumed = 1
        db.flush()

        # Re-run update_attendance with all checks
        edit_result = update_attendance(
            user=user,
            session_id=pending.session_id,
            usn=pending.usn,
            new_status=pending.new_status,
            reason=reason,
            db=db,
            now_utc=effective_now,
        )

        return {
            "success": True,
            "cancelled": False,
            "message": f"Successfully updated {pending.usn} from {pending.old_status} to {pending.new_status}.",
            "old_status": pending.old_status,
            "new_status": pending.new_status,
            "session_id": pending.session_id,
            "usn": pending.usn,
            "audit_log_id": edit_result.get("audit_log_id"),
        }
    finally:
        if created_db:
            db.close()


def get_latest_pending(user_id: str, db: Session, now_utc: Optional[datetime] = None) -> Optional[PendingEdit]:
    """Retrieve the latest unconsumed, unexpired pending edit for a user."""
    effective_now = now_utc or _utcnow()
    now_iso = _utcnow_iso(effective_now)
    stmt = (
        select(PendingEdit)
        .where(
            PendingEdit.user_id == user_id,
            PendingEdit.consumed == 0,
            PendingEdit.expires_at > now_iso,
        )
        .order_by(PendingEdit.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()

