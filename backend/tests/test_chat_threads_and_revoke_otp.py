"""Tests for user-scoped chat persistence/isolation and revoke-all OTP security."""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import models
from app.db.connection import get_sync_session_factory
from app.auth.jwt import create_access_token


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)



def _auth_headers(user_id: str, role: str = "FACULTY") -> dict:
    token = create_access_token({"sub": user_id, "role": role})
    return {"Authorization": f"Bearer {token}"}



@pytest.mark.no_auth_override
def test_chat_threads_crud_and_isolation(client):
    """Test creating, listing, syncing, and strict user isolation for chat threads."""
    headers_a = _auth_headers("faculty_cn", "FACULTY")
    headers_b = _auth_headers("faculty_ds", "FACULTY")

    # 1. Create a thread for user A
    res_a = client.post(
        "/api/v1/agent/threads",
        json={"title": "Computer Networks Discussion"},
        headers=headers_a,
    )
    assert res_a.status_code == 200, res_a.text
    thread_a = res_a.json()
    thread_a_id = thread_a["thread_id"]
    assert thread_a["title"] == "Computer Networks Discussion"
    assert thread_a["user_id"] == "faculty_cn"

    # 2. User B cannot see User A's thread in list
    res_b_list = client.get("/api/v1/agent/threads", headers=headers_b)
    assert res_b_list.status_code == 200
    b_threads = res_b_list.json()
    assert not any(t["thread_id"] == thread_a_id for t in b_threads)

    # 3. User B cannot access User A's thread by ID
    res_b_get = client.get(f"/api/v1/agent/threads/{thread_a_id}", headers=headers_b)
    assert res_b_get.status_code == 404

    # 4. Sync messages to User A's thread
    sync_payload = {
        "title": "Computer Networks Discussion",
        "messages": [
            {
                "id": "msg-1",
                "sender": "user",
                "text": "What is the attendance for CN today?",
                "timestamp": "10:00 AM",
            },
            {
                "id": "msg-2",
                "sender": "assistant",
                "text": "CN attendance is 88%.",
                "timestamp": "10:01 AM",
            },
        ],
    }
    sync_res = client.post(
        f"/api/v1/agent/threads/{thread_a_id}/sync",
        json=sync_payload,
        headers=headers_a,
    )
    assert sync_res.status_code == 200, sync_res.text
    detail = sync_res.json()
    assert len(detail["messages"]) == 2
    assert detail["messages"][0]["text"] == "What is the attendance for CN today?"

    # 5. List threads for User A shows updated message count and last message
    list_a = client.get("/api/v1/agent/threads", headers=headers_a).json()
    target = next(t for t in list_a if t["thread_id"] == thread_a_id)
    assert target["message_count"] == 2
    assert "CN attendance is 88%" in target["last_message"]

    # 6. Delete thread
    del_res = client.delete(f"/api/v1/agent/threads/{thread_a_id}", headers=headers_a)
    assert del_res.status_code == 200
    after_del = client.get(f"/api/v1/agent/threads/{thread_a_id}", headers=headers_a)
    assert after_del.status_code == 404


def test_revoke_all_sessions_otp_flow(client):
    """Test OTP request and verification for revoking all devices."""
    headers = _auth_headers("faculty_cn", "FACULTY")

    # 1. Request OTP
    req_res = client.post("/api/v1/auth/sessions/revoke-all/request-otp", headers=headers)
    assert req_res.status_code == 200, req_res.text
    req_data = req_res.json()
    assert "message" in req_data
    assert "email" in req_data
    dev_otp = req_data.get("dev_otp")
    assert dev_otp is not None
    assert len(dev_otp) == 6

    # 2. Try revoking with invalid OTP
    bad_res = client.post(
        "/api/v1/auth/sessions/revoke-all",
        json={"otp": "000000"},
        headers=headers,
    )
    assert bad_res.status_code == 400
    assert "Invalid verification code" in bad_res.json()["detail"]

    # 3. Revoke with valid OTP
    good_res = client.post(
        "/api/v1/auth/sessions/revoke-all",
        json={"otp": dev_otp},
        headers=headers,
    )
    assert good_res.status_code == 200, good_res.text
    assert "All other sessions have been revoked" in good_res.json()["message"]
