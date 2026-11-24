"""N9: image quality gate unit tests.

The gate runs BEFORE the vision model: a blurry or badly lit photo must be
rejected without ever reaching OCR. These tests use real synthetic images so
the Laplacian-variance and brightness measurements are exercised, not mocked.
"""

from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from tools.quality_gate import (  # noqa: E402
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    SHARPNESS_THRESHOLD,
    check_image_quality,
    quality_gate_rejection_response,
)


def _write(path, image):
    assert cv2.imwrite(str(path), image)
    return str(path)


def test_missing_file_is_rejected_without_raising(tmp_path):
    result = check_image_quality(str(tmp_path / "nope.jpg"))
    assert result["ok"] is False
    assert result["reasons"]
    assert result["sharpness"] == 0.0


def test_sharp_well_lit_image_passes(tmp_path):
    # High-frequency checkerboard: high Laplacian variance, mid brightness.
    image = np.indices((400, 400)).sum(axis=0) % 2
    image = (image * 255).astype(np.uint8)
    result = check_image_quality(_write(tmp_path / "sharp.png", image))
    assert result["ok"] is True, result
    assert result["sharpness"] >= SHARPNESS_THRESHOLD
    assert BRIGHTNESS_MIN <= result["brightness"] <= BRIGHTNESS_MAX


def test_uniform_image_fails_the_sharpness_check(tmp_path):
    # A flat grey image has near-zero detail (blur/blank sheet).
    image = np.full((400, 400), 128, dtype=np.uint8)
    result = check_image_quality(_write(tmp_path / "flat.png", image))
    assert result["ok"] is False
    assert result["sharpness"] < SHARPNESS_THRESHOLD
    assert any("blurry" in reason for reason in result["reasons"])


def test_too_dark_image_fails_the_lighting_check(tmp_path):
    image = np.indices((400, 400)).sum(axis=0) % 2
    image = (image * 20).astype(np.uint8)  # sharp but almost black
    result = check_image_quality(_write(tmp_path / "dark.png", image))
    assert result["ok"] is False
    assert result["brightness"] < BRIGHTNESS_MIN
    assert any("dark" in reason for reason in result["reasons"])


def test_overexposed_image_fails_the_lighting_check(tmp_path):
    # A blown-out sheet: high-frequency contrast keeps it sharp, but the mean
    # (252.5) must exceed the generous 250 ceiling.
    image = np.full((400, 400), 255, dtype=np.uint8)
    image[::2] = 250
    result = check_image_quality(_write(tmp_path / "bright.png", image))
    assert result["ok"] is False
    assert result["brightness"] > BRIGHTNESS_MAX
    assert any("overexposed" in reason for reason in result["reasons"])


def test_rejection_body_uses_the_standard_error_envelope():
    body = quality_gate_rejection_response(
        10.0, 30.0, ["Image is blurry."], {"sharpness_min": 100.0}
    )
    assert body == {
        "error": {
            "code": "QUALITY_REJECTED",
            "message": "Photo not clear enough. Please retake.",
        }
    }
