"""Gemini Vision AI service specifically tuned for DSCE Exam Form-B attendance sheets.

Supports multi-exam column isolation, subject code / date / session-slot disambiguation,
and bottom invigilator verification tally extraction.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Preferred models in priority order for Vision OCR. Only the first two are
# tried: a longer chain multiplied latency when a model was slow/unavailable.
PREFERRED_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.8-flash",
    "gemini-flash-latest",
)
VISION_MODEL_ATTEMPTS = 2


class ExamScanResultList(list):
    """List subclass that retains extracted metadata (tally, detected columns)

    while remaining 100% compatible with existing list-based consumers and tests.
    """

    def __init__(
        self,
        rows: Optional[List[Dict[str, Any]]] = None,
        tally: Optional[Dict[str, Any]] = None,
        detected_columns: Optional[List[Dict[str, Any]]] = None,
        target_column_matched: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(rows or [])
        self.tally = tally or {}
        self.detected_columns = detected_columns or []
        self.target_column_matched = target_column_matched or {}


def build_exam_form_b_prompt(
    target_subject_code: Optional[str] = None,
    target_date: Optional[str] = None,
    target_start_time: Optional[str] = None,
    target_session_slot: Optional[str] = None,
    target_room_no: Optional[str] = None,
    target_semester: Optional[Any] = None,
) -> str:
    """Construct an explicit prompt guiding Gemini Vision to extract the exact target column

    from multi-exam Form-B sheets.
    """
    slot_info = target_session_slot or ""
    if not slot_info and target_start_time:
        try:
            hour = int(str(target_start_time).split(":")[0])
            slot_info = "Forenoon / Morning (FN)" if hour < 13 else "Afternoon / Evening (AN)"
        except Exception:
            slot_info = str(target_start_time)

    date_variants = ""
    if target_date:
        parts = re.split(r"[-/]", str(target_date).strip())
        if len(parts) == 3:
            if len(parts[0]) == 4:  # YYYY-MM-DD -> DD-MM-YYYY
                date_variants = f"{parts[2]}-{parts[1]}-{parts[0]} (or {target_date})"
            else:
                date_variants = f"{target_date}"
        else:
            date_variants = str(target_date)

    prompt = f"""You are an expert OCR assistant processing an EXAM ATTENDANCE FORM-B photograph from an Indian engineering college (DSCE / VTU format).

A single physical Form-B sheet typically contains multiple exam columns (up to 5 columns) across different dates and sessions (Forenoon / Morning and Afternoon / Evening).

TARGET EXAM TO EXTRACT:
- Target Subject Code: {target_subject_code or "Any / First completed exam column"}
- Target Date: {date_variants or "Any"}
- Target Session Slot: {slot_info or "Any (FN or AN)"}
- Target Room: {target_room_no or "Any"}
- Target Semester: {target_semester or "Any"}

RULES FOR MULTI-EXAM COLUMN EXTRACTION:
1. Examine the column headers across the table. Each column contains a Date and a Subject Code (e.g., '02-11-2026 / 22CY72', '03-11-2026 / 22CY741').
2. Locate the column matching Target Subject Code '{target_subject_code or ""}'.
   - If two columns occur on the same date: the first (leftmost) column for that date represents the Forenoon / Morning (FN) exam; the second column represents the Afternoon / Evening (AN) exam. Pick the column corresponding to the target session.
3. Once the matching column is identified, scan student signatures ONLY from that specific column. Do not mix or read marks from any other column!
   - If the cell in this column has a handwritten signature or signed mark -> status is "PRESENT"
   - If the cell contains "Ab", "AB", "A", is crossed out, or is BLANK / EMPTY -> status is "ABSENT"
   - If illegible or cut off -> status is "UNREVIEWED"
4. Also extract the bottom verification tally for this target column:
   - "No. of Students Present" (e.g. 32 or 30+1)
   - "No. of Students Absent" (e.g. "NIL" or "01")
   - "Initials of Invigilator" (e.g. "RK", "DVS", "VD")

