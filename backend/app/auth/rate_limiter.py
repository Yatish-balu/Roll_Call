"""Thread-safe, sliding-window in-memory rate limiter for RollCall AI API.

Provides resource protection and DoS defense across expensive endpoints:
1. /api/v1/agent/chat (LLM query reasoning)
2. /api/v1/agent/process-file (Vision / OCR and image preprocessing)
3. /api/v1/agent/confirm (Atomic database batch commits)
4. /api/v1/reports/* (Excel and PDF document rendering)

Configurable via environment variables. When ``REDIS_URL`` is set and reachable,
counters live in Redis so every worker and every instance sees the same quota;
without Redis the limiter degrades to the previous process-local sliding window
and logs the degraded mode (never silently disabled).
Isolates quotas by authenticated user ID (sub) with IP address fallback.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import jwt
from fastapi import HTTPException, Request, status

from app.security.rate_limit import get_redis_client

logger = logging.getLogger("rollcall.auth.rate_limiter")

#: Atomic sliding window: prune, count, then either reject with a Retry-After or
#: add the request. Identical semantics to the in-memory implementation.
_REDIS_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry = math.ceil((tonumber(oldest[2]) + window) - now)
  if retry < 1 then retry = 1 end
  return {0, retry}
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, math.ceil(window * 1000))
return {1, 0}
"""


class InMemoryRateLimiter:
    """
    Thread-safe in-memory sliding-window rate limiter.
    Tracks timestamp history per rate-limit key.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._requests: Dict[str, List[float]] = {}

    def is_enabled(self) -> bool:
        """Check whether rate limiting is globally active."""
        val = os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower()
        return val not in ("false", "0", "no", "off")

    def get_limit_for_operation(self, operation: str) -> int:
        """
        Retrieve configurable maximum allowed requests per minute for an operation.
        """
        env_var_map = {
            "chat": ("RATE_LIMIT_AGENT_CHAT", 60),
            "process_file": ("RATE_LIMIT_PROCESS_FILE", 20),
            "confirm": ("RATE_LIMIT_CONFIRM", 30),
            "reports": ("RATE_LIMIT_REPORTS", 30),
            "default": ("RATE_LIMIT_DEFAULT", 120),
        }
        env_var, default_val = env_var_map.get(operation, ("RATE_LIMIT_DEFAULT", 120))
        raw = os.getenv(env_var)
        if raw:
            try:
                parsed = int(raw.strip())
                if parsed > 0:
                    return parsed
            except ValueError:
                logger.warning("Invalid %s value '%s'; using default %d", env_var, raw, default_val)
        return default_val

    def check(
        self,
        key: str,
        limit: int,
        window_seconds: float = 60.0,
    ) -> Tuple[bool, int]:
        """
        Evaluate sliding-window request count for the specified key.
        Returns (is_allowed, retry_after_seconds).
        """
        if not self.is_enabled():
            return True, 0

        now = time.time()
        window_start = now - window_seconds

        with self._lock:
            history = self._requests.get(key, [])
            # Prune timestamps outside the sliding window
            history = [ts for ts in history if ts > window_start]

            if len(history) >= limit:
                # Calculate remaining seconds until oldest call rolls out of the window
                oldest = history[0]
                retry_after = max(1, int(oldest + window_seconds - now) + 1)
                self._requests[key] = history
                return False, retry_after

            history.append(now)
            self._requests[key] = history
            return True, 0

    def reset(self) -> None:
        """Clear all tracked request histories (primarily used in tests)."""
        with self._lock:
            self._requests.clear()


class RedisSlidingWindowLimiter:
    """Shared sliding-window limiter with an automatic in-memory fallback.

    With ``REDIS_URL`` configured, the window is a sorted set per key and the
    check/add decision is a single Lua script, so concurrent workers cannot
    overshoot the quota. If Redis is unset or temporarily unreachable, the
    limiter continues on the process-local window and reports it in the log.
    """

    KEY_PREFIX = "ratelimit:sliding:"

    def __init__(self, memory: Optional[InMemoryRateLimiter] = None) -> None:
        self._memory = memory or InMemoryRateLimiter()
        self._warned = False

    @property
    def memory(self) -> InMemoryRateLimiter:
        return self._memory

    def is_enabled(self) -> bool:
        return self._memory.is_enabled()

    def get_limit_for_operation(self, operation: str) -> int:
        return self._memory.get_limit_for_operation(operation)

    def check(
        self,
        key: str,
        limit: int,
        window_seconds: float = 60.0,
    ) -> Tuple[bool, int]:
        if not self.is_enabled():
            return True, 0

        client = get_redis_client()
        if client is not None:
            now = time.time()
            # A unique member per request: two requests in the same microsecond
            # must still count as two entries.
            member = f"{now:.6f}:{uuid.uuid4().hex}"
            try:
                result = client.eval(
                    _REDIS_SLIDING_WINDOW_SCRIPT,
                    1,
                    f"{self.KEY_PREFIX}{key}",
                    now,
                    window_seconds,
                    limit,
                    member,
                )
                return bool(int(result[0])), int(result[1])
            except Exception as exc:  # pragma: no cover - exercised with a fake
                if not self._warned:
                    self._warned = True
                    logger.warning(
                        "Redis rate limiting failed (%s); using the process-local "
                        "sliding window until Redis recovers.",
                        exc,
                    )

        return self._memory.check(key, limit=limit, window_seconds=window_seconds)

    def reset(self) -> None:
        """Clear in-memory state and this application's Redis keys (tests)."""
        self._memory.reset()
        client = get_redis_client()
        if client is None:
            return
        try:
            for redis_key in client.scan_iter(match=f"{self.KEY_PREFIX}*", count=500):
                client.delete(redis_key)
        except Exception as exc:  # pragma: no cover - Redis outage
            logger.warning("Could not clear Redis rate-limit keys: %s", exc)


# Global singleton instance
rate_limiter = RedisSlidingWindowLimiter()


def reset_rate_limiter() -> None:
    """Helper to reset the rate limiter state between tests."""
    rate_limiter.reset()


def get_client_identifier(request: Request) -> str:
    """
    Extract a unique rate-limiting key.
    Prefers authenticated user ID ('sub') extracted from Bearer token claims,
    falling back to client IP address.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        try:
            unverified = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_aud": False,
                    "verify_iss": False,
                },
            )
            sub = unverified.get("sub")
            if sub:
                return f"user:{str(sub).strip()}"
        except Exception:
            pass

    client_ip = request.client.host if request.client and request.client.host else "unknown-client"
    return f"ip:{client_ip}"


def rate_limit_dependency(operation: str) -> Callable[[Request], None]:
    """
    Factory creating a FastAPI dependency that enforces rate limiting for an operation.
    Raises HTTP 429 Too Many Requests if the quota is exceeded.
    """
    def dependency(request: Request) -> None:
        if not rate_limiter.is_enabled():
            return

        client_id = get_client_identifier(request)
        rate_key = f"{operation}:{client_id}"
        limit = rate_limiter.get_limit_for_operation(operation)

        allowed, retry_after = rate_limiter.check(rate_key, limit=limit, window_seconds=60.0)
        if not allowed:
            logger.warning(
                "Rate limit exceeded for %s on operation '%s'. Limit: %d/min. Retry after %ds.",
                client_id,
                operation,
                limit,
                retry_after,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {limit} requests per minute allowed for this operation.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency


# Convenience dependencies
rate_limit_chat = rate_limit_dependency("chat")
rate_limit_process_file = rate_limit_dependency("process_file")
rate_limit_confirm = rate_limit_dependency("confirm")
rate_limit_reports = rate_limit_dependency("reports")

