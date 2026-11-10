"""Pytest configuration and global test fixtures for RollCall AI.

Ensures:
1. Existing non-auth test suites execute with an authenticated mock user (avoiding breaking 303 baseline tests).
2. The security/auth test suite (test_auth_api.py) executes with real JWT cryptographic verification.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Automatically ensure backend directory is prepended to sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest
from app.auth.dependencies import get_current_user
from app.auth.rate_limiter import reset_rate_limiter
from app.auth.roles import Role
from app.main import app
from app.schemas.auth import AuthenticatedUser

TEST_DEFAULT_ADMIN = AuthenticatedUser(
    user_id="00000000-0000-0000-0000-000000000001",
    email="admin@rollcall.edu",
    role=Role.ADMIN,
    claims={
        "sub": "00000000-0000-0000-0000-000000000001",
        "email": "admin@rollcall.edu",
        "role": "ADMIN",
        "app_metadata": {"role": "ADMIN"},
    },
)


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Ensure clean rate limiting state for every test."""
    reset_rate_limiter()
    yield
    reset_rate_limiter()


@pytest.fixture(autouse=True)
def auth_dependency_override(request):
    """
    Autouse fixture for existing test suites.
    When running test_auth_api.py, test_security_regression.py, or tests marked with @pytest.mark.no_auth_override,
    the override is skipped so real JWT cryptographic verification executes.
    """
    path_str = str(request.fspath)
    if "test_auth_api" in path_str or "test_security_regression" in path_str or "no_auth_override" in getattr(request, "keywords", {}):
        yield
        return

    app.dependency_overrides[get_current_user] = lambda: TEST_DEFAULT_ADMIN
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)

