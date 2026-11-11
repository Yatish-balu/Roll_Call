"""Per-tool authorization policy for the AI agent.

Route-level RBAC decides *whether* a caller may use an agent endpoint. This
module adds a second, independent gate at the tool boundary: every tool has a
minimum role, and the registry denies anything not explicitly mapped. A new
route that forgets a role check therefore cannot silently expose a write-capable
tool.

The policy is enforced with the caller's database-verified role, never with a
model claim or a token-supplied string.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Optional

from app.schemas.auth import Role

# Higher rank inherits the lower one's tools.
_ROLE_RANK: Dict[Role, int] = {
    Role.VIEWER: 10,
    Role.FACULTY: 20,
    Role.ADMIN: 30,
}

# Deny-by-default: a tool not listed here is not callable through an agent that
# has an authenticated role attached.
TOOL_MINIMUM_ROLE: Dict[str, Role] = {
    # Read-only, scope-restricted queries and summaries: every signed-in user.
    "query_tool": Role.VIEWER,
    "summary_tool": Role.VIEWER,
    # File ingestion and validation mutate the review pipeline: faculty only.
    "read_csv_tool": Role.FACULTY,
    "read_photo_tool": Role.FACULTY,
    "validate_tool": Role.FACULTY,
    # Exports write data out of the system: faculty and above.
    "export_tool": Role.FACULTY,
}


class ToolAccessDenied(PermissionError):
    """Raised when a role may not execute a tool."""

    def __init__(self, tool_name: str, role: Role, required: Optional[Role]) -> None:
        self.tool_name = tool_name
        self.role = role
        self.required = required
        if required is None:
            message = f"Tool '{tool_name}' is not registered in the agent policy."
        else:
            message = (
                f"Tool '{tool_name}' requires role {required.value}; "
                f"the caller has {role.value}."
            )
        super().__init__(message)


def allowed_tools(role: Optional[Role]) -> FrozenSet[str]:
    """Return the tool names callable by ``role`` (``None`` means unrestricted)."""

    if role is None:
        return frozenset(TOOL_MINIMUM_ROLE)
    rank = _ROLE_RANK.get(role)
    if rank is None:
        return frozenset()
    return frozenset(
        name for name, required in TOOL_MINIMUM_ROLE.items() if rank >= _ROLE_RANK[required]
    )


def require_tool_access(tool_name: str, role: Optional[Role]) -> None:
    """Raise :class:`ToolAccessDenied` unless ``role`` may run ``tool_name``.

    ``role=None`` means the caller is an internal/local pipeline (no HTTP
    identity attached); the route layer is responsible for that case.
    """

    if role is None:
        return

    required = TOOL_MINIMUM_ROLE.get(tool_name)
    rank = _ROLE_RANK.get(role)
    if required is None or rank is None or rank < _ROLE_RANK[required]:
        raise ToolAccessDenied(tool_name, role, required)
