"""FastAPI router for Agent Chat and Pending Edits confirmation (Prompt N7 / Rule D13)."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, Role
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser
from app.services.pending_edits import confirm_pending, get_latest_pending, prepare_edit

logger = logging.getLogger("rollcall.routers.chat")

router = APIRouter(prefix="/chat", tags=["Chat"])


class ChatMessageRequest(BaseModel):
    query: str = Field(..., min_length=1, description="User query or edit command")


class ChatConfirmRequest(BaseModel):
    pending_id: str = Field(..., description="Pending edit ID to confirm or reject")
    decision: str = Field(..., description="'yes' to commit or 'no' to cancel")
    reason: Optional[str] = Field(None, description="Optional override reason")


def _parse_edit_intent(text: str) -> Optional[Dict[str, str]]:
    """Parse natural language edit commands into components."""
    clean = text.strip()
    
    # Pattern: Mark [USN] (as) [Present|Absent] for [Subject] (on date/today)
    match = re.search(
        r"(?:mark|change|set)\s+(?:usn\s+)?([A-Za-z0-9]+)\s+(?:as\s+)?(present|absent)\s+(?:for\s+)?([A-Za-z0-9_\-\s]+?)(?:\s+(today|\d{4}-\d{2}-\d{2}))?$",
        clean,
        re.IGNORECASE,
    )
    if match:
        usn = match.group(1).upper()
        status_val = match.group(2).capitalize()
        subject = match.group(3).strip()
        date_val = match.group(4) or "today"
        return {"usn": usn, "status": status_val, "subject": subject, "date": date_val}
    return None


@router.post(
    "",
    summary="Chat with Attendance Agent with staged edit support",
    description="Processes natural-language queries or edit commands. All attendance edits require two-step confirmation.",
)
def chat_endpoint(
    payload: ChatMessageRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    text = payload.query.strip()
    lower_text = text.lower()

    # Rule D1: Identity spoofing prevention
    if "i am the admin" in lower_text or "unlock it" in lower_text:
        if current_user.role != Role.ADMIN:
            return {
                "reply": "Refused: Your account is not authorized as an administrator. Roles are strictly determined by verified credentials, not chat text.",
                "needs_confirmation": False,
            }

    # Step 2: Handle inline 'Yes' or 'No' confirming the latest pending edit
    if lower_text in ("yes", "y", "confirm", "no", "n", "cancel"):
        pending = get_latest_pending(current_user.user_id, db)
        if not pending:
            return {
                "reply": "There are no pending edits to confirm. What would you like to change?",
                "needs_confirmation": False,
            }
        decision = lower_text in ("yes", "y", "confirm")
        res = confirm_pending(user=current_user, pending_id=pending.edit_id, decision=decision, db=db)
        if "error" in res:
            return {"reply": res["error"], "needs_confirmation": False}
        return {
            "reply": res.get("message", "Edit processed."),
            "needs_confirmation": False,
            "success": res.get("success", True),
            "cancelled": res.get("cancelled", False),
        }

    # Step 1: Detect edit command
    edit_intent = _parse_edit_intent(text)
    if edit_intent:
        prep = prepare_edit(
            user=current_user,
            subject=edit_intent["subject"],
            usn=edit_intent["usn"],
            new_status=edit_intent["status"],
            date_str=edit_intent["date"],
            db=db,
        )
        if "error" in prep:
            return {
                "reply": prep["error"],
                "needs_confirmation": False,
            }
        return {
            "reply": prep["confirm_text"],
            "needs_confirmation": True,
            "pending_id": prep["pending_id"],
            "confirm_text": prep["confirm_text"],
            "session_id": prep.get("session_id"),
            "usn": prep.get("usn"),
            "old_status": prep.get("old_status"),
            "new_status": prep.get("new_status"),
        }

    # General query fallback: route to AttendanceAgent
    try:
        from app.agent import AttendanceAgent
        agent = AttendanceAgent(db_target=db)
        agent_res = agent.process_request(user_input=text)
        return {
            "reply": agent_res.reply if hasattr(agent_res, "reply") else str(agent_res),
            "needs_confirmation": False,
        }
    except Exception as exc:
        logger.warning("Agent query fallback exception: %s", exc)
        return {
            "reply": f"Understood query: '{text}'. Please specify an action or request.",
            "needs_confirmation": False,
        }


@router.post(
    "/confirm",
    summary="Confirm or reject a pending attendance edit",
    description="Explicit confirmation endpoint called by the UI confirmation card.",
)
def confirm_endpoint(
    payload: ChatConfirmRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    res = confirm_pending(
        user=current_user,
        pending_id=payload.pending_id,
        decision=payload.decision,
        reason=payload.reason,
        db=db,
    )
    if "error" in res:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res["error"],
        )
    return res