Return a strictly valid JSON object — nothing else, no markdown fences:
{{
  "detected_columns": [
    {{"column_index": 1, "date": "02-11-2026", "subject_code": "22CY72", "slot": "FN"}},
    {{"column_index": 2, "date": "02-11-2026", "subject_code": "22CY73", "slot": "AN"}},
    {{"column_index": 3, "date": "03-11-2026", "subject_code": "22CY741", "slot": "FN"}}
  ],
  "target_column_matched": {{"column_index": 3, "subject_code": "{target_subject_code or ""}"}},
  "tally": {{
    "students_present": 31,
    "students_absent": 1,
    "invigilator_initials": "DVS"
  }},
  "records": [
    {{"sl_no": 1, "usn": "1DS23CY037", "name": "Nikhita Thupakula", "status": "PRESENT", "confidence": 0.98}},
    {{"sl_no": 4, "usn": "1DS23CY040", "name": "Pragathi B S", "status": "ABSENT", "confidence": 0.96}}
  ]
}}
"""
    return prompt


def scan_form_b_image(
    image_bytes: bytes,
    target_subject_code: Optional[str] = None,
    target_date: Optional[str] = None,
    target_start_time: Optional[str] = None,
    target_session_slot: Optional[str] = None,
    target_room_no: Optional[str] = None,
    target_semester: Optional[Any] = None,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """Scan Form-B photo using image normalization and Google Gemini Vision AI.

    Disambiguates multi-exam columns when subject_code or date or slot is provided.
    Returns an ExamScanResultList containing all parsed student rows and metadata.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("GEMINI_API_KEY not configured. Cannot run vision scan.")
        return ExamScanResultList()

    # 1. Preprocess and normalize image (orientation, contrast, bounded scaling)
    processed_bytes = image_bytes
    try:
        from app.services.image_pipeline import validate_and_preprocess_image

        processed_bytes, _meta = validate_and_preprocess_image(
            image_bytes, max_dimension=1280, jpeg_quality=80
        )
    except Exception as e:
        logger.debug("Image preprocessing bypassed, using original bytes: %s", e)
        processed_bytes = image_bytes

    # Build targeted prompt
    prompt = build_exam_form_b_prompt(
        target_subject_code=target_subject_code,
        target_date=target_date,
        target_start_time=target_start_time,
        target_session_slot=target_session_slot,
        target_room_no=target_room_no,
        target_semester=target_semester,
    )

    # Encode image
    b64 = base64.b64encode(processed_bytes).decode("utf-8")
    mime = "image/png" if processed_bytes.startswith(b"\x89PNG") else "image/jpeg"

    # Try the modern google.genai client with a bounded timeout. The legacy SDK
    # is only used when the modern one cannot be imported at all - retrying the
    # same models through a second SDK only doubled the wait.
    raw_response_text = None
    last_err = None
    modern_sdk_available = False

    try:
        from app.services.vision_client import create_vision_client

        client = create_vision_client(api_key)
        modern_sdk_available = True
        from PIL import Image
        import io
        pil_img = Image.open(io.BytesIO(processed_bytes))
        scan_started = time.monotonic()

        for model_name in PREFERRED_MODELS[:VISION_MODEL_ATTEMPTS]:
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=[pil_img, prompt],
                )
                if resp and resp.text:
                    raw_response_text = resp.text.strip()
                    logger.info(
                        "Form-B scan succeeded with model %s in %.2fs",
                        model_name,
                        time.monotonic() - scan_started,
                    )
                    break
            except Exception as exc:
                last_err = exc
                err_str = str(exc)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    logger.warning("Model %s hit rate-limit (429), switching to next model.", model_name)
                else:
                    logger.debug("Model %s failed: %s", model_name, exc)
    except Exception as genai_err:
        logger.debug("google.genai SDK unavailable or error: %s, falling back to google.generativeai", genai_err)

    if not raw_response_text and not modern_sdk_available:
        try:
            import google.generativeai as legacy_genai
            legacy_genai.configure(api_key=api_key)

            for model_name in PREFERRED_MODELS[:VISION_MODEL_ATTEMPTS]:
                try:
                    model_obj = legacy_genai.GenerativeModel(model_name)
                    response = model_obj.generate_content([
                        {"mime_type": mime, "data": b64},
                        prompt,
                    ])
                    if response and response.text:
                        raw_response_text = response.text.strip()
                        logger.info("Successfully scanned Form-B using legacy genai with model: %s", model_name)
                        break
                except Exception as exc:
                    last_err = exc
                    logger.debug("Legacy genai model %s failed: %s", model_name, exc)
        except Exception as legacy_err:
            logger.error("Failed to run legacy genai: %s", legacy_err)

    if not raw_response_text:
        logger.error("All Gemini vision models failed for Form-B scan: %s", last_err)
        return ExamScanResultList()

    # Parse JSON output
    cleaned_text = raw_response_text
    if cleaned_text.startswith("```"):
        cleaned_text = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned_text)
        cleaned_text = re.sub(r"\n?```$", "", cleaned_text).strip()

    try:
        parsed = json.loads(cleaned_text)
    except Exception as parse_err:
        logger.warning("Could not parse Gemini JSON response directly: %s. Raw text: %s", parse_err, cleaned_text[:200])
        # Attempt regex extraction of array if wrapped in other text
        match = re.search(r"(\[.*\]|\{.*\})", cleaned_text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1))
            except Exception:
                return ExamScanResultList()
        else:
            return ExamScanResultList()

    tally_data = {}
    detected_cols = []
    target_matched = {}
    raw_records = []

    if isinstance(parsed, dict):
        tally_data = parsed.get("tally") or {}
        detected_cols = parsed.get("detected_columns") or []
        target_matched = parsed.get("target_column_matched") or {}
        raw_records = parsed.get("records") or parsed.get("students") or []
    elif isinstance(parsed, list):
        raw_records = parsed

    valid_rows = []
    for item in raw_records:
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

    return ExamScanResultList(
        rows=valid_rows,
        tally=tally_data,
        detected_columns=detected_cols,
        target_column_matched=target_matched,
    )
