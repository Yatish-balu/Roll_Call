"""N7: AI chat attendance-edit tool — server-side proposal preparation.

This tool is the LLM-facing entry point for chat-driven attendance edits.
It does NOT modify attendance — it only validates the request, checks
authorization and the 24-hour lock, and stores a pending_edits row bound
to the authenticated user. The actual change is applied only after the
user confirms via POST /api/chat/confirm.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db import crud
from app.services.attendance_edits import resolve_edit_intent, propose_attendance_edit


def update_attendance_tool(
    db: Session,
    actor_id: str,
    actor_role: str,
    query: str,
    session_id: Optional[str] = None,
    usn: Optional[str] = None,
    new_status: Optional[str] = None,
    reason: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Prepare an attendance-edit proposal for user confirmation.

    This is the tool the LLM calls when a teacher asks to change a
    student's attendance status via chat. It resolves the intent from
    natural language, verifies the caller is authorized for the session,
    checks the 24-hour edit lock, and stores a pending edit (5-minute
    expiry, single use, bound to the caller). Attendance is NOT modified
    here.

    Returns a dict with ``status`` ("proposed" or "clarification_required"),
    ``needs_confirmation``, ``confirmation_id``, ``confirmation_request``
    and a human-readable ``message``.
    """
    from app.schemas.auth import AuthenticatedUser

    user = AuthenticatedUser(
        user_id=actor_id,
        role=actor_role,
        claims={},
    )

    intent = resolve_edit_intent(
        db,
        query=query,
        session_id=session_id,
        usn=usn,
        new_status=new_status,
    )

    return propose_attendance_edit(
        db=db,
        current_user=user,
        intent=intent,
        reason=reason,
        request_id=kwargs.get("request_id"),
    )


__all__ = ["update_attendance_tool"]
