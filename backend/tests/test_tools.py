"""Tests for read_csv_tool, validate_tool, and summary_tool."""

import io
import pytest
import pandas as pd
from tools import (
    read_csv_tool,
    read_csv_as_records,
    validate_tool,
    summary_tool,
)


@pytest.fixture
def known_students():
    """Fixture providing a master list of registered student USNs."""
    return {"1MS21CS001", "1MS21CS002", "1MS21CS003", "1MS21IS001", "1MS21IS002"}


# ==========================================
# 1. read_csv_tool Tests
# ==========================================

def test_read_csv_valid():
    """Case 1: Standard valid attendance CSV parsing."""
    csv_data = """usn,name,branch,room_id,status
1MS21CS001,Alice Smith,CSE,LH-101,present
1MS21CS002,Bob Jones,CSE,LH-101,absent
"""
    df = read_csv_tool(io.StringIO(csv_data))
    assert len(df) == 2
    assert list(df.columns) == ["usn", "name", "branch", "room_id", "status"]
    assert df.iloc[0]["usn"] == "1MS21CS001"
    assert df.iloc[0]["status"] == "present"


def test_read_csv_whitespace_and_empty_rows():
    """Case 2: Handles messy CSV with extra spaces in headers/cells and empty rows."""
    csv_data = """  Student USN  , Name  , Branch , Room No , Status  
  1MS21CS001   , Alice ,   CSE  ,  LH-101  ,  present  

  1MS21CS002   , Bob   ,   CSE  ,  LH-102  ,  absent   
  
"""
    df = read_csv_tool(io.StringIO(csv_data))
    assert len(df) == 2
    assert "usn" in df.columns
    assert "room_id" in df.columns
    assert df.iloc[0]["usn"] == "1MS21CS001"
    assert df.iloc[0]["room_id"] == "LH-101"
    assert df.iloc[1]["status"] == "absent"


