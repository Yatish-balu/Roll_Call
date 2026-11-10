"""Script to generate synthetic test photos for photo tool integration tests."""

from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

PHOTOS_DIR = Path(__file__).resolve().parent

ROWS_8 = [
    ("1MS21CS001", "Alice Smith", "P"),
    ("1MS21CS002", "Bob Jones", "A"),
    ("1MS21CS003", "Charlie Brown", "P"),
    ("1MS21CS004", "Diana Prince", "P"),
    ("1MS21CS005", "Ethan Hunt", "A"),
    ("1MS21CS006", "Fiona Gallagher", "P"),
    ("1MS21CS007", "George Miller", "P"),
    ("1MS21CS008", "Hannah Lee", "A"),
]


def create_sheet(rows, output_path: Path, skew_angle: float = 0.0, noise: bool = False, blank_indices=None):
    img = Image.new("RGB", (700, 400), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    draw.text((20, 20), "USN           STUDENT NAME          STATUS", fill=(0, 0, 0), font=font)
    draw.line([(20, 35), (680, 35)], fill=(0, 0, 0), width=1)

    y = 50
    for idx, (usn, name, st) in enumerate(rows):
        status_text = "" if blank_indices and idx in blank_indices else st
        line_text = f"{usn:<14}{name:<22}{status_text}"
        draw.text((20, y), line_text, fill=(0, 0, 0), font=font)
        y += 35

    cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    if skew_angle != 0.0:
        h, w = cv_img.shape[:2]
        center = (w // 2, h // 2)
        m = cv2.getRotationMatrix2D(center, skew_angle, 1.0)
        cv_img = cv2.warpAffine(cv_img, m, (w, h), borderValue=(255, 255, 255))

    if noise:
        gauss = np.random.normal(0, 15, cv_img.shape).astype(np.float32)
        noisy = np.clip(cv_img.astype(np.float32) + gauss, 0, 255).astype(np.uint8)
        cv_img = noisy

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), cv_img)


def main():
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. sheet_clean.jpg
    create_sheet(ROWS_8, PHOTOS_DIR / "sheet_clean.jpg")

    # 2. sheet_skewed.jpg
    create_sheet(ROWS_8, PHOTOS_DIR / "sheet_skewed.jpg", skew_angle=5.0)

    # 3. sheet_noisy.jpg
    create_sheet(ROWS_8, PHOTOS_DIR / "sheet_noisy.jpg", noise=True)

    # 4. sheet_partial.jpg (rows 2 and 5 blank -> PENDING)
    create_sheet(ROWS_8, PHOTOS_DIR / "sheet_partial.jpg", blank_indices={2, 5})

    # 5. sheet_ambiguous.jpg
    create_sheet(ROWS_8[:2], PHOTOS_DIR / "sheet_ambiguous.jpg")

    # 6. sheet_empty.jpg
    empty_img = np.ones((400, 700, 3), dtype=np.uint8) * 255
    cv2.imwrite(str(PHOTOS_DIR / "sheet_empty.jpg"), empty_img)

    print(f"Generated 6 test photos in {PHOTOS_DIR}")


if __name__ == "__main__":
    main()
