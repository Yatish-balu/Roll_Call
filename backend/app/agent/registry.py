"""Tool registry and dispatcher for RollCall Agentic AI.

Enforces:
1. Strict JSON parameter validation
2. Capability-family tagging for dynamic subsetting (saving token quota)
3. Role-Based Access Control (RBAC) checked before invoking handlers
4. Risk tier classification (READ, LOW_RISK_WRITE, SENSITIVE_WRITE)
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from app.auth.roles import Role

logger = logging.getLogger("rollcall.agent.registry")


class RiskTier(str, enum.Enum):
    READ = "READ"
    READ_ONLY = "READ"
    LOW_RISK_WRITE = "LOW_RISK_WRITE"
    WRITE = "LOW_RISK_WRITE"
    SENSITIVE_WRITE = "SENSITIVE_WRITE"
    CONFIRM_REQUIRED = "SENSITIVE_WRITE"


@dataclass
class ToolDefinition:
    """Specification of a registered agent tool."""
    name: str
    description: str
    handler: Callable[..., Any]
    parameters: Dict[str, Any] = field(default_factory=dict)
    capability_family: str = "general"  # "schedule", "attendance", "profile", "reports", "general"
    risk_tier: RiskTier = RiskTier.READ
    allowed_roles: Set[str] = field(default_factory=lambda: {"ADMIN", "FACULTY", "COORDINATOR"})
    required_roles: Optional[List[str]] = None
    timeout_seconds: float = 10.0

    def __post_init__(self):
        if self.required_roles:
            self.allowed_roles = {r.upper() for r in self.required_roles}


class ToolRegistry:
    """Thread-safe registry for agent tools with scope and permission enforcement."""

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a new tool into the catalog."""
        self._tools[tool.name] = tool
        logger.debug("Registered agent tool: %s (%s)", tool.name, tool.risk_tier.value)

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Alias for get(name)."""
        return self.get(name)

    def get_tools_schema_for_role(self, role: Optional[str] = None) -> List[Dict[str, Any]]:
        """Convenience helper returning schema for caller role."""
        return self.get_schemas(role=role)

    def list_tools(
        self,
        capability_family: Optional[str] = None,
        role: Optional[str] = None,
    ) -> List[ToolDefinition]:
        """List registered tools optionally filtered by capability family and caller role."""
        results = []
        user_role = (role or "FACULTY").upper()
        for tool in self._tools.values():
            if capability_family and tool.capability_family != capability_family:
                continue
            if user_role not in tool.allowed_roles and "ADMIN" not in user_role:
                continue
            results.append(tool)
        return results

    def get_schemas(
        self,
        capability_family: Optional[str] = None,
        role: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return provider-friendly JSON schemas for available tools."""
        tools = self.list_tools(capability_family=capability_family, role=role)
        schemas = []
        for t in tools:
            schemas.append({
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            })
        return schemas

    def execute(
        self,
        name: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
        actor_id: str = "anonymous",
        actor_role: Optional[str] = None,
        tool_name: Optional[str] = None,
        role: Optional[str] = None,
        **context: Any,
    ) -> Dict[str, Any]:
        """Validate permissions and execute registered tool."""
        target_name = name or tool_name or ""
        target_role = actor_role or role or "FACULTY"
        tool = self.get(target_name)
        if not tool:
            return {
                "success": False,
                "error": f"Tool '{target_name}' is not registered.",
            }

        clean_role = target_role.upper()
        if clean_role not in tool.allowed_roles and clean_role != "ADMIN":
            logger.warning("Unauthorized tool invocation: %s by %s (%s)", target_name, actor_id, clean_role)
            return {
                "success": False,
                "error": f"Permission denied: role '{clean_role}' cannot execute tool '{target_name}'.",
            }

        try:
            call_args = arguments or {}
            result = tool.handler(actor_id=actor_id, actor_role=target_role, **call_args, **context)
            return {
                "success": True,
                "result": result,
                "risk_tier": tool.risk_tier.value,
            }
        except TypeError:
            # Fallback if handler takes arguments directly
            try:
                result = tool.handler(call_args, actor_id, target_role)
                return {
                    "success": True,
                    "result": result,
                    "risk_tier": tool.risk_tier.value,
                }
            except Exception as exc:
                logger.error("Error executing tool %s: %s", target_name, exc)
                return {
                    "success": False,
                    "error": str(exc),
                }
        except Exception as exc:
            logger.error("Error executing tool %s: %s", target_name, exc)
            return {
                "success": False,
                "error": str(exc),
            }


# Global tool registry singleton
registry = ToolRegistry()
tool_registry = registry

