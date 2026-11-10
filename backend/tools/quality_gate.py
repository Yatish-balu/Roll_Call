"""Blur and lighting quality gate for attendance sheet photos (Prompt N9 / Rule D3 / T-GATE).

Evaluates image sharpness using Laplacian variance and lighting using mean luminance.
This is strictly a photographic quality check to ensure OCR readability.
Never refer to this tool as anti-spoofing.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Union
import cv2
import numpy as np

try:
    from config import QUALITY_BRIGHTNESS_MAX, QUALITY_BRIGHTNESS_MIN, QUALITY_SHARPNESS_MIN
except ImportError:
    from app.config import QUALITY_BRIGHTNESS_MAX, QUALITY_BRIGHTNESS_MIN, QUALITY_SHARPNESS_MIN


def check_image_quality(
    image_input: Union[str, bytes, np.ndarray],
    sharpness_min: float = QUALITY_SHARPNESS_MIN,
    brightness_min: float = QUALITY_BRIGHTNESS_MIN,
    brightness_max: float = QUALITY_BRIGHTNESS_MAX,
) -> Dict[str, Any]:
    """Inspect an image for sharpness and brightness before running OCR or Vision extraction.

    Returns:
        dict: {
            "ok": bool,
            "sharpness": float,
            "brightness": float,
            "reasons": list of strings explaining failures if not ok,
            "thresholds": dict of applied thresholds,
        }
    """
    thresholds = {
        "sharpness_min": float(sharpness_min),
        "brightness_min": float(brightness_min),
        "brightness_max": float(brightness_max),
    }

    gray: Optional[np.ndarray] = None

    try:
        if isinstance(image_input, np.ndarray):
            if len(image_input.shape) == 3:
                gray = cv2.cvtColor(image_input, cv2.COLOR_BGR2GRAY)
            else:
                gray = image_input
        elif isinstance(image_input, (bytes, bytearray)):
            nparr = np.frombuffer(image_input, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                gray = img
        elif isinstance(image_input, str):
            if not os.path.exists(image_input) or os.path.isdir(image_input):
                return {
                    "ok": False,
                    "sharpness": 0.0,
                    "brightness": 0.0,
                    "reasons": [f"File not found or unreadable: '{image_input}'."],
                    "thresholds": thresholds,
                }
            gray = cv2.imread(image_input, cv2.IMREAD_GRAYSCALE)

        if gray is None or gray.size == 0:
            return {
                "ok": False,
                "sharpness": 0.0,
                "brightness": 0.0,
                "reasons": ["Unreadable file: The provided file is not a valid image."],
                "thresholds": thresholds,
            }

        # 1. Sharpness calculation: variance of the Laplacian
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        sharpness = float(laplacian.var())

        # 2. Brightness calculation: mean pixel intensity
        brightness = float(np.mean(gray))

        reasons: List[str] = []

        if sharpness < sharpness_min:
            reasons.append(
                f"Image sharpness ({sharpness:.1f}) is below the required minimum of {sharpness_min:.1f}. "
                "The image is too blurry. Please retake the photo with a steady camera."
            )

        if brightness < brightness_min:
            reasons.append(
                f"Image brightness ({brightness:.1f}) is below the minimum threshold of {brightness_min:.1f}. "
                "The image is too dark. Please take the photo in better lighting."
            )
        elif brightness > brightness_max:
            reasons.append(
                f"Image brightness ({brightness:.1f}) exceeds the maximum threshold of {brightness_max:.1f}. "
                "The image is overexposed. Please avoid direct glare or flash."
            )

        is_ok = len(reasons) == 0

        return {
            "ok": is_ok,
            "sharpness": round(sharpness, 2),
            "brightness": round(brightness, 2),
            "reasons": reasons,
            "thresholds": thresholds,
        }

    except Exception as exc:
        return {
            "ok": False,
            "sharpness": 0.0,
            "brightness": 0.0,
            "reasons": [f"Error analyzing image quality: {str(exc)}"],
            "thresholds": thresholds,
        }

