"""Agentic AI package for RollCall AI.

Provides backward-compatible exports for AttendanceAgent as well as the new
Phase 0 modular components (LLMProvider, ToolRegistry, AgentTaskManager).
"""

from app.agent.legacy_agent import *  # noqa: F401, F403
from app.agent.provider import LLMProvider, GeminiProvider, MockProvider, ModelResponse, ToolCallRequest
from app.agent.registry import ToolDefinition, ToolRegistry, RiskTier, registry
from app.agent.stream import AgentTaskManager, TaskState, AgentEvent, task_manager

__all__ = [  # noqa: F405
    "AttendanceAgent",
    "CONFIDENCE_CONFIRMATION_THRESHOLD",
    "LLMProvider",
    "GeminiProvider",
    "MockProvider",
    "ModelResponse",
    "ToolCallRequest",
    "ToolDefinition",
    "ToolRegistry",
    "RiskTier",
    "registry",
    "AgentTaskManager",
    "TaskState",
    "AgentEvent",
    "task_manager",
]
