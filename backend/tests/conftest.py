"""Pytest configuration and global test fixtures for RollCall AI.

Ensures:
1. Existing non-auth test suites execute with an authenticated mock user (avoiding breaking 303 baseline tests).
2. The security/auth test suite (test_auth_api.py) executes with real JWT cryptographic verification.
3. The test suite never writes to the live development database: every test
   runs against a disposable copy, so tests cannot contaminate each other or
   the recovered historical attendance data.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Automatically ensure backend directory is prepended to sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# ---------------------------------------------------------------------------
# Test isolation: point the application at a disposable copy of the database.
#
# This must happen BEFORE app.db.connection is imported, because the module
# resolves SQLITE_PATH into DEFAULT_DB_PATH at import time. The live database
# (data/attendance.db) is preserved untouched and only ever read.
# ---------------------------------------------------------------------------
_REPO_ROOT = _BACKEND_DIR.parent
_LIVE_DB = _REPO_ROOT / "data" / "attendance.db"

# Load local .env if available so environment variables are present during test runs
try:
    from dotenv import dotenv_values
    _env_file = _REPO_ROOT / ".env"
    if _env_file.exists():
        _vals = dotenv_values(_env_file)
        # Load database variables for backend tests without overriding AI mock expectations
        for _k in ("DATABASE_URL", "DATABASE_URL_SYNC", "READONLY_DATABASE_URL", "DB_BACKEND"):
            if _k in _vals and _k not in os.environ:
                os.environ[_k] = _vals[_k]
except ImportError:
    pass

_ISOLATED_DIR = tempfile.mkdtemp(prefix="rollcall_test_db_")
_ISOLATED_DB = Path(_ISOLATED_DIR) / "attendance.db"
if _LIVE_DB.exists():
    shutil.copy2(_LIVE_DB, _ISOLATED_DB)
os.environ["SQLITE_PATH"] = str(_ISOLATED_DB)
os.environ["DATABASE_PATH"] = str(_ISOLATED_DB)
# Tests run against the SQLite backend, never against Supabase.
os.environ["DB_BACKEND"] = "sqlite"

# Bring the isolated copy (or fresh CI database) to the current schema head so
# that the application models and the database agree. The live database is only
# read (copied) here and is never migrated.
try:
    from alembic import command
    from alembic.config import Config

    _alembic_cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    _alembic_cfg.set_main_option(
        "sqlalchemy.url", "sqlite:///" + str(_ISOLATED_DB).replace("\\", "/")
    )

    # The live snapshot predates Alembic: it has the 0001 schema but no
    # alembic_version table, so an upgrade from base would try to recreate
    # existing tables. Stamp the baseline first, exactly as a legacy database
    # must be bootstrapped.
    _conn = sqlite3.connect(str(_ISOLATED_DB))
    try:
        _has_version = _conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
        ).fetchone()
        _has_legacy_tables = _conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'students'"
        ).fetchone()
    finally:
        _conn.close()
    if _has_legacy_tables and not _has_version:
        command.stamp(_alembic_cfg, "0001_initial_schema")

    command.upgrade(_alembic_cfg, "head")
except Exception as _migration_error:  # pragma: no cover - surfaced in the logs
    print(
        f"WARNING: the isolated test database could not be migrated to head: {_migration_error}"
    )

import pytest
from sqlalchemy.orm import sessionmaker
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


def seed_test_admin_user(engine) -> None:
    """
    Insert the conftest TEST_DEFAULT_ADMIN as a real users row in the given engine.

    Required since N4: every write is audited and audit_log.actor_id has a
    foreign key to users.user_id, so the mock-auth admin must actually exist.
    """
    from app.db.models import User

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        if db.get(User, TEST_DEFAULT_ADMIN.user_id) is None:
            db.add(
                User(
                    user_id=TEST_DEFAULT_ADMIN.user_id,
                    email=TEST_DEFAULT_ADMIN.email or "admin@rollcall.edu",
                    role="ADMIN",
                    hashed_password=None,
                    is_active=1,
                    created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
            )
            db.commit()


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
    if "test_auth" in path_str or "test_security_regression" in path_str or "no_auth_override" in getattr(request, "keywords", {}):
        yield
        return


    app.dependency_overrides[get_current_user] = lambda: TEST_DEFAULT_ADMIN
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)

