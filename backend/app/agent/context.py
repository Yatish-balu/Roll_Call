"""Conversation context, memory, and prompt synthesis for RollCall AI Agent.

Manages:
1. Multi-turn conversation message history per actor/task.
2. System prompt construction (Antigravity-style instructions, identity, date/time awareness, role constraints).
3. Sliding window token management / transcript compaction.
4. Draft memory for pending or uncommitted actions (e.g. attendance edits awaiting approval).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class ActionDraft:
    """Represents a pending action drafted by the agent awaiting user confirmation."""
    draft_id: str
    action_type: str  # e.g., "create_session", "update_attendance"
    payload: Dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "PENDING"  # PENDING, APPROVED, REJECTED, EXECUTED


class ConversationContext:
    """Maintains active session memory, user state, and message transcript."""

    def __init__(
        self,
        actor_id: str,
        role: str,
        assigned_subjects: Optional[List[str]] = None,
        max_history_turns: int = 20,
    ):
        self.actor_id = actor_id
        self.role = role.upper()
        self.assigned_subjects = assigned_subjects or []
        self.max_history_turns = max_history_turns
        self.messages: List[Dict[str, Any]] = []
        self.drafts: Dict[str, ActionDraft] = {}
        self.scratchpad: Dict[str, Any] = {}

    def add_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})
        self._truncate_if_needed()

    def add_assistant_message(
        self,
        content: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        msg: Dict[str, Any] = {"role": "assistant"}
        if content is not None:
            msg["content"] = content
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)
        self._truncate_if_needed()

    def add_tool_response(self, tool_call_id: str, tool_name: str, result: Any) -> None:
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": str(result),
        })
        self._truncate_if_needed()

    def create_draft(self, draft_id: str, action_type: str, payload: Dict[str, Any]) -> ActionDraft:
        draft = ActionDraft(draft_id=draft_id, action_type=action_type, payload=payload)
        self.drafts[draft_id] = draft
        return draft

    def get_draft(self, draft_id: str) -> Optional[ActionDraft]:
        return self.drafts.get(draft_id)

    def _truncate_if_needed(self) -> None:
        """Sliding window compaction: retain last N turns while keeping system context intact."""
        if len(self.messages) > self.max_history_turns * 2:
            self.messages = self.messages[-(self.max_history_turns * 2):]

    def build_prompt_messages(self) -> List[Dict[str, Any]]:
        """Synthesize the complete message list including authoritative system instructions."""
        now = datetime.now(timezone.utc)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S UTC (Day: %A)")

        system_instruction = (
            f"You are Antigravity RollCall AI, an autonomous agentic academic assistant.\n"
            f"CURRENT TIME: {now_str}\n"
            f"ACTOR IDENTITY:\n"
            f"- User ID: {self.actor_id}\n"
            f"- Role: {self.role}\n"
            f"- Assigned Subjects: {', '.join(self.assigned_subjects) if self.assigned_subjects else 'None'}\n\n"
            f"OPERATIONAL SCOPE & STRICT DOMAIN BOUNDARY:\n"
            f"You are strictly and exclusively an academic attendance, class session, timetable, and classroom management assistant for the institutional RollCall AI system.\n"
            f"ALLOWED DOMAIN OPERATIONS:\n"
            f"1. Student attendance records, attendance summaries, statistics, absentee tracking, and attendance percentages.\n"
            f"2. Academic schedules, timetables, and class session management (finding, creating, modifying sessions).\n"
            f"3. Pending and unreviewed attendance sessions awaiting review or confirmation.\n"
            f"4. Classroom vacancy and room availability lookups.\n"
            f"5. Attendance roster sheet extraction, OCR verification, and attendance modification proposals.\n"
            f"6. User/faculty profile management (e.g. updating display name) within RollCall AI.\n\n"
            f"STRICT OUT-OF-DOMAIN REFUSAL POLICY (ZERO TOLERANCE):\n"
            f"- You are STRICTLY FORBIDDEN from answering any questions outside of the RollCall AI institutional scope.\n"
            f"- Out-of-domain topics include: general science, physics, quantum computing, general programming/coding questions unrelated to RollCall, recipes, cooking, news, politics, history, geography, sports, entertainment, movies, general trivia, personal advice, or creative writing.\n"
            f"- If the user asks ANY question or gives ANY request outside RollCall AI's domain (for example, 'explain what is quantum computing', 'what is the capital of France', 'recipe for pizza', 'write a poem', 'explain relativity'), you MUST IMMEDIATELY and POLITELY REFUSE.\n"
            f"- You must NEVER provide any factual explanation or summary of the out-of-domain topic, even briefly.\n"
            f"- When refusing an out-of-domain query, respond strictly with:\n"
            f"  'I am RollCall AI, specialized exclusively for institutional attendance, classroom scheduling, and student roster management. I cannot assist with topics outside of attendance and class operations. How can I help you with your attendance or schedule today?'\n\n"
            f"OPERATIONAL PRINCIPLES:\n"
            f"1. Goal-Driven & Autonomous: Proactively resolve in-domain user requests using available tools.\n"
            f"2. Strict RBAC Enforcement: Never attempt actions unauthorized for {self.role}. If {self.role} == 'FACULTY', you can only create/modify sessions for their assigned subjects.\n"
            f"3. Confirmation for Destructive Actions: Modifying attendance records or bulk deleting sessions requires explicit user confirmation via a draft.\n"
            f"4. Truthfulness: Never invent data or numerical figures; ground all facts in database tool outputs.\n"
            f"5. Conciseness: Be precise, structured, and helpful. Format tables and lists cleanly in markdown.\n"
        )

        return [{"role": "system", "content": system_instruction}] + copy.deepcopy(self.messages)


class ContextManager:
    """In-memory pool of active conversation contexts indexed by actor_id."""

    def __init__(self):
        self._contexts: Dict[str, ConversationContext] = {}

    def get_or_create(
        self,
        actor_id: str,
        role: str,
        assigned_subjects: Optional[List[str]] = None,
    ) -> ConversationContext:
        if actor_id not in self._contexts:
            self._contexts[actor_id] = ConversationContext(
                actor_id=actor_id,
                role=role,
                assigned_subjects=assigned_subjects,
            )
        return self._contexts[actor_id]

    def reset_context(self, actor_id: str) -> None:
        if actor_id in self._contexts:
            del self._contexts[actor_id]


# Global context manager singleton
context_manager = ContextManager()

