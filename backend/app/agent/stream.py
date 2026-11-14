"""Server-Sent Events (SSE) streaming task manager for RollCall AI.

Provides real-time step-by-step visibility to the frontend:
- task.started
- step.started
- tool.started
- tool.completed
- input.required
- approval.required
- task.completed
- task.failed

Maintains an event queue with replay capabilities via Last-Event-ID for reconnection resilience.
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

logger = logging.getLogger("rollcall.agent.stream")


class TaskState(str, enum.Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class AgentEvent:
    event_id: str
    task_id: str
    event_type: str  # e.g. "step.started", "tool.started", "task.completed"
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_sse(self) -> str:
        """Format as standard W3C Server-Sent Event."""
        payload = json.dumps({
            "task_id": self.task_id,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp,
        })
        return f"id: {self.event_id}\nevent: {self.event_type}\ndata: {payload}\n\n"


@dataclass
class AgentTask:
    task_id: str
    actor_id: str
    user_prompt: str
    state: TaskState = TaskState.CREATED
    events: List[AgentEvent] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_sequence: int = 0
    subscribers: List[asyncio.Queue] = field(default_factory=list)


class AgentTaskManager:
    """In-memory task & event manager supporting SSE publishing and event replay."""

    def __init__(self):
        self._tasks: Dict[str, AgentTask] = {}

    def create_task(self, actor_id: str, prompt: str) -> AgentTask:
        """Create and track a new agent execution task."""
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        task = AgentTask(task_id=task_id, actor_id=actor_id, user_prompt=prompt)
        self._tasks[task_id] = task

        # Initial event
        self.emit_event(
            task_id,
            event_type="task.started",
            message="RollCall AI agent started processing your request.",
        )
        return task

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        return self._tasks.get(task_id)

    def update_status(self, task_id: str, new_state: TaskState, message: Optional[str] = None) -> Optional[AgentTask]:
        """Update task status and emit corresponding event."""
        task = self.get_task(task_id)
        if not task:
            return None
        task.state = new_state
        event_name = f"task.{new_state.value.lower()}"
        msg = message or f"Task status updated to {new_state.value}."
        self.emit_event(task_id, event_type=event_name, message=msg)
        return task

    def emit_event(
        self,
        task_id: str,
        event_type: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Optional[AgentEvent]:
        """Emit an event, append to task history, and notify active SSE listeners."""
        task = self.get_task(task_id)
        if not task:
            return None

        task.event_sequence += 1
        event = AgentEvent(
            event_id=f"{task_id}_{task.event_sequence}",
            task_id=task_id,
            event_type=event_type,
            message=message,
            data=data or {},
        )
        task.events.append(event)
        task.updated_at = event.timestamp

        # Broadcast to all connected SSE clients
        for q in list(task.subscribers):
            try:
                q.put_nowait(event)
            except Exception:
                pass

        return event

    async def subscribe_events(
        self,
        task_id: str,
        last_event_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Subscribe to a task's SSE event stream with replay support."""
        task = self.get_task(task_id)
        if not task:
            yield f"event: error\ndata: {json.dumps({'error': 'Task not found'})}\n\n"
            return

        # 1. Replay missed events if client reconnects with Last-Event-ID
        start_idx = 0
        if last_event_id:
            for idx, ev in enumerate(task.events):
                if ev.event_id == last_event_id:
                    start_idx = idx + 1
                    break

        for ev in task.events[start_idx:]:
            yield ev.to_sse()

        # If task already terminal, finish stream
        if task.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
            return

        # 2. Listen for live events
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        task.subscribers.append(queue)

        try:
            while True:
                # Send heartbeat every 15s to keep proxy alive
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield event.to_sse()
                    if event.event_type in ("task.completed", "task.failed", "task.cancelled"):
                        break
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            if queue in task.subscribers:
                task.subscribers.remove(queue)


# Global task manager singleton
task_manager = AgentTaskManager()
