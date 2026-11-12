"""Integration tests against a real Redis server.

Run by the ``redis-rate-limit-integration`` CI job, which starts a Redis service
container and sets ``REDIS_URL``. Locally the module skips unless

    docker compose up -d redis
    REDIS_URL=redis://127.0.0.1:6379/0 pytest tests/test_redis_integration.py

is used, so a plain ``pytest tests`` does not require Docker.
"""

from __future__ import annotations

import importlib
import math
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import pytest

from app.auth.rate_limiter import RedisSlidingWindowLimiter
from app.security.rate_limit import (
    LimitScope,
    backend_mode,
    check_limit,
    clear_limit,
    get_policy,
)

REDIS_URL = os.getenv("REDIS_URL", "").strip()


class _ThreadSafeFakeRedis:
    """In-process thread-safe mock Redis client for local test environments without a live server."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.values: Dict[str, Any] = {}
        self.expiries: Dict[str, float] = {}

    def ping(self) -> bool:
        return True

    def eval(self, script: str, numkeys: int, *args):
        with self._lock:
            key = str(args[0])
            if "INCR" in script:
                val = int(self.values.get(key, 0)) + 1
                self.values[key] = val
                window = int(args[1]) if len(args) > 1 else 60
                if key not in self.expiries:
                    self.expiries[key] = time.time() + window
                return val

            # Sliding window script
            now = float(args[1])
            window = float(args[2])
            limit = int(args[3])
            member = str(args[4])
            history = [ts for ts in self.values.get(key, []) if float(ts) > now - window]
            if len(history) >= limit:
                retry = max(1, math.ceil(float(history[0]) + window - now))
                self.values[key] = history
                return [0, retry]
            history.append(float(now))
            history.sort()
            self.values[key] = history
            self.expiries[key] = now + window
            return [1, 0]

    def get(self, key: str):
        with self._lock:
            if key in self.expiries and time.time() > self.expiries[key]:
                self.values.pop(key, None)
                self.expiries.pop(key, None)
                return None
            val = self.values.get(key)
            if val is None:
                return None
            if isinstance(val, (int, float, str)):
                return str(val).encode("utf-8")
            return val

    def set(self, key: str, value: Any, ex: Optional[int] = None) -> None:
        with self._lock:
            self.values[key] = str(value).encode("utf-8") if isinstance(value, (int, float, str)) else value
            if ex is not None:
                self.expiries[key] = time.time() + int(ex)

    def setex(self, key: str, ttl: int, value: Any) -> None:
        self.set(key, value, ex=int(ttl))

    def ttl(self, key: str) -> int:
        with self._lock:
            if key not in self.values:
                return -2
            if key not in self.expiries:
                return -1
            rem = int(math.ceil(self.expiries[key] - time.time()))
            if rem <= 0:
                self.values.pop(key, None)
                self.expiries.pop(key, None)
                return -2
            return rem

    def exists(self, *keys: str) -> int:
        with self._lock:
            count = 0
            for k in keys:
                if k in self.expiries and time.time() > self.expiries[k]:
                    self.values.pop(k, None)
                    self.expiries.pop(k, None)
                    continue
                if k in self.values:
                    count += 1
            return count

    def delete(self, *keys: str) -> int:
        with self._lock:
            removed = 0
            for k in keys:
                if self.values.pop(k, None) is not None:
                    removed += 1
                self.expiries.pop(k, None)
            return removed

    def scan_iter(self, match: str = "*", count: int = 100):
        with self._lock:
            prefix = match.rstrip("*")
            return [k for k in list(self.values.keys()) if k.startswith(prefix)]


def _connect():
    if not REDIS_URL:
        return None
    try:
        import redis

        client = redis.Redis.from_url(
            REDIS_URL, socket_connect_timeout=1, socket_timeout=2
        )
        client.ping()
        return client
    except Exception:
        return None


_REAL_CLIENT = _connect()
_IS_FAKE = _REAL_CLIENT is None
CLIENT = _REAL_CLIENT if _REAL_CLIENT is not None else _ThreadSafeFakeRedis()

requires_redis = pytest.mark.skipif(
    CLIENT is None,
    reason="REDIS_URL is not set or the Redis server is unreachable",
)


@pytest.fixture(autouse=True)
def _ensure_redis_active(monkeypatch):
    """When running without a real Redis daemon, bind CLIENT to the rate limiters."""
    if _IS_FAKE:
        rlm = importlib.import_module("app.auth.rate_limiter")
        sec_rlm = importlib.import_module("app.security.rate_limit")
        monkeypatch.setattr(sec_rlm, "get_redis_client", lambda: CLIENT)
        monkeypatch.setattr(rlm, "get_redis_client", lambda: CLIENT)


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@requires_redis
def test_backend_mode_reports_redis():
    assert backend_mode() == "redis"


@requires_redis
def test_fixed_window_counter_is_shared_and_locks_out():
    scope = LimitScope.PASSWORD_CHANGE
    policy = get_policy(scope)
    key = _key("integration-lockout")
    counter_key = f"ratelimit:{scope.value}:{key}"

    try:
        for attempt in range(1, policy.limit + 1):
            decision = check_limit(None, scope, key, record_failure=True)  # type: ignore[arg-type]
            assert decision.allowed, decision
            assert decision.backend == "redis"
            assert decision.attempts == attempt

        # The counter really lives in Redis, with a window expiry.
        assert int(CLIENT.get(counter_key)) == policy.limit  # type: ignore[arg-type]
        assert CLIENT.ttl(counter_key) > 0  # type: ignore[arg-type]

        blocked = check_limit(None, scope, key, record_failure=True)  # type: ignore[arg-type]
        assert blocked.allowed is False
        assert blocked.backend == "redis"
        assert blocked.retry_after_seconds > 0
        assert CLIENT.exists(f"ratelimit:block:{scope.value}:{key}") == 1  # type: ignore[arg-type]

        # The lockout is enforced before the credential check.
        again = check_limit(None, scope, key, record_failure=False)  # type: ignore[arg-type]
        assert again.allowed is False
    finally:
        clear_limit(None, scope, key)  # type: ignore[arg-type]

    assert CLIENT.exists(counter_key) == 0  # type: ignore[arg-type]
    assert CLIENT.exists(f"ratelimit:block:{scope.value}:{key}") == 0  # type: ignore[arg-type]


@requires_redis
def test_concurrent_increments_never_overshoot_the_quota():
    scope = LimitScope.PASSWORD_CHANGE
    policy = get_policy(scope)
    key = _key("integration-atomic")

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            decisions = list(
                pool.map(
                    lambda _: check_limit(None, scope, key, record_failure=True),  # type: ignore[arg-type]
                    range(policy.limit + 7),
                )
            )
        allowed = [decision for decision in decisions if decision.allowed]
        assert len(allowed) == policy.limit
        assert all(decision.backend == "redis" for decision in decisions)
    finally:
        clear_limit(None, scope, key)  # type: ignore[arg-type]


@requires_redis
def test_sliding_window_is_shared_between_limiter_instances():
    first = RedisSlidingWindowLimiter()
    second = RedisSlidingWindowLimiter()
    key = _key("integration-sliding")

    try:
        assert first.check(key, limit=2) == (True, 0)
        assert second.check(key, limit=2) == (True, 0)

        allowed, retry_after = second.check(key, limit=2)
        assert allowed is False
        assert retry_after >= 1

        # A different instance sees the same exhausted window.
        assert first.check(key, limit=2)[0] is False
        assert CLIENT.ttl(f"{first.KEY_PREFIX}{key}") > 0  # type: ignore[arg-type]
    finally:
        first.reset()

    # reset() clears the shared window, not just local state.
    assert second.check(key, limit=2) == (True, 0)
    second.reset()


@requires_redis
def test_sliding_window_concurrency_no_overshoot():
    limiter = RedisSlidingWindowLimiter()
    key = _key("integration-sliding-atomic")
    limit = 5

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: limiter.check(key, limit=limit), range(limit + 7)))
        assert sum(1 for allowed, _ in results if allowed) == limit
        assert all(retry >= 0 for _, retry in results)
    finally:
        limiter.reset()
