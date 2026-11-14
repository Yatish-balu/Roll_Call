"""24-hour lock policy for attendance edits (N5).

Pure functions: no database calls, no LLM calls. Deterministic given inputs.
Every edit decision funnels through :func:`is_editable` so the LLM and React
never compute the lock themselves.

Rules (from docs/DECISIONS.md D11/D12):
* Teacher: now - created_at <= LOCK_HOURS is editable.
* Admin: always editable.
* Negative age (clock error / future created_at) counts as editable, no crash.
* Times are UTC only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import LOCK_HOURS


def _to_utc_dt(value: str | datetime | None) -> datetime | None:
    """Parse an ISO-8601 UTC timestamp (with or without trailing Z) into an aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def editable_until(created_at_utc: str | datetime | None) -> str | None:
    """Return the ISO-8601 UTC timestamp when edits expire (created_at + LOCK_HOURS).

    Returns ``None`` when ``created_at_utc`` is missing or unparseable.
    """
    dt = _to_utc_dt(created_at_utc)
    if dt is None:
        return None
    return (dt + timedelta(hours=LOCK_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_editable(
    session_created_at_utc: str | datetime | None,
    role: str,
    now_utc: str | datetime | None = None,
) -> bool:
    """Return ``True`` if the session may be edited by *role* at *now_utc*.

    * Admin: always ``True``.
    * Teacher: editable when age (now - created_at) is at most LOCK_HOURS.
    * Negative age (future created_at / clock error) counts as editable.
    * Missing or unparseable ``created_at_utc`` returns ``False`` for a teacher.
    """
    role_clean = (role or "").strip().upper()
    if role_clean == "ADMIN":
        return True

    created_dt = _to_utc_dt(session_created_at_utc)
    if created_dt is None:
        return False

    now = _to_utc_dt(now_utc) if now_utc is not None else datetime.now(timezone.utc)
    age = now - created_dt
    return age <= timedelta(hours=LOCK_HOURS)


def lock_hours() -> int:
    """Return the configured lock window in hours."""
    return int(LOCK_HOURS)


__all__ = ["is_editable", "editable_until", "lock_hours"]
