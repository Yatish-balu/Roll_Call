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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("rollcall.services.document_extraction")

USN_PATTERN = re.compile(r"\b\d{1,2}[A-Za-z]{2}\d{2}[A-Za-z]{2}\d{3}\b")

# Honest-extraction contract shared across the document readers.
EXTRACTION_OK = "ok"
EXTRACTION_PARTIAL = "partial"
EXTRACTION_UNREADABLE = "unreadable"


def build_extraction_metadata(
    status: str,
    confidence: float,
    extracted_chars: int,
    extraction_error: Optional[str] = None,
    honest_failure_message: Optional[str] = None,
    allow_llm_inference: Optional[bool] = None,
) -> Dict[str, Any]:
    """Return the standard metadata block attached to every extraction result."""
    if allow_llm_inference is None:
        allow_llm_inference = status != EXTRACTION_UNREADABLE
    return {
        "extraction_status": status,
        "extraction_confidence": round(max(0.0, min(1.0, float(confidence))), 3),
        "extracted_chars": int(max(0, extracted_chars)),
        "extraction_error": extraction_error,
        "honest_failure_message": honest_failure_message,
        "allow_llm_inference": bool(allow_llm_inference),
    }


class DocumentExtractionResult(tuple):
    """``(records, issues)`` tuple that also carries extraction metadata.

    Tuple subclassing keeps every existing ``records, issues = fn(path)``
    caller working while exposing ``.metadata`` / ``.to_dict()`` for the
    honesty-aware callers and tests.
    """

    metadata: Dict[str, Any]

    def __new__(
        cls,
        records: List[Dict[str, Any]],
        issues: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "DocumentExtractionResult":
        obj = super().__new__(cls, (records, issues))
        obj.metadata = metadata or build_extraction_metadata(
            EXTRACTION_UNREADABLE, 0.0, 0, "unreadable"
        )
        return obj

    @property
    def records(self) -> List[Dict[str, Any]]:
        return self[0]

    @property
    def issues(self) -> List[str]:
        return self[1]

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "records": self.records,
            "issues": self.issues,
        }
        payload.update(self.metadata)
        return payload


def _rows_metadata(
    records: List[Dict[str, Any]],
    issues: List[str],
    extracted_chars: int,
) -> Dict[str, Any]:
    """Summarise row extraction honestly (never invents a success)."""
    if not records:
        return build_extraction_metadata(
            EXTRACTION_UNREADABLE,
            0.0,
            extracted_chars,
            "no_rows_detected",
            "No student rows could be read from this document. Check that it contains "
            "a USN column and a status column.",
            False,
        )
    flagged = [
        r for r in records
        if r.get("extraction_issue") in ("INVALID_IDENTIFIER", "AMBIGUOUS_STATUS")
    ]
    status = EXTRACTION_PARTIAL if flagged else EXTRACTION_OK
    # A partial read is still useful, so keep it above the "unreadable" floor.
    confidence = 1.0 if not flagged else 0.5 + 0.5 * (1.0 - len(flagged) / len(records))
    message = None
    if status == EXTRACTION_PARTIAL:
        message = (
            f"{len(flagged)} of {len(records)} rows are ambiguous or use an invalid "
            "identifier and need manual review."
        )
    return build_extraction_metadata(
        status,
        confidence,
        extracted_chars,
        None,
        message,
        True,
    )

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
    """Raised when a document cannot be interpreted as an attendance roster.

    ``code`` is a stable machine-readable cause (``empty_file``,
    ``unsupported_format``, ``malformed_csv``, ``no_extractable_text``, ...)
    so callers can report a specific problem instead of a vague failure.
    """

    def __init__(self, message: str, code: str = "unreadable") -> None:
        super().__init__(message)
        self.code = code

    @property
    def extraction_error(self) -> str:
        """The stable extraction-error code, matching the result metadata key."""
        return self.code

    @property
    def honest_failure_message(self) -> str:
        """User-facing explanation, matching the result metadata key."""
        return str(self)

    @property
    def allow_llm_inference(self) -> bool:
        """Unreadable documents never permit downstream inference."""
        return False


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
            "with at least a USN column and a status column.",
            code="missing_header_row",
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
        if not workbook.sheetnames:
            raise DocumentExtractionError(
                "The workbook contains no worksheets.", code="empty_file"
            )
        sheet = workbook[workbook.sheetnames[0]]
        rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()

    if not any(any(str(cell or "").strip() for cell in row) for row in rows):
        raise DocumentExtractionError(
            "The workbook is empty.", code="empty_file"
        )

    records, issues = _build_rows(rows)
    chars = sum(
        len(str(cell)) for row in rows for cell in row if str(cell or "").strip()
    )
    return DocumentExtractionResult(records, issues, _rows_metadata(records, issues, chars))


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
            "attendance table as text (not a scanned image).",
            code="no_extractable_text",
        )

    # Re-split the positional rows into their individual cells.
    refined: List[List[Any]] = []
    for row in rows:
        cells = _split_line_into_cells(row) if len(row) <= 1 else list(row)
        if cells:
            refined.append(cells)

    records, issues = _build_rows(refined)
    chars = len("\n".join(text_lines)) or sum(
        len(str(cell)) for row in refined for cell in row if str(cell or "").strip()
    )
    return DocumentExtractionResult(records, issues, _rows_metadata(records, issues, chars))


