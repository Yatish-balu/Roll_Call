"""Server-side authorization policy for AI tools.

The backend is the authorization authority for every AI tool call. The model
may *select* a tool, but it can never widen the caller's permissions: the
registry consults this policy before a handler runs, using the role that came
from the verified authentication context.

This is defense in depth. Route-level dependencies (``require_roles``) remain
the primary control; this policy ensures a future/alternate call path cannot
skip it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Final, FrozenSet, Optional, Union

from app.auth.roles import role_satisfies
from app.schemas.auth import Role


class ToolAuthorizationError(PermissionError):
    """Raised when an actor attempts to execute a tool above their role."""


ToolAccessDenied = ToolAuthorizationError


class _TrustedInternalExecution:
    """Opaque capability for explicitly trusted, non-user initiated jobs."""


TRUSTED_INTERNAL: Final = _TrustedInternalExecution()


@dataclass(frozen=True)
class ToolPolicy:
    """Minimum role required to execute one registered AI tool."""

    tool_name: str
    required_role: Role
    reason: str


#: Minimum role per AI tool. ADMIN inherits FACULTY, FACULTY inherits VIEWER.
TOOL_POLICIES: Dict[str, ToolPolicy] = {
    "read_csv_tool": ToolPolicy(
        "read_csv_tool", Role.FACULTY, "parses uploaded attendance data"
    ),
    "read_photo_tool": ToolPolicy(
        "read_photo_tool", Role.FACULTY, "runs OCR over uploaded attendance images"
    ),
    "validate_tool": ToolPolicy(
        "validate_tool", Role.FACULTY, "processes attendance records"
    ),
    "summary_tool": ToolPolicy(
        "summary_tool", Role.FACULTY, "aggregates attendance into reports"
    ),
    "export_tool": ToolPolicy(
        "export_tool", Role.FACULTY, "writes report files"
    ),
    "query_tool": ToolPolicy(
        "query_tool", Role.VIEWER, "read-only attendance queries"
    ),
}

TOOL_MINIMUM_ROLE: Dict[str, Role] = {
    name: policy.required_role for name, policy in TOOL_POLICIES.items()
}


def required_role_for_tool(tool_name: str) -> Optional[Role]:
    """Return the minimum role for *tool_name* (``None`` for unknown tools)."""
    policy = TOOL_POLICIES.get(tool_name)
    return policy.required_role if policy else None


def authorize_tool(tool_name: str, actor_role: Union[Role, str, _TrustedInternalExecution, None]) -> None:
    """Raise :class:`ToolAuthorizationError` when *actor_role* may not run *tool_name*.

    Unknown tools are left to the registry's "unknown tool" handling so the
    caller gets a consistent error. Missing or invalid roles are treated as
    VIEWER. Trusted internal jobs must pass the opaque sentinel explicitly.
    """
    policy = TOOL_POLICIES.get(tool_name)
    if policy is None:
        return

    if actor_role is TRUSTED_INTERNAL:
        return

    if isinstance(actor_role, Role):
        role = actor_role
    elif actor_role is None:
        role = Role.VIEWER
    else:
        try:
            role = Role(str(actor_role).strip().upper())
        except ValueError:
            role = Role.VIEWER

    if not role_satisfies(role, policy.required_role):
        raise ToolAuthorizationError(
            f"Forbidden: role '{role.value}' may not execute AI tool "
            f"'{tool_name}' (requires '{policy.required_role.value}')."
        )


def require_tool_access(tool_name: str, role: Optional[Role]) -> None:
    """Compatibility alias for authorize_tool."""
    authorize_tool(tool_name, role)


def allowed_tools(role: Optional[Role]) -> FrozenSet[str]:
    """Return the tool names callable by ``role`` (``None`` means unrestricted)."""
    if role is None:
        return frozenset(TOOL_MINIMUM_ROLE)
    return frozenset(
        name for name, min_role in TOOL_MINIMUM_ROLE.items()
        if role_satisfies(role, min_role)
    )


def tool_permission_matrix() -> Dict[str, str]:
    """Role matrix for documentation/status endpoints (no secrets)."""
    return {name: policy.required_role.value for name, policy in TOOL_POLICIES.items()}
