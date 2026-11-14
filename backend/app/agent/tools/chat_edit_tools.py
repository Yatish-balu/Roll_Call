"""N7: Chat-driven attendance edit tool (proposal only).

The LLM never writes attendance directly. This tool validates the request,
checks authorization and the 24-hour lock, and stores a single-use pending
edit bound to the caller. The actual write happens only after the user
confirms through ``POST /api/v1/agent/chat/confirm``.
"""

from __future__ import annotations

from app.agent.registry import RiskTier, ToolDefinition
from tools.update_attendance_tool import update_attendance_tool

CHAT_ATTENDANCE_EDIT_TOOL = ToolDefinition(
    name="update_attendance",
    description=(
        "Propose an attendance status change from a chat request. Never writes "
        "attendance: validates authorization and the 24-hour edit lock, then "
        "returns a confirmation request that the user must approve."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The user's natural-language edit request.",
            },
            "session_id": {"type": "string", "description": "Session ID"},
            "usn": {"type": "string", "description": "Student USN"},
            "new_status": {
                "type": "string",
                "enum": ["PRESENT", "ABSENT"],
                "description": "Requested attendance status",
            },
            "reason": {
                "type": "string",
                "description": "Reason for the edit (required for admin overrides)",
            },
        },
        "required": ["query"],
    },
    capability_family="attendance",
    risk_tier=RiskTier.SENSITIVE_WRITE,
    allowed_roles={"FACULTY", "ADMIN"},
    handler=update_attendance_tool,
)

__all__ = ["CHAT_ATTENDANCE_EDIT_TOOL"]
