"""Tool for extracting attendance records from a photo of an attendance sheet.

Pipeline:
  1. Load & clean the image with OpenCV (grayscale, denoise, deskew, adaptive threshold).
  2. Send the cleaned image to a vision LLM (Google Gemini) with a strict JSON prompt.
  3. Parse and validate the returned JSON rows (usn, name, status, confidence).
  4. If the LLM call fails or returns malformed JSON, fall back to EasyOCR text extraction.

Environment variables required (add to .env):
  GEMINI_API_KEY   - Google AI Studio API key for Gemini vision model.

Optional environment variables:
  PHOTO_LLM_MODEL  - Gemini model to use (default: gemini-2.0-flash).
  PHOTO_MIN_CONFIDENCE - Minimum confidence threshold to keep a row (default: 0.5).
  PHOTO_OCR_GPU    - Set to "1" to enable EasyOCR GPU acceleration (default: 0).
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import re
import warnings
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_STATUSES = {"PRESENT", "ABSENT", "PENDING", "UNREVIEWED"}

STATUS_ALIASES: Dict[str, str] = {
    "present": "PRESENT",
    "p": "PRESENT",
    "1": "PRESENT",
    "yes": "PRESENT",
    "true": "PRESENT",
    "absent": "ABSENT",
    "a": "ABSENT",
    "0": "ABSENT",
    "no": "ABSENT",
    "false": "ABSENT",
    "pending": "PENDING",
    "unreviewed": "UNREVIEWED",
    "ambiguous": "UNREVIEWED",
    "?": "UNREVIEWED",
}

# Strict prompt telling the vision LLM exactly what to return.
VISION_PROMPT = """You are an OCR assistant processing an attendance sheet photograph.
Your task is to extract each student's attendance row.

Return a valid JSON array — nothing else, no markdown fences, no commentary.
Each element must have EXACTLY these keys:
  "usn"        : string — the student roll number / USN (e.g. "1MS21CS042")
  "name"       : string — the student's full name as written on the sheet
  "status"     : string — one of: "PRESENT", "ABSENT", "PENDING", "UNREVIEWED"
                  Use "PENDING" if the cell is blank/missing.
                  Use "UNREVIEWED" if the status mark is ambiguous or illegible.
  "confidence" : float between 0.0 and 1.0 — your confidence in this row's accuracy.
                  Set < 0.70 for any row where handwriting was difficult to read.

Rules:
- If a cell is empty, null, or illegible → use "PENDING" or "UNREVIEWED" accordingly.
- Do NOT default blank attendance to "ABSENT".
- Return ONLY the JSON array. Example:
[
  {"usn": "1MS21CS001", "name": "Alice Smith",   "status": "PRESENT",    "confidence": 0.97},
  {"usn": "1MS21CS002", "name": "Bob Jones",     "status": "ABSENT",     "confidence": 0.95},
  {"usn": "1MS21CS003", "name": "Charlie Brown", "status": "UNREVIEWED", "confidence": 0.48}
]"""

DEFAULT_MODEL = "gemini-2.0-flash"
DEFAULT_MIN_CONFIDENCE = 0.5


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

class ExtractionSource(str, Enum):
    LLM = "llm"
    OCR_FALLBACK = "ocr_fallback"


@dataclass
class PhotoRow:
    """One extracted row from an attendance sheet photo."""
    usn: str
    name: str
    status: str
    confidence: float
    source: ExtractionSource
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "usn": self.usn,
            "name": self.name,
            "status": self.status,
            "confidence": self.confidence,
            "source": self.source.value,
        }


@dataclass
class PhotoExtractionResult:
    """Full result from read_photo_tool."""
    image_path: str
    rows: List[PhotoRow]
    source: ExtractionSource
    warnings: List[str] = field(default_factory=list)
    raw_llm_response: Optional[str] = None
    error: Optional[str] = None

    @property
    def valid_rows(self) -> List[PhotoRow]:
        return [r for r in self.rows if r.status != "UNREVIEWED" or r.confidence >= DEFAULT_MIN_CONFIDENCE]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "image_path": self.image_path,
            "source": self.source.value,
            "total_rows": len(self.rows),
            "warnings": self.warnings,
            "error": self.error,
            "rows": [r.to_dict() for r in self.rows],
        }


# ---------------------------------------------------------------------------
# Image Preprocessing
# ---------------------------------------------------------------------------

def preprocess_image(image_path: str | Path) -> np.ndarray:
    """
    Load and clean an attendance sheet image for best OCR / vision LLM accuracy.

    Steps:
      1. Load with OpenCV preserving colour (for LLM) and make a grayscale copy.
      2. Denoise (fastNlMeansDenoising).
      3. Deskew by detecting the dominant rotation angle from Hough lines.
      4. Apply adaptive thresholding on the grayscale copy to sharpen text.
      5. Return the deskewed *colour* image (PIL-ready, uint8 RGB).
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    bgr = cv2.imread(str(path))
    if bgr is None:
        raise ValueError(f"OpenCV could not decode image: {image_path}")

    # --- Denoise ---
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)

    # --- Deskew ---
    angle = _detect_skew_angle(denoised)
    if abs(angle) > 0.5:
        bgr = _rotate_image(bgr, angle)
        denoised = _rotate_image(denoised, angle)

    # --- Adaptive threshold (for OCR fallback preview) ---
    thresh = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 21, 10,
    )

    # Return RGB colour (best for LLM; thresh stored separately for OCR fallback)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return rgb, thresh


