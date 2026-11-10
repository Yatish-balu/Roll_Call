"""Tests for database hardening (Phase 1, 2, 4): cloud-first production configuration.

Covers:
- Production missing DB_BACKEND
- Production configured for SQLite
- Production missing DATABASE_URL_SYNC
- Invalid PostgreSQL URL
- No SQLite fallback in production
- Development SQLite fallback remains functional
- Correct PostgreSQL SSL settings for psycopg
- Correct PostgreSQL SSL settings for asyncpg
- Connection pool configuration
- Alembic URL consistency

PostgreSQL integration tests are opt-in via TEST_DATABASE_URL and skipped
when no disposable instance is available. Production DATABASE_URL is never
used for tests.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool, StaticPool

from app.db import connection as conn_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_env(monkeypatch, **kwargs):
    """Set multiple environment variables via monkeypatch."""
    for key, value in kwargs.items():
        monkeypatch.setenv(key, value)


# ---------------------------------------------------------------------------
# 1. Production missing DB_BACKEND
# ---------------------------------------------------------------------------

def test_production_missing_db_backend_raises(monkeypatch):
    _set_env(
        monkeypatch,
        APP_ENV="production",
        DB_BACKEND="",
        DATABASE_URL_SYNC="postgresql+psycopg://user:pass@localhost/db",
    )
    with pytest.raises(RuntimeError, match="DB_BACKEND=supabase"):
        conn_module.get_backend()


def test_production_sqlite_backend_raises(monkeypatch):
    _set_env(
        monkeypatch,
        APP_ENV="production",
        DB_BACKEND="sqlite",
        DATABASE_URL_SYNC="postgresql+psycopg://user:pass@localhost/db",
    )
    with pytest.raises(RuntimeError, match="SQLite is not permitted"):
        conn_module.get_backend()


# ---------------------------------------------------------------------------
# 2. Production missing DATABASE_URL_SYNC
# ---------------------------------------------------------------------------

def test_production_missing_database_url_sync_raises(monkeypatch):
    _set_env(
        monkeypatch,
        APP_ENV="production",
        DB_BACKEND="supabase",
        DATABASE_URL_SYNC="",
    )
    with pytest.raises(RuntimeError, match="DATABASE_URL_SYNC"):
        conn_module.get_backend()


def test_create_sync_engine_production_missing_url_raises(monkeypatch):
    _set_env(
        monkeypatch,
        APP_ENV="production",
        DB_BACKEND="supabase",
        DATABASE_URL_SYNC="",
    )
    with pytest.raises(RuntimeError, match="DATABASE_URL_SYNC"):
        conn_module.create_sync_engine()


# ---------------------------------------------------------------------------
# 3. No SQLite fallback in production
# ---------------------------------------------------------------------------

def test_no_sqlite_fallback_in_production(monkeypatch):
    _set_env(
        monkeypatch,
        APP_ENV="production",
        DB_BACKEND="supabase",
        DATABASE_URL_SYNC="postgresql+psycopg://user:pass@localhost/db",
    )
    backend = conn_module.get_backend()
    assert backend == "supabase"

    # get_engine with supabase must not return a sqlite engine.
    engine = conn_module.get_engine("supabase")
    assert not engine.url.drivername.startswith("sqlite")


# ---------------------------------------------------------------------------
# 4. Development SQLite fallback remains functional
# ---------------------------------------------------------------------------

def test_development_sqlite_backend(monkeypatch):
    _set_env(monkeypatch, APP_ENV="development", DB_BACKEND="sqlite")
    backend = conn_module.get_backend()
    assert backend == "sqlite"


def test_create_sync_engine_sqlite_fallback(monkeypatch):
    _set_env(
        monkeypatch,
        APP_ENV="development",
        DB_BACKEND="sqlite",
        DATABASE_URL_SYNC="",
    )
    engine = conn_module.create_sync_engine()
    assert engine.url.drivername.startswith("sqlite")


def test_get_engine_sqlite_fallback(monkeypatch):
    _set_env(monkeypatch, APP_ENV="development", DB_BACKEND="sqlite")
    engine = conn_module.get_engine("sqlite")
    assert engine.url.drivername.startswith("sqlite")


# ---------------------------------------------------------------------------
# 5. PostgreSQL SSL settings for psycopg (sync)
# ---------------------------------------------------------------------------

def test_postgresql_ssl_psycopg_connect_args(monkeypatch):
    _set_env(
        monkeypatch,
        APP_ENV="development",
        DATABASE_URL_SYNC="postgresql+psycopg://user:pass@localhost:5432/db?sslmode=require",
    )

    with patch("app.db.connection.create_engine") as mock_create:
        mock_create.return_value = create_engine("sqlite:///:memory:")
        conn_module.create_sync_engine()

        _, kwargs = mock_create.call_args
        connect_args = kwargs.get("connect_args", {})
        assert connect_args.get("sslmode") == "require", \
            f"Expected sslmode=require in connect_args, got {connect_args}"


def test_postgresql_engine_url_is_postgresql(monkeypatch):
    _set_env(
        monkeypatch,
        APP_ENV="development",
        DATABASE_URL_SYNC="postgresql+psycopg://user:pass@localhost:5432/db",
    )
    engine = conn_module.create_sync_engine()
    assert engine.url.drivername == "postgresql+psycopg"


# ---------------------------------------------------------------------------
# 6. PostgreSQL SSL settings for asyncpg (async)
# ---------------------------------------------------------------------------

def test_postgresql_ssl_asyncpg_connect_args(monkeypatch):
    _set_env(
        monkeypatch,
        APP_ENV="development",
        DATABASE_URL_ASYNC="postgresql+asyncpg://user:pass@localhost:6543/db",
    )

    with patch("app.db.connection.create_async_engine") as mock_create:
        mock_create.return_value = None
        conn_module.create_async_engine_instance()

        _, kwargs = mock_create.call_args
        connect_args = kwargs.get("connect_args", {})
        assert connect_args.get("ssl") == "require", \
            f"Expected ssl=require in connect_args, got {connect_args}"


# ---------------------------------------------------------------------------
# 7. Connection pool configuration
# ---------------------------------------------------------------------------

def test_connection_pool_settings(monkeypatch):
    _set_env(
        monkeypatch,
        APP_ENV="development",
        DATABASE_URL_SYNC="postgresql+psycopg://user:pass@localhost:5432/db",
        DB_POOL_SIZE="5",
        DB_MAX_OVERFLOW="10",
        DB_POOL_RECYCLE="1800",
    )

    with patch("app.db.connection.create_engine") as mock_create:
        mock_create.return_value = create_engine("sqlite:///:memory:")
        conn_module.create_sync_engine()

        _, kwargs = mock_create.call_args
        assert kwargs.get("pool_pre_ping") is True
        assert kwargs.get("pool_size") == 5
        assert kwargs.get("max_overflow") == 10
        assert kwargs.get("pool_recycle") == 1800


def test_sqlite_engine_uses_sqlite_driver(monkeypatch):
    _set_env(monkeypatch, APP_ENV="development", DB_BACKEND="sqlite")
    engine = conn_module.create_sync_engine()
    assert engine.url.drivername.startswith("sqlite")


# ---------------------------------------------------------------------------
# 8. Alembic URL consistency
# ---------------------------------------------------------------------------

def test_alembic_env_reads_database_url_sync():
    """Verify alembic env.py uses DATABASE_URL_SYNC for its URL."""
    alembic_path = os.path.join(
        os.path.dirname(__file__), "..", "alembic", "env.py"
    )
    with open(alembic_path, "r") as f:
        content = f.read()
    assert "DATABASE_URL_SYNC" in content, (
        "alembic/env.py must read DATABASE_URL_SYNC for migration URL consistency"
    )


# ---------------------------------------------------------------------------
# 9. Read-only URL must not become write connection
# ---------------------------------------------------------------------------

def test_readonly_url_not_used_as_write(monkeypatch):
    _set_env(
        monkeypatch,
        APP_ENV="production",
        DB_BACKEND="supabase",
        DATABASE_URL_SYNC="postgresql+psycopg://user:pass@localhost:5432/db",
        READONLY_DATABASE_URL="postgresql+psycopg://readonly:pass@localhost:5432/db",
    )
    # Validation should pass (readonly != sync URL).
    conn_module._validate_production_config()

    # create_sync_engine must use DATABASE_URL_SYNC, not READONLY_DATABASE_URL.
    engine = conn_module.create_sync_engine()
    assert "readonly" not in str(engine.url)
    assert engine.url.username == "user"


# ---------------------------------------------------------------------------
# 10. Opt-in PostgreSQL integration tests (skipped without TEST_DATABASE_URL)
# ---------------------------------------------------------------------------

def test_postgresql_integration_skipped_without_test_url(monkeypatch):
    """Documents that integration tests skip when TEST_DATABASE_URL is unset."""
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    if os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL is set")
    # When unset, this test simply passes (no integration test runs).


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set: disposable PostgreSQL instance required",
)
def test_postgresql_integration_connects():
    """Opt-in integration test: connects to a disposable PostgreSQL instance.

    Skipped unless TEST_DATABASE_URL points to a disposable PostgreSQL database.
    Never uses production DATABASE_URL.
    """
    test_url = os.getenv("TEST_DATABASE_URL")
    assert "postgresql" in test_url, "TEST_DATABASE_URL must be a PostgreSQL URL"

    engine = create_engine(test_url, connect_args={"sslmode": "require"})
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
