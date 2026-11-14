"""Unit tests for RollCall AI strict domain boundaries and out-of-domain refusal policy."""

import pytest
from app.agent.context import ConversationContext
from app.agent.orchestrator import AgentOrchestrator
from app.agent.provider import MockProvider, ModelResponse
from app.agent.registry import ToolRegistry
from app.agent.stream import AgentTaskManager


def test_system_prompt_enforces_domain_restriction():
    """Verify system instruction contains strict domain boundaries and explicit out-of-domain refusals."""
    ctx = ConversationContext(
        actor_id="faculty_cn",
        role="FACULTY",
        assigned_subjects=["CN"],
    )
    ctx.add_user_message("explain what is quantum computing")

    messages = ctx.build_prompt_messages()
    system_msg = messages[0]["content"]

    assert "OPERATIONAL SCOPE & STRICT DOMAIN BOUNDARY" in system_msg
    assert "STRICT OUT-OF-DOMAIN REFUSAL POLICY" in system_msg
    assert "quantum computing" in system_msg.lower()
    assert "exclusively for institutional attendance, classroom scheduling, and student roster management" in system_msg


def test_orchestrator_refusal_response_handling():
    """Verify orchestrator successfully delivers standard refusal when model detects out-of-scope query."""
    expected_refusal = (
        "I am RollCall AI, specialized exclusively for institutional attendance, classroom scheduling, "
        "and student roster management. I cannot assist with topics outside of attendance and class operations. "
        "How can I help you with your attendance or schedule today?"
    )

    provider = MockProvider()
    provider.queue_response(ModelResponse(content=expected_refusal))

    registry = ToolRegistry()
    manager = AgentTaskManager()
    orchestrator = AgentOrchestrator(provider=provider, registry=registry, manager=manager)

    res = orchestrator.execute_prompt(
        actor_id="faculty_cn",
        role="FACULTY",
        prompt="explain what is quantum computing",
    )

    assert res.status == "COMPLETED"
    assert res.final_response == expected_refusal
    assert res.steps_executed == 1