def extract_text_from_pdf(path: str, max_chars: int = 24000) -> str:
    """Return the readable text of a PDF, or an empty string.

    Used for document classification (calendar vs timetable vs roster) and for
    extracting structured events from a Calendar of Events PDF. Never invent
    content when the PDF is scanned/image-only.
    """
    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(path) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception:
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(path)
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            return ""

    return text.strip()[:max_chars]


def extract_text_from_pdf_result(
    path: str, max_chars: int = 24000
) -> Dict[str, Any]:
    """Return ``{"text", **metadata}`` for a PDF, honestly reporting blank scans.

    ``extract_text_from_pdf`` keeps its historical ``str`` return for existing
    callers; this variant is for callers that must distinguish "empty PDF" from
    "PDF with text" before asking a model anything.
    """
    try:
        text = extract_text_from_pdf(path, max_chars=max_chars)
    except Exception as exc:  # defensive: extract_text_from_pdf already guards
        return {
            "text": "",
            **build_extraction_metadata(
                EXTRACTION_UNREADABLE,
                0.0,
                0,
                "unreadable_pdf",
                "The PDF could not be opened or parsed.",
                False,
            ),
        }

    if not text.strip():
        return {
            "text": "",
            **build_extraction_metadata(
                EXTRACTION_UNREADABLE,
                0.0,
                0,
                "no_extractable_text",
                (
                    "The PDF contains no selectable text. It is probably a scan; "
                    "upload a text-based PDF or a clear photo instead."
                ),
                False,
            ),
        }
    return {
        "text": text,
        **build_extraction_metadata(EXTRACTION_OK, 1.0, len(text)),
    }


_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def _read_text_with_fallback(path: str) -> str:
    """Read a text/CSV file, tolerating BOMs, CRLF and non-UTF8 encodings."""
    file_path = Path(path)
    raw = file_path.read_bytes()
    if not raw.strip():
        raise DocumentExtractionError(
            "The uploaded file is empty.", code="empty_file"
        )
    if b"\x00" in raw[:8192]:
        raise DocumentExtractionError(
            "The uploaded file looks binary, not a CSV or text file.",
            code="malformed_csv",
        )
    for encoding in _TEXT_ENCODINGS:
        try:
            # utf-8-sig strips the BOM; the plain decoders keep CRLF intact.
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentExtractionError(
        "The uploaded file could not be decoded as text.", code="malformed_csv"
    )


def _sniff_delimiter(text: str) -> str:
    """Detect the column delimiter of a CSV/TXT attendance sheet."""
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        counts = {delimiter: sample.count(delimiter) for delimiter in (",", ";", "\t", "|")}
        best = max(counts, key=counts.get)
        return best if counts[best] else ","