def test_read_csv_missing_file():
    """Case 3: Missing file path raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        read_csv_tool("data/non_existent_file_12345.csv")


# ==========================================
# 2. validate_tool Tests
# ==========================================

def test_validate_clean_data(known_students):
    """Case 4: Completely valid dataset passes validation."""
    records = [
        {"usn": "1MS21CS001", "name": "Alice", "branch": "CSE", "room_id": "LH-101", "status": "present"},
        {"usn": "1MS21CS002", "name": "Bob", "branch": "CSE", "room_id": "LH-101", "status": "absent"},
    ]
    result = validate_tool(records, known_usns=known_students)
    assert result.is_valid is True
    assert len(result.errors) == 0
    assert len(result.valid_records) == 2
    assert len(result.invalid_records) == 0


def test_validate_duplicate_usn():
    """Case 5: Flags duplicate USN appearances in attendance sheet."""
    records = [
        {"usn": "1MS21CS001", "branch": "CSE", "room_id": "LH-101", "status": "present"},
        {"usn": "1MS21CS002", "branch": "CSE", "room_id": "LH-101", "status": "absent"},
        {"usn": "1MS21CS001", "branch": "CSE", "room_id": "LH-101", "status": "present"},  # Duplicate
    ]
    result = validate_tool(records)
    assert result.is_valid is False
    assert "DUPLICATE_USN" in result.error_types()
    assert result.summary["DUPLICATE_USN"] == 1
    assert len(result.valid_records) == 2
    assert len(result.invalid_records) == 1


def test_validate_unknown_usn(known_students):
    """Case 6: Flags USNs that do not exist in the registered students list."""
    records = [
        {"usn": "1MS21CS001", "branch": "CSE", "room_id": "LH-101", "status": "present"},
        {"usn": "99UNKNOWN99", "branch": "ECE", "room_id": "LH-101", "status": "present"},
    ]
    result = validate_tool(records, known_usns=known_students)
    assert result.is_valid is False
    assert "UNKNOWN_USN" in result.error_types()
    assert result.summary["UNKNOWN_USN"] == 1
    assert result.errors[0].usn == "99UNKNOWN99"


def test_validate_missing_room():
    """Case 7: Flags rows where room is missing, empty, or whitespace."""
    records = [
        {"usn": "1MS21CS001", "branch": "CSE", "room_id": "", "status": "present"},
        {"usn": "1MS21CS002", "branch": "CSE", "room_id": "   ", "status": "present"},
        {"usn": "1MS21CS003", "branch": "CSE", "room_id": None, "status": "present"},
    ]
    result = validate_tool(records)
    assert result.is_valid is False
    assert result.summary.get("MISSING_ROOM") == 3
    assert len(result.valid_records) == 0


def test_validate_missing_branch():
    """Case 8: Flags rows where branch is missing or empty."""
    records = [
        {"usn": "1MS21CS001", "branch": "", "room_id": "LH-101", "status": "present"},
        {"usn": "1MS21CS002", "branch": None, "room_id": "LH-101", "status": "present"},
    ]
    result = validate_tool(records)
    assert result.is_valid is False
    assert result.summary.get("MISSING_BRANCH") == 2
    assert len(result.invalid_records) == 2


def test_validate_blank_status():
    """Case 9: Flags rows where attendance status is missing, empty, or None."""
    records = [
        {"usn": "1MS21CS001", "branch": "CSE", "room_id": "LH-101", "status": ""},
        {"usn": "1MS21CS002", "branch": "CSE", "room_id": "LH-101", "status": "   "},
        {"usn": "1MS21CS003", "branch": "CSE", "room_id": "LH-101", "status": None},
    ]
    result = validate_tool(records)
    assert result.is_valid is False
    assert result.summary.get("BLANK_STATUS") == 3
    assert len(result.valid_records) == 0


def test_validate_combined_bad_data(known_students):
    """Case 10: Multi-issue bad dataset flags duplicate, unknown USN, missing room/branch, blank status."""
    bad_records = [
        # Row 1: Valid
        {"usn": "1MS21CS001", "branch": "CSE", "room_id": "LH-101", "status": "present"},
        # Row 2: Unknown USN + Blank status
        {"usn": "UNKNOWN_USN_999", "branch": "ME", "room_id": "LH-101", "status": ""},
        # Row 3: Missing room + Missing branch
        {"usn": "1MS21CS002", "branch": "", "room_id": "", "status": "absent"},
        # Row 4: Duplicate USN (1MS21CS001 appeared in Row 1)
        {"usn": "1MS21CS001", "branch": "CSE", "room_id": "LH-101", "status": "present"},
    ]
    result = validate_tool(bad_records, known_usns=known_students)
    assert result.is_valid is False
    assert len(result.valid_records) == 1
    assert len(result.invalid_records) == 3

    error_types = result.error_types()
    assert "UNKNOWN_USN" in error_types
    assert "BLANK_STATUS" in error_types
    assert "MISSING_ROOM" in error_types
    assert "MISSING_BRANCH" in error_types
    assert "DUPLICATE_USN" in error_types


# ==========================================
# 3. summary_tool Tests
# ==========================================

def test_summary_room_wise():
    """Case 11: Calculates room-wise present, absent, total, and percentage."""
    records = [
        {"room_id": "LH-101", "branch": "CSE", "status": "present"},
        {"room_id": "LH-101", "branch": "CSE", "status": "present"},
        {"room_id": "LH-101", "branch": "CSE", "status": "absent"},
        {"room_id": "LH-102", "branch": "ISE", "status": "present"},
        {"room_id": "LH-102", "branch": "ISE", "status": "absent"},
    ]
    report = summary_tool(records)
    room_df = report.room_wise

    assert len(room_df) == 2
    lh101 = room_df[room_df["room_id"] == "LH-101"].iloc[0]
    assert lh101["present"] == 2
    assert lh101["absent"] == 1
    assert lh101["total"] == 3
    assert lh101["percentage"] == 66.67

    lh102 = room_df[room_df["room_id"] == "LH-102"].iloc[0]
    assert lh102["present"] == 1
    assert lh102["absent"] == 1
    assert lh102["total"] == 2
    assert lh102["percentage"] == 50.0


def test_summary_branch_wise():
    """Case 12: Calculates branch-wise present, absent, total, and percentage."""
    records = [
        {"room_id": "LH-101", "branch": "CSE", "status": "present"},
        {"room_id": "LH-101", "branch": "CSE", "status": "present"},
        {"room_id": "LH-101", "branch": "CSE", "status": "present"},
        {"room_id": "LH-101", "branch": "ISE", "status": "absent"},
    ]
    report = summary_tool(records)
    branch_df = report.branch_wise

    assert len(branch_df) == 2
    cse = branch_df[branch_df["branch"] == "CSE"].iloc[0]
    assert cse["present"] == 3
    assert cse["absent"] == 0
    assert cse["percentage"] == 100.0

    ise = branch_df[branch_df["branch"] == "ISE"].iloc[0]
    assert ise["present"] == 0
    assert ise["absent"] == 1
    assert ise["percentage"] == 0.0


def test_summary_empty_and_zero_division():
    """Case 13: Handles empty data gracefully without division by zero errors."""
    empty_report = summary_tool([])
    assert empty_report.overall["total"] == 0
    assert empty_report.overall["percentage"] == 0.0
    assert empty_report.room_wise.empty
    assert empty_report.branch_wise.empty


def test_summary_status_variations():
    """Case 14: Accurately normalizes casing and alias variations of status."""
    records = [
        {"room_id": "LH-101", "branch": "CSE", "status": "PRESENT"},
        {"room_id": "LH-101", "branch": "CSE", "status": "Present"},
        {"room_id": "LH-101", "branch": "CSE", "status": "p"},
        {"room_id": "LH-101", "branch": "CSE", "status": "Absent"},
        {"room_id": "LH-101", "branch": "CSE", "status": "0"},
    ]
    report = summary_tool(records)
    assert report.overall["present"] == 3
    assert report.overall["absent"] == 2
    assert report.overall["percentage"] == 60.0


def test_end_to_end_pipeline(known_students):
    """Case 15: Pipeline read_csv -> validate -> summary on valid records."""
    csv_raw = """USN,Name,Branch,Room,Status
