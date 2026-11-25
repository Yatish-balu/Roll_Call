"""FastAPI router for SSE streaming agent endpoints."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent.stream import task_manager, TaskState
from app.auth import get_current_user
from app.schemas.auth import AuthenticatedUser

logger = logging.getLogger("rollcall.routers.agent_stream")

router = APIRouter(prefix="/agent/tasks", tags=["Agent Streaming"])


def _run_orchestrator_background(task_id: str, actor_id: str, role: str, prompt: str) -> None:
    """
    Execute the agent request in a background thread, emitting SSE events.
    Uses the battle-tested AttendanceAgent (legacy_agent) with proper DB scope
    so all queries (students, sessions, attendance) are correctly scoped and grounded.
    Falls back to AgentOrchestrator if legacy agent import fails.
    """
    try:
        from app.db.connection import get_sync_session_factory
        from app.db import crud
        from app.db.models import User
        from app.auth.roles import Role
        from app.auth.session_scope import resolve_data_scope
        from app.schemas.auth import AuthenticatedUser as AU
        from datetime import date

        factory = get_sync_session_factory()
        with factory() as db:
            assigned_subs: list = []
            teacher_name = actor_id
            teacher_email = ""
            actor_name_full = actor_id

            try:
                assigned_subs = crud.get_teacher_subjects(db, user_id=actor_id) or []
                user = db.query(User).filter(User.user_id == actor_id).first()
                if user:
                    teacher_name = user.name or actor_id
                    teacher_email = user.email or ""
                # Prioritize full_name from user_profiles if present
                from sqlalchemy import text as sa_text
                try:
                    prof = db.execute(
                        sa_text("SELECT full_name FROM user_profiles WHERE user_id = :uid"),
                        {"uid": actor_id},
                    ).fetchone()
                    if prof and prof[0] and str(prof[0]).strip():
                        teacher_name = str(prof[0]).strip()
                except Exception:
                    pass
                actor_name_full = teacher_name
            except Exception as e:
                logger.debug("Teacher profile pre-fetch encountered: %s", e)

            # Resolve DB-scoped permissions for this teacher
            try:
                role_enum = Role(role.lower()) if role.lower() in [r.value for r in Role] else Role.FACULTY
            except Exception:
                role_enum = Role.FACULTY

            try:
                auth_user = AU(user_id=actor_id, role=role_enum, name=teacher_name)
                scope = resolve_data_scope(db, auth_user)
            except Exception as scope_exc:
                logger.warning("Could not resolve scope for %s: %s — using unrestricted fallback", actor_id, scope_exc)
                scope = None

            # Emit task.started event so frontend knows processing began
            task_manager.emit_event(
                task_id,
                event_type="step.started",
                message="Processing your request...",
                data={"step": 1},
            )
            task_manager.update_status(task_id, TaskState.RUNNING, message="Executing request.")

            # Gatekeeper evaluation (async-safe)
            from app.agent.gatekeeper import evaluate_user_intent, GATEKEEPER_DOMAIN_REFUSAL, GATEKEEPER_SECURITY_REFUSAL
            from app.agent.orchestrator import _run_coroutine_sync
            from app.agent.guardrails import validate_agent_output

            gk_decision = _run_coroutine_sync(evaluate_user_intent(prompt, user_role=role.lower()))
            if gk_decision.decision in ("OUT_OF_SCOPE", "PROMPT_INJECTION"):
                refusal = gk_decision.refusal_message or (
                    GATEKEEPER_DOMAIN_REFUSAL if gk_decision.decision == "OUT_OF_SCOPE" else GATEKEEPER_SECURITY_REFUSAL
                )
                task_manager.update_status(task_id, TaskState.COMPLETED, message=refusal)
                task_manager.emit_event(
                    task_id,
                    event_type="task.completed",
                    message=refusal,
                    data={"final_response": refusal, "out_of_scope": True},
                )
                return

            from app.agent.legacy_agent import _is_confirmation_input, _is_cancellation_input

            effective_prompt = getattr(gk_decision, "normalized_intent", "").strip() or prompt
            clean_check = effective_prompt.lower()
            is_direct_query = (
                (any(w in clean_check for w in ["department", "dept"]) and any(w in clean_check for w in ["work", "belong", "which", "my", "where", "in which"]))
                or any(w in clean_check for w in ["who is", "usn of", "what usn", "which usn", "what is the usn"])
                or _is_confirmation_input(clean_check)
                or _is_cancellation_input(clean_check)
                or "mobile" in clean_check
                or "session" in clean_check
                or any(w in clean_check for w in ["profile", "attendance summary", "overall attendance", "vacant", "schedule", "defaulter"])
            )

            if not is_direct_query and getattr(gk_decision, "needs_clarification", False) and getattr(gk_decision, "clarification_question", None):
                clarify = gk_decision.clarification_question
                task_manager.update_status(task_id, TaskState.COMPLETED, message=clarify)
                task_manager.emit_event(
                    task_id,
                    event_type="task.completed",
                    message=clarify,
                    data={"final_response": clarify, "needs_clarification": True},
                )
                return

            # --- Primary Path: Use AttendanceAgent (legacy_agent) with full scope ---
            try:
                from app.agent.legacy_agent import AttendanceAgent
                agent = AttendanceAgent(
                    db_target=db,
                    scope=scope,
                    role=role_enum,
                    actor_role=role_enum,
                    actor_id=actor_id,
                    actor_name=actor_name_full,
                    assigned_subjects=assigned_subs,
                )
                resp = agent.process_request(user_input=effective_prompt, gatekeeper_decision=gk_decision)
                out_check = validate_agent_output(
                    resp.message or "",
                    tool_called=bool(resp.tool_calls),
                    gatekeeper_decision=gk_decision,
                )
                final_msg = out_check.sanitized_response if (not out_check.allowed or out_check.sanitized_response) else (resp.message or "Request completed.")
                task_manager.emit_event(
                    task_id,
                    event_type="task.completed",
                    message=final_msg,
                    data={
                        "final_response": final_msg,
                        "data": resp.data or [],
                        "tool_calls": resp.tool_calls or [],
                        "needs_confirmation": resp.needs_confirmation,
                        "confirmation_request": getattr(resp, "confirmation_request", None),
                    },
                )
                task_manager.update_status(task_id, TaskState.COMPLETED, message=final_msg)
                return
            except Exception as legacy_exc:
                logger.warning("AttendanceAgent failed for task %s: %s — falling back to orchestrator", task_id, legacy_exc)

            # --- Fallback Path: AgentOrchestrator (Gemini ReAct loop) ---
            try:
                today_str = date.today().isoformat()
                today_sessions = crud.get_sessions_by_date(db, date=today_str)
                my_today = [
                    s for s in today_sessions
                    if (isinstance(s, dict) and (s.get("teacher_id") == actor_id or s.get("subject_code") in assigned_subs))
                    or (hasattr(s, "teacher_id") and (s.teacher_id == actor_id or s.subject_code in assigned_subs))
                ]
                if my_today:
                    session_descs = [
                        f"{(s['subject_code'] if isinstance(s, dict) else s.subject_code)} "
                        f"({(s['session_id'] if isinstance(s, dict) else s.session_id)})"
                        for s in my_today
                    ]
                    today_schedule_summary = f"{len(my_today)} session(s) today: " + ", ".join(session_descs)
                else:
                    today_schedule_summary = f"No sessions today ({today_str}) for {', '.join(assigned_subs) or 'your subjects'}."
                all_pending = crud.get_pending_unreviewed_sessions(db, subject=assigned_subs[0] if assigned_subs else None)
                pending_summary = (
                    f"{len(all_pending)} session(s) with pending attendance." if all_pending
                    else "All attendance records are fully reviewed."
                )
            except Exception:
                today_schedule_summary = ""
                pending_summary = ""

            from app.agent.orchestrator import AgentOrchestrator
            orchestrator = AgentOrchestrator()
            orchestrator.execute_prompt(
                actor_id=actor_id,
                role=role,
                prompt=prompt,
                assigned_subjects=assigned_subs,
                actor_name=teacher_name,
                actor_email=teacher_email,
                today_schedule_summary=today_schedule_summary,
                pending_sessions_summary=pending_summary,
                task_id=task_id,
                db=db,
            )
    except Exception as exc:
        logger.error("Background agent execution failed for task %s: %s", task_id, exc, exc_info=True)
        try:
            task_manager.emit_event(
                task_id,
                event_type="task.failed",
                message=f"An internal error occurred: {exc}",
                data={"error": str(exc)},
            )
            task_manager.update_status(task_id, TaskState.FAILED, message=str(exc))
        except Exception:
            pass


class CreateTaskRequest(BaseModel):
    prompt: str


class CreateTaskResponse(BaseModel):
    task_id: str
    stream_url: str
    status: str


class TaskStatusResponse(BaseModel):
    task_id: str
    actor_id: str
    status: str
    prompt: str
    event_count: int
    created_at: str
    updated_at: str


@router.post(
    "",
    response_model=CreateTaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new streaming agent task",
)
def create_agent_task(
    payload: CreateTaskRequest,
    background_tasks: BackgroundTasks,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> Dict[str, Any]:
    clean_prompt = payload.prompt.strip()
    if not clean_prompt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Task prompt cannot be empty.",
        )

    task = task_manager.create_task(
        actor_id=current_user.user_id,
        prompt=clean_prompt,
    )

    role_str = getattr(current_user.role, "value", str(current_user.role))
    background_tasks.add_task(
        _run_orchestrator_background,
        task.task_id,
        current_user.user_id,
        role_str,
        clean_prompt,
    )

    return {
        "task_id": task.task_id,
        "stream_url": f"/api/v1/agent/tasks/{task.task_id}/events",
        "status": task.state.value,
    }


@router.get(
    "/{task_id}/events",
    summary="Subscribe to real-time Server-Sent Events (SSE) for an agent task",
)
async def stream_task_events(
    task_id: str,
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found.",
        )

    # Actor isolation: ensure user can only stream their own tasks unless admin
    if getattr(current_user.role, "value", str(current_user.role)).upper() != "ADMIN" and task.actor_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to view this task's event stream.",
        )

    return StreamingResponse(
        task_manager.subscribe_events(task_id, last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/{task_id}",
    response_model=TaskStatusResponse,
    summary="Get current state of an agent task",
)
def get_task_status(
    task_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> Dict[str, Any]:
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found.",
        )

    if getattr(current_user.role, "value", str(current_user.role)).upper() != "ADMIN" and task.actor_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to view this task.",
        )

    return {
        "task_id": task.task_id,
        "actor_id": task.actor_id,
        "status": task.state.value,
        "prompt": task.user_prompt,
        "event_count": len(task.events),
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }

