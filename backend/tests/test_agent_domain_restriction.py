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


def test_attendance_agent_strict_domain_restriction():
    """Verify AttendanceAgent strictly refuses out-of-domain queries like DDCO explanations."""
    from app.agent.legacy_agent import AttendanceAgent, OUT_OF_DOMAIN_REFUSAL
    from app.security.ai_policy import TRUSTED_INTERNAL

    agent = AttendanceAgent(
        actor_role=TRUSTED_INTERNAL,
        actor_name="Nida Afreen Rizvi",
        actor_id="faculty_rm",
        assigned_subjects=["22RMK56", "RM"],
    )

    out_of_domain_queries = [
        "xplain me what is ddco and basics",
        "explain what is quantum computing",
        "what is ddco",
        "ddco basics",
        "how to write binary search in python",
        "recipe for pasta",
        "write a poem about trees",
        "who is the prime minister of india",
        "tell me a joke",
        "explain operating systems",
    ]

    for q in out_of_domain_queries:
        resp = agent.process_request(user_input=q, request_id=f"test_{q[:10]}")
        assert resp.success is True
        assert resp.message == OUT_OF_DOMAIN_REFUSAL, f"Expected refusal for '{q}', got '{resp.message}'"

    # Verify in-domain queries are NOT blocked by domain restriction
    in_domain_queries = [
        "show my schedule for today",
        "what is your task",
        "who are you",
        "how are you",
        "find vacant classrooms",
        "list defaulters (<75%)",
    ]
    for q in in_domain_queries:
        resp = agent.process_request(user_input=q, request_id=f"test_{q[:10]}")
        assert resp.message != OUT_OF_DOMAIN_REFUSAL, f"In-domain query '{q}' was wrongly refused"


