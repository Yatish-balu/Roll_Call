"""Rate limiting with shared (cross-worker) state.

Two backends are supported:

``redis``
    Shared counters in Redis, so several application workers (or several
    instances) see the same counters. Counters are incremented atomically and
    carry an expiry.

``database``
    The fallback used when no Redis is configured. The counters live in the
    application database, which is **also shared between workers** - so the
    protection is not process-local, it is durable and cluster-wide as long as
    every worker uses the same database. This is the documented single-cluster
    fallback; it is explicitly *not* a distributed store across independent
    databases or regions.

The limiter never silently disables itself: if Redis is configured but
unreachable, the database backend is used and the degraded mode is reported
(:func:`backend_mode`).
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger("rollcall.security.rate_limit")


class LimitScope(str, Enum):
    """The sensitive operations that get their own quota."""

    LOGIN = "login"
    REFRESH = "refresh"
    PASSWORD_RESET = "password_reset"
    PASSWORD_CHANGE = "password_change"
    MFA_VERIFY = "mfa_verify"
    UPLOAD = "upload"
    API = "api"


@dataclass(frozen=True)
class LimitPolicy:
    """Quota for one scope."""

    limit: int
    window_seconds: int
    #: Extra lockout applied once the quota is exhausted (0 = no extra lockout).
    lockout_seconds: int = 0
    #: Base delay applied per failed attempt (progressive backoff).
    base_delay_seconds: float = 0.0
    max_delay_seconds: float = 5.0


DEFAULT_POLICIES: Dict[LimitScope, LimitPolicy] = {
    # The lockout defaults to the counting window so that the advertised
    # Retry-After matches the window the legacy quota already used.
    LimitScope.LOGIN: LimitPolicy(limit=5, window_seconds=600, lockout_seconds=0, base_delay_seconds=0.2),
    LimitScope.REFRESH: LimitPolicy(limit=30, window_seconds=600, lockout_seconds=300, base_delay_seconds=0.0),
    LimitScope.PASSWORD_RESET: LimitPolicy(limit=3, window_seconds=3600, lockout_seconds=1800, base_delay_seconds=0.0),
    # Verified-password actions (change password, MFA enable/disable) must not
    # become an unlimited password oracle for a stolen access token.
    LimitScope.PASSWORD_CHANGE: LimitPolicy(limit=5, window_seconds=600, lockout_seconds=900, base_delay_seconds=0.0),
    LimitScope.MFA_VERIFY: LimitPolicy(limit=5, window_seconds=300, lockout_seconds=900, base_delay_seconds=0.0),
    LimitScope.UPLOAD: LimitPolicy(limit=20, window_seconds=600, lockout_seconds=300, base_delay_seconds=0.0),
    LimitScope.API: LimitPolicy(limit=120, window_seconds=60, lockout_seconds=0, base_delay_seconds=0.0),
}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def get_policy(scope: LimitScope) -> LimitPolicy:
    """Return the effective policy for a scope (environment overridable)."""
    base = DEFAULT_POLICIES[scope]
    prefix = f"SEC_{scope.value.upper()}"
    return LimitPolicy(
        limit=_env_int(f"{prefix}_LIMIT", base.limit),
        window_seconds=_env_int(f"{prefix}_WINDOW_SECONDS", base.window_seconds),
        lockout_seconds=_env_int(f"{prefix}_LOCKOUT_SECONDS", base.lockout_seconds),
        base_delay_seconds=base.base_delay_seconds,
        max_delay_seconds=base.max_delay_seconds,
    )


@dataclass
class LimitDecision:
    """Outcome of a limit check."""

    allowed: bool
    scope: str
    key: str
    attempts: int = 0
    limit: int = 0
    retry_after_seconds: int = 0
    delay_seconds: float = 0.0
    backend: str = "database"
    degraded: bool = False

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.attempts)


#: How long a failed Redis connection is remembered before retrying. A blip
#: must not permanently downgrade a worker to the database backend.
_REDIS_RETRY_SECONDS = 30.0

#: INCR + EXPIRE in one round trip. The TTL is set only when the counter is
#: created, so a fixed counting window does not slide on every request.
_REDIS_INCREMENT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

_redis_state: Dict[str, Any] = {
    "client": None,
    "checked": False,
    "error": "",
    "next_retry": 0.0,
}
_redis_lock = threading.Lock()

#: State of the degraded, process-local fallback (used only when the shared
#: rate-limit table is not available yet).
_FALLBACK_STATE: Dict[str, Any] = {"counts": {}, "warned": False}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def get_redis_client():
    """Return a Redis client when ``REDIS_URL`` is configured and reachable.

    When Redis is configured but unreachable the caller falls back to the
    database backend and the degraded mode is reported.
    """
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return None
    with _redis_lock:
        if _redis_state["client"] is not None:
            return _redis_state["client"]
        import time

        now = time.monotonic()
        if _redis_state["error"] and now < float(_redis_state["next_retry"] or 0):
            return None
        _redis_state["checked"] = True
        try:
            import redis  # type: ignore

            client = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
            client.ping()
            _redis_state["client"] = client
            _redis_state["error"] = ""
            return client
        except Exception as exc:
            _redis_state["error"] = str(exc)
            _redis_state["next_retry"] = now + _REDIS_RETRY_SECONDS
            logger.warning(
                "REDIS_URL is configured but Redis is unreachable (%s); "
                "falling back to the shared database rate-limit counters for "
                "at most %.0fs before retrying.",
                exc,
                _REDIS_RETRY_SECONDS,
            )
            return None


def backend_mode() -> str:
    """Return the active backend: ``redis`` or ``database``."""
    return "redis" if get_redis_client() is not None else "database"


def _redis_increment(client, scope: str, key: str, window_seconds: int) -> int:
    """Atomically increment a Redis counter, setting its TTL on creation."""
    redis_key = f"ratelimit:{scope}:{key}"
    return int(client.eval(_REDIS_INCREMENT_SCRIPT, 1, redis_key, window_seconds))


def _redis_blocked_until(client, scope: str, key: str) -> int:
    redis_key = f"ratelimit:block:{scope}:{key}"
    try:
        value = client.get(redis_key)
    except Exception:
        return 0
    if value is None:
        return 0
    try:
        return max(0, int(value) - int(_utcnow().timestamp()))
    except (TypeError, ValueError):
        return 0


def _fallback_counts() -> Dict[str, Dict[str, Any]]:
    """In-process counters used only when the shared table is unavailable."""
    return _FALLBACK_STATE.setdefault("counts", {})


def _fallback_check(scope: LimitScope, key: str, policy: LimitPolicy, record_failure: bool) -> LimitDecision:
    """Degraded, process-local fallback.

    Used when the shared ``security_rate_limits`` table does not exist yet
    (migration 0016 pending). The existing database-backed login attempt quota
    still applies, so authentication is never left unprotected; this fallback
    only makes the *progressive delay* per-process until the migration is
    applied. It is logged as a deployment blocker.
    """
    now = _utcnow()
    store = _fallback_counts()
    entry = store.setdefault(f"{scope.value}:{key}", {"attempts": 0, "window": now, "blocked_until": None})
    if (now - entry["window"]).total_seconds() > policy.window_seconds:
        entry["attempts"] = 0
        entry["window"] = now
    blocked_until = entry.get("blocked_until")
    if blocked_until is not None and blocked_until > now:
        return LimitDecision(
            allowed=False,
            scope=scope.value,
            key=key,
            attempts=entry["attempts"],
            limit=policy.limit,
            retry_after_seconds=int((blocked_until - now).total_seconds()),
            backend="memory",
            degraded=True,
        )
    if record_failure:
        entry["attempts"] = int(entry["attempts"]) + 1
    if entry["attempts"] > policy.limit:
        lockout = policy.lockout_seconds or policy.window_seconds
        entry["blocked_until"] = now + timedelta(seconds=lockout)
        return LimitDecision(
            allowed=False,
            scope=scope.value,
            key=key,
            attempts=entry["attempts"],
            limit=policy.limit,
            retry_after_seconds=lockout,
            backend="memory",
            degraded=True,
        )
    delay = min(policy.max_delay_seconds, policy.base_delay_seconds * max(0, entry["attempts"] - 1))
    return LimitDecision(
        allowed=True,
        scope=scope.value,
        key=key,
        attempts=entry["attempts"],
        limit=policy.limit,
        delay_seconds=delay,
        backend="memory",
        degraded=True,
    )


def check_limit(
    db: Session,
    scope: LimitScope,
    key: str,
    *,
    record_failure: bool = True,
    commit: bool = False,
) -> LimitDecision:
    """Check (and optionally count) a rate limit for one key.

    The decision includes the progressive back-off delay the caller should
    apply, the remaining quota and whether the limiter is running in degraded
    (database fallback) mode. ``commit=True`` persists the counter
    immediately, which the authentication flows need so that a counter survives
    the request.
    """
    policy = get_policy(scope)
    clean_key = (key or "").strip()[:200]
    if not clean_key:
        return LimitDecision(allowed=True, scope=scope.value, key="", limit=policy.limit)

    client = get_redis_client()
    if client is not None:
        try:
            blocked_for = _redis_blocked_until(client, scope.value, clean_key)
            if blocked_for > 0:
                return LimitDecision(
                    allowed=False,
                    scope=scope.value,
                    key=clean_key,
                    attempts=policy.limit,
                    limit=policy.limit,
                    retry_after_seconds=blocked_for,
                    backend="redis",
                )
            attempts = (
                _redis_increment(client, scope.value, clean_key, policy.window_seconds)
                if record_failure
                else int(client.get(f"ratelimit:{scope.value}:{clean_key}") or 0)
            )
            # Mirrors the database backend: the quota-th failure still gets the
            # credential check, the next one is refused before it.
            if attempts > policy.limit:
                lockout = max(1, policy.lockout_seconds or policy.window_seconds)
                client.setex(
                    f"ratelimit:block:{scope.value}:{clean_key}",
                    lockout,
                    int(_utcnow().timestamp()) + lockout,
                )
                return LimitDecision(
                    allowed=False,
                    scope=scope.value,
                    key=clean_key,
                    attempts=attempts,
                    limit=policy.limit,
                    retry_after_seconds=lockout,
                    backend="redis",
                )
            delay = min(policy.max_delay_seconds, policy.base_delay_seconds * max(0, attempts - 1))
            return LimitDecision(
                allowed=True,
                scope=scope.value,
                key=clean_key,
                attempts=attempts,
                limit=policy.limit,
                delay_seconds=delay,
                backend="redis",
            )
        except Exception as exc:
            logger.warning("Redis rate limiting failed (%s); using the database backend.", exc)

    # ---- database backend (shared between workers through the database) ----
    from app.db.models import SecurityRateLimit

    now = _utcnow()
    try:
        row = db.execute(
            select(SecurityRateLimit).where(
                SecurityRateLimit.scope == scope.value,
                SecurityRateLimit.key == clean_key,
            )
        ).scalars().first()
    except Exception as exc:
        # The shared table does not exist yet (migration 0016 pending): fall
        # back to the in-process counters and report the degraded mode.
        if not _FALLBACK_STATE.get("warned"):
            _FALLBACK_STATE["warned"] = True
            logger.error(
                "DEPLOYMENT BLOCKER: the shared rate-limit table is unavailable (%s). "
                "Rate limiting falls back to process-local counters until migration 0016 "
                "is applied.",
                exc,
            )
        return _fallback_check(scope, clean_key, policy, record_failure)

    if row is None:
        if not record_failure:
            return LimitDecision(
                allowed=True,
                scope=scope.value,
                key=clean_key,
                attempts=0,
                limit=policy.limit,
                delay_seconds=0.0,
                backend="database",
                degraded=bool(os.getenv("REDIS_URL", "").strip()),
            )
        try:
            with db.begin_nested():
                row = SecurityRateLimit(
                    scope=scope.value,
                    key=clean_key,
                    attempts=0,
                    window_started_at=_iso(now),
                    blocked_until=None,
                    updated_at=_iso(now),
                )
                db.add(row)
                db.flush()
        except IntegrityError:
            row = db.execute(
                select(SecurityRateLimit).where(
                    SecurityRateLimit.scope == scope.value,
                    SecurityRateLimit.key == clean_key,
                )
            ).scalars().first()
            if row is None and commit:
                db.rollback()
                row = db.execute(
                    select(SecurityRateLimit).where(
                        SecurityRateLimit.scope == scope.value,
                        SecurityRateLimit.key == clean_key,
                    )
                ).scalars().first()
            if row is None:
                raise

    blocked_until = _parse(row.blocked_until)
    if blocked_until is not None and blocked_until > now:
        retry_after = int((blocked_until - now).total_seconds())
        return LimitDecision(
            allowed=False,
            scope=scope.value,
            key=clean_key,
            attempts=row.attempts,
            limit=policy.limit,
            retry_after_seconds=retry_after,
            backend="database",
            degraded=bool(os.getenv("REDIS_URL", "").strip()),
        )
    if blocked_until is not None:
        # The lockout has expired: the caller gets a fresh budget, so a
        # legitimate user (or an account an attacker tried to lock out)
        # recovers instead of staying blocked forever.
        row.attempts = 0
        row.blocked_until = None
        row.window_started_at = _iso(now)

    if _parse(row.window_started_at) is None or (
        now - _parse(row.window_started_at)
    ).total_seconds() > policy.window_seconds:
        # The counting window has fully elapsed: start a fresh counter.
        row.attempts = 0
        row.window_started_at = _iso(now)

    if record_failure:
        row.attempts = int(row.attempts or 0) + 1
    row.updated_at = _iso(now)
    db.flush()
    if commit:
        db.commit()

    if not record_failure and row.attempts >= policy.limit:
        # The quota is already exhausted: this attempt is refused before the
        # credential check, exactly like the legacy per-account quota.
        lockout = policy.lockout_seconds or policy.window_seconds
        row.blocked_until = _iso(now + timedelta(seconds=lockout))
        db.flush()
        if commit:
            db.commit()
        return LimitDecision(
            allowed=False,
            scope=scope.value,
            key=clean_key,
            attempts=row.attempts,
            limit=policy.limit,
            retry_after_seconds=lockout,
            backend="database",
            degraded=bool(os.getenv("REDIS_URL", "").strip()),
        )

    if row.attempts > policy.limit:
        lockout = policy.lockout_seconds or policy.window_seconds
        row.blocked_until = _iso(now + timedelta(seconds=lockout))
        db.flush()
        if commit:
            db.commit()
        return LimitDecision(
            allowed=False,
            scope=scope.value,
            key=clean_key,
            attempts=row.attempts,
            limit=policy.limit,
            retry_after_seconds=lockout,
            backend="database",
            degraded=bool(os.getenv("REDIS_URL", "").strip()),
        )

    delay = min(policy.max_delay_seconds, policy.base_delay_seconds * max(0, row.attempts - 1))
    return LimitDecision(
        allowed=True,
        scope=scope.value,
        key=clean_key,
        attempts=row.attempts,
        limit=policy.limit,
        delay_seconds=delay,
        backend="database",
        degraded=bool(os.getenv("REDIS_URL", "").strip()),
    )


def clear_limit(db: Session, scope: LimitScope, key: str) -> None:
    """Clear the counter for a key (used after a successful authentication)."""
    clean_key = (key or "").strip()[:200]
    if not clean_key:
        return
    client = get_redis_client()
    if client is not None:
        try:
            client.delete(f"ratelimit:{scope.value}:{clean_key}")
            client.delete(f"ratelimit:block:{scope.value}:{clean_key}")
            return
        except Exception:
            pass
    from app.db.models import SecurityRateLimit

    db.execute(
        delete(SecurityRateLimit).where(
            SecurityRateLimit.scope == scope.value,
            SecurityRateLimit.key == clean_key,
        )
    )
    db.flush()
