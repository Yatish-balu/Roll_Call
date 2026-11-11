"""Shared authorization + audit service for attendance edits (N5, N7).

Every attendance write path - direct API, chat confirmation and the legacy UI
commit - goes through this service so that:

* **Authorization** is decided by exactly one policy: ADMIN is unrestricted;
  every other role needs session ownership, coordinator ownership, or an
  exact (normalized) teacher-subject-code mapping. There is **no time-based
  editing lock**: sessions of any age and any lifecycle status (including
  ``COMPLETED``) may be edited by an authorized faculty member, and no admin
  override reason is required.
* **Every successful modification** produces one append-only audit record per
  affected student, carrying actor identity, actor role, session, USN, the
  previous status, the new status and a UTC timestamp.
* The attendance change and its audit records are written in **one
  transaction**: if the audit insert fails, the attendance change is rolled
  back.
* Failed, rejected and unauthorized modifications never produce a
  successful-edit audit event.

The **AI chat attendance-editing workflow (N7)** is built on the same service:
a proposal only stores a pending edit (attendance is never touched), and the
confirmation applies the stored proposal through the existing atomic
``apply_attendance_edit_atomic`` primitive.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db import crud
from app.db.models import AuditLog
from app.schemas.auth import AuthenticatedUser, Role

logger = logging.getLogger("rollcall.services.attendance_edits")

# Principal used when a write happens outside an authenticated request (the
# legacy local UI). It is never a person and never carries a privileged
# browser session - it exists so that such writes stay attributable.
SYSTEM_ACTOR_ID = "system"
SYSTEM_ACTOR_ROLE = "SYSTEM"

# A proposed attendance edit expires after five minutes (N7).
PENDING_EDIT_TTL_MINUTES = 5



def _utcnow_iso() -> str:
    """Current UTC timestamp in canonical ISO 8601 Z format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class AttendanceChange:
    """One student's attendance modification, ready to be audited."""

    usn: str
    old_status: Optional[str]
    new_status: Optional[str]
    attendance_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Authorization (the single N3/N5 policy)
# ---------------------------------------------------------------------------

def assert_session_edit_authorized(
    current_user: AuthenticatedUser,
    session: Dict[str, Any],
    db: Optional[Session] = None,
) -> None:
    """Enforce faculty ownership of a session for attendance edits (N3/N5).

    ADMIN keeps institutional access to every session. FACULTY access is allowed
    only when one of these holds:
      * the session is attributed to that faculty member,
      * the session is attributed to nobody / the legacy sentinel AND the
        faculty is mapped to the session's subject code (``teacher_subjects``)
        or is the session coordinator.

    Legacy sessions are never assigned to anybody, but they are no longer
    world-readable by every faculty account: an unmapped faculty member is
    denied, and an authorized administrator can grant access by adding the
    subject-code mapping. Historical attendance data is not modified.

    Session age and lifecycle status are deliberately NOT considered: there is
    no 24-hour editing lock and no admin override reason.
    """
    if current_user.role == Role.ADMIN:
        return
    # Every non-admin role is authorized the same way (ownership / coordinator /
    # subject mapping); write endpoints are separately role-gated.
    owner = session.get("teacher_id")
    owned = owner is not None and str(owner).strip() not in ("", "legacy")

    if owned:
        if str(owner).strip() == current_user.user_id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Forbidden: session '{session.get('session_id')}' is assigned to another "
                "faculty member. You can only access your own sessions."
            ),
        )

    # Unowned / legacy session: authorize by subject mapping, never by guesswork.
    coordinator = session.get("coordinator_faculty_id")
    if coordinator and str(coordinator).strip() == current_user.user_id:
        return

    subject_code = str(session.get("subject_code") or "").strip()
    if subject_code and db is not None and crud.is_teacher_assigned_to_subject(
        db, current_user.user_id, subject_code
    ):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            f"Forbidden: session '{session.get('session_id')}' has no faculty owner and "
            + (
                f"subject code '{subject_code}' is not mapped to your account."
                if subject_code
                else "no subject code, so access requires an administrator."
            )
        ),
    )


