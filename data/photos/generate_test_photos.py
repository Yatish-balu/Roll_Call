"""
Synthetic attendance sheet photo generator for testing.

Creates 5 realistic-looking attendance sheet images in data/photos/:

  sheet_clean.jpg        - Clean, straight, well-lit sheet (all PRESENT/ABSENT marks)
  sheet_skewed.jpg       - Sheet rotated ~5 degrees to test deskew
  sheet_noisy.jpg        - Sheet with Gaussian noise to test denoising
  sheet_partial.jpg      - Sheet with some blank cells (→ PENDING rows)
  sheet_ambiguous.jpg    - Sheet with faint/scrawled marks (→ UNREVIEWED rows)
  sheet_empty.jpg        - Completely blank sheet (0 rows expected)

Run:
  python data/photos/generate_test_photos.py
"""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = Path(__file__).parent
FONT_SIZE_HEADER = 18
FONT_SIZE_BODY = 16
ROW_HEIGHT = 34
HEADER_H = 50
LEFT_MARGIN = 40

# Columns: idx, usn, name, status
COL_X = [40, 80, 230, 480]
COL_LABELS = ["#", "USN", "Student Name", "Status"]
IMG_W, IMG_H_BASE = 620, 60  # width; height grows with rows


STUDENTS = [
    ("1MS21CS001", "Alice Smith",    "✓"),
    ("1MS21CS002", "Bob Jones",      "✗"),
    ("1MS21CS003", "Charlie Brown",  "✓"),
    ("1MS21CS004", "Diana Prince",   "✓"),
    ("1MS21CS005", "Ethan Hunt",     "✗"),
    ("1MS21CS006", "Fiona Gallagher","✓"),
    ("1MS21CS007", "George Miller",  "✓"),
    ("1MS21CS008", "Hannah Lee",     "✗"),
]


def _try_get_font(size: int):
    """Get a PIL font, falling back to default."""
    for fname in ["arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]:
        try:
            return ImageFont.truetype(fname, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _draw_sheet(
    students: List[Tuple[str, str, str]],
    title: str = "Attendance Sheet",
) -> Image.Image:
    """Draw a full attendance sheet as a PIL image."""
    n_rows = len(students)
    height = HEADER_H + ROW_HEIGHT + n_rows * ROW_HEIGHT + 20
    img = Image.new("RGB", (IMG_W, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    font_h = _try_get_font(FONT_SIZE_HEADER)
    font_b = _try_get_font(FONT_SIZE_BODY)

    # Title
    draw.text((IMG_W // 2 - 120, 8), title, fill=(0, 0, 0), font=font_h)
    draw.line([(LEFT_MARGIN, 35), (IMG_W - LEFT_MARGIN, 35)], fill=(0, 0, 0), width=2)

    # Column headers
    for x, label in zip(COL_X, COL_LABELS):
        draw.text((x, 42), label, fill=(0, 0, 0), font=font_b)
    draw.line([(LEFT_MARGIN, 66), (IMG_W - LEFT_MARGIN, 66)], fill=(0, 0, 0), width=2)

    # Data rows
    for i, (usn, name, mark) in enumerate(students):
        y = HEADER_H + ROW_HEIGHT + i * ROW_HEIGHT
        # Alternating background
        if i % 2 == 0:
            draw.rectangle([(LEFT_MARGIN, y), (IMG_W - LEFT_MARGIN, y + ROW_HEIGHT - 2)],
                           fill=(245, 245, 255))
        draw.text((COL_X[0], y + 6), str(i + 1), fill=(0, 0, 0), font=font_b)
        draw.text((COL_X[1], y + 6), usn, fill=(0, 0, 0), font=font_b)
        draw.text((COL_X[2], y + 6), name, fill=(0, 0, 0), font=font_b)
        draw.text((COL_X[3], y + 6), mark, fill=(0, 0, 0), font=font_h)

    # Bottom line
    draw.line([(LEFT_MARGIN, height - 10), (IMG_W - LEFT_MARGIN, height - 10)],
              fill=(0, 0, 0), width=1)
    return img


def _pil_to_cv2_bgr(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _save(img: Image.Image, name: str) -> None:
    path = OUTPUT_DIR / name
    img.save(str(path), quality=95)
    print(f"  Written: {path}")


def generate_all():
    print(f"Generating synthetic attendance sheet photos in {OUTPUT_DIR} ...")

    # --- 1. Clean sheet ---
    sheet = _draw_sheet(STUDENTS, title="Attendance Sheet (Clean)")
    _save(sheet, "sheet_clean.jpg")

    # --- 2. Skewed sheet ---
    bgr = _pil_to_cv2_bgr(sheet)
    h, w = bgr.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), 5.2, 1.0)
    skewed = cv2.warpAffine(bgr, M, (w, h), borderValue=(255, 255, 255))
    cv2.imwrite(str(OUTPUT_DIR / "sheet_skewed.jpg"), skewed, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"  Written: {OUTPUT_DIR / 'sheet_skewed.jpg'}")

    # --- 3. Noisy sheet ---
    bgr_noisy = bgr.copy().astype(np.float32)
    noise = np.random.normal(0, 22, bgr_noisy.shape)
    bgr_noisy = np.clip(bgr_noisy + noise, 0, 255).astype(np.uint8)
    cv2.imwrite(str(OUTPUT_DIR / "sheet_noisy.jpg"), bgr_noisy, [cv2.IMWRITE_JPEG_QUALITY, 90])
    print(f"  Written: {OUTPUT_DIR / 'sheet_noisy.jpg'}")

    # --- 4. Partial sheet (some blank status cells → PENDING) ---
    partial_students = list(STUDENTS)
    partial_students[2] = (STUDENTS[2][0], STUDENTS[2][1], "")   # blank → PENDING
    partial_students[5] = (STUDENTS[5][0], STUDENTS[5][1], "")   # blank → PENDING
    partial_sheet = _draw_sheet(partial_students, title="Attendance Sheet (Partial)")
    _save(partial_sheet, "sheet_partial.jpg")

    # --- 5. Ambiguous sheet (faint marks → UNREVIEWED) ---
    bgr_amb = _pil_to_cv2_bgr(
        _draw_sheet(STUDENTS, title="Attendance Sheet (Ambiguous)")
    ).astype(np.float32)
    # Fade the image toward white (simulate poor photocopy)
    bgr_amb = np.clip(bgr_amb * 0.45 + 140, 0, 255).astype(np.uint8)
    cv2.imwrite(str(OUTPUT_DIR / "sheet_ambiguous.jpg"), bgr_amb, [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(f"  Written: {OUTPUT_DIR / 'sheet_ambiguous.jpg'}")

    # --- 6. Blank sheet (0 rows expected) ---
    blank = Image.new("RGB", (IMG_W, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(blank)
    font_h = _try_get_font(FONT_SIZE_HEADER)
    draw.text((IMG_W // 2 - 100, 80), "Attendance Sheet", fill=(200, 200, 200), font=font_h)
    _save(blank, "sheet_empty.jpg")

    print("Done. 6 test images created.")


if __name__ == "__main__":
    generate_all()
