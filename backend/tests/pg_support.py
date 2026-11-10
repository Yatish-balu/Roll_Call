"""Helpers for opt-in PostgreSQL integration tests.

Design rules (see N1 database hardening):

* PostgreSQL integration tests are kept separate from the SQLite unit suite and
  only run when ``TEST_DATABASE_URL`` is explicitly configured.
* The configured database must be a *disposable* test database. The helpers
  below refuse to touch the application's ``DATABASE_URL_SYNC`` or the
  ``READONLY_DATABASE_URL`` and require "test" in the database name, so no
  destructive operation (schema drop / migration) can hit production by
  accident.
* When ``TEST_DATABASE_URL`` is unset the calling test skips with an explicit
  reason instead of silently passing.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

SKIP_REASON = "TEST_DATABASE_URL not set: disposable PostgreSQL instance required"


class UnsafeTestDatabase(RuntimeError):
    """Raised when TEST_DATABASE_URL points at a non-disposable database."""


def normalize_pg_url(raw: str) -> str:
    """Normalize a PostgreSQL URL to the project-standard psycopg v3 driver."""
    url = raw.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def configured_test_url() -> str | None:
    """Return the normalized TEST_DATABASE_URL, or None when it is not set."""
    raw = (os.getenv("TEST_DATABASE_URL") or "").strip()
    if not raw:
        return None
    return normalize_pg_url(raw)


def validate_disposable(url: str) -> None:
    """Reject any target that could be the application's real database."""
    for env_name in ("DATABASE_URL_SYNC", "READONLY_DATABASE_URL", "DATABASE_URL"):
        configured = (os.getenv(env_name) or "").strip()
        if configured and normalize_pg_url(configured) == normalize_pg_url(url):
            raise UnsafeTestDatabase(
                f"TEST_DATABASE_URL must not equal {env_name}. "
                "Refusing to run destructive PostgreSQL integration tests."
            )

    database = (urlsplit(url).path or "").lstrip("/") or ""
    if "test" not in database.lower():
        raise UnsafeTestDatabase(
            "TEST_DATABASE_URL must point at a disposable database whose name "
            f"contains 'test' (got database {database!r})."
        )


def create_test_engine(url: str):
    """Create a psycopg engine for the disposable test database."""
    from sqlalchemy import create_engine

    connect_args: dict = {"connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "10"))}
    host = (urlsplit(url).hostname or "").lower()
    if host not in ("localhost", "127.0.0.1", "::1") and "sslmode=" not in url:
        connect_args["sslmode"] = "require"
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)
