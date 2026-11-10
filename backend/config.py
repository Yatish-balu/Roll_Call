"""System configuration constants for RollCall AI."""

from __future__ import annotations

# Quality Gate Thresholds (Prompt N9 / SPEC 4.4 / T-GATE)
QUALITY_SHARPNESS_MIN: float = 100.0
QUALITY_BRIGHTNESS_MIN: float = 60.0
QUALITY_BRIGHTNESS_MAX: float = 200.0

# Student Attendance Health Bands (Prompt N12 / Rule D5 / T-BAND)
HEALTH_BAND_GREEN_THRESHOLD: float = 85.0
HEALTH_BAND_YELLOW_THRESHOLD: float = 70.0

# Defaulter Thresholds (Prompt N10 / Rule D9 / T-DEF)
DEFAULTER_THRESHOLD_DEFAULT: float = 75.0

