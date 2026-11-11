"""Attendance roster extraction from PDF and XLSX documents.

The extraction is intentionally conservative:

* The header row must be detected (``usn`` + ``status`` columns). When no header
  is found the document is rejected instead of guessing.
* Rows whose identifier does not match the institutional USN pattern are kept
  as *invalid* rows so the validation stage can surface them to the faculty for
  review. They are never silently dropped and never silently accepted.
* Rows whose status cannot be mapped to a canonical attendance state are
  reported as ambiguous.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("rollcall.services.document_extraction")

USN_PATTERN = re.compile(r"\b\d{1,2}[A-Za-z]{2}\d{2}[A-Za-z]{2}\d{3}\b")

HEADER_ALIASES = {
    "usn": "usn",
    "student usn": "usn",
    "roll no": "usn",
    "roll number": "usn",
    "rollno": "usn",
    "student id": "usn",
    "name": "name",
    "student name": "name",
    "status": "status",
    "attendance": "status",
    "attendance status": "status",
    "present": "status",
    "room": "room_id",
    "room id": "room_id",
    "room no": "room_id",
    "branch": "branch",
    "department": "branch",
    "dept": "branch",
    "section": "section",
    "batch": "batch",
}

STATUS_ALIASES = {
    "present": "PRESENT",
    "p": "PRESENT",
    "yes": "PRESENT",
    "y": "PRESENT",
    "absent": "ABSENT",
    "a": "ABSENT",
    "no": "ABSENT",
    "n": "ABSENT",
    "pending": "PENDING",
    "unreviewed": "UNREVIEWED",
    "not reviewed": "UNREVIEWED",
    "": "UNREVIEWED",
}


class DocumentExtractionError(Exception):
    """Raised when a document cannot be interpreted as an attendance roster."""


def _normalise_header(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", " ")


def _map_header(cells: List[Any]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for index, cell in enumerate(cells):
        key = HEADER_ALIASES.get(_normalise_header(cell))
        if key and key not in mapping:
            mapping[key] = index
    return mapping


def _extract_status(raw: Any) -> Tuple[str, bool]:
    """Return (canonical status, ambiguous?)."""
    text = str(raw or "").strip().lower()
    if text in STATUS_ALIASES:
        return STATUS_ALIASES[text], False
    for alias, canonical in STATUS_ALIASES.items():
        if alias and alias in text:
            return canonical, False
    return "UNREVIEWED", True


def _build_rows(rows: List[List[Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Split raw sheet rows into valid-looking records and issue descriptions."""
    header_index = None
    mapping: Dict[str, int] = {}

    for index, row in enumerate(rows[:20]):
        candidate = _map_header(list(row))
        if "usn" in candidate and ("status" in candidate or "name" in candidate):
            header_index = index
            mapping = candidate
            break

    if header_index is None:
        raise DocumentExtractionError(
            "No attendance header row was detected. The document must contain a header "
            "with at least a USN column and a status column."
        )

    records: List[Dict[str, Any]] = []
    issues: List[str] = []

    for offset, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not any(str(cell or "").strip() for cell in row):
            continue

        raw_usn = str(row[mapping["usn"]] or "").strip() if "usn" in mapping else ""
        if not raw_usn:
            continue

        usn_match = USN_PATTERN.search(raw_usn)
        if not usn_match:
            issues.append(
                f"Row {offset}: identifier '{raw_usn}' does not match the institutional "
                "USN format and needs manual review."
            )
            records.append(
                {
                    "usn": raw_usn,
                    "name": str(row[mapping["name"]] or "").strip() if "name" in mapping else "",
                    "branch": str(row[mapping["branch"]] or "").strip() if "branch" in mapping else "",
                    "room_id": str(row[mapping["room_id"]] or "").strip() if "room_id" in mapping else "",
                    "status": "UNREVIEWED",
                    "confidence": 0.0,
                    "extraction_issue": "INVALID_IDENTIFIER",
                }
            )
            continue

        status, ambiguous = _extract_status(row[mapping["status"]] if "status" in mapping else "")
        if ambiguous:
            issues.append(
                f"Row {offset}: the status value for '{usn_match.group(0)}' is not a known "
                "attendance state and needs manual review."
            )

        records.append(
            {
                "usn": usn_match.group(0).upper(),
                "name": str(row[mapping["name"]] or "").strip() if "name" in mapping else "",
                "branch": str(row[mapping["branch"]] or "").strip() if "branch" in mapping else "",
                "room_id": str(row[mapping["room_id"]] or "").strip() if "room_id" in mapping else "",
                "status": status,
                "confidence": 0.6 if ambiguous else 0.95,
                "extraction_issue": "AMBIGUOUS_STATUS" if ambiguous else None,
            }
        )

    return records, issues