def session_is_editable(session: Dict[str, Any]) -> bool:
    """Whether a session may be edited.

    Always True: sessions of any age and any lifecycle status stay editable
    for an authorized actor. Kept as an explicit function so the policy is
    visible in one place and cannot drift into a time-based lock.
    """
    return True


# ---------------------------------------------------------------------------
# Status capture + auditing
# ---------------------------------------------------------------------------

def capture_attendance_statuses(
    db: Union[sqlite3.Connection, Session, str],
    session_id: str,
    usns: Optional[Iterable[str]] = None,
) -> Dict[str, Optional[str]]:
    """Return the current status of every attendance row of a session.

    Used to record the *previous* status of each affected student before the
    write happens.
    """
    wanted = {str(u).strip().upper() for u in usns} if usns is not None else None
    statuses: Dict[str, Optional[str]] = {}
    try:
        records = crud.get_attendance_by_session(db, session_id=session_id)
    except Exception:
        records = []
    for record in records:
        usn = str(record.get("usn") or "").strip().upper()
        if not usn:
            continue
        if wanted is not None and usn not in wanted:
            continue
        statuses[usn] = record.get("status")
    if wanted is not None:
        for usn in wanted:
            statuses.setdefault(usn, None)
    return statuses


def write_attendance_audit(
    db: Union[sqlite3.Connection, Session, str],
    *,
    actor_id: str,
    actor_role: str,
    session_id: str,
    changes: Sequence[AttendanceChange],
    action: str,
    entity_type: str = "attendance",
    reason: Optional[str] = None,
) -> int:
    """Append one audit record per attendance change.

    The records are written through the existing append-only audit
    infrastructure (``crud.create_audit_entry``). Any failure propagates, so
    the caller - which performs the audit inside the same transaction as the
    attendance write - rolls the attendance change back.
    """
    if not changes:
        return 0

    clean_actor = (actor_id or "").strip()
    if not clean_actor:
        raise ValueError("An actor identity is required to audit an attendance change.")

    written = 0
    for change in changes:
        entity_id = change.attendance_id or f"{session_id}:{change.usn}"
        crud.create_audit_entry(
            db,
            actor_id=clean_actor,
            actor_role=actor_role,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            session_id=session_id,
            usn=change.usn,
            old_value=change.old_status,
            new_value=change.new_status,
            reason=reason,
            timestamp=_utcnow_iso(),
        )
        written += 1
    return written


def actor_identity(
    current_user: Optional[AuthenticatedUser],
) -> tuple[str, str]:
    """Return (actor_id, actor_role) for an authenticated caller.

    The identity and role come exclusively from the verified authentication
    context - never from a request payload, chat text or LLM output.
    """
    if current_user is None:
        return SYSTEM_ACTOR_ID, SYSTEM_ACTOR_ROLE
    role = getattr(current_user.role, "value", None) or str(current_user.role or "").strip().upper()
    return (current_user.user_id or "").strip(), role


def actor_exists(db: Union[sqlite3.Connection, Session, str], actor_id: str) -> bool:
    """True when the actor identity exists in the ``users`` table.

    The audit log references ``users.user_id``, so an unknown actor cannot be
    recorded. Callers must check this instead of inventing a principal.
    """
    clean = (actor_id or "").strip()
    if not clean:
        return False
    try:
        if isinstance(db, Session):
            from app.db.models import User

            return db.get(User, clean) is not None
        cursor = db.execute(
            "SELECT 1 FROM users WHERE user_id = ? LIMIT 1", (clean,)
        ).fetchone()
        return cursor is not None
    except Exception:
        return False


