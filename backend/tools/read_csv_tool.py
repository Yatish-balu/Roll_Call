"""Tool for reading and parsing attendance CSV / TXT files."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

# Honest-extraction contract shared across the document readers.
EXTRACTION_OK = "ok"
EXTRACTION_PARTIAL = "partial"
EXTRACTION_UNREADABLE = "unreadable"

TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

# Standard header normalization mapping
COLUMN_MAPPING = {
    "usn": "usn",
    "student_usn": "usn",
    "roll_no": "usn",
    "rollno": "usn",
    "name": "name",
    "student_name": "name",
    "branch": "branch",
    "dept": "branch",
    "department": "branch",
    "room": "room_id",
    "room_id": "room_id",
    "room_no": "room_id",
    "status": "status",
    "attendance": "status",
    "attendance_status": "status",
    "source": "source",
    "confidence": "confidence",
    "session_id": "session_id",
}

DEFAULT_COLUMNS = ["usn", "name", "branch", "room_id", "status"]


def _build_metadata(
    status: str,
    confidence: float,
    extracted_chars: int,
    extraction_error: Optional[str] = None,
    honest_failure_message: Optional[str] = None,
    allow_llm_inference: Optional[bool] = None,
) -> Dict[str, Any]:
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


class CSVExtractionResult(pd.DataFrame):
    """A DataFrame that also carries the standard extraction metadata.

    Existing callers that treat the return value as a plain DataFrame (column
    access, ``to_dict``, ``len``) keep working unchanged.
    """

    _metadata = ["extraction_metadata"]

    @property
    def _constructor(self) -> type["CSVExtractionResult"]:
        return CSVExtractionResult

    @property
    def extraction_metadata(self) -> Dict[str, Any]:
        meta = getattr(self, "_extraction_metadata", None)
        if isinstance(meta, dict):
            return meta
        return _build_metadata(EXTRACTION_OK, 1.0, 0)

    @extraction_metadata.setter
    def extraction_metadata(self, value: Dict[str, Any]) -> None:
        object.__setattr__(self, "_extraction_metadata", dict(value))

    @property
    def extraction_status(self) -> str:
        return self.extraction_metadata["extraction_status"]

    @property
    def extraction_confidence(self) -> float:
        return self.extraction_metadata["extraction_confidence"]

    @property
    def extracted_chars(self) -> int:
        return self.extraction_metadata["extracted_chars"]

    @property
    def extraction_error(self) -> Optional[str]:
        return self.extraction_metadata["extraction_error"]

    @property
    def honest_failure_message(self) -> Optional[str]:
        return self.extraction_metadata["honest_failure_message"]

    @property
    def allow_llm_inference(self) -> bool:
        return self.extraction_metadata["allow_llm_inference"]

    def to_extraction_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "records": self.to_dict(orient="records"),
            "total_rows": int(len(self)),
        }
        payload.update(self.extraction_metadata)
        return payload


def normalize_column_name(col: str) -> str:
    """Normalize column header: strip, lower, replace spaces and dashes with underscore."""
    clean = str(col).strip().lower().replace(" ", "_").replace("-", "_")
    return COLUMN_MAPPING.get(clean, clean)


def _decode_bytes(data: bytes) -> str:
    for encoding in TEXT_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("The file could not be decoded as text (unknown encoding).")


def _read_text_source(
    source: Union[str, Path, io.StringIO, io.BytesIO], encoding: Optional[str]
) -> str:
    """Return the raw text of a path or in-memory buffer."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {source}")
        raw = path.read_bytes()
        if not raw.strip():
            return ""
        if b"\x00" in raw[:8192]:
            raise ValueError("The file looks binary, not a CSV or text file.")
        if encoding and encoding != "utf-8":
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                pass
        return _decode_bytes(raw)

    if isinstance(source, io.BytesIO):
        raw = source.getvalue()
        if not raw.strip():
            return ""
        if b"\x00" in raw[:8192]:
            raise ValueError("The file looks binary, not a CSV or text file.")
        return _decode_bytes(raw)

    if isinstance(source, io.StringIO):
        return source.getvalue()

    raise TypeError(
        f"Unsupported CSV source type: {type(source).__name__}. "
        "Expected a path, StringIO, or BytesIO."
    )


def _sniff_delimiter(text: str) -> str:
    """Detect comma / semicolon / tab / pipe separated columns."""
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        counts = {delimiter: sample.count(delimiter) for delimiter in (",", ";", "\t", "|")}
        best = max(counts, key=counts.get)
        return best if counts[best] else ","


