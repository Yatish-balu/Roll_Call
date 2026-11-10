"""Tests for Photographic Quality Gate and T-GATE verification matrix (Prompt N9)."""

from __future__ import annotations

import importlib
import tempfile
import cv2
import numpy as np
import pytest

from tools.quality_gate import check_image_quality
from tools.read_photo_tool import read_photo_tool

rpt_mod = importlib.import_module("tools.read_photo_tool")


@pytest.fixture
def sample_clear_image(tmp_path):
    """Generate a sharp, well-lit synthetic attendance table image."""
    img = np.ones((400, 600), dtype=np.uint8) * 160  # Good brightness (~160)
    # Draw high-contrast text and sharp lines
    cv2.putText(img, "USN: 1MS21CS001  STATUS: PRESENT", (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 0, 2)
    cv2.putText(img, "USN: 1MS21CS002  STATUS: ABSENT", (30, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 0, 2)
    cv2.putText(img, "USN: 1MS21CS003  STATUS: PRESENT", (30, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 0, 2)
    for y in range(50, 350, 60):
        cv2.line(img, (20, y), (580, y), 0, 2)
    for x in (20, 250, 450, 580):
        cv2.line(img, (x, 50), (x, 300), 0, 2)

    path = tmp_path / "clear_sheet.png"
    cv2.imwrite(str(path), img)
    return path


def test_t_gate_clear_photo(sample_clear_image, monkeypatch):
    """Row 1: Clear photo of a printed sheet -> ok = true. Vision API called once."""
    q = check_image_quality(str(sample_clear_image))
    assert q["ok"] is True
    assert q["sharpness"] >= 100.0
    assert 60.0 <= q["brightness"] <= 200.0
    assert len(q["reasons"]) == 0

    # Test read_photo_tool calls vision API when clear
    vision_calls = []
    def fake_gemini(rgb, key, model):
        vision_calls.append(True)
        return '[{"usn": "1MS21CS001", "name": "Alice", "status": "PRESENT", "confidence": 0.95}]'

    monkeypatch.setattr(rpt_mod, "_call_gemini", fake_gemini)
    res = read_photo_tool(str(sample_clear_image), api_key="dummy_key")

    assert len(vision_calls) == 1
    assert len(res.rows) == 1
    assert res.rows[0].usn == "1MS21CS001"


def test_t_gate_blurred_photo(sample_clear_image, monkeypatch, tmp_path):
    """Row 2: Same photo after GaussianBlur -> ok = false, reason mentions sharpness. Vision API called 0 times."""
    original = cv2.imread(str(sample_clear_image), cv2.IMREAD_GRAYSCALE)
    blurred = cv2.GaussianBlur(original, (31, 31), 15.0)

    blur_path = tmp_path / "blurred.png"
    cv2.imwrite(str(blur_path), blurred)

    q = check_image_quality(str(blur_path))
    assert q["ok"] is False
    assert any("sharpness" in r.lower() or "blurry" in r.lower() for r in q["reasons"])

    # Vision API must be called ZERO times
    vision_calls = []
    def fake_gemini(rgb, key, model):
        vision_calls.append(True)
        return "[]"

    monkeypatch.setattr(rpt_mod, "_call_gemini", fake_gemini)
    res = read_photo_tool(str(blur_path), api_key="dummy_key")

    assert len(vision_calls) == 0
    assert res.error is not None
    assert "quality gate" in res.error.lower()


def test_t_gate_dark_photo(sample_clear_image, tmp_path):
    """Row 3: Same photo darkened a lot -> ok = false, reason mentions brightness."""
    original = cv2.imread(str(sample_clear_image), cv2.IMREAD_GRAYSCALE)
    dark = (original * 0.15).astype(np.uint8)  # Mean brightness drops to ~24

    dark_path = tmp_path / "dark.png"
    cv2.imwrite(str(dark_path), dark)

    q = check_image_quality(str(dark_path))
    assert q["ok"] is False
    assert q["brightness"] < 60.0
    assert any("brightness" in r.lower() or "dark" in r.lower() for r in q["reasons"])


def test_t_gate_overexposed_photo(sample_clear_image, tmp_path):
    """Row 4: Same photo overexposed -> ok = false, reason mentions brightness / overexposed."""
    original = cv2.imread(str(sample_clear_image), cv2.IMREAD_GRAYSCALE)
    overexposed = np.clip(original.astype(np.int32) + 100, 0, 255).astype(np.uint8)  # Mean ~250

    over_path = tmp_path / "overexposed.png"
    cv2.imwrite(str(over_path), overexposed)

    q = check_image_quality(str(over_path))
    assert q["ok"] is False
    assert q["brightness"] > 200.0
    assert any("brightness" in r.lower() or "overexposed" in r.lower() for r in q["reasons"])


def test_t_gate_unreadable_file(tmp_path):
    """Row 5: Unreadable file (not an image) -> Clear error, no crash."""
    bad_file = tmp_path / "corrupt.png"
    bad_file.write_bytes(b"NOT_AN_IMAGE_RANDOM_TEXT_DATA_123456789")

    q = check_image_quality(str(bad_file))
    assert q["ok"] is False
    assert any("unreadable" in r.lower() or "not a valid image" in r.lower() for r in q["reasons"])
