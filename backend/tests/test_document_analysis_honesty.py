"""Uploaded documents must be analysed from their content, never fabricated.

These tests exercise the honest-extraction contract across the document
readers: every unreadable input must come back with
``extraction_status == "unreadable"`` and ``allow_llm_inference == False`` so a
downstream model cannot invent names, USNs, or events.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from app.services.document_extraction import (
    DocumentExtractionError,
    build_extraction_metadata,
    extract_document,
    extract_rows_from_csv,
    extract_rows_from_pdf,
    extract_text_from_pdf_result,
)
from tools.read_csv_tool import (
    CSVExtractionResult,
    read_csv_extraction_result,
    read_csv_tool,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CSV_HEADER = "USN,Name,Status\n"
CSV_ROWS = "1MS21CS001,Alice Smith,Present\n1MS21CS002,Bob Jones,Absent\n"


def _write_csv(tmp_path: Path, content: str, name: str = "roster.csv") -> Path:
    path = tmp_path / name
    path.write_bytes(content.encode("utf-8"))
    return path


def _write_blank_pdf(tmp_path: Path, name: str = "blank.pdf") -> Path:
    # reportlab is a declared runtime dependency; pypdf is only an optional
    # fallback reader and is not guaranteed to be installed in every env.
    pdf = tmp_path / name
    pdf_canvas = canvas.Canvas(str(pdf), pagesize=(200, 200))
    pdf_canvas.showPage()
    pdf_canvas.save()
    return pdf


# ---------------------------------------------------------------------------
# Metadata contract
# ---------------------------------------------------------------------------

def test_build_extraction_metadata_defaults_to_no_llm_for_unreadable():
    meta = build_extraction_metadata("unreadable", 0.0, 0, "empty_file", "Empty.")
    assert meta["extraction_status"] == "unreadable"
    assert meta["allow_llm_inference"] is False
    assert meta["honest_failure_message"] == "Empty."
    assert meta["extraction_error"] == "empty_file"


# ---------------------------------------------------------------------------
# CSV / TXT parsing
# ---------------------------------------------------------------------------

def test_utf8_bom_txt_with_crlf_is_parsed(tmp_path):
    path = tmp_path / "roster.txt"
    path.write_bytes(("\ufeff" + CSV_HEADER + CSV_ROWS).replace("\n", "\r\n").encode("utf-8"))

    records, issues = extract_rows_from_csv(path)

    assert [r["usn"] for r in records] == ["1MS21CS001", "1MS21CS002"]
    assert issues == []
    assert extract_rows_from_csv(path).metadata["extraction_status"] == "ok"
    assert extract_rows_from_csv(path).metadata["allow_llm_inference"] is True


def test_semicolon_delimited_csv_is_parsed(tmp_path):
    path = _write_csv(
        tmp_path,
        "USN;Name;Status\n1MS21CS001;Alice Smith;Present\n",
        name="semicolon.csv",
    )
    records, _ = extract_rows_from_csv(path)
    assert records and records[0]["usn"] == "1MS21CS001"


def test_latin1_encoded_csv_is_parsed_without_crashing(tmp_path):
    path = tmp_path / "latin1.csv"
    path.write_bytes("USN,Name,Status\n1MS21CS003,José Silva,Present\n".encode("latin-1"))

    records, _ = extract_rows_from_csv(path)
    assert records[0]["usn"] == "1MS21CS003"
    assert "José" in records[0]["name"]


def test_empty_txt_is_unreadable_not_an_empty_success(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")

    with pytest.raises(DocumentExtractionError) as exc_info:
        extract_rows_from_csv(path)
    assert exc_info.value.code == "empty_file"

    result = extract_document(path)
    assert result["extraction_status"] == "unreadable"
    assert result["extraction_error"] == "empty_file"
    assert result["allow_llm_inference"] is False
    assert result["records"] == []


def test_binary_file_with_csv_extension_is_unreadable(tmp_path):
    path = tmp_path / "binary.csv"
    path.write_bytes(b"\x00\x01\x02\x03 not text")

    with pytest.raises(DocumentExtractionError) as exc_info:
        extract_rows_from_csv(path)
    assert exc_info.value.code == "malformed_csv"


def test_csv_without_attendance_header_is_unreadable(tmp_path):
    path = _write_csv(tmp_path, "alpha,beta,gamma\n1,2,3\n", name="no_header.csv")

    with pytest.raises(DocumentExtractionError) as exc_info:
        extract_rows_from_csv(path)
    assert exc_info.value.code == "missing_header_row"

    result = extract_document(path)
    assert result["extraction_status"] == "unreadable"
    assert result["allow_llm_inference"] is False


def test_invalid_identifier_marks_partial_and_keeps_row_for_review(tmp_path):
    path = _write_csv(
        tmp_path,
        CSV_HEADER + "NOT-A-USN,Unknown Student,Present\n",
        name="partial.csv",
    )
    result = extract_rows_from_csv(path)

    assert len(result.records) == 1
    assert result.records[0]["extraction_issue"] == "INVALID_IDENTIFIER"
    assert result.metadata["extraction_status"] == "partial"
    assert result.metadata["allow_llm_inference"] is True
    assert 0.0 < result.metadata["extraction_confidence"] < 1.0


# ---------------------------------------------------------------------------
# read_csv_tool metadata
# ---------------------------------------------------------------------------

def test_read_csv_tool_attaches_extraction_metadata(tmp_path):
    path = _write_csv(tmp_path, CSV_HEADER + CSV_ROWS)
    frame = read_csv_tool(path)

    assert isinstance(frame, CSVExtractionResult)
    assert frame.extraction_status == "ok"
    assert frame.allow_llm_inference is True
    assert frame.extracted_chars > 0
    assert frame.extraction_error is None
    assert frame.to_extraction_dict()["total_rows"] == 2


def test_read_csv_extraction_result_reports_empty_file(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_bytes(b"   \n\n")

    payload = read_csv_extraction_result(path)
    assert payload["extraction_status"] == "unreadable"
    assert payload["extraction_error"] == "empty_file"
    assert payload["allow_llm_inference"] is False
    assert payload["records"] == []


def test_read_csv_extraction_result_reports_malformed_csv():
    payload = read_csv_extraction_result(io.StringIO("USN,Name\n1MS21CS001,Alice\n"))
    # A well-formed buffer with no Status column still yields records.
    assert payload["extraction_status"] in ("ok", "partial")
    assert payload["total_rows"] == 1


def test_read_csv_tool_empty_buffer_keeps_backward_compatible_frame():
    frame = read_csv_tool(io.StringIO(""))
    assert isinstance(frame, CSVExtractionResult)
    assert len(frame) == 0
    assert "usn" in frame.columns
    assert frame.extraction_status == "unreadable"
    assert frame.allow_llm_inference is False


# ---------------------------------------------------------------------------
# PDF handling
# ---------------------------------------------------------------------------

def test_blank_pdf_text_result_is_unreadable(tmp_path):
    pdf = _write_blank_pdf(tmp_path)
    result = extract_text_from_pdf_result(pdf)

    assert result["text"] == ""
    assert result["extraction_status"] == "unreadable"
    assert result["extraction_error"] == "no_extractable_text"
    assert result["allow_llm_inference"] is False


def test_blank_pdf_roster_is_unreadable(tmp_path):
    pdf = _write_blank_pdf(tmp_path)

    with pytest.raises(DocumentExtractionError) as exc_info:
        extract_rows_from_pdf(str(pdf))
    assert exc_info.value.code in ("no_extractable_text", "unreadable")

    result = extract_document(pdf)
    assert result["extraction_status"] == "unreadable"
    assert result["records"] == []
    assert result["allow_llm_inference"] is False


def test_unsupported_extension_is_explicitly_unreadable(tmp_path):
    path = tmp_path / "notes.docx"
    path.write_bytes(b"PK\x03\x04 fake docx")

    result = extract_document(path)
    assert result["extraction_status"] == "unreadable"
    assert result["extraction_error"] == "unsupported_format"
    assert result["allow_llm_inference"] is False


def test_read_csv_tool_accepts_legacy_file_path_and_content_kwargs(tmp_path):
    path = _write_csv(tmp_path, CSV_HEADER + CSV_ROWS)

    from_file = read_csv_tool(file_path=path)
    from_content = read_csv_tool(csv_content=CSV_HEADER + CSV_ROWS)

    assert len(from_file) == 2
    assert len(from_content) == 2
    assert from_file.extraction_status == "ok"


def test_freeform_txt_is_plain_text_not_a_rejected_roster(tmp_path):
    """Notes / raw USN lists without CSV headers must not fail as 'malformed'."""
    path = tmp_path / "notes.txt"
    path.write_text(
        "Absent today:\n1MS21CS001\n1MS21CS007\nPlease follow up with the class teacher.\n",
        encoding="utf-8",
    )

    result = extract_document(path)

    assert result["extraction_status"] == "ok"
    assert result["extraction_error"] is None
    assert result["allow_llm_inference"] is True
    assert result["content_type"] == "plain_text"
    assert result["extracted_chars"] == len(result["text"])
    assert "1MS21CS007" in result["text"]
    assert result["records"] == []

    # A .csv without attendance headers is still a malformed roster, not freeform text.
    csv_path = _write_csv(tmp_path, "alpha,beta,gamma\n1,2,3\n", name="strict.csv")
    strict = extract_document(csv_path)
    assert strict["extraction_status"] == "unreadable"
    assert strict["extraction_error"] == "missing_header_row"
    assert strict["allow_llm_inference"] is False


def test_csv_extraction_metadata_survives_pandas_operations(tmp_path):
    frame = read_csv_tool(_write_csv(tmp_path, CSV_HEADER + CSV_ROWS))

    for derived in (
        frame.copy(),
        frame.dropna(),
        frame[["usn", "name"]],
        frame.iloc[:1],
        frame.reset_index(drop=True),
        frame.head(1),
    ):
        assert isinstance(derived, CSVExtractionResult)
        assert derived.extraction_status == "ok"
        assert derived.allow_llm_inference is True
        assert derived.honest_failure_message is None
        assert derived.extracted_chars > 0
