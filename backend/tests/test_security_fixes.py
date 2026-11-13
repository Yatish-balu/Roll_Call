"""Regression tests for the security audit fixes.

Covers:
* rate-limit buckets are derived from a *verified* JWT subject,
* ``X-Forwarded-For`` is ignored unless the proxy is explicitly trusted,
* export destinations are confined to an allow-listed root,
* scoped raw SQL rejects constructs the regex rewrite cannot cover,
* the agent never resolves a local file path from chat text.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import jwt as pyjwt
import pytest
from starlette.requests import Request

from app.agent import AttendanceAgent
from app.auth.jwt import create_access_token
from app.auth.rate_limiter import get_client_identifier
from app.schemas.auth import Role
from app.security.client_ip import get_client_ip
from tools.export_tool import _validate_output_path
from tools.query_tool import _apply_scope_to_sql

# 48 characters: avoids the PyJWT short-key warning while staying test-only.
TEST_JWT_SECRET = "rollcall-test-secret-" + "x" * 28


def _request(headers=None, client=("203.0.113.9", 1234)) -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": raw_headers,
            "client": client,
            "scheme": "http",
            "query_string": b"",
        }
    )


# ---------------------------------------------------------------------------
# Rate-limit identity
# ---------------------------------------------------------------------------

def test_forged_token_cannot_choose_rate_limit_bucket(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    now = dt.datetime.now(dt.timezone.utc)
    forged = pyjwt.encode(
        {"sub": "victim", "exp": int((now + dt.timedelta(hours=1)).timestamp())},
        "attacker-controlled-secret-0123456789",
        algorithm="HS256",
    )

    identifier = get_client_identifier(
        _request({"Authorization": f"Bearer {forged}"})
    )

    assert identifier == "ip:203.0.113.9"
    assert "victim" not in identifier


def test_verified_token_uses_user_bucket(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    token = create_access_token({"sub": "user-42"}, secret=TEST_JWT_SECRET)

    identifier = get_client_identifier(
        _request({"Authorization": f"Bearer {token}"})
    )

    assert identifier == "user:user-42"


# ---------------------------------------------------------------------------
# Client IP resolution
# ---------------------------------------------------------------------------

def test_forwarded_for_is_ignored_without_explicit_trust(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)

    assert get_client_ip(_request({"X-Forwarded-For": "198.51.100.7"})) == "203.0.113.9"


def test_forwarded_for_is_used_when_proxy_is_trusted(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")

    assert (
        get_client_ip(_request({"X-Forwarded-For": "198.51.100.7, 10.0.0.1"}))
        == "198.51.100.7"
    )


# ---------------------------------------------------------------------------
# Export path confinement
# ---------------------------------------------------------------------------

def test_export_rejects_path_outside_allowed_roots(tmp_path):
    outside = Path(tmp_path.anchor) / "rollcall-audit-outside.xlsx"

    with pytest.raises(ValueError):
        _validate_output_path(outside)


def test_export_allows_path_inside_temp_during_development(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")

    resolved = _validate_output_path(tmp_path / "report.xlsx")

    assert resolved == (tmp_path / "report.xlsx").resolve()


# ---------------------------------------------------------------------------
# Scoped raw SQL
# ---------------------------------------------------------------------------

class _Scoped:
    subject_codes = frozenset({"CS101"})

    def visible_session_ids(self, db=None):
        return {"SESS-1"}


@pytest.mark.parametrize(
    "sql",
    [
        "WITH x AS (SELECT * FROM attendance) SELECT * FROM x",
        "SELECT * FROM attendance UNION SELECT * FROM attendance",
        "SELECT * FROM attendance, students",
        "SELECT * FROM (attendance JOIN students ON attendance.usn = students.usn)",
        "SELECT * FROM attendance a, (SELECT * FROM students) s",
        "SELECT * FROM attendance a JOIN LATERAL (SELECT 1) x ON true",
    ],
)
def test_scoped_sql_rejects_constructs_the_rewrite_cannot_cover(sql):
    with pytest.raises(ValueError):
        _apply_scope_to_sql(sql, _Scoped())


def test_scoped_sql_still_rewrites_plain_references():
    rewritten, params = _apply_scope_to_sql(
        "SELECT * FROM attendance", _Scoped()
    )

    assert "FROM (SELECT * FROM attendance" in rewritten
    assert params


# ---------------------------------------------------------------------------
# Agent input handling
# ---------------------------------------------------------------------------

def test_agent_does_not_read_paths_embedded_in_chat_text(tmp_path):
    secret_file = tmp_path / "attendance.csv"
    secret_file.write_text("usn,name,status\n1MS21CS001,Alice,PRESENT\n", encoding="utf-8")

    agent = AttendanceAgent(role=Role.ADMIN)
    response = agent.process_request(user_input=f"please read {secret_file}")

    assert response.success is False
    assert response.data in (None, [])