def _detect_skew_angle(gray: np.ndarray) -> float:
    """Estimate document skew angle using Hough line detection."""
    try:
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=100)
        if lines is None or len(lines) < 5:
            return 0.0
        angles = []
        for line in lines[:50]:
            theta = line[0][1]
            angle = math.degrees(theta) - 90.0
            if abs(angle) < 45:
                angles.append(angle)
        return float(np.median(angles)) if angles else 0.0
    except Exception:
        return 0.0


def _rotate_image(img: np.ndarray, angle: float) -> np.ndarray:
    """Rotate an image by angle degrees around its centre without cropping."""
    h, w = img.shape[:2]
    center = (w / 2, h / 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    # Compute new bounding dimensions
    cos = abs(M[0, 0])
    sin = abs(M[0, 1])
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)
    M[0, 2] += (new_w - w) / 2
    M[1, 2] += (new_h - h) / 2
    border = 255 if img.ndim == 2 else (255, 255, 255)
    return cv2.warpAffine(img, M, (new_w, new_h),
                          flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT,
                          borderValue=border)


def _image_to_base64(rgb: np.ndarray) -> Tuple[str, str]:
    """Encode an RGB numpy array to a base64 JPEG string."""
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("cv2.imencode failed — could not encode image to JPEG.")
    b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
    return b64, "image/jpeg"


# ---------------------------------------------------------------------------
# JSON validation helpers
# ---------------------------------------------------------------------------

def _normalize_status(raw: Any) -> str:
    """Map raw status string to a canonical four-state value."""
    if raw is None or str(raw).strip() == "":
        return "PENDING"
    clean = str(raw).strip().lower()
    return STATUS_ALIASES.get(clean, str(raw).strip().upper())


def _validate_confidence(val: Any) -> float:
    """Clamp confidence to [0.0, 1.0]."""
    try:
        f = float(val)
        return max(0.0, min(1.0, f))
    except (TypeError, ValueError):
        return 0.5