def ensure_system_actor(db: Union[sqlite3.Connection, Session, str]) -> str:
    """Ensure the non-privileged system principal exists (idempotent).

    Only used by write paths that have no authenticated caller (the legacy
    local UI). The principal is inactive and is not a person.
    """
    try:
        if isinstance(db, Session):
            from app.db.models import User

            if db.get(User, SYSTEM_ACTOR_ID) is None:
                db.add(
                    User(
                        user_id=SYSTEM_ACTOR_ID,
                        email="system@rollcall.internal",
                        role=SYSTEM_ACTOR_ROLE,
                        hashed_password=None,
                        is_active=0,
                        created_at=_utcnow_iso(),
                    )
                )
                db.flush()
        else:
            from app.db.connection import get_connection

            conn = get_connection(db) if not isinstance(db, sqlite3.Connection) else db
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO users (user_id, email, role, hashed_password, "
                    "is_active, created_at) VALUES (?, ?, ?, NULL, 0, ?)",
                    (
                        SYSTEM_ACTOR_ID,
                        "system@rollcall.internal",
                        SYSTEM_ACTOR_ROLE,
                        _utcnow_iso(),
                    ),
                )
                conn.commit()
            finally:
                if not isinstance(db, sqlite3.Connection):
                    conn.close()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not ensure the system audit principal: %s", exc)
    return SYSTEM_ACTOR_ID


# ---------------------------------------------------------------------------
# N7: AI chat attendance editing (proposal -> explicit confirmation)
# ---------------------------------------------------------------------------

# Word-shaped tokens that may carry a session id or a USN inside a chat message.
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")

# Shape of a RollCall USN (e.g. 1MS21CS001, 1DS24CY015).
_USN_SHAPE_RE = re.compile(r"^\d[A-Za-z]{2}\d{2}[A-Za-z]{2}\d{3}$")

# Status vocabulary understood in a natural-language request.
_STATUS_KEYWORDS: Dict[str, str] = {
    "present": "PRESENT",
    "attended": "PRESENT",
    "absent": "ABSENT",
    "missing": "ABSENT",
    "pending": "PENDING",
    "unreviewed": "UNREVIEWED",
    "unclear": "UNREVIEWED",
    "ambiguous": "UNREVIEWED",
}


@dataclass(frozen=True)
class EditIntent:
    """A resolved (or partially resolved) attendance-edit intent."""

    session_id: Optional[str] = None
    usn: Optional[str] = None
    new_status: Optional[str] = None
    missing: Tuple[str, ...] = ()
    ambiguous: bool = False

    @property
    def is_resolved(self) -> bool:
        return not self.missing and not self.ambiguous


def _normalize_status(raw: Optional[str]) -> Optional[str]:
    """Normalize an explicit status, raising ValueError for an invalid one."""
    if raw is None or not str(raw).strip():
        return None
    return crud.normalize_attendance_status(str(raw).strip())


def resolve_edit_intent(
    db: Union[sqlite3.Connection, Session, str],
    *,
    query: Optional[str] = None,
    session_id: Optional[str] = None,
    usn: Optional[str] = None,
    new_status: Optional[str] = None,
) -> EditIntent:
    """Resolve the intended session, student and status of an attendance edit.

    Explicit values win. Anything missing is looked up in the free-text query,
    but only tokens that actually resolve to an existing session or student in
    the database are considered - the model never decides what exists.

    Nothing here touches attendance: this is pure intent resolution.
    """
    missing: List[str] = []
    text = (query or "").strip()

    # --- session -------------------------------------------------------
    resolved_session: Optional[str] = None
    explicit_session = (session_id or "").strip()
    if explicit_session:
        resolved_session = explicit_session
    else:
        session_candidates: List[str] = []
        for token in _TOKEN_RE.findall(text):
            candidate = token.strip()
            if not candidate:
                continue
            if crud.get_session(db, session_id=candidate):
                if candidate not in session_candidates:
                    session_candidates.append(candidate)
        if len(session_candidates) == 1:
            resolved_session = session_candidates[0]
        elif len(session_candidates) > 1:
            return EditIntent(ambiguous=True, missing=("session",))

    # --- student -------------------------------------------------------
    resolved_usn: Optional[str] = None
    explicit_usn = (usn or "").strip()
    if explicit_usn:
        resolved_usn = explicit_usn
    else:
        usn_candidates: List[str] = []
        for token in _TOKEN_RE.findall(text):
            candidate = token.strip().upper()
            if not candidate:
                continue
            if crud.get_student(db, usn=candidate):
                if candidate not in usn_candidates:
                    usn_candidates.append(candidate)
        if len(usn_candidates) == 1:
            resolved_usn = usn_candidates[0]
        elif len(usn_candidates) > 1:
            return EditIntent(session_id=resolved_session, ambiguous=True, missing=("usn",))

    # --- status --------------------------------------------------------
    resolved_status: Optional[str] = None
    if new_status is not None and str(new_status).strip():
        # An explicitly supplied status must be valid (raises ValueError -> 422).
        resolved_status = _normalize_status(new_status)
    else:
        found: Set[str] = set()
        lowered = text.lower()
        for word, status_value in _STATUS_KEYWORDS.items():
            if re.search(rf"\b{word}\b", lowered):
                found.add(status_value)
        if len(found) == 1:
            resolved_status = found.pop()
        elif len(found) > 1:
            return EditIntent(
                session_id=resolved_session, usn=resolved_usn, ambiguous=True, missing=("new_status",)
            )

    if not resolved_session:
        missing.append("session")
    if not resolved_usn:
        missing.append("usn")
    if not resolved_status:
        missing.append("new_status")

    return EditIntent(
        session_id=resolved_session,
        usn=resolved_usn,
        new_status=resolved_status,
        missing=tuple(missing),
    )