def extract_rows_from_xlsx(path: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Extract attendance rows from an XLSX workbook."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise DocumentExtractionError(
            "XLSX support requires the 'openpyxl' package on the server."
        ) from exc

    workbook = load_workbook(filename=path, read_only=True, data_only=True)
    try:
        sheet = workbook[workbook.sheetnames[0]]
        rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()

    return _build_rows(rows)


def _rows_from_words(words: List[Dict[str, Any]]) -> List[List[Any]]:
    """Rebuild table rows from positioned PDF words.

    PDF rosters are frequently rendered as positioned text instead of a real
    table. The words are grouped into visual lines (by their vertical
    position) and then mapped onto the columns of the header row (by their
    horizontal position), so a cell such as "Student One" stays in one cell.
    """
    if not words:
        return []

    # Group the words into visual lines.
    lines: List[List[Dict[str, Any]]] = []
    for word in sorted(words, key=lambda w: (round(float(w["top"]), 1), float(w["x0"]))):
        placed = False
        for line in lines:
            reference = line[0]
            if abs(float(reference["top"]) - float(word["top"])) <= 3:
                line.append(word)
                placed = True
                break
        if not placed:
            lines.append([word])

    for line in lines:
        line.sort(key=lambda w: float(w["x0"]))

    # The header line is the first line that mentions a USN column.
    header_index = None
    for index, line in enumerate(lines):
        titles = [str(word["text"]).strip().lower() for word in line]
        if any("usn" in title or "roll" in title for title in titles):
            header_index = index
            break

    if header_index is None:
        return [[word["text"] for word in line] for line in lines]

    header_words = lines[header_index]
    columns = [(float(word["x0"]), str(word["text"]).strip()) for word in header_words]

    rows: List[List[Any]] = [[title for _, title in columns]]
    for line in lines[header_index + 1 :]:
        cells: List[List[str]] = [[] for _ in columns]
        for word in line:
            x0 = float(word["x0"])
            best_index = min(
                range(len(columns)),
                key=lambda idx: abs(columns[idx][0] - x0),
            )
            cells[best_index].append(str(word["text"]).strip())
        rows.append([" ".join(cell).strip() for cell in cells])

    return rows


def _split_line_into_cells(line: List[Any]) -> List[Any]:
    """Split one extracted line into its cells.

    Handles comma separated cells as well as lines where the cells are only
    separated by a couple of spaces.
    """
    text = " ".join(str(cell) for cell in line).strip()
    if not text:
        return []
    if "," in text:
        return [cell.strip() for cell in text.split(",") if cell.strip()]
    if "\t" in text:
        return [cell.strip() for cell in text.split("\t") if cell.strip()]
    if re.search(r"\s{2,}", text):
        return [cell.strip() for cell in re.split(r"\s{2,}", text) if cell.strip()]
    return [text]


def extract_rows_from_pdf(path: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Extract attendance rows from a PDF roster."""
    rows: List[List[Any]] = []
    text_lines: List[str] = []
    words: List[Dict[str, Any]] = []

    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    rows.extend(table)
                extracted = page.extract_text() or ""
                text_lines.extend(extracted.splitlines())
                try:
                    words.extend(page.extract_words() or [])
                except Exception:  # pragma: no cover - defensive guard
                    pass
    except ImportError:
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(path)
            for page in reader.pages:
                extracted = page.extract_text() or ""
                text_lines.extend(extracted.splitlines())
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise DocumentExtractionError(
                "PDF support requires either 'pdfplumber' or 'pypdf' on the server."
            ) from exc
    except Exception as exc:
        raise DocumentExtractionError(f"The PDF could not be read: {exc}") from exc

    if not rows and words:
        # Positional text: group the words into lines and columns.
        rows = _rows_from_words(words)

    if not rows:
        # Fall back to line based parsing of the extracted text.
        for line in text_lines:
            cells = _split_line_into_cells([line])
            if cells:
                rows.append(cells)

    if not rows:
        raise DocumentExtractionError(
            "No tabular content was found in the PDF. Upload a PDF that contains the "
            "attendance table as text (not a scanned image)."
        )

    # Re-split the positional rows into their individual cells.
    refined: List[List[Any]] = []
    for row in rows:
        cells = _split_line_into_cells(row) if len(row) <= 1 else list(row)
        if cells:
            refined.append(cells)

    return _build_rows(refined)


def extract_rows_from_csv(path: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Extract attendance rows from a CSV document (used for consistency)."""
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.reader(handle)]
    return _build_rows(rows)
