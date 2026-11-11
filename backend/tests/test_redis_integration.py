"""Integration tests against a real Redis server.

Run by the ``redis-rate-limit-integration`` CI job, which starts a Redis service
container and sets ``REDIS_URL``. Locally the module skips unless

    docker compose up -d redis
    REDIS_URL=redis://127.0.0.1:6379/0 pytest tests/test_redis_integration.py

is used, so a plain ``pytest tests`` does not require Docker.
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

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


CLIENT = _connect()

requires_redis = pytest.mark.skipif(
    CLIENT is None,
    reason="REDIS_URL is not set or the Redis server is unreachable",
)


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
