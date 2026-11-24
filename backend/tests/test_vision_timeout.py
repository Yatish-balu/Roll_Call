"""Vision calls must be time-bounded so image uploads cannot hang indefinitely."""

import pytest

from app.services import exam_vision, vision_client


def test_vision_timeout_defaults_to_20_seconds(monkeypatch):
    monkeypatch.delenv("VISION_TIMEOUT_MS", raising=False)
    assert vision_client.vision_timeout_ms() == 20000


def test_vision_timeout_is_configurable_and_clamped(monkeypatch):
    monkeypatch.setenv("VISION_TIMEOUT_MS", "8000")
    assert vision_client.vision_timeout_ms() == 8000

    monkeypatch.setenv("VISION_TIMEOUT_MS", "1")
    assert vision_client.vision_timeout_ms() == 5000

    monkeypatch.setenv("VISION_TIMEOUT_MS", "not-a-number")
    assert vision_client.vision_timeout_ms() == 20000


def test_form_b_scan_tries_at_most_two_models(monkeypatch):
    """The legacy SDK must not repeat the same model attempts after modern ones."""
    assert exam_vision.VISION_MODEL_ATTEMPTS == 2
