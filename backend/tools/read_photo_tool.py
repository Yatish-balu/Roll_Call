"""Tool for extracting attendance records from a photo of an attendance sheet.

Pipeline:
  1. Load & clean the image with OpenCV (grayscale, denoise, deskew, adaptive threshold).
  2. Send the cleaned image to a vision LLM (Google Gemini) with a strict JSON prompt.
  3. Parse and validate the returned JSON rows (usn, name, status, confidence).
  4. If the LLM call fails or returns malformed JSON, fall back to EasyOCR text extraction.

Environment variables required (add to .env):
  GEMINI_API_KEY   - Google AI Studio API key for Gemini vision model.

Optional environment variables:
  PHOTO_LLM_MODEL  - Gemini model to use (default: gemini-3.5-flash-lite,
                     the same model the chat provider uses).
  PHOTO_MIN_CONFIDENCE - Minimum confidence threshold to keep a row (default: 0.5).
  PHOTO_OCR_GPU    - Set to "1" to enable EasyOCR GPU acceleration (default: 0).
"""

from __future__ import annotations

import base64
import concurrent.futures
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
    "ab": "ABSENT",
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

DEFAULT_MODEL = "gemini-3.5-flash-lite"
# Tried in order when the primary model is unavailable (retired model name,
# regional outage, quota). Mirrors app/agent/provider.py's fallbacks.
DEFAULT_FALLBACK_MODELS = ("gemini-3.8-flash", "gemini-3.5-flash")
DEFAULT_MIN_CONFIDENCE = 0.5

# Honest-extraction contract shared by every reader in the project.
EXTRACTION_OK = "ok"
EXTRACTION_PARTIAL = "partial"
EXTRACTION_UNREADABLE = "unreadable"

MAX_IMAGE_BYTES = 40 * 1024 * 1024  # refuse to buffer absurd files
DEFAULT_OCR_TIMEOUT_SECONDS = 90.0


class VisionTimeoutError(RuntimeError):
    """Raised when the vision model call exceeds its deadline."""


class OcrTimeoutError(RuntimeError):
    """Raised when the local OCR fallback exceeds its deadline."""


def _ocr_timeout_seconds() -> float:
    try:
        value = float(os.getenv("OCR_TIMEOUT_SECONDS", str(DEFAULT_OCR_TIMEOUT_SECONDS)).strip())
    except (TypeError, ValueError):
        value = DEFAULT_OCR_TIMEOUT_SECONDS
    return max(5.0, min(value, 600.0))

def _count_extracted_chars(rows: List["PhotoRow"]) -> int:
    return sum(len(r.usn) + len(r.name) + len(r.status) for r in rows)


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
    """Full result from read_photo_tool.

    Besides the historical fields, every result carries the standard
    honest-extraction metadata so downstream callers can hard-stop instead of
    guessing when the image could not be read.
    """
    image_path: str
    rows: List[PhotoRow]
    source: ExtractionSource
    warnings: List[str] = field(default_factory=list)
    raw_llm_response: Optional[str] = None
    error: Optional[str] = None
    extraction_status: str = EXTRACTION_UNREADABLE
    extraction_confidence: float = 0.0
    extracted_chars: int = 0
    extraction_error: Optional[str] = None
    honest_failure_message: Optional[str] = None
    allow_llm_inference: bool = False

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
            "extraction_status": self.extraction_status,
            "extraction_confidence": self.extraction_confidence,
            "extracted_chars": self.extracted_chars,
            "extraction_error": self.extraction_error,
            "honest_failure_message": self.honest_failure_message,
            "allow_llm_inference": self.allow_llm_inference,
        }


# ---------------------------------------------------------------------------
# Image Preprocessing
# ---------------------------------------------------------------------------

