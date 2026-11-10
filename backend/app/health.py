"""Shared attendance health band calculation (Prompt N12 / Rule D5 / T-BAND)."""

from __future__ import annotations

from typing import Union

try:
    from config import HEALTH_BAND_GREEN_THRESHOLD, HEALTH_BAND_YELLOW_THRESHOLD
except ImportError:
    from app.config import HEALTH_BAND_GREEN_THRESHOLD, HEALTH_BAND_YELLOW_THRESHOLD


def health_band(percent: Union[int, float]) -> str:
    """Classify attendance percentage into standard tri-color health bands.

    Matrix (T-BAND):
    - Percent > 85.0: Green (e.g. 100.0, 85.1)
    - 70.0 <= Percent <= 85.0: Yellow (e.g. 85.0, 70.0)
    - Percent < 70.0: Red (e.g. 69.9, 0.0)
    """
    p = float(percent)
    if p > HEALTH_BAND_GREEN_THRESHOLD:
        return "Green"
    elif p >= HEALTH_BAND_YELLOW_THRESHOLD:
        return "Yellow"
    else:
        return "Red"