def _clarification_payload(intent: EditIntent) -> Dict[str, Any]:
    """Build the 'ask the user' payload for an unresolved intent."""
    questions = {
        "session": "Which session should the attendance change apply to?",
        "usn": "Which student (USN) should the attendance change apply to?",
        "new_status": "Which attendance status should be proposed (PRESENT, ABSENT, PENDING or UNREVIEWED)?",
    }
    question = " ".join(questions.get(part, "") for part in intent.missing).strip()
    return {
        "status": "clarification_required",
        "needs_confirmation": False,
        "confirmation_request": None,
        "clarification": {
            "question": question,
            "missing": list(intent.missing),
            "ambiguous": intent.ambiguous,
        },
        "message": (
            "I could not resolve the requested attendance change unambiguously."
            if not intent.ambiguous
            else "The request matches more than one record; please be more specific."
        ),
    }


def propose_attendance_edit(
    db: Session,
    current_user: AuthenticatedUser,
    *,
    intent: EditIntent,
    reason: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a pending attendance-edit proposal (Step A of the chat workflow).

    **Attendance is never modified here.** The proposal is stored as a
    ``pending_edits`` row bound to the authenticated user and expires after
    five minutes; the stored row is the only thing the confirmation may apply.

    Raises HTTPException: 404 (unknown session/student), 403 (not authorized),
    409 (no attendance record / status already set).
    """
    if not intent.is_resolved:
        return _clarification_payload(intent)

    session = crud.get_session(db, session_id=intent.session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{intent.session_id}' not found.",
        )

    # Authorization is decided by the backend, never by the model or the client.
    assert_session_edit_authorized(current_user, session, db)

    student = crud.get_student(db, usn=intent.usn)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with USN '{intent.usn}' not found.",
        )

    current = crud.get_attendance_record(db, intent.session_id, intent.usn)
    if not current:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"No attendance record exists for student '{intent.usn}' in session "
                f"'{intent.session_id}'; there is nothing to modify."
            ),
        )

    old_status = str(current.get("status") or "").strip().upper()
    new_status = str(intent.new_status or "").strip().upper()
    if old_status == new_status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Student '{intent.usn}' is already marked {new_status} in session "
                f"'{intent.session_id}'."
            ),
        )

    pending = crud.create_pending_edit(
        db,
        user_id=current_user.user_id,
        session_id=intent.session_id,
        usn=intent.usn,
        old_status=old_status,
        new_status=new_status,
        ttl_minutes=PENDING_EDIT_TTL_MINUTES,
    )
    db.commit()

    expires_at = pending.get("expires_at")
    question = (
        f"Confirm marking {student.get('name') or intent.usn} ({intent.usn}) as "
        f"{new_status} in session {intent.session_id} "
        f"({session.get('date')} - {session.get('subject')})? "
        f"Current status: {old_status}."
    )
    affected_row = {
        "session_id": intent.session_id,
        "session_date": session.get("date"),
        "subject": session.get("subject"),
        "usn": intent.usn,
        "student_name": student.get("name"),
        "name": student.get("name"),
        "branch": student.get("branch"),
        "room_id": current.get("room_id"),
        "current_status": old_status,
        "old_status": old_status,
        "new_status": new_status,
        "proposed_status": new_status,
        "confirmation_id": pending.get("edit_id"),
        "expires_at": expires_at,
    }
    return {
        "status": "proposed",
        "success": True,
        "needs_confirmation": True,
        "confirmation_id": pending.get("edit_id"),
        "expires_at": expires_at,
        "expires_in_seconds": PENDING_EDIT_TTL_MINUTES * 60,
        "session": {
            "session_id": intent.session_id,
            "date": session.get("date"),
            "subject": session.get("subject"),
            "subject_code": session.get("subject_code"),
        },
        "student": {
            "usn": intent.usn,
            "name": student.get("name"),
            "branch": student.get("branch"),
        },
        "current_status": old_status,
        "proposed_status": new_status,
        "confirmation_request": {
            "needed": True,
            "question": question,
            "issues": [],
            "affected_rows": [affected_row],
        },
        "clarification": None,
        "message": (
            "A proposed attendance change is awaiting your confirmation. "
            f"Nothing has been changed yet; confirm within "
            f"{PENDING_EDIT_TTL_MINUTES} minutes."
        ),
        "request_id": request_id,
        "tool_calls": [],
    }


def confirm_attendance_edit(
    db: Session,
    current_user: AuthenticatedUser,
    *,
    confirmation_id: str,
    reason: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply a previously proposed attendance edit (Step B of the chat workflow).

    Only the confirmation identifier is accepted: the student, session and
    proposed status always come from the stored pending edit, and the actor
    identity/role always come from the verified authentication context.

    Raises HTTPException: 400 (missing id), 404 (unknown/inaccessible
    confirmation), 409 (already used / conflicting / stale), 410 (expired),
    403 (authorization lost since the proposal).
    """
    from app.db.models import PendingEdit

    clean_id = (confirmation_id or "").strip()
    if not clean_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A confirmation identifier is required.",
        )

    edit = db.get(PendingEdit, clean_id)
    # Unknown and not-owned confirmations are indistinguishable on purpose:
    # the response must not reveal that somebody else's proposal exists.
    if edit is None or edit.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Confirmation not found.",
        )

    now_ts = _utcnow_iso()
    if int(edit.consumed or 0) != 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This confirmation has already been used.",
        )
    if str(edit.expires_at) <= now_ts:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This confirmation has expired. Please propose the change again.",
        )

    session = crud.get_session(db, session_id=edit.session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Confirmation not found.",
        )

    # Revalidate authorization at confirmation time: access may have been
    # revoked between the proposal and the confirmation.
    assert_session_edit_authorized(current_user, session, db)

    actor_id, actor_role = actor_identity(current_user)
    try:
        result = crud.apply_attendance_edit_atomic(
            db,
            edit_id=clean_id,
            user_id=actor_id,
            authenticated_role=actor_role,
            reason=reason,
        )
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        message = str(exc)
        lowered = message.lower()
        if "expired" in lowered:
            code = status.HTTP_410_GONE
        elif "no longer exists" in lowered:
            code = status.HTTP_404_NOT_FOUND
        else:
            # already consumed / concurrently consumed / stale edit
            code = status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=message)

    db.commit()

    return {
        "success": True,
        "status": "confirmed",
        "confirmation_id": clean_id,
        "session_id": result.get("session_id"),
        "usn": result.get("usn"),
        "old_status": result.get("old_status"),
        "new_status": result.get("new_status"),
        "audit_log_id": result.get("audit_log_id"),
        "message": (
            f"Attendance updated for {result.get('usn')}: "
            f"{result.get('old_status')} -> {result.get('new_status')}."
        ),
        "request_id": request_id,
    }