def preprocess_image(image_path: str | Path) -> Tuple[np.ndarray, np.ndarray]:
    """
    Load and clean an attendance sheet image for best OCR / vision LLM accuracy.

    Steps:
      1. Load and auto-orient upright via EXIF.
      2. Denoise and deskew by detecting dominant rotation angle from Hough lines.
      3. Apply CLAHE contrast enhancement on luminance to recover faint or shadowed text.
      4. Apply unsharp masking to sharpen character strokes and numbers.
      5. Apply adaptive thresholding on grayscale copy for OCR fallback.
      6. Return (deskewed_colour_rgb, thresholded_binary).
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    # Auto-orient using EXIF (ensures mobile camera photos are upright)
    try:
        from PIL import Image as PILImage, ImageOps
        with PILImage.open(str(path)) as pil_raw:
            oriented = ImageOps.exif_transpose(pil_raw)
            if oriented is not None:
                if oriented.mode != "RGB":
                    oriented = oriented.convert("RGB")
                rgb_arr = np.array(oriented)
                bgr = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2BGR)
            else:
                bgr = cv2.imread(str(path))
    except Exception:
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

    # --- Contrast enhancement (CLAHE on Luminance) for faint/poorly-visible text ---
    try:
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        l_clahe = clahe.apply(l)
        enhanced_bgr = cv2.cvtColor(cv2.merge((l_clahe, a, b)), cv2.COLOR_LAB2BGR)
        blurred = cv2.GaussianBlur(enhanced_bgr, (0, 0), sigmaX=1.5)
        bgr = cv2.addWeighted(enhanced_bgr, 1.35, blurred, -0.35, 0)
    except Exception:
        pass

    # --- Adaptive threshold (for OCR fallback preview) ---
    thresh = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 21, 10,
    )

    # Return RGB colour (best for LLM; thresh stored separately for OCR fallback)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return rgb, thresh


def assess_image_legibility(rgb: np.ndarray, thresh: np.ndarray) -> Dict[str, Any]:
    """Judge whether an image plausibly contains a readable table of text.

    This is a *structural* pre-check: it measures ink density, text-sized
    connected components, and long horizontal rules that indicate a table.
    A blank page, a page with only a title, or a sheet so degraded that no
    row structure survives is reported as low legibility so callers never
    trust a model that invents rows for it.

    Returns a dict with ``legible`` (bool), ``score`` (0-1), and diagnostic
    counts. The score is intentionally conservative: it is used only to block
    hopeless inputs, never to invent confidence.
    """
    diagnostics: Dict[str, Any] = {
        "legible": False,
        "score": 0.0,
        "reason": None,
        "dark_ratio": 0.0,
        "text_like_components": 0,
        "horizontal_rules": 0,
        "row_bands": 0,
    }
    try:
        binary = (thresh < 128).astype("uint8")
    except Exception:
        diagnostics["reason"] = "unreadable_image"
        return diagnostics

    if binary.size == 0:
        diagnostics["reason"] = "blank_or_empty_image"
        return diagnostics

    height, width = binary.shape[:2]
    dark_ratio = float(binary.mean())
    diagnostics["dark_ratio"] = round(dark_ratio, 5)

    # Text-sized blobs: handwriting/print produces many medium components,
    # while sensor noise produces either tiny specks or one huge smear.
    text_like = 0
    try:
        num_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            binary, connectivity=8
        )
        max_h = max(120, int(height * 0.25))
        for label_index in range(1, num_labels):
            _x, _y, comp_w, comp_h, area = stats[label_index]
            if 12 <= area <= 5000 and 5 <= comp_h <= max_h and 2 <= comp_w <= max(250, int(width * 0.9)):
                text_like += 1
    except Exception:
        text_like = 0
    diagnostics["text_like_components"] = text_like

    # Long horizontal rules are the strongest signal of a tabular sheet.
    # A morphological opening with a half-width kernel only survives genuine
    # straight rules, so sensor noise cannot fake table structure.
    horizontal_rules = 0
    try:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(10, int(width * 0.5)), 1)
        )
        opened = cv2.morphologyEx(binary * 255, cv2.MORPH_OPEN, kernel)
        ruled_rows = np.where(opened.sum(axis=1) > 0)[0]
        previous = -10
        for ruled_row in ruled_rows:
            if int(ruled_row) - previous > 2:
                horizontal_rules += 1
            previous = int(ruled_row)
    except Exception:
        horizontal_rules = 0
    diagnostics["horizontal_rules"] = horizontal_rules

    # Count contiguous bands of inked rows; a table has several bands.
    row_bands = 0
    try:
        row_fraction = binary.mean(axis=1)
        inked = row_fraction > 0.02
        row_bands = int(inked.sum())
    except Exception:
        row_bands = 0
    diagnostics["row_bands"] = row_bands

    # Blank white page (or nothing but a faint title).
    if dark_ratio < 0.002 or text_like < 5:
        diagnostics["reason"] = "blank_or_empty_image"
        return diagnostics

    # A page that is more than a fifth ink, with no ruled table, is a smear or
    # a noise field rather than a readable attendance sheet.
    if horizontal_rules == 0 and dark_ratio > 0.20:
        diagnostics["score"] = 0.1
        diagnostics["reason"] = "low_legibility_image"
        return diagnostics

    if horizontal_rules >= 2:
        score = 0.85
    elif horizontal_rules == 1:
        score = 0.70
    elif text_like >= 20 and row_bands >= 8:
        # Ruled-off sheets exist; dense, multi-band text is still a table.
        score = 0.60
    else:
        score = 0.20

    diagnostics["score"] = score
    diagnostics["legible"] = score >= 0.35
    if not diagnostics["legible"]:
        diagnostics["reason"] = "low_legibility_image"
    return diagnostics


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
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=FutureWarning)
            import google.generativeai as genai  # lazy import; optional dep
    except ImportError as exc:
        raise RuntimeError(
            "google-generativeai package not installed. "
            "Run: pip install google-generativeai"
        ) from exc

    genai.configure(api_key=api_key)
    b64, mime = _image_to_base64(rgb)

    timeout_ms = 20000
    try:
        from app.services.vision_client import vision_timeout_ms

        timeout_ms = vision_timeout_ms()
    except Exception:
        pass

    model_obj = genai.GenerativeModel(model)
    contents = [
        {"mime_type": mime, "data": b64},
        VISION_PROMPT,
    ]
    try:
        response = model_obj.generate_content(
            contents,
            request_options={"timeout": max(5, timeout_ms // 1000)},
        )
    except TypeError:
        # Older google-generativeai releases do not accept request_options.
        response = model_obj.generate_content(contents)
    except Exception as exc:
        if _is_timeout_error(exc):
            raise VisionTimeoutError(f"Vision model {model} timed out: {exc}") from exc
        raise
    return response.text


def _is_timeout_error(exc: BaseException) -> bool:
    """Recognise the many shapes a vision/network timeout can take."""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    markers = ("timeout", "timed out", "deadline", "deadlineexceeded", "504")
    return ("timeout" in name or "deadline" in name) or any(m in text for m in markers)


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
                        DEFAULT_MODEL ('gemini-3.5-flash-lite').
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

    # Step 0: An empty upload is not an attendance sheet. Say so.
    try:
        file_size = os.path.getsize(image_path)
    except OSError:
        file_size = -1
    if file_size == 0:
        return _unreadable_result(
            image_path=image_path,
            source=ExtractionSource.LLM,
            warn=warn,
            code="empty_file",
            message="The uploaded image file is empty (0 bytes). Please re-upload the attendance photo.",
        )
    if file_size > MAX_IMAGE_BYTES:
        return _unreadable_result(
            image_path=image_path,
            source=ExtractionSource.LLM,
            warn=warn,
            code="file_too_large",
            message=(
                "The uploaded image is too large to process. Please upload a photo "
                "smaller than 40 MB."
            ),
        )

    # Step 1: Preprocess
    try:
        rgb, thresh = preprocess_image(image_path)
    except (FileNotFoundError, ValueError):
        raise
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"Image preprocessing failed: {exc}") from exc

    # Step 1b: Structural legibility gate. A blank page (or one degraded past
    # recognition) must never be handed to a model that might invent rows.
    legibility = assess_image_legibility(rgb, thresh)
    if not legibility.get("legible"):
        code = legibility.get("reason") or "low_legibility_image"
        warn.append(
            f"Image legibility check failed (score={legibility.get('score')}, "
            f"text_components={legibility.get('text_like_components')}, "
            f"rules={legibility.get('horizontal_rules')})."
        )
        return _unreadable_result(
            image_path=image_path,
            source=ExtractionSource.LLM,
            warn=warn,
            code=code,
            message=(
                "The image does not contain a readable attendance table. Retake the "
                "photo in even lighting, keep the whole sheet in frame, and make sure "
                "the USN and status columns are visible."
            ),
        )

    raw_response: Optional[str] = None
    source = ExtractionSource.LLM
    llm_timed_out = False

    # Step 2: Try LLM
    if not force_ocr and resolved_key:
        candidates = [resolved_model] + [
            m for m in DEFAULT_FALLBACK_MODELS if m != resolved_model
        ]
        for candidate in candidates:
            try:
                raw_response = _call_gemini(rgb, resolved_key, candidate)
                rows = _parse_and_validate_json(raw_response, resolved_min_conf, source, warn)
                if rows:
                    return _success_result(
                        image_path=image_path,
                        rows=rows,
                        source=source,
                        warn=warn,
                        min_conf=resolved_min_conf,
                        raw_response=raw_response,
                    )
                warn.append(f"LLM returned an empty row list ({candidate}).")
                break  # a valid-but-empty answer will not improve with another model
            except VisionTimeoutError as exc:
                llm_timed_out = True
                warn.append(f"LLM call timed out ({candidate}): {exc}. Trying the next model.")
                logger.warning("LLM %s timed out: %s", candidate, exc)
            except json.JSONDecodeError as exc:
                warn.append(f"LLM JSON parse error ({candidate}): {exc}. Trying the next model.")
                logger.warning("LLM %s returned malformed JSON — falling back to EasyOCR: %s", candidate, exc)
            except ValueError as exc:
                warn.append(f"LLM response validation error ({candidate}): {exc}. Trying the next model.")
                logger.warning("LLM %s response invalid — falling back to EasyOCR: %s", candidate, exc)
            except Exception as exc:  # network, quota, retired model name, etc.
                if _is_timeout_error(exc):
                    llm_timed_out = True
                warn.append(
                    f"LLM call failed ({type(exc).__name__}: {exc}) on {candidate}. Trying next model."
                )
                logger.warning("LLM call failed on %s (%s: %s); trying next candidate", candidate, type(exc).__name__, exc)
        warn.append("All LLM attempts failed. Falling back to EasyOCR.")
    elif not force_ocr and not resolved_key:
        warn.append("GEMINI_API_KEY not set. Falling back to EasyOCR.")

    # Step 3: OCR fallback (bounded so a stuck OCR job cannot hang the request)
    source = ExtractionSource.OCR_FALLBACK
    try:
        rows = _run_ocr_with_timeout(thresh, resolved_min_conf, warn)
    except OcrTimeoutError as exc:
        warn.append(f"OCR fallback timed out: {exc}")
        return _unreadable_result(
            image_path=image_path,
            source=source,
            warn=warn,
            code="ocr_timeout",
            message=(
                "Reading the image timed out and was stopped. Please try again "
                "with a smaller, clearer photo."
            ),
            raw_response=raw_response,
        )
    except Exception as exc:
        return _unreadable_result(
            image_path=image_path,
            source=source,
            warn=warn,
            code="ocr_failed",
            message=(
                "The image could not be read. Please re-upload a clear photo of the "
                "attendance sheet."
            ),
            raw_response=raw_response,
            error=f"OCR fallback also failed: {type(exc).__name__}: {exc}",
        )

    if rows:
        return _success_result(
            image_path=image_path,
            rows=rows,
            source=source,
            warn=warn,
            min_conf=resolved_min_conf,
            raw_response=raw_response,
        )

    code = "ocr_timeout" if llm_timed_out else "no_rows_detected"
    if code == "ocr_timeout":
        message = (
            "Reading the image timed out and no student rows were recovered. Please "
            "try again, or upload a CSV export instead."
        )
    else:
        message = (
            "No student rows could be read from the image. Please re-upload a clearer "
            "photo where the USN and status columns are fully visible, or upload a CSV."
        )
    return _unreadable_result(
        image_path=image_path,
        source=source,
        warn=warn,
        code=code,
        message=message,
        raw_response=raw_response,
    )


def _run_ocr_with_timeout(
    thresh: np.ndarray,
    min_confidence: float,
    warn: List[str],
) -> List[PhotoRow]:
    """Run the EasyOCR fallback under a hard wall-clock deadline."""
    timeout = _ocr_timeout_seconds()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_ocr_fallback, thresh, min_confidence, warn)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        raise OcrTimeoutError(f"OCR exceeded {timeout:.0f}s") from exc
    finally:
        executor.shutdown(wait=False)


def _success_result(
    image_path: str,
    rows: List[PhotoRow],
    source: ExtractionSource,
    warn: List[str],
    min_conf: float,
    raw_response: Optional[str],
) -> PhotoExtractionResult:
    """Build a result whose metadata honestly reflects the extracted rows."""
    confidences = [r.confidence for r in rows]
    mean_conf = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
    uncertain = [
        r for r in rows
        if r.confidence < min_conf or r.status in ("UNREVIEWED", "PENDING")
    ]
    status = EXTRACTION_PARTIAL if uncertain else EXTRACTION_OK
    if status == EXTRACTION_PARTIAL:
        warn.append(
            f"{len(uncertain)} of {len(rows)} extracted rows are uncertain and need "
            "human review; they were not treated as ABSENT."
        )
    return PhotoExtractionResult(
        image_path=image_path,
        rows=rows,
        source=source,
        warnings=warn,
        raw_llm_response=raw_response,
        error=None,
        extraction_status=status,
        extraction_confidence=mean_conf,
        extracted_chars=_count_extracted_chars(rows),
        extraction_error=None,
        honest_failure_message=None,
        allow_llm_inference=True,
    )


def _unreadable_result(
    image_path: str,
    source: ExtractionSource,
    warn: List[str],
    code: str,
    message: str,
    raw_response: Optional[str] = None,
    error: Optional[str] = None,
) -> PhotoExtractionResult:
    """Build an explicit, honest failure result: no rows and no LLM guessing."""
    return PhotoExtractionResult(
        image_path=image_path,
        rows=[],
        source=source,
        warnings=warn,
        raw_llm_response=raw_response,
        error=error or code,
        extraction_status=EXTRACTION_UNREADABLE,
        extraction_confidence=0.0,
        extracted_chars=0,
        extraction_error=code,
        honest_failure_message=message,
        allow_llm_inference=False,
    )
