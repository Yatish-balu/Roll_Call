"""Unit tests for Agentic AI Phase 0 Foundation (Provider, Registry, SSE Streaming)."""

import pytest
from fastapi.testclient import TestClient

from app.agent.provider import MockProvider, ModelResponse, ToolCallRequest
from app.agent.registry import ToolDefinition, ToolRegistry, RiskTier
from app.agent.stream import task_manager, TaskState
from app.auth import create_access_token
from app.main import app


def _auth_header(user_id: str, role: str) -> dict:
    token = create_access_token(
        {
            "sub": user_id,
            "email": f"{user_id}@rollcall.internal",
            "role": role,
            "type": "access",
        }
    )
    return {"Authorization": f"Bearer {token}"}


def test_mock_provider_generation():
    provider = MockProvider()
    resp = provider.generate([{"role": "user", "content": "Show my classes"}])
    assert "Mock response for: Show my classes" in (resp.content or "")

    # Test queued response
    provider.queue_response(ModelResponse(
        content="I will check timetable.",
        tool_calls=[ToolCallRequest(name="get_my_timetable", arguments={"date": "2026-11-14"})],
    ))
    resp2 = provider.generate([{"role": "user", "content": "Next turn"}])
    assert len(resp2.tool_calls) == 1
    assert resp2.tool_calls[0].name == "get_my_timetable"


def test_tool_registry_rbac_and_execution():
    registry = ToolRegistry()

    def sample_tool_handler(actor_id: str, actor_role: str, date: str, **ctx):
        return {"status": "ok", "date": date, "queried_by": actor_id}

    tool = ToolDefinition(
        name="get_schedule",
        description="Lookup schedule for a given date",
        parameters={"type": "object", "properties": {"date": {"type": "string"}}},
        handler=sample_tool_handler,
        capability_family="schedule",
        risk_tier=RiskTier.READ,
        allowed_roles={"FACULTY", "ADMIN"},
    )
    registry.register(tool)

    # 1. Successful execution by FACULTY
    res = registry.execute("get_schedule", {"date": "2026-11-14"}, actor_id="faculty_cn", actor_role="FACULTY")
    assert res["success"] is True
    assert res["result"]["date"] == "2026-11-14"

    # 2. Denied execution by unauthorized role
    res_denied = registry.execute("get_schedule", {"date": "2026-11-14"}, actor_id="student_1", actor_role="STUDENT")
    assert res_denied["success"] is False
    assert "Permission denied" in res_denied["error"]

    # 3. Dynamic subsetting
    schemas = registry.get_schemas(capability_family="schedule", role="FACULTY")
    assert len(schemas) == 1
    assert schemas[0]["name"] == "get_schedule"

    empty_schemas = registry.get_schemas(capability_family="attendance", role="FACULTY")
    assert len(empty_schemas) == 0


def test_sse_streaming_task_endpoints():
    from app.auth.dependencies import get_current_user
    from app.schemas.auth import AuthenticatedUser
    from app.auth.roles import Role
    from app.db.connection import get_sync_session_factory
    from app.db.models import User

    factory = get_sync_session_factory()
    with factory() as session:
        if session.get(User, "faculty_cn") is None:
            session.add(
                User(
                    user_id="faculty_cn",
                    name="Prof. Computer Networks",
                    email="faculty_cn@rollcall.internal",
                    role="FACULTY",
                    is_active=1,
                    created_at="2026-11-13T10:00:00Z",
                )
            )
            session.commit()

    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id="faculty_cn",
        role=Role.FACULTY,
        email="faculty_cn@rollcall.internal",
    )
    try:
        client = TestClient(app)
        headers = _auth_header("faculty_cn", "FACULTY")

        # 1. Create task
        res = client.post("/api/v1/agent/tasks", json={"prompt": "Create session for tomorrow"}, headers=headers)
        assert res.status_code == 201, res.text
        data = res.json()
        task_id = data["task_id"]
        assert task_id.startswith("task_")

        # 2. Get task status
        status_res = client.get(f"/api/v1/agent/tasks/{task_id}", headers=headers)
        assert status_res.status_code == 200
        st_data = status_res.json()
        assert st_data["actor_id"] == "faculty_cn"
        assert st_data["status"] in ("CREATED", "PLANNING", "RUNNING", "COMPLETED")
        assert st_data["event_count"] >= 1

        # 3. Stream event replay test (mark task completed so SSE generator terminates)
        task_manager.update_status(task_id, TaskState.COMPLETED)
        stream_res = client.get(f"/api/v1/agent/tasks/{task_id}/events", headers=headers)
        assert stream_res.status_code == 200
        assert "text/event-stream" in stream_res.headers["content-type"]
        assert "event: task.started" in stream_res.text
        assert "event: task.completed" in stream_res.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)