def extract_rows_from_csv(path: str) -> DocumentExtractionResult:
    """Extract attendance rows from a CSV/TXT document.

    Handles UTF-8 BOM, CRLF line endings, and comma/semicolon/tab/pipe
    delimiters. Empty or binary files raise ``DocumentExtractionError`` with a
    specific code instead of returning a bare empty list.
    """
    text = _read_text_with_fallback(path)
    delimiter = _sniff_delimiter(text)
    try:
        rows = [row for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)]
    except csv.Error as exc:
        raise DocumentExtractionError(
            f"The CSV could not be parsed: {exc}", code="malformed_csv"
        ) from exc

    if not any(any(str(cell or "").strip() for cell in row) for row in rows):
        raise DocumentExtractionError(
            "The uploaded file contains no data rows.", code="empty_file"
        )

    records, issues = _build_rows(rows)
    return DocumentExtractionResult(
        records, issues, _rows_metadata(records, issues, len(text))
    )


def extract_text_from_txt(path: str) -> Dict[str, Any]:
    """Read a freeform ``.txt`` file as plain text (no roster assumptions).

    Notes, notices, and raw lists of USNs legitimately have no CSV column
    headers. Returning the text with ``extraction_status="ok"`` lets the agent
    answer from the real content instead of rejecting the upload as a
    malformed roster.
    """
    text = _read_text_with_fallback(path)
    if not text.strip():
        raise DocumentExtractionError(
            "The uploaded text file is empty.", code="empty_file"
        )
    return {
        "text": text,
        **build_extraction_metadata(EXTRACTION_OK, 1.0, len(text)),
    }


def extract_document(path: str) -> Dict[str, Any]:
    """Extract any supported attendance document into an honest result dict.

    Never raises for unreadable input: the returned dict always carries
    ``extraction_status``, ``extraction_error``, ``honest_failure_message``
    and ``allow_llm_inference`` so the agent can report the real problem
    instead of guessing. The suffix decides the reader.
    """
    suffix = Path(path).suffix.lower()

    # A freeform .txt is not necessarily a CSV. Try the structured roster
    # reader first, and only fall back to plain text when the file simply does
    # not look like an attendance table. Header validation stays strict for
    # .csv (and for .txt files that do contain tabular attendance data).
    if suffix == ".txt":
        try:
            text_result = extract_text_from_txt(path)
        except DocumentExtractionError as exc:
            return {
                "records": [],
                "issues": [str(exc)],
                **build_extraction_metadata(
                    EXTRACTION_UNREADABLE,
                    0.0,
                    0,
                    exc.code,
                    str(exc),
                    False,
                ),
            }
        try:
            result = extract_rows_from_csv(path)
        except DocumentExtractionError as exc:
            if exc.code != "missing_header_row":
                return {
                    "records": [],
                    "issues": [str(exc)],
                    **build_extraction_metadata(
                        EXTRACTION_UNREADABLE,
                        0.0,
                        0,
                        exc.code,
                        str(exc),
                        False,
                    ),
                }
            metadata = {
                key: text_result[key]
                for key in (
                    "extraction_status",
                    "extraction_confidence",
                    "extracted_chars",
                    "extraction_error",
                    "honest_failure_message",
                    "allow_llm_inference",
                )
            }
            return {
                "records": [],
                "issues": [],
                "text": text_result["text"],
                "content_type": "plain_text",
                **metadata,
            }
        else:
            return {**result.to_dict(), "content_type": "attendance_table"}

    try:
        if suffix == ".csv":
            result = extract_rows_from_csv(path)
        elif suffix == ".pdf":
            result = extract_rows_from_pdf(path)
        elif suffix in (".xlsx", ".xls"):
            result = extract_rows_from_xlsx(path)
        else:
            raise DocumentExtractionError(
                f"Unsupported file format '{suffix}'.",
                code="unsupported_format",
            )
    except DocumentExtractionError as exc:
        return {
            "records": [],
            "issues": [str(exc)],
            **build_extraction_metadata(
                EXTRACTION_UNREADABLE,
                0.0,
                0,
                exc.code,
                str(exc),
                False,
            ),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "records": [],
            "issues": [str(exc)],
            **build_extraction_metadata(
                EXTRACTION_UNREADABLE,
                0.0,
                0,
                "unreadable_document",
                f"The document could not be read: {exc}",
                False,
            ),
        }

    return result.to_dict()