def _empty_result() -> CSVExtractionResult:
    frame = CSVExtractionResult(columns=DEFAULT_COLUMNS)
    frame.extraction_metadata = _build_metadata(
        EXTRACTION_UNREADABLE,
        0.0,
        0,
        "empty_file",
        "The uploaded file is empty. Please upload a CSV with a header row and student rows.",
        False,
    )
    return frame


def read_csv_tool(
    source: Optional[Union[str, Path, io.StringIO, io.BytesIO]] = None,
    encoding: str = "utf-8",
    *,
    file_path: Optional[Union[str, Path]] = None,
    csv_content: Optional[str] = None,
    **kwargs: Any,
) -> pd.DataFrame:
    """
    Read an attendance CSV file or buffer into a cleaned pandas DataFrame.

    - Trims whitespace from all string headers and cell values.
    - Normalizes known column headers (e.g. 'Student USN' -> 'usn', 'Room' -> 'room_id').
    - Drops completely empty rows.
    - Preserves empty strings/None for missing values instead of converting to NaN strings.
    - Tolerates UTF-8 BOMs, Windows CRLF, latin-1/cp1252 encodings, and the
      comma/semicolon/tab/pipe delimiters used by different spreadsheet exports.
    - The returned DataFrame also carries ``extraction_status`` and the other
      honest-extraction metadata fields as attributes.

    Legacy keyword aliases ``file_path`` (a path) and ``csv_content`` (raw CSV
    text) are accepted so older tool wrappers calling this function with those
    names keep working.
    """
    if source is None:
        if csv_content is not None:
            source = io.StringIO(csv_content)
        elif file_path is not None:
            source = file_path
        else:
            raise ValueError("read_csv_tool requires a source, file_path, or csv_content.")
    elif isinstance(source, str) and "\n" in source and not Path(source).exists():
        # A raw CSV string rather than a path (legacy behaviour).
        source = io.StringIO(source)

    text = _read_text_source(source, encoding)
    if not text.strip():
        return _empty_result()

    delimiter = _sniff_delimiter(text)
    try:
        df = pd.read_csv(
            io.StringIO(text, newline=""),
            sep=delimiter,
            encoding=encoding,
            dtype=str,
            skip_blank_lines=True,
        )
    except pd.errors.EmptyDataError:
        return _empty_result()
    except Exception as e:
        raise ValueError(f"Malformed or unreadable CSV source: {e}") from e

    # Clean column headers
    df.columns = [normalize_column_name(c) for c in df.columns]

    # Strip whitespace across all string columns
    for col in df.columns:
        df[col] = df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)

    # Drop rows where all columns are empty or null
    is_empty_row = df.apply(
        lambda row: all(pd.isna(val) or str(val).strip() == "" for val in row),
        axis=1,
    )
    df = df[~is_empty_row].reset_index(drop=True)

    result = CSVExtractionResult(df)
    if len(result) == 0:
        result.extraction_metadata = _build_metadata(
            EXTRACTION_UNREADABLE,
            0.0,
            len(text),
            "no_rows_detected",
            "The CSV has a header but no usable data rows.",
            False,
        )
    else:
        result.extraction_metadata = _build_metadata(EXTRACTION_OK, 1.0, len(text))
    return result


def read_csv_as_records(
    source: Union[str, Path, io.StringIO, io.BytesIO],
    encoding: str = "utf-8",
) -> List[Dict[str, Any]]:
    """Convenience helper to read CSV and return a list of row dictionaries."""
    df = read_csv_tool(source, encoding=encoding)
    return df.to_dict(orient="records")


def read_csv_extraction_result(
    source: Union[str, Path, io.StringIO, io.BytesIO],
    encoding: str = "utf-8",
) -> Dict[str, Any]:
    """Read a CSV and return records plus honest-extraction metadata.

    Never raises for malformed or empty input: the returned dict always carries
    the six metadata fields so callers can explain the real problem instead of
    passing an empty frame to a model that might invent rows.
    """
    try:
        frame = read_csv_tool(source, encoding=encoding)
    except FileNotFoundError:
        raise
    except Exception as exc:
        return {
            "records": [],
            "total_rows": 0,
            **_build_metadata(
                EXTRACTION_UNREADABLE,
                0.0,
                0,
                "malformed_csv",
                f"The CSV could not be read: {exc}",
                False,
            ),
        }

    payload = frame.to_extraction_dict() if isinstance(frame, CSVExtractionResult) else {
        "records": frame.to_dict(orient="records"),
        "total_rows": int(len(frame)),
        **_build_metadata(EXTRACTION_OK, 1.0, 0),
    }
    return payload
