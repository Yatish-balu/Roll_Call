"""Mobile Photo Intake & OCR Preprocessing Pipeline for RollCall AI.

Ensures:
1. Strict content-based MIME validation & magic byte inspection (rejecting HTML, SVG, EXEs).
2. Decompression-bomb safety limit enforcement.
3. Server-side EXIF orientation normalisation (transposes upright via EXIF tag 274).
4. Aspect-ratio preserving downscale to max 1600px edge (protecting memory & LLM tokens).
5. JPEG 85 compression & contrast/illumination enhancement.
6. Explicit uncertainty: confidence < 0.50 or ambiguous marks stay UNREVIEWED/PENDING, never ABSENT.
7. Structured proposal generation with matched vs unmatched student counts.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from PIL import Image, ImageEnhance, ImageOps
from sqlalchemy.orm import Session

from app.db import crud
from tools.read_photo_tool import read_photo_tool

logger = logging.getLogger("rollcall.services.image_pipeline")

# Safety limits
MAX_UPLOAD_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB
MAX_ALLOWED_PIXELS = 25_000_000           # 25 Megapixels
TARGET_MAX_DIMENSION = 1600               # Longest edge downscale target
JPEG_DEFAULT_QUALITY = 85                 # Quality for JPEG compression

# Set Pillow decompression bomb threshold safely
Image.MAX_IMAGE_PIXELS = MAX_ALLOWED_PIXELS


# Magic byte signatures
ALLOWED_MAGIC_SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"RIFF", "image/webp"),  # RIFF....WEBP checked in validator
]


def detect_image_mime(data: bytes) -> str:
    """Sniff real MIME type from content magic bytes."""
    if len(data) < 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is too small to be a valid image.",
        )

    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"

    # Block executable, script, or markup files immediately
    if data.startswith(b"MZ") or data.startswith(b"\x7fELF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Executable binary uploads are strictly forbidden.",
        )
    if b"<svg" in data[:1024].lower() or b"<?xml" in data[:1024].lower() or b"<html" in data[:1024].lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SVG, XML, or HTML markup uploads are not supported for attendance OCR.",
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unsupported image format. Please upload a standard JPEG, PNG, or WebP photo.",
    )


def enhance_contrast_and_illumination(img: Image.Image) -> Image.Image:
    """Enhance contrast for dim or shadowed classroom attendance sheets."""
    try:
        # Convert to RGB if palette/RGBA
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        # Mild contrast enhancement (1.2 factor preserves legibility without clipping)
        enhancer = ImageEnhance.Contrast(img)
        enhanced = enhancer.enhance(1.2)
        # Sharpness touchup to enhance handwriting strokes
        sharpness = ImageEnhance.Sharpness(enhanced)
        return sharpness.enhance(1.1)
    except Exception as exc:
        logger.warning("Image contrast enhancement skipped due to: %s", exc)
        return img


def validate_and_preprocess_image(
    image_bytes: bytes,
    max_dimension: int = TARGET_MAX_DIMENSION,
    jpeg_quality: int = JPEG_DEFAULT_QUALITY,
) -> Tuple[bytes, Dict[str, Any]]:
    """Validate, orient upright, downscale, and compress a mobile attendance photo.

    Returns:
        (processed_jpeg_bytes, metadata_dict)
    """
    original_size = len(image_bytes)
    if original_size > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Uploaded photo exceeds max allowed size of {MAX_UPLOAD_SIZE_BYTES // (1024*1024)}MB.",
        )

    mime_type = detect_image_mime(image_bytes)

    try:
        bio = io.BytesIO(image_bytes)
        with Image.open(bio) as img:
            # Check for decompression bombs
            total_pixels = img.width * img.height
            if total_pixels > MAX_ALLOWED_PIXELS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image resolution exceeds safe limits ({img.width}x{img.height}).",
                )

            orig_w, orig_h = img.width, img.height

            # 1. Server-side EXIF orientation normalisation
            try:
                oriented_img = ImageOps.exif_transpose(img)
            except Exception:
                oriented_img = img

            if oriented_img is None:
                oriented_img = img

            curr_w, curr_h = oriented_img.width, oriented_img.height

            # 2. Aspect-ratio preserving downscale to max_dimension
            longest_edge = max(curr_w, curr_h)
            if longest_edge > max_dimension:
                scale = max_dimension / float(longest_edge)
                target_w = max(1, int(curr_w * scale))
                target_h = max(1, int(curr_h * scale))
                resized_img = oriented_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            else:
                resized_img = oriented_img
                target_w, target_h = curr_w, curr_h

            # 3. Contrast & illumination enhancement
            enhanced_img = enhance_contrast_and_illumination(resized_img)

            # Ensure RGB mode for JPEG encoding
            if enhanced_img.mode != "RGB":
                enhanced_img = enhanced_img.convert("RGB")

            # 4. JPEG 85 compression
            out_buf = io.BytesIO()
            enhanced_img.save(out_buf, format="JPEG", quality=jpeg_quality, optimize=True)
            processed_bytes = out_buf.getvalue()

            metadata = {
                "original_mime": mime_type,
                "original_size_bytes": original_size,
                "processed_size_bytes": len(processed_bytes),
                "original_dimensions": (orig_w, orig_h),
                "processed_dimensions": (target_w, target_h),
                "compression_ratio": round(len(processed_bytes) / max(1, original_size), 3),
            }

            return processed_bytes, metadata

    except Image.DecompressionBombError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image decompression bomb detected. Upload was rejected for security.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to process image: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or corrupted image file: {exc}",
        )


def process_mobile_attendance_sheet(
    image_bytes: bytes,
    session_id: Optional[str] = None,
    db: Optional[Session] = None,
    max_dimension: int = TARGET_MAX_DIMENSION,
    jpeg_quality: int = JPEG_DEFAULT_QUALITY,
) -> Dict[str, Any]:
    """Execute complete mobile photo intake, normalization, OCR, and proposal generation."""
    # 1. Preprocess image
    normalized_bytes, meta = validate_and_preprocess_image(
        image_bytes, max_dimension=max_dimension, jpeg_quality=jpeg_quality
    )

    # 2. Run OCR via read_photo_tool using temporary file
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(normalized_bytes)
        tmp_path = tmp.name

    try:
        ocr_result = read_photo_tool(image_path=tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    extracted_rows: List[Dict[str, Any]] = []
    overall_confidence = 0.0
    raw_warnings: List[str] = []

    if hasattr(ocr_result, "rows"):
        for row_item in ocr_result.rows:
            extracted_rows.append({
                "usn": getattr(row_item, "usn", ""),
                "name": getattr(row_item, "name", ""),
                "status": getattr(row_item, "status", "UNREVIEWED"),
                "confidence": getattr(row_item, "confidence", 1.0),
            })
        if ocr_result.rows:
            overall_confidence = sum(r["confidence"] for r in extracted_rows) / len(extracted_rows)
        raw_warnings = list(getattr(ocr_result, "warnings", []))
    elif isinstance(ocr_result, dict):
        extracted_rows = ocr_result.get("rows", [])
        overall_confidence = ocr_result.get("confidence", 0.0)
        raw_warnings = ocr_result.get("warnings", [])

    # 3. Enforce explicit uncertainty policy
    normalized_rows: List[Dict[str, Any]] = []
    unreviewed_count = 0
    present_count = 0
    absent_count = 0

    for r in extracted_rows:
        raw_status = str(r.get("status") or "PENDING").upper()
        row_conf = float(r.get("confidence", 0.0))

        # Explicit uncertainty rule: confidence < 0.50 becomes UNREVIEWED, never ABSENT
        if row_conf < 0.50 or raw_status in ("?", "UNKNOWN", "UNCLEAR", "AMBIGUOUS"):
            status_val = "UNREVIEWED"
        elif raw_status in ("PRESENT", "1", "P"):
            status_val = "PRESENT"
        elif raw_status in ("ABSENT", "0", "A"):
            status_val = "ABSENT"
        elif raw_status in ("PENDING", ""):
            status_val = "PENDING"
        else:
            status_val = "UNREVIEWED"

        if status_val in ("UNREVIEWED", "PENDING"):
            unreviewed_count += 1
        elif status_val == "PRESENT":
            present_count += 1
        elif status_val == "ABSENT":
            absent_count += 1

        normalized_rows.append({
            "usn": str(r.get("usn") or "").strip().upper(),
            "name": str(r.get("name") or "").strip(),
            "status": status_val,
            "confidence": round(row_conf, 3),
        })

    # 4. Roster matching against database if session provided
    matched_students = []
    unmatched_students = []

    if db and session_id:
        existing_roster = crud.get_existing_attendance_usns(db, session_id=session_id)
        if not existing_roster:
            all_students = {s["usn"].upper() for s in crud.get_all_students(db)}
        else:
            all_students = {u.upper() for u in existing_roster}

        for nr in normalized_rows:
            if nr["usn"] in all_students:
                matched_students.append(nr)
            else:
                unmatched_students.append(nr)
    else:
        matched_students = normalized_rows

    success_flag = True
    if hasattr(ocr_result, "error"):
        success_flag = getattr(ocr_result, "error") is None
    elif isinstance(ocr_result, dict):
        success_flag = ocr_result.get("success", True)

    return {
        "success": success_flag,
        "proposal_type": "mobile_photo_ocr",
        "session_id": session_id,
        "metadata": meta,
        "overall_confidence": overall_confidence,
        "stats": {
            "total_extracted": len(normalized_rows),
            "matched_count": len(matched_students),
            "unmatched_count": len(unmatched_students),
            "present_count": present_count,
            "absent_count": absent_count,
            "unreviewed_count": unreviewed_count,
        },
        "matched_students": matched_students,
        "unmatched_students": unmatched_students,
        "rows": normalized_rows,
        "raw_ocr_warnings": raw_warnings,
    }
