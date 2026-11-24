"""Shared Gemini Vision client with a bounded timeout and no retry storms.

Uploads used to make up to eight sequential vision calls (four model names via
the modern SDK, then the same four again via the legacy SDK). When the first
model was slow or unavailable, the UI sat at "Uploading… 0%" while the request
blocked. Every vision call now uses one client with a short, configurable
timeout and a single attempt; callers may still try one fallback model.
"""

from __future__ import annotations

import os
from typing import Any


def vision_timeout_ms() -> int:
    """Per-request Gemini timeout in milliseconds (default 20 seconds)."""
    try:
        value = int(os.getenv("VISION_TIMEOUT_MS", "20000").strip())
    except ValueError:
        value = 20000
    return max(5000, min(value, 120000))


def create_vision_client(api_key: str) -> Any:
    """Return a google-genai Client whose calls cannot hang the upload pipeline."""
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=vision_timeout_ms(),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
