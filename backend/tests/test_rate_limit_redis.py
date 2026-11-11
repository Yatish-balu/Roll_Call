"""Redis-backed rate limiting.

These tests use a small in-process fake instead of a live Redis server, so the
shared-counter behaviour is verified in CI where no Redis is available.
"""

from __future__ import annotations

import importlib
import math
import time
from typing import List

import pytest

from app.auth.rate_limiter import RedisSlidingWindowLimiter
from app.security.rate_limit import LimitScope, clear_limit, get_policy

# ``app.auth`` re-exports the limiter singleton under the same name as the
# submodule, so resolve the modules through the import system explicitly.
rate_limiter_module = importlib.import_module("app.auth.rate_limiter")
rate_limit_module = importlib.import_module("app.security.rate_limit")


class FakeRedis:
    """Minimal stand-in for the two scripts the limiters execute."""

    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.expiries: dict[str, float] = {}
        self.eval_calls: List[str] = []

    def eval(self, script: str, numkeys: int, *args):
        key = args[0]
        self.eval_calls.append(key)
        if "INCR" in script:
            value = int(self.values.get(key, 0)) + 1
            self.values[key] = value
            return value

        # Sliding window: (key, now, window, limit, member)
        now, window, limit, member = float(args[1]), float(args[2]), int(args[3]), args[4]
        history = [ts for ts in self.values.get(key, []) if float(ts) > now - window]  # type: ignore[union-attr]
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
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value) -> None:
        self.values[key] = value
        self.expiries[key] = time.time() + int(ttl)

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)
            self.expiries.pop(key, None)

    def scan_iter(self, match: str = "*", count: int = 100):
        prefix = match.rstrip("*")
        for key in list(self.values):
            if key.startswith(prefix):
                yield key


@pytest.fixture()
def fake_redis(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(rate_limit_module, "get_redis_client", lambda: client)
    monkeypatch.setattr(rate_limiter_module, "get_redis_client", lambda: client)
    return client


def test_fixed_window_counting_and_lockout_use_redis(fake_redis):
    policy = get_policy(LimitScope.PASSWORD_CHANGE)  # limit 5, lockout 900
    scope = LimitScope.PASSWORD_CHANGE
    key = "redis-user"

    for attempt in range(1, policy.limit + 1):
        decision = rate_limit_module.check_limit(None, scope, key, record_failure=True)  # type: ignore[arg-type]
        assert decision.allowed, decision
        assert decision.backend == "redis"
        assert decision.attempts == attempt

    blocked = rate_limit_module.check_limit(None, scope, key, record_failure=True)  # type: ignore[arg-type]
    assert not blocked.allowed
    assert blocked.backend == "redis"
    assert blocked.retry_after_seconds > 0
    assert f"ratelimit:block:{scope.value}:{key}" in fake_redis.values

    # While the block is active no further increments happen.
    before = int(fake_redis.values[f"ratelimit:{scope.value}:{key}"])
    again = rate_limit_module.check_limit(None, scope, key, record_failure=True)  # type: ignore[arg-type]
    assert not again.allowed
    assert int(fake_redis.values[f"ratelimit:{scope.value}:{key}"]) == before
    assert len([k for k in fake_redis.eval_calls if k.endswith(":redis-user")]) == policy.limit + 1


def test_read_only_check_reads_the_shared_counter(fake_redis):
    scope = LimitScope.LOGIN
    rate_limit_module.check_limit(None, scope, "readonly", record_failure=True)  # type: ignore[arg-type]
    rate_limit_module.check_limit(None, scope, "readonly", record_failure=True)  # type: ignore[arg-type]

    decision = rate_limit_module.check_limit(None, scope, "readonly", record_failure=False)  # type: ignore[arg-type]
    assert decision.allowed
    assert decision.attempts == 2

    fake_redis.values[f"ratelimit:{scope.value}:readonly"] = 99
    blocked = rate_limit_module.check_limit(None, scope, "readonly", record_failure=False)  # type: ignore[arg-type]
    assert not blocked.allowed
    assert blocked.retry_after_seconds > 0


def test_clear_limit_removes_redis_state(fake_redis):
    scope = LimitScope.LOGIN
    rate_limit_module.check_limit(None, scope, "clear-me", record_failure=True)  # type: ignore[arg-type]
    clear_limit(None, scope, "clear-me")  # type: ignore[arg-type]
    assert f"ratelimit:{scope.value}:clear-me" not in fake_redis.values
    assert f"ratelimit:block:{scope.value}:clear-me" not in fake_redis.values


def test_sliding_window_limiter_uses_redis(fake_redis):
    limiter = RedisSlidingWindowLimiter()
    assert limiter.check("chat:user:1", limit=2) == (True, 0)
    assert limiter.check("chat:user:1", limit=2) == (True, 0)

    allowed, retry_after = limiter.check("chat:user:1", limit=2)
    assert allowed is False
    assert retry_after >= 1
    assert any(key.endswith("chat:user:1") for key in fake_redis.eval_calls)


def test_sliding_window_limiter_isolated_per_key(fake_redis):
    limiter = RedisSlidingWindowLimiter()
    assert limiter.check("reports:user:1", limit=1) == (True, 0)
    assert limiter.check("reports:user:2", limit=1) == (True, 0)
    assert limiter.check("reports:user:1", limit=1)[0] is False


def test_sliding_window_falls_back_to_memory_when_redis_errors(monkeypatch):
    class BrokenRedis:
        def eval(self, *args, **kwargs):
            raise ConnectionError("redis is down")

    monkeypatch.setattr(rate_limiter_module, "get_redis_client", lambda: BrokenRedis())
    limiter = RedisSlidingWindowLimiter()
    limiter._warned = True  # silence the expected warning in the test log

    assert limiter.check("chat:fallback", limit=1) == (True, 0)
    allowed, retry_after = limiter.check("chat:fallback", limit=1)
    assert allowed is False
    assert retry_after > 0


def test_reset_clears_redis_sliding_keys(fake_redis):
    limiter = RedisSlidingWindowLimiter()
    limiter.check("chat:reset", limit=5)
    limiter.reset()
    assert not any(
        key.startswith(limiter.KEY_PREFIX + "chat:reset") for key in fake_redis.values
    )
    assert limiter.check("chat:reset", limit=5) == (True, 0)


def test_no_redis_url_means_database_backend(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert rate_limit_module.get_redis_client() is None
    assert rate_limit_module.backend_mode() == "database"


def test_unreachable_redis_is_cached_for_a_cooldown(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setitem(rate_limit_module._redis_state, "client", None)
    monkeypatch.setitem(rate_limit_module._redis_state, "error", "")
    monkeypatch.setitem(rate_limit_module._redis_state, "next_retry", 0.0)

    assert rate_limit_module.get_redis_client() is None
    assert rate_limit_module._redis_state["error"]
    assert rate_limit_module._redis_state["next_retry"] > time.monotonic()

    # The cooldown short-circuits the retry instead of reconnecting per request.
    started = time.monotonic()
    assert rate_limit_module.get_redis_client() is None
    assert time.monotonic() - started < 1.0
