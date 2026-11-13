"""FastAPI router for SSE streaming agent endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent.orchestrator import AgentOrchestrator
from app.agent.stream import task_manager, TaskState
from app.auth import get_current_user
from app.schemas.auth import AuthenticatedUser

logger = logging.getLogger("rollcall.routers.agent_stream")

router = APIRouter(prefix="/agent/tasks", tags=["Agent Streaming"])


def _run_orchestrator_background(task_id: str, actor_id: str, role: str, prompt: str) -> None:
    try:
        from app.db.connection import get_sync_session_factory
        from app.db import crud
        from app.db.models import User
        from datetime import date
        factory = get_sync_session_factory()
        with factory() as db:
            assigned_subs = []
            teacher_name = actor_id
            teacher_email = ""
            today_schedule_summary = ""
            pending_summary = ""
            try:
                assigned_subs = crud.get_teacher_subjects(db, user_id=actor_id) or []
                user = db.query(User).filter(User.user_id == actor_id).first()
                if user:
                    teacher_name = user.name or actor_id
                    teacher_email = user.email or ""

                # Fast fetch of today's sessions for this teacher
                today_str = date.today().isoformat()
                today_sessions = crud.get_sessions_by_date(db, date=today_str)
                my_today = [
                    s for s in today_sessions
                    if (isinstance(s, dict) and (s.get("teacher_id") == actor_id or s.get("subject_code") in assigned_subs))
                    or (hasattr(s, "teacher_id") and (s.teacher_id == actor_id or s.subject_code in assigned_subs))
                ]
                if my_today:
                    session_descs = []
                    for s in my_today:
                        s_id = s["session_id"] if isinstance(s, dict) else s.session_id
                        sub = s["subject_code"] if isinstance(s, dict) else s.subject_code
                        room = (s.get("room_id") if isinstance(s, dict) else getattr(s, "room_id", None)) or "—"
                        session_descs.append(f"{sub} ({s_id}, Room: {room})")
                    today_schedule_summary = f"{len(my_today)} session(s) scheduled for today ({today_str}): " + ", ".join(session_descs)
                else:
                    today_schedule_summary = f"No active sessions scheduled for today ({today_str}) for your assigned subjects ({', '.join(assigned_subs) if assigned_subs else 'None'})."

                # Check pending sessions for this teacher's subjects
                all_pending = crud.get_pending_unreviewed_sessions(db, subject=assigned_subs[0] if assigned_subs else None)
                if all_pending:
                    pending_summary = f"{len(all_pending)} session(s) with pending/unreviewed attendance."
                else:
                    pending_summary = "All session attendance records are fully reviewed."
            except Exception as e:
                logger.debug("Teacher snapshot pre-fetch encountered: %s", e)

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
        logger.error("Background agent execution failed for task %s: %s", task_id, exc)


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

