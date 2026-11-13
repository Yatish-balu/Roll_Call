"""Named application constants (N3, N4, N5, N9, N10, N12, N15).

Single source of truth for every numeric threshold, lock duration, upload
limit, and colour-band boundary used by the backend. The frontend reads these
through ``GET /api/meta/config`` and never hard-codes them.
"""

from __future__ import annotations

import os
from typing import Final


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (ValueError, TypeError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Edit lock policy (N5)
# ---------------------------------------------------------------------------
LOCK_HOURS: Final[int] = _env_int("EDIT_LOCK_HOURS", 24)
"""Hours after session creation until editing locks for a teacher."""

ADMIN_OVERRIDE_ALLOWED: Final[bool] = True
"""Admin may override an edit lock with a reason text (D12)."""

# ---------------------------------------------------------------------------
# Colour bands for class health (D5, N12)
# Green above 85, yellow 70 to 85 inclusive, red below 70.
# ---------------------------------------------------------------------------
BAND_GREEN_ABOVE_PERCENT: Final[float] = _env_float("BAND_GREEN_ABOVE_PERCENT", 85.0)
BAND_YELLOW_FROM_PERCENT: Final[float] = _env_float("BAND_YELLOW_FROM_PERCENT", 70.0)

# ---------------------------------------------------------------------------
# Defaulter threshold (N10)
# Defaulter = strictly below threshold (75.0 is NOT a defaulter).
# ---------------------------------------------------------------------------
DEFAULTER_THRESHOLD_PERCENT: Final[float] = _env_float("DEFAULTER_THRESHOLD_PERCENT", 75.0)
DEFAULTER_REQUIRED_PERCENT: Final[float] = _env_float("DEFAULTER_REQUIRED_PERCENT", 75.0)

# ---------------------------------------------------------------------------
# Upload limits (N15)
# ---------------------------------------------------------------------------
MAX_IMAGE_UPLOAD_BYTES: Final[int] = _env_int("MAX_IMAGE_UPLOAD_BYTES", 10 * 1024 * 1024)
MAX_CSV_UPLOAD_BYTES: Final[int] = _env_int("MAX_CSV_UPLOAD_BYTES", 5 * 1024 * 1024)

# ---------------------------------------------------------------------------
# Chat confirmation (D13)
# ---------------------------------------------------------------------------
CHAT_CONFIRM_EXPIRY_MINUTES: Final[int] = _env_int("CHAT_CONFIRM_EXPIRY_MINUTES", 5)

# ---------------------------------------------------------------------------
# Access token TTL (N2)
# ---------------------------------------------------------------------------
ACCESS_TOKEN_TTL_MINUTES: Final[int] = _env_int("ACCESS_TOKEN_TTL_MINUTES", 480)

__all__ = [
    "LOCK_HOURS",
    "ADMIN_OVERRIDE_ALLOWED",
    "BAND_GREEN_ABOVE_PERCENT",
    "BAND_YELLOW_FROM_PERCENT",
    "DEFAULTER_THRESHOLD_PERCENT",
    "DEFAULTER_REQUIRED_PERCENT",
    "MAX_IMAGE_UPLOAD_BYTES",
    "MAX_CSV_UPLOAD_BYTES",
    "CHAT_CONFIRM_EXPIRY_MINUTES",
    "ACCESS_TOKEN_TTL_MINUTES",
]
