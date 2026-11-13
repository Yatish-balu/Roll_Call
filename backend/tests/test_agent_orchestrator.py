"""Unit tests for Agent Orchestrator, Context Memory, and ReAct Execution Loop."""

import pytest
from app.agent.context import ContextManager, ConversationContext
from app.agent.orchestrator import AgentOrchestrator, OrchestratorResult
from app.agent.provider import MockProvider, ModelResponse, ToolCallRequest
from app.agent.registry import RiskTier, ToolDefinition, ToolRegistry
from app.agent.stream import AgentTaskManager, TaskState


def test_conversation_context_and_prompt_synthesis():
    ctx = ConversationContext(
        actor_id="faculty_cn",
        role="FACULTY",
        assigned_subjects=["CS101", "CS102"],
    )
    ctx.add_user_message("What is my schedule tomorrow?")
    ctx.add_assistant_message("Here is your schedule: CS101 at 9 AM.")

    messages = ctx.build_prompt_messages()
    assert len(messages) == 3
    assert messages[0]["role"] == "system"
    assert "faculty_cn" in messages[0]["content"]
    assert "CS101, CS102" in messages[0]["content"]
    assert messages[1]["content"] == "What is my schedule tomorrow?"
    assert messages[2]["content"] == "Here is your schedule: CS101 at 9 AM."


def test_orchestrator_direct_text_response():
    provider = MockProvider()
    provider.queue_response(ModelResponse(content="Your next class is CS101 at 10 AM."))

    registry = ToolRegistry()
    manager = AgentTaskManager()
    orchestrator = AgentOrchestrator(provider=provider, registry=registry, manager=manager)

    res = orchestrator.execute_prompt(
        actor_id="faculty_cn",
        role="FACULTY",
        prompt="Tell me my next class",
    )

    assert res.status == "COMPLETED"
    assert "CS101" in res.final_response
    assert res.steps_executed == 1

    task = manager.get_task(res.task_id)
    assert task is not None
    assert task.state == TaskState.COMPLETED
    event_types = [e.event_type for e in task.events]
    assert "task.started" in event_types
    assert "step.started" in event_types
    assert "task.completed" in event_types


def test_orchestrator_tool_calling_and_observation_loop():
    provider = MockProvider()
    # Step 1: LLM decides to call tool `lookup_room`
    provider.queue_response(ModelResponse(
        content=None,
        tool_calls=[ToolCallRequest(id="call_1", name="lookup_room", arguments={"room_id": "LH-101"})],
    ))
    # Step 2: LLM receives tool response and answers user
    provider.queue_response(ModelResponse(
        content="Room LH-101 is available with a capacity of 60.",
    ))

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="lookup_room",
        description="Lookup details for a classroom",
        risk_tier=RiskTier.READ_ONLY,
        required_roles=["FACULTY", "ADMIN"],
        handler=lambda args, actor, role: {"room": args["room_id"], "capacity": 60, "status": "vacant"},
    ))

    manager = AgentTaskManager()
    orchestrator = AgentOrchestrator(provider=provider, registry=registry, manager=manager)

    res = orchestrator.execute_prompt(
        actor_id="faculty_cn",
        role="FACULTY",
        prompt="Check room LH-101",
    )

    assert res.status == "COMPLETED"
    assert "Room LH-101 is available" in res.final_response
    assert res.steps_executed == 2

    task = manager.get_task(res.task_id)
    event_types = [e.event_type for e in task.events]
    assert "tool.started" in event_types
    assert "tool.completed" in event_types
    assert "task.completed" in event_types


def test_orchestrator_confirms_destructive_actions_via_draft():
    provider = MockProvider()
    provider.queue_response(ModelResponse(
        content=None,
        tool_calls=[ToolCallRequest(
            id="call_edit",
            name="delete_attendance_session",
            arguments={"session_id": "sess_999"},
        )],
    ))

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="delete_attendance_session",
        description="Permanently delete a class session",
        risk_tier=RiskTier.CONFIRM_REQUIRED,
        required_roles=["FACULTY", "ADMIN"],
        handler=lambda args, actor, role: {"status": "deleted"},
    ))

    manager = AgentTaskManager()
    orchestrator = AgentOrchestrator(provider=provider, registry=registry, manager=manager)

    res = orchestrator.execute_prompt(
        actor_id="faculty_cn",
        role="FACULTY",
        prompt="Delete session sess_999",
    )

    # Must NOT execute destructive tool immediately; must pause and create draft
    assert res.status == "WAITING_FOR_APPROVAL"
    assert res.draft_created is not None
    assert res.draft_created["action_type"] == "delete_attendance_session"
    assert res.draft_created["payload"] == {"session_id": "sess_999"}

    task = manager.get_task(res.task_id)
    assert task.state == TaskState.WAITING_FOR_APPROVAL
    event_types = [e.event_type for e in task.events]
    assert "approval.required" in event_types
