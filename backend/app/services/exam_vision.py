"""Gemini Vision AI service specifically tuned for DSCE Exam Form-B attendance sheets."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

EXAM_FORM_B_PROMPT = """You are an OCR assistant processing an EXAM ATTENDANCE FORM-B photograph from an Indian engineering college (DSCE / VTU format).

The sheet has columns:
1. Sl. No
2. USN (e.g. 1DS23CY037)
3. STUDENT NAME
4. Exam Date & Subject columns (e.g. 02-11-2026 / 22CY72) containing signature boxes.

TASK:
Examine each student row and inspect the attendance/signature box for the exam:
- If the box contains a HANDWRITTEN SIGNATURE (any cursive writing or signed mark) → status is "PRESENT"
- If the box contains "Ab", "AB", "A", is crossed out, or is completely BLANK / EMPTY → status is "ABSENT"
- If illegible or cut off → status is "UNREVIEWED"

Return a strictly valid JSON array — nothing else, no markdown fences, no extra text.
Each element must have EXACTLY these keys:
  "sl_no"      : integer (e.g. 1)
  "usn"        : string (e.g. "1DS23CY037")
  "name"       : string (student full name)
  "status"     : "PRESENT", "ABSENT", or "UNREVIEWED"
  "confidence" : float between 0.0 and 1.0 (confidence in your assessment)

Example:
[
  {"sl_no": 1, "usn": "1DS23CY037", "name": "Nikhita Thupakula", "status": "PRESENT", "confidence": 0.98},
  {"sl_no": 4, "usn": "1DS23CY040", "name": "Pragathi B S", "status": "ABSENT", "confidence": 0.96}
]
"""

DEFAULT_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODELS = ("gemini-3.8-flash", "gemini-3.5-flash", "gemini-2.5-flash")


def scan_form_b_image(image_bytes: bytes) -> List[Dict[str, Any]]:
    """Scan Form-B photo using image normalization and Google Gemini Vision AI."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("GEMINI_API_KEY not configured. Cannot run vision scan.")
        return []

    # 1. Preprocess and normalize image (orientation, contrast, bounded scaling)
    processed_bytes = image_bytes
    try:
        from app.services.image_pipeline import validate_and_preprocess_image
        processed_bytes, _meta = validate_and_preprocess_image(image_bytes, max_dimension=1600, jpeg_quality=85)
    except Exception as e:
        logger.debug("Image preprocessing bypassed, using original bytes: %s", e)
        processed_bytes = image_bytes

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
    except Exception as e:
        logger.error("Failed to configure google.generativeai: %s", e)
        return []

    # Encode image
    b64 = base64.b64encode(processed_bytes).decode("utf-8")
    mime = "image/jpeg"
    if processed_bytes.startswith(b"\x89PNG"):
        mime = "image/png"

    models_to_try = [DEFAULT_MODEL] + list(FALLBACK_MODELS)
    last_err = None

    for m in models_to_try:
        try:
            model_obj = genai.GenerativeModel(m)
            response = model_obj.generate_content([
                {"mime_type": mime, "data": b64},
                EXAM_FORM_B_PROMPT,
            ])
            text = (response.text or "").strip()
            # Clean markdown code blocks if wrapped
            if text.startswith("```"):
                text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
                text = re.sub(r"\n?```$", "", text).strip()

            parsed = json.loads(text)
            if isinstance(parsed, list):
                valid_rows = []
                for item in parsed:
                    if isinstance(item, dict) and "usn" in item:
                        raw_status = str(item.get("status", "ABSENT")).upper()
                        status = "PRESENT" if raw_status in ("PRESENT", "P", "1") else "ABSENT"
                        valid_rows.append({
                            "sl_no": int(item.get("sl_no", len(valid_rows) + 1)),
                            "usn": str(item["usn"]).strip().upper(),
                            "name": str(item.get("name", "")).strip(),
                            "status": status,
                            "confidence": float(item.get("confidence", 0.9)),
                        })
                return valid_rows
        except Exception as e:
            last_err = e
            logger.warning("Gemini model %s failed: %s", m, e)

    logger.error("All Gemini vision models failed for Form-B scan: %s", last_err)
    return []
