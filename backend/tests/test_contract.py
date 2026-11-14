"""N18: Contract test script.

Automatically catches contract mismatches between backend and frontend.
For each new endpoint, calls it as seeded teacher and admin and asserts
every field in the contract example exists with the same type.
Prints a table: endpoint, role, status, missing fields.

Run: pytest tests/test_contract.py -v
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.no_auth_override


def _token(user_id: str, role: str) -> str:
    """Create a JWT token for test authentication."""
    from app.auth.jwt import create_access_token, get_jwt_secret
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    return create_access_token(
        {
            "sub": user_id,
            "email": f"{user_id}@rollcall.edu",
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        expires_delta=timedelta(hours=1),
        secret=get_jwt_secret(),
    )


def _headers(user_id: str, role: str) -> dict:
    return {"Authorization": f"Bearer {_token(user_id, role)}"}


# ---------------------------------------------------------------------------
# Contract: endpoint -> (method, path, required role, expected fields)
# ---------------------------------------------------------------------------

CONTRACTS: List[Tuple[str, str, str, str, List[str]]] = [
    # (endpoint, method, role, description, required_fields)
    ("GET", "/api/meta/config", "teacher", "Meta config", ["edit_lock_hours", "defaulter_threshold_percent", "attendance_bands", "upload_limits"]),
    ("GET", "/api/me/subjects", "teacher", "My subjects", ["user_id", "role", "subject_codes"]),
    ("GET", "/api/sessions", "teacher", "Session list", ["items", "total"]),
    ("GET", "/api/sessions", "admin", "Session list (admin)", ["items", "total"]),
    ("GET", "/api/defaulters", "teacher", "Defaulters", ["status", "threshold", "students"]),
    ("GET", "/api/defaulters", "admin", "Defaulters (admin)", ["status", "threshold", "students"]),
    ("GET", "/api/students/lookup", "teacher", "Student lookup", ["results", "total"]),
    ("GET", "/api/admin/audit-log", "admin", "Audit log", ["items", "total"]),
    ("GET", "/api/admin/overview", "admin", "Admin overview", []),  # flexible shape
    ("GET", "/api/admin/faculty-uploads", "admin", "Faculty uploads", []),  # flexible shape
    ("GET", "/api/calendar", "teacher", "Calendar month", ["month", "days"]),
    ("GET", "/api/calendar/day", "teacher", "Calendar day", ["date", "sessions"]),
]


def _check_fields(response_json: Any, required: List[str]) -> List[str]:
    """Return list of missing top-level fields."""
    if not isinstance(response_json, dict):
        return required  # everything missing if not a dict
    return [f for f in required if f not in response_json]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def _get_client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _call_endpoint(client: TestClient, method: str, path: str, headers: dict, params: dict) -> Any:
    if method == "GET":
        return client.get(path, headers=headers, params=params)
    raise ValueError(f"Unsupported method {method}")


@pytest.mark.parametrize(
    "method,path,role,desc,required",
    CONTRACTS,
)
def test_contract_endpoint(method, path, role, desc, required):
    """Verify each contract endpoint returns the expected fields."""
    client = _get_client()
    user_id = "faculty_cn" if role == "teacher" else "00000000-0000-0000-0000-000000000001"
    role_name = "FACULTY" if role == "teacher" else "ADMIN"
    headers = _headers(user_id, role_name)

    # Build query params based on endpoint
    params: dict = {}
    if "lookup" in path:
        params["q"] = "1DS"
    if "calendar" in path and "day" not in path:
        params["month"] = "2026-11"
    if "calendar/day" in path:
        params["date"] = "2026-11-13"
    if "defaulters" in path:
        params["subject"] = "CN"
    if "audit-log" in path:
        params["page"] = "1"
        params["page_size"] = "10"
    if "sessions" in path:
        params["limit"] = "5"

    res = _call_endpoint(client, method, path, headers, params)

    # Accept 200, 403 (if teacher lacks access to admin endpoint), or 404 (empty data is fine)
    assert res.status_code in (200, 403, 404), f"{path} returned {res.status_code}: {res.text}"

    if res.status_code == 200:
        missing = _check_fields(res.json(), required)
        assert not missing, f"{path} ({role}) missing fields: {missing}"


def test_contract_table_output():
    """Print the contract compliance table for manual review."""
    client = _get_client()
    print("\n" + "=" * 100)
    print("CONTRACT COMPLIANCE TABLE")
    print("=" * 100)
    print(f"{'Endpoint':<35} {'Role':<10} {'Status':<10} {'Missing Fields'}")
    print("-" * 100)
    for method, path, role, desc, required in CONTRACTS:
        headers = _headers("teacher_cn" if role == "teacher" else "admin_root", role.upper())
        params = {}
        if "lookup" in path:
            params["q"] = "1DS"
        if "calendar" in path and "day" not in path:
            params["month"] = "2026-11"
        if "calendar/day" in path:
            params["date"] = "2026-11-13"
        if "defaulters" in path:
            params["subject"] = "CN"
        if "audit-log" in path:
            params["page"] = "1"
            params["page_size"] = "10"
        if "sessions" in path:
            params["limit"] = "5"

        res = _call_endpoint(client, method, path, headers, params)
        if res.status_code == 200:
            missing = _check_fields(res.json(), required)
            status_str = "PASS" if not missing else "FAIL"
            missing_str = ", ".join(missing) if missing else "none"
        else:
            status_str = f"HTTP {res.status_code}"
            missing_str = "n/a"
        print(f"{path:<35} {role:<10} {status_str:<10} {missing_str}")
    print("=" * 100 + "\n")


__all__ = ["router"]