def _parse_and_validate_json(
    raw_text: str,
    min_confidence: float,
    source: ExtractionSource,
    warn: List[str],
) -> List[PhotoRow]:
    """
    Parse LLM / OCR JSON output into validated PhotoRow list.
    - Strips markdown fences if present.
    - Skips rows below min_confidence with a warning.
    - Normalizes status aliases.
    """
    # Strip ```json ... ``` fences
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```\s*$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse failed: {e}") from e

    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array, got {type(data).__name__}")

    rows: List[PhotoRow] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            warn.append(f"Row {i}: not a dict, skipped.")
            continue

        usn = str(item.get("usn") or "").strip()
        if not usn:
            warn.append(f"Row {i}: missing USN, skipped.")
            continue

        name = str(item.get("name") or "").strip()
        status = _normalize_status(item.get("status"))
        if status not in VALID_STATUSES:
            warn.append(f"Row {i} USN={usn}: unknown status '{status}', defaulting to UNREVIEWED.")
            status = "UNREVIEWED"

        confidence = _validate_confidence(item.get("confidence", 0.8))

        if confidence < min_confidence:
            warn.append(
                f"Row {i} USN={usn}: confidence {confidence:.2f} < threshold {min_confidence:.2f}; "
                "status overridden to UNREVIEWED."
            )
            status = "UNREVIEWED"

        rows.append(PhotoRow(
            usn=usn,
            name=name,
            status=status,
            confidence=confidence,
            source=source,
            raw=item,
        ))
    return rows


# ---------------------------------------------------------------------------
# LLM Backend (Google Gemini)
# ---------------------------------------------------------------------------

def _call_gemini(rgb: np.ndarray, api_key: str, model: str) -> str:
    """
    Send the preprocessed image to Google Gemini vision and return raw response text.
    Raises RuntimeError on API / network failure.
    """
    try:
        import google.generativeai as genai  # lazy import; optional dep
    except ImportError as exc:
        raise RuntimeError(
            "google-generativeai package not installed. "
            "Run: pip install google-generativeai"
        ) from exc

    genai.configure(api_key=api_key)
    b64, mime = _image_to_base64(rgb)

    model_obj = genai.GenerativeModel(model)
    response = model_obj.generate_content(
        [
            {"mime_type": mime, "data": b64},
            VISION_PROMPT,
        ]
    )
    return response.text


# ---------------------------------------------------------------------------
# OCR Fallback Backend (EasyOCR)
# ---------------------------------------------------------------------------

_EASYOCR_READER = None  # lazy singleton to avoid heavy import at module load


def _get_easyocr_reader(gpu: bool = False):
    """Lazily initialise the EasyOCR reader (expensive one-time cost)."""
    global _EASYOCR_READER
    if _EASYOCR_READER is None:
        try:
            import easyocr  # lazy import; optional dep
        except ImportError as exc:
            raise RuntimeError(
                "easyocr package not installed. "
                "Run: pip install easyocr"
            ) from exc
        _EASYOCR_READER = easyocr.Reader(["en"], gpu=gpu, verbose=False)
    return _EASYOCR_READER


# Known USN pattern: digits, letters, digits (e.g. 1MS21CS042, 4SF22IS010)
_USN_PATTERN = re.compile(r"\b\d[A-Z]{2}\d{2}[A-Z]{2}\d{3}\b", re.IGNORECASE)
# Tick / cross / presence marks
_TICK_PATTERN = re.compile(r"[✓✔√☑Pp1]", re.UNICODE)
_CROSS_PATTERN = re.compile(r"[✗✘Xx0]", re.UNICODE)


def _ocr_fallback(thresh: np.ndarray, min_confidence: float, warn: List[str]) -> List[PhotoRow]:
    """
    Run EasyOCR on the thresholded image and heuristically reconstruct rows.

    Strategy:
    - Detect all text bounding boxes sorted by (y, x).
    - Cluster adjacent detections as rows using a vertical tolerance.
    - Per row: first USN-shaped token → USN, other long tokens → name,
      tick/cross marks → status.
    - Rows without a USN are skipped with a warning.
    """
    gpu = os.getenv("PHOTO_OCR_GPU", "0") == "1"
    reader = _get_easyocr_reader(gpu=gpu)

    # EasyOCR returns list of ([bbox_coords], text, prob)
    results = reader.readtext(thresh, detail=1, paragraph=False)
    if not results:
        warn.append("OCR fallback: EasyOCR returned no text detections.")
        return []

    # Sort detections top-to-bottom then left-to-right
    def _top_left_y(det):
        bbox = det[0]
        return (min(p[1] for p in bbox), min(p[0] for p in bbox))

    detections = sorted(results, key=_top_left_y)

    # Cluster into rows by y-coordinate tolerance
    row_clusters: List[List] = []
    current_cluster: List = []
    last_y: Optional[float] = None
    y_tolerance = 20  # pixels

    for det in detections:
        bbox, text, prob = det
        mid_y = sum(p[1] for p in bbox) / len(bbox)
        if last_y is None or abs(mid_y - last_y) <= y_tolerance:
            current_cluster.append((bbox, text.strip(), float(prob)))
            if last_y is None:
                last_y = mid_y
            else:
                last_y = (last_y + mid_y) / 2
        else:
            if current_cluster:
                row_clusters.append(current_cluster)
            current_cluster = [(bbox, text.strip(), float(prob))]
            last_y = mid_y

    if current_cluster:
        row_clusters.append(current_cluster)

    rows: List[PhotoRow] = []
    for cluster in row_clusters:
        texts = [(t, p) for _, t, p in cluster]
        all_text = " ".join(t for t, _ in texts)
        avg_prob = sum(p for _, p in texts) / max(len(texts), 1)

        # Find USN
        usn_match = _USN_PATTERN.search(all_text)
        if not usn_match:
            continue  # no USN → skip this cluster
        usn = usn_match.group(0).upper()

        # Build name from tokens that are not USN, not status marks
        non_usn = all_text.replace(usn_match.group(0), "").strip()
        # Remove tick/cross characters before name extraction
        name_tokens = [
            tok for tok in non_usn.split()
            if not _TICK_PATTERN.fullmatch(tok) and not _CROSS_PATTERN.fullmatch(tok)
            and len(tok) > 1 and not _USN_PATTERN.match(tok)
        ]
        name = " ".join(name_tokens).title().strip() or ""

        # Determine status from tokens not part of USN or student name
        status_candidate_text = non_usn
        for tok in name_tokens:
            status_candidate_text = re.sub(rf"\b{re.escape(tok)}\b", "", status_candidate_text, flags=re.IGNORECASE)
        status_candidate_text = status_candidate_text.strip()

        if _TICK_PATTERN.search(status_candidate_text):
            status = "PRESENT"
        elif _CROSS_PATTERN.search(status_candidate_text):
            status = "ABSENT"
        elif avg_prob < 0.5:
            status = "UNREVIEWED"
        else:
            status = "PENDING"

        confidence = _validate_confidence(avg_prob)
        if confidence < min_confidence and status != "PENDING":
            warn.append(
                f"OCR fallback: USN={usn} confidence {confidence:.2f} < threshold {min_confidence:.2f}; "
                "status overridden to UNREVIEWED."
            )
            status = "UNREVIEWED"

        rows.append(PhotoRow(
            usn=usn,
            name=name,
            status=status,
            confidence=confidence,
            source=ExtractionSource.OCR_FALLBACK,
        ))

    return rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_photo_tool(
    image_path: str | Path,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    min_confidence: Optional[float] = None,
    force_ocr: bool = False,
) -> PhotoExtractionResult:
    """
    Extract attendance rows from a photo of a handwritten / printed attendance sheet.

    Args:
        image_path:     Path to the input image (JPEG, PNG, BMP, etc.).
        api_key:        Google Gemini API key. Falls back to GEMINI_API_KEY env var.
        model:          Gemini model name. Falls back to PHOTO_LLM_MODEL env var or
                        'gemini-2.0-flash'.
        min_confidence: Rows below this threshold are forced to UNREVIEWED.
                        Falls back to PHOTO_MIN_CONFIDENCE env var or 0.5.
        force_ocr:      Skip LLM entirely and go straight to EasyOCR (useful for tests
                        or when no API key is available).

    Returns:
        PhotoExtractionResult with a list of PhotoRow objects.

    Raises:
        FileNotFoundError: if image_path does not exist.
        ValueError:        if the image cannot be decoded.
    """
    image_path = str(image_path)
    resolved_key = api_key or os.getenv("GEMINI_API_KEY", "")
    resolved_model = model or os.getenv("PHOTO_LLM_MODEL", DEFAULT_MODEL)
    resolved_min_conf = min_confidence or float(os.getenv("PHOTO_MIN_CONFIDENCE", str(DEFAULT_MIN_CONFIDENCE)))
    warn: List[str] = []

    # Step 1: Preprocess
    try:
        rgb, thresh = preprocess_image(image_path)
    except (FileNotFoundError, ValueError):
        raise
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"Image preprocessing failed: {exc}") from exc

    raw_response: Optional[str] = None
    source = ExtractionSource.LLM

    # Step 2: Try LLM
    if not force_ocr and resolved_key:
        try:
            raw_response = _call_gemini(rgb, resolved_key, resolved_model)
            rows = _parse_and_validate_json(raw_response, resolved_min_conf, source, warn)
            return PhotoExtractionResult(
                image_path=image_path,
                rows=rows,
                source=source,
                warnings=warn,
                raw_llm_response=raw_response,
            )
        except json.JSONDecodeError as exc:
            warn.append(f"LLM JSON parse error: {exc}. Falling back to EasyOCR.")
            logger.warning("LLM returned malformed JSON — falling back to EasyOCR: %s", exc)
        except ValueError as exc:
            warn.append(f"LLM response validation error: {exc}. Falling back to EasyOCR.")
            logger.warning("LLM response invalid — falling back to EasyOCR: %s", exc)
        except Exception as exc:  # network, quota, etc.
            warn.append(f"LLM call failed ({type(exc).__name__}: {exc}). Falling back to EasyOCR.")
            logger.warning("LLM call failed — falling back to EasyOCR: %s", exc)
    elif not force_ocr and not resolved_key:
        warn.append("GEMINI_API_KEY not set. Falling back to EasyOCR.")

    # Step 3: OCR fallback
    source = ExtractionSource.OCR_FALLBACK
    try:
        rows = _ocr_fallback(thresh, resolved_min_conf, warn)
    except Exception as exc:
        return PhotoExtractionResult(
            image_path=image_path,
            rows=[],
            source=source,
            warnings=warn,
            raw_llm_response=raw_response,
            error=f"OCR fallback also failed: {type(exc).__name__}: {exc}",
        )

    return PhotoExtractionResult(
        image_path=image_path,
        rows=rows,
        source=source,
        warnings=warn,
        raw_llm_response=raw_response,
    )
