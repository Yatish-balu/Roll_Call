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
        orchestrator = AgentOrchestrator()
        orchestrator.execute_prompt(actor_id=actor_id, role=role, prompt=prompt, task_id=task_id)
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

