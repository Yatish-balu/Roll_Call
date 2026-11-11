"""Upload hardening helpers (size, type, image limits, malware scanning).

The backend is the security boundary for uploads - frontend validation is a
convenience only. These helpers implement the checks that must hold no matter
what the client sends:

* bounded streaming reads (the caller enforces the byte budget),
* extension / magic-byte consistency,
* image dimension and pixel-count limits (decompression-bomb protection),
* a malware scanner interface.

No scanner is bundled: when none is configured the scanner reports
``available=False`` so the deployment can state the limitation honestly. It is
never reported as "the file was scanned".
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("rollcall.security.uploads")

#: Maximum accepted image dimensions (width/height) and total pixel count.
MAX_IMAGE_WIDTH = 10_000
MAX_IMAGE_HEIGHT = 10_000
MAX_IMAGE_PIXELS = 25_000_000  # 25 megapixels

#: Magic-byte signatures of the allowed image formats.
_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
    (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
)


@dataclass
class UploadCheckResult:
    """Outcome of an upload validation."""

    ok: bool
    detail: str = ""
    content_type: Optional[str] = None
    pixel_count: Optional[int] = None


def detect_image_type(header: bytes) -> Optional[Tuple[str, str]]:
    """Return ``(extension, content_type)`` for a known image header."""
    for signature, extension, content_type in _IMAGE_SIGNATURES:
        if header.startswith(signature):
            return extension, content_type
    return None


def check_extension_consistency(filename: str, header: bytes) -> UploadCheckResult:
    """Reject a file whose extension does not match its content."""
    extension = Path(filename or "").suffix.lower()
    detected = detect_image_type(header or b"")
    if detected is None:
        # Not an image: CSV/TXT uploads are validated separately.
        return UploadCheckResult(ok=True)
    expected_extension, expected_type = detected
    if extension and extension not in (expected_extension, ".jpeg" if expected_extension == ".jpg" else expected_extension):
        return UploadCheckResult(
            ok=False,
            detail=(
                f"File extension '{extension}' does not match the file content "
                f"('{expected_extension}')."
            ),
            content_type=expected_type,
        )
    return UploadCheckResult(ok=True, content_type=expected_type)


def check_declared_content_type(declared: Optional[str], expected: Optional[str]) -> UploadCheckResult:
    """Reject a file whose declared MIME type contradicts its content."""
    if not declared or not expected:
        return UploadCheckResult(ok=True, content_type=expected)
    clean = declared.split(";")[0].strip().lower()
    if clean in ("application/octet-stream", ""):
        return UploadCheckResult(ok=True, content_type=expected)
    if clean != expected:
        return UploadCheckResult(
            ok=False,
            detail=f"Declared content type '{clean}' does not match the file content ('{expected}').",
            content_type=expected,
        )
    return UploadCheckResult(ok=True, content_type=expected)


def check_image_dimensions(path: str) -> UploadCheckResult:
    """Enforce the image dimension and pixel-count limits.

    The image is *not* fully decoded here, so a decompression bomb cannot be
    triggered by this check; the pixel count is read from the header.
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - dependency missing
        return UploadCheckResult(ok=True)

    try:
        with Image.open(path) as image:
            width, height = image.size
    except Exception as exc:
        return UploadCheckResult(ok=False, detail=f"The image could not be read: {exc}")

    if width <= 0 or height <= 0:
        return UploadCheckResult(ok=False, detail="The image has invalid dimensions.")
    if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT:
        return UploadCheckResult(
            ok=False,
            detail=f"The image dimensions {width}x{height} exceed the limit of {MAX_IMAGE_WIDTH}x{MAX_IMAGE_HEIGHT}.",
        )
    pixels = width * height
    if pixels > MAX_IMAGE_PIXELS:
        return UploadCheckResult(
            ok=False,
            detail=f"The image has {pixels} pixels which exceeds the limit of {MAX_IMAGE_PIXELS}.",
            pixel_count=pixels,
        )
    return UploadCheckResult(ok=True, pixel_count=pixels)


# ---------------------------------------------------------------------------
# Malware scanner integration
# ---------------------------------------------------------------------------

class MalwareScanner:
    """Interface for a malware scanning service."""

    name = "base"
    available = False

    def scan(self, path: str) -> Tuple[bool, str]:
        """Return ``(clean, detail)`` for the file at ``path``."""
        raise NotImplementedError


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() == "production"


class NullMalwareScanner(MalwareScanner):
    """Scanner used when no scanning service is configured."""

    name = "none"
    available = False

    def scan(self, path: str) -> Tuple[bool, str]:
        logger.warning(
            "No malware scanner is configured; the uploaded file was NOT scanned."
        )
        return True, "No malware scanner configured; the file was not scanned."


class UnavailableMalwareScanner(MalwareScanner):
    """Production scanner that fails closed when no scanner is configured."""

    name = "unavailable"
    available = False

    def scan(self, path: str) -> Tuple[bool, str]:
        logger.error(
            "PRODUCTION: upload rejected because MALWARE_SCAN_COMMAND is not configured."
        )
        return (
            False,
            "No malware scanner is configured; uploads are disabled in production.",
        )


def get_malware_scanner() -> MalwareScanner:
    """Return the configured scanner, or the null scanner when none is set.

    The scanner command is read from ``MALWARE_SCAN_COMMAND``; when it is unset
    the null scanner is returned and the deployment limitation is documented
    rather than hidden.
    """
    command = os.getenv("MALWARE_SCAN_COMMAND", "").strip()
    if not command:
        # In production an unscanned upload is not accepted: the deployment has
        # to configure a scanner (for example ClamAV) rather than silently
        # accepting files that were never checked.
        if _is_production():
            return UnavailableMalwareScanner()
        return NullMalwareScanner()

    import shlex
    import subprocess

    class _CommandScanner(MalwareScanner):
        name = "command"
        available = True

        def scan(self, path: str) -> Tuple[bool, str]:
            try:
                completed = subprocess.run(
                    shlex.split(command) + [path],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except Exception as exc:
                logger.error("Malware scan failed: %s", exc)
                # Fail closed in production: a scanner that cannot run must not
                # be reported as a clean scan.
                return (not _is_production()), f"Scan could not be executed: {exc}"
            clean = completed.returncode == 0
            return clean, (completed.stdout or completed.stderr or "").strip()[:500]

    return _CommandScanner()
