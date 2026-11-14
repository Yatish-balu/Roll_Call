"""Colour-band computation for class health (D5, N12).

Green above 85, yellow 70 to 85 inclusive, red below 70.
Bands are class health, not eligibility.
"""

from __future__ import annotations

from app.config import BAND_GREEN_ABOVE_PERCENT, BAND_YELLOW_FROM_PERCENT


def health_band(percent: float | None) -> str:
    """Return the colour band for an attendance percentage.

    * ``percent`` is ``None`` or unparseable -> ``"red"``
    * ``percent > BAND_GREEN_ABOVE_PERCENT`` (strictly above 85.0) -> ``"green"``
    * ``BAND_YELLOW_FROM_PERCENT <= percent <= BAND_GREEN_ABOVE_PERCENT`` -> ``"yellow"``
    * ``percent < BAND_YELLOW_FROM_PERCENT`` -> ``"red"``

    Boundary note: 85.0 is yellow (green requires strictly above 85). 70.0 is
    yellow (red requires strictly below 70).
    """
    if percent is None:
        return "red"
    try:
        pct = float(percent)
    except (TypeError, ValueError):
        return "red"

    if pct > BAND_GREEN_ABOVE_PERCENT:
        return "green"
    if pct >= BAND_YELLOW_FROM_PERCENT:
        return "yellow"
    return "red"


__all__ = ["health_band"]
