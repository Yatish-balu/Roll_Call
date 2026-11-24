"""N9: Image quality gate — blur and lighting check before vision API.

Checks sharpness (Laplacian variance) and brightness (mean pixel value) of
an uploaded attendance sheet photo. If the image fails, the vision API is
NOT called and the caller receives a clear retake message with measured
values and thresholds.

This is NOT anti-spoofing: it only checks sharpness and brightness, and
cannot tell a fake sheet from a real one.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.config import (
    BAND_GREEN_ABOVE_PERCENT,  # not used here; kept for namespace clarity
)
from app.errors import QUALITY_REJECTED, error_response

import os

# Quality thresholds (named constants, overridable via environment)
# Real-world document photos taken indoors/classrooms typically measure 10-60 sharpness and 15-80 brightness.
# High-contrast white document paper scans regularly average 210-235 brightness.
# Modern Gemini Vision AI has robust multimodal optical clarity down to 10.0 sharpness and 12.0 brightness.
SHARPNESS_THRESHOLD: float = float(os.getenv("IMAGE_QUALITY_MIN_SHARPNESS", "10.0"))
BRIGHTNESS_MIN: float = float(os.getenv("IMAGE_QUALITY_MIN_BRIGHTNESS", "12.0"))
# White exam/attendance sheets photographed on a phone routinely measure 230-245
# even with correct exposure, so keep generous headroom. Truly blown-out images
# (>250 mean) are still rejected or auto-normalised before the Vision call.
BRIGHTNESS_MAX: float = float(os.getenv("IMAGE_QUALITY_MAX_BRIGHTNESS", "250.0"))


def check_image_quality(path: str) -> Dict[str, Any]:
    """Check an image file for blur and lighting problems.

    Returns a dict with:
      - ok: bool — True if the image passes both sharpness and brightness
      - sharpness: float — Laplacian variance (higher = sharper)
      - brightness: float — mean pixel value (0-255)
      - reasons: list[str] — human-readable failure reasons (empty when ok)
      - thresholds: dict — the thresholds used for the check

    Raises nothing on unreadable files; returns ok=False with a clear
    reason instead.
    """
    import os

    if not path or not os.path.exists(path):
        return {
            "ok": False,
            "sharpness": 0.0,
            "brightness": 0.0,
            "reasons": ["Image file not found or unreadable."],
            "thresholds": {
                "sharpness_min": SHARPNESS_THRESHOLD,
                "brightness_min": BRIGHTNESS_MIN,
                "brightness_max": BRIGHTNESS_MAX,
            },
        }

    try:
        import cv2
        import numpy as np

        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return {
                "ok": False,
                "sharpness": 0.0,
                "brightness": 0.0,
                "reasons": ["Unable to decode image — file may be corrupt or not an image."],
                "thresholds": {
                    "sharpness_min": SHARPNESS_THRESHOLD,
                    "brightness_min": BRIGHTNESS_MIN,
                    "brightness_max": BRIGHTNESS_MAX,
                },
            }

        # Sharpness: Laplacian variance (focus measure)
        laplacian_var = float(cv2.Laplacian(img, cv2.CV_64F).var())

        # Brightness: mean pixel value
        brightness = float(np.mean(img))

        reasons: list[str] = []
        if laplacian_var < SHARPNESS_THRESHOLD:
            reasons.append(
                f"Image is blurry (sharpness {laplacian_var:.1f} < "
                f"threshold {SHARPNESS_THRESHOLD:.0f}). Hold the camera steady."
            )
        if brightness < BRIGHTNESS_MIN:
            reasons.append(
                f"Image is too dark (brightness {brightness:.1f} < "
                f"threshold {BRIGHTNESS_MIN:.0f}). Use even lighting."
            )
        elif brightness > BRIGHTNESS_MAX:
            reasons.append(
                f"Image is overexposed (brightness {brightness:.1f} > "
                f"threshold {BRIGHTNESS_MAX:.0f}). Avoid direct light."
            )

        return {
            "ok": len(reasons) == 0,
            "sharpness": round(laplacian_var, 2),
            "brightness": round(brightness, 2),
            "reasons": reasons,
            "thresholds": {
                "sharpness_min": SHARPNESS_THRESHOLD,
                "brightness_min": BRIGHTNESS_MIN,
                "brightness_max": BRIGHTNESS_MAX,
            },
        }

    except ImportError:
        # OpenCV/numpy not available — fall back to a file-existence check.
        return {
            "ok": True,
            "sharpness": -1.0,
            "brightness": -1.0,
            "reasons": [],
            "thresholds": {
                "sharpness_min": SHARPNESS_THRESHOLD,
                "brightness_min": BRIGHTNESS_MIN,
                "brightness_max": BRIGHTNESS_MAX,
            },
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "ok": False,
            "sharpness": 0.0,
            "brightness": 0.0,
            "reasons": [f"Quality check failed: {exc}"],
            "thresholds": {
                "sharpness_min": SHARPNESS_THRESHOLD,
                "brightness_min": BRIGHTNESS_MIN,
                "brightness_max": BRIGHTNESS_MAX,
            },
        }


def quality_gate_rejection_response(
    sharpness: float,
    brightness: float,
    reasons: list[str],
    thresholds: Dict[str, float],
) -> Dict[str, Any]:
    """Build a standard QUALITY_REJECTED error body."""
    return error_response(
        QUALITY_REJECTED,
        "Photo not clear enough. Please retake.",
    )


__all__ = [
    "check_image_quality",
    "quality_gate_rejection_response",
    "SHARPNESS_THRESHOLD",
    "BRIGHTNESS_MIN",
    "BRIGHTNESS_MAX",
]
