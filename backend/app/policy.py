"""24-Hour Edit Lock Policy (Prompt N5 / Playbook Rule D1, D2, D11).

Pure policy functions for session editability.
No database or LLM dependencies.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Union


def _parse_utc_datetime(val: Union[str, datetime]) -> datetime:
    """Parse string or datetime to timezone-aware UTC datetime."""
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    
    clean = str(val).strip()
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    
    dt = datetime.fromisoformat(clean)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def editable_until(session_created_at_utc: Union[str, datetime]) -> datetime:
    """Return the UTC datetime exactly 24 hours after session creation."""
    created = _parse_utc_datetime(session_created_at_utc)
    return created + timedelta(hours=24)


def is_editable(
    session_created_at_utc: Union[str, datetime],
    role: str,
    now_utc: Optional[datetime] = None,
) -> bool:
    """
    Evaluate whether a session is editable based on caller's role and session age.
    
    Rules (T-LOCK):
    - Admin: Always editable (True).
    - Teacher: Editable if now_utc - created_at_utc <= 24 hours.
    - Negative age (clock skew / future created_at): counts as editable (True), no crash.
    """
    clean_role = (role.value if hasattr(role, "value") else str(role)).strip().upper()
    if clean_role == "ADMIN" or clean_role == "ROLE.ADMIN" or clean_role.endswith(".ADMIN"):
        return True

    now = now_utc if now_utc is not None else datetime.now(timezone.utc)
    now = _parse_utc_datetime(now)
    created = _parse_utc_datetime(session_created_at_utc)

    # Negative age / future time -> editable (True)
    if now < created:
        return True

    age = now - created
    return age <= timedelta(hours=24)
