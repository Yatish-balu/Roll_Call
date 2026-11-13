"""Agent audit trail and threat-radar logging for RollCall AI Agent.

Provides :class:`AgentAuditLogger`, which records three kinds of events from the
agentic loop:

1. Tool executions (``AGENT_TOOL_CALL``)
2. Blocked security threats (``SECURITY_THREAT_BLOCKED``) — raised when
   :class:`PromptInjectionGuard` or :class:`ScopeGuard` rejects an input/action.
3. User approval / rejection events for drafted destructive actions
   (``AGENT_APPROVAL_EVENT``).

When a SQLAlchemy :class:`~sqlalchemy.orm.Session` is supplied the event is also
persisted to the ``audit_log`` table. A structured audit-log dict is always
returned, so callers can stream it to the frontend even without a database.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db.models import AuditLog


class AgentAuditLogger:
    """Structured audit logger for the agentic loop."""

    ACTION_TOOL_CALL = "AGENT_TOOL_CALL"
    ACTION_THREAT_BLOCKED = "SECURITY_THREAT_BLOCKED"
    ACTION_APPROVAL_EVENT = "AGENT_APPROVAL_EVENT"

    RISK_TIER_HIGH = "HIGH"

    def _now_iso(self) -> str:
        """Current UTC timestamp as an ISO-8601 string."""
        return datetime.now(timezone.utc).isoformat()

    def _persist(self, db: Optional[Session], entry: Dict[str, Any]) -> None:
        """Write the entry to the ``audit_log`` table when a session is given."""
        if db is None:
            return
        db.add(
            AuditLog(
                actor_id=entry["actor_id"],
                actor_role=entry.get("actor_role"),
                action=entry["action"],
                session_id=entry.get("session_id"),
                usn=entry.get("usn"),
                entity_type=entry["entity_type"],
                entity_id=entry["entity_id"],
                old_value=entry.get("old_value"),
                new_value=entry.get("new_value"),
                reason=entry.get("reason"),
                timestamp=entry["timestamp"],
            )
        )
        db.commit()

    def log_tool_execution(
        self,
        task_id: str,
        actor_id: str,
        role: str,
        tool_name: str,
        arguments: dict,
        success: bool,
        duration_seconds: float,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Log an executed agent tool call.

        Persists ``action="AGENT_TOOL_CALL`` with the tool name, arguments,
        success flag and duration when ``db`` is provided. Always returns the
        audit-log dict.
        """
        entry: Dict[str, Any] = {
            "action": self.ACTION_TOOL_CALL,
            "actor_id": actor_id,
            "actor_role": role,
            "session_id": task_id,
            "usn": None,
            "entity_type": "agent_tool",
            "entity_id": tool_name,
            "old_value": None,
            "new_value": json.dumps(
                {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "success": success,
                    "duration_seconds": duration_seconds,
                },
                default=str,
            ),
            "reason": None,
            "timestamp": self._now_iso(),
        }
        self._persist(db, entry)
        return entry

    def log_security_threat(
        self,
        task_id: str,
        actor_id: str,
        role: str,
        threat_type: str,
        reason: str,
        raw_payload: str,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Log a blocked prompt-injection or scope-violation event.

        Triggered when :class:`PromptInjectionGuard` or
        :class:`ScopeGuard` rejects an input/action. Records
        ``action="SECURITY_THREAT_BLOCKED`` with ``risk_tier="HIGH"`` and the
        blocking reason when ``db`` is provided. Always returns the audit-log
        dict.
        """
        entry: Dict[str, Any] = {
            "action": self.ACTION_THREAT_BLOCKED,
            "actor_id": actor_id,
            "actor_role": role,
            "session_id": task_id,
            "usn": None,
            "entity_type": "security_threat",
            "entity_id": threat_type,
            "old_value": None,
            "new_value": json.dumps(
                {
                    "threat_type": threat_type,
                    "risk_tier": self.RISK_TIER_HIGH,
                    "raw_payload": raw_payload,
                },
                default=str,
            ),
            "reason": reason,
            "timestamp": self._now_iso(),
        }
        self._persist(db, entry)
        return entry

    def log_approval_event(
        self,
        task_id: str,
        draft_id: str,
        actor_id: str,
        action_type: str,
        approved: bool,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Log a user confirmation or rejection of a drafted destructive action.

        Records ``action="AGENT_APPROVAL_EVENT`` with the draft id, action type
        and approve/reject outcome when ``db`` is provided. Always returns the
        audit-log dict.
        """
        verb = "Approved" if approved else "Rejected"
        entry: Dict[str, Any] = {
            "action": self.ACTION_APPROVAL_EVENT,
            "actor_id": actor_id,
            "actor_role": None,
            "session_id": task_id,
            "usn": None,
            "entity_type": "approval",
            "entity_id": draft_id,
            "old_value": None,
            "new_value": json.dumps(
                {
                    "action_type": action_type,
                    "approved": approved,
                },
                default=str,
            ),
            "reason": f"{verb} draft {draft_id} for {action_type}",
            "timestamp": self._now_iso(),
        }
        self._persist(db, entry)
        return entry