1MS21CS001,Alice Smith,CSE,LH-101,present
1MS21CS002,Bob Jones,CSE,LH-101,present
1MS21IS001,Charlie,ISE,LH-102,absent
BAD_USN_999,Ghost Student,ME,LH-102,present
"""
    # 1. Read CSV
    df = read_csv_tool(io.StringIO(csv_raw))
    assert len(df) == 4

    # 2. Validate
    val_result = validate_tool(df, known_usns=known_students)
    assert val_result.is_valid is False
    assert len(val_result.valid_records) == 3
    assert len(val_result.invalid_records) == 1
    assert val_result.invalid_records[0]["usn"] == "BAD_USN_999"

    # 3. Summarize only valid attendance
    summary = summary_tool(val_result.valid_records)
    assert summary.overall["present"] == 2
    assert summary.overall["absent"] == 1
    assert summary.overall["total"] == 3
    assert summary.overall["percentage"] == 66.67


# ==========================================
# 4. Phase 1 Edge Cases & Four-State Model Tests
# ==========================================

def test_read_csv_empty_and_malformed_sources():
    """Requirement 4: Empty and malformed CSV input handling."""
    # Empty StringIO returns empty DataFrame
    df_empty = read_csv_tool(io.StringIO(""))
    assert df_empty.empty

    # Whitespace only StringIO returns empty DataFrame
    df_whitespace = read_csv_tool(io.StringIO("   \n\n  \n"))
    assert df_whitespace.empty


def test_validate_missing_columns():
    """Requirement 4: Flags missing mandatory columns."""
    df_missing_status = pd.DataFrame([
        {"usn": "1MS21CS001", "name": "Alice", "branch": "CSE", "room_id": "LH-101"}
    ])
    result = validate_tool(df_missing_status, required_columns=["usn", "status", "room_id", "branch"])
    assert result.is_valid is False
    assert "MISSING_COLUMN" in result.error_types()
    err = [e for e in result.errors if e.error_type == "MISSING_COLUMN"][0]
    assert err.field == "status"


def test_validate_unknown_room():
    """Requirement 4: Flags rooms not in known rooms master list."""
    known_rooms = {"LH-101", "LH-102"}
    records = [
        {"usn": "1MS21CS001", "branch": "CSE", "room_id": "LH-101", "status": "PRESENT"},
        {"usn": "1MS21CS002", "branch": "CSE", "room_id": "ROOM-999-UNKNOWN", "status": "PRESENT"},
    ]
    result = validate_tool(records, known_rooms=known_rooms)
    assert result.is_valid is False
    assert "UNKNOWN_ROOM" in result.error_types()
    assert result.summary["UNKNOWN_ROOM"] == 1
    assert len(result.valid_records) == 1
    assert len(result.invalid_records) == 1


def test_validate_invalid_status():
    """Requirement 4: Flags invalid attendance statuses."""
    records = [
        {"usn": "1MS21CS001", "branch": "CSE", "room_id": "LH-101", "status": "PRESENT"},
        {"usn": "1MS21CS002", "branch": "CSE", "room_id": "LH-101", "status": "MAYBE_PRESENT"},
        {"usn": "1MS21CS003", "branch": "CSE", "room_id": "LH-101", "status": "EXCUSED"},
    ]
    result = validate_tool(records)
    assert result.is_valid is False
    assert "INVALID_STATUS" in result.error_types()
    assert result.summary["INVALID_STATUS"] == 2
    assert len(result.valid_records) == 1


def test_validate_conflicting_statuses_for_same_student():
    """Requirement 4: Flags duplicate records for the same student that have conflicting statuses."""
    records = [
        {"usn": "1MS21CS001", "branch": "CSE", "room_id": "LH-101", "status": "PRESENT"},
        {"usn": "1MS21CS002", "branch": "CSE", "room_id": "LH-101", "status": "PRESENT"},
        # Duplicate appearance with conflicting status: row 1 was PRESENT, row 3 is ABSENT
        {"usn": "1MS21CS001", "branch": "CSE", "room_id": "LH-101", "status": "ABSENT"},
    ]
    result = validate_tool(records)
    assert result.is_valid is False
    assert "DUPLICATE_USN" in result.error_types()
    assert "CONFLICTING_STATUS" in result.error_types()
    conflict_err = [e for e in result.errors if e.error_type == "CONFLICTING_STATUS"][0]
    assert conflict_err.usn == "1MS21CS001"
    assert "conflicts with" in conflict_err.message


def test_summary_four_state_metrics_and_confirmed_percentage():
    """
    Requirement 1 & 3:
    - Keep PRESENT and ABSENT counts strictly separate from PENDING and UNREVIEWED.
    - Confirmed attendance percentage is strictly: PRESENT / (PRESENT + ABSENT).
    - Neither PENDING nor UNREVIEWED is ever defaulted or miscounted as ABSENT.
    - Display unresolved counts as separate metrics.
    """
    records = [
        {"room_id": "LH-101", "branch": "CSE", "status": "PRESENT"},
        {"room_id": "LH-101", "branch": "CSE", "status": "PRESENT"},
        {"room_id": "LH-101", "branch": "CSE", "status": "PRESENT"},  # 3 present
        {"room_id": "LH-101", "branch": "CSE", "status": "ABSENT"},   # 1 absent
        {"room_id": "LH-101", "branch": "CSE", "status": "PENDING"},  # 1 pending (missing sheet)
        {"room_id": "LH-101", "branch": "CSE", "status": "UNREVIEWED"}, # 1 unreviewed (ambiguous)
    ]
    report = summary_tool(records)
    overall = report.overall

    # Separate counts
    assert overall["present"] == 3
    assert overall["absent"] == 1
    assert overall["pending"] == 1
    assert overall["unreviewed"] == 1
    assert overall["unresolved"] == 2
    assert overall["confirmed"] == 4
    assert overall["total"] == 6

    # Confirmed percentage calculation: 3 / (3 + 1) * 100 = 75.0%
    # (NOT 3 / 6 * 100 = 50% which would miscount pending/unreviewed as absent!)
    assert overall["percentage"] == 75.0

    # Room-wise verification
    lh101 = report.room_wise_records()[0]
    assert lh101["present"] == 3
    assert lh101["absent"] == 1
    assert lh101["pending"] == 1
    assert lh101["unreviewed"] == 1
    assert lh101["unresolved"] == 2
    assert lh101["confirmed"] == 4
    assert lh101["total"] == 6
    assert lh101["percentage"] == 75.0


def test_missing_or_ambiguous_never_defaults_to_absent():
    """
    Requirement 1: Verify missing sheets / ambiguous entries are never defaulted to ABSENT.
    """
    records = [
        {"room_id": "LH-101", "branch": "CSE", "status": None},         # missing sheet -> PENDING
        {"room_id": "LH-101", "branch": "CSE", "status": ""},           # blank status -> PENDING
        {"room_id": "LH-101", "branch": "CSE", "status": "ambiguous"},  # ambiguous -> UNREVIEWED
        {"room_id": "LH-101", "branch": "CSE", "status": "unreviewed"}, # unreviewed -> UNREVIEWED
    ]
    report = summary_tool(records)
    overall = report.overall

    # Zero students should be counted as ABSENT!
    assert overall["absent"] == 0
    assert overall["present"] == 0
    assert overall["pending"] == 2
    assert overall["unreviewed"] == 2
    assert overall["unresolved"] == 4
    assert overall["confirmed"] == 0
    assert overall["percentage"] == 0.0

