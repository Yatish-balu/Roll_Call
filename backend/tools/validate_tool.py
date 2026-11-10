"""Tool for validating attendance records against business rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Collection, Dict, List, Optional, Set, Union
import pandas as pd


@dataclass
class ValidationError:
    """Represents a single validation issue found in a record."""
    row_index: int
    usn: Optional[str]
    error_type: str
    field: str
    message: str
    row_data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "row_index": self.row_index,
            "usn": self.usn,
            "error_type": self.error_type,
            "field": self.field,
            "message": self.message,
            "row_data": self.row_data,
        }


@dataclass
class ValidationResult:
    """Holds comprehensive results of attendance dataset validation."""
    is_valid: bool
    total_records: int
    valid_records: List[Dict[str, Any]]
    invalid_records: List[Dict[str, Any]]
    errors: List[ValidationError] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "total_records": self.total_records,
            "valid_count": len(self.valid_records),
            "invalid_count": len(self.invalid_records),
            "errors": [e.to_dict() for e in self.errors],
            "summary": self.summary,
        }

    def error_types(self) -> Set[str]:
        return {e.error_type for e in self.errors}


def _is_blank(value: Any) -> bool:
    """Check if value is None, NaN, or an empty/whitespace string."""
    if value is None:
        return True
    if pd.isna(value):
        return True
    return str(value).strip() == ""


VALID_STATUS_ALIASES = {
    "present", "p", "1", "yes", "true",
    "absent", "a", "0", "no", "false",
    "pending",
    "unreviewed", "ambiguous",
}

STATUS_CANONICAL = {
    "present": "PRESENT", "p": "PRESENT", "1": "PRESENT", "yes": "PRESENT", "true": "PRESENT",
    "absent": "ABSENT", "a": "ABSENT", "0": "ABSENT", "no": "ABSENT", "false": "ABSENT",
    "pending": "PENDING",
    "unreviewed": "UNREVIEWED", "ambiguous": "UNREVIEWED",
}


def validate_tool(
    data: Union[pd.DataFrame, List[Dict[str, Any]]],
    known_usns: Optional[Collection[str]] = None,
    known_rooms: Optional[Collection[str]] = None,
    required_columns: Optional[Collection[str]] = None,
) -> ValidationResult:
    """
    Validate attendance records according to business rules:
    - Flags missing required columns.
    - Flags duplicate USNs within the dataset.
    - Flags conflicting statuses for duplicate appearances of the same student.
    - Flags unknown USNs (if known_usns master collection is supplied).
    - Flags missing room ('room_id' or 'room') and unknown rooms (if known_rooms supplied).
    - Flags missing branch ('branch').
    - Flags blank status ('status') and invalid statuses (not PRESENT, ABSENT, PENDING, UNREVIEWED).

    Args:
        data: DataFrame or list of dictionary records.
        known_usns: Optional set/list of valid registered USNs.
        known_rooms: Optional set/list of valid registered room IDs.
        required_columns: Optional list of mandatory columns (e.g. ['usn', 'status', 'room_id', 'branch']).

    Returns:
        ValidationResult with clean records, invalid records, and itemized errors.
    """
    errors: List[ValidationError] = []

    if isinstance(data, pd.DataFrame):
        actual_cols = set(data.columns)
        records: List[Dict[str, Any]] = data.to_dict(orient="records")
    else:
        records = [dict(r) for r in data]
        actual_cols = set(records[0].keys()) if records else set()

    # Column name aliasing for required check
    normalized_actual_cols = set()
    for col in actual_cols:
        c = str(col).strip().lower()
        if c in ("room", "room_no"):
            normalized_actual_cols.add("room_id")
        elif c in ("dept", "department"):
            normalized_actual_cols.add("branch")
        elif c in ("student_usn", "roll_no", "rollno"):
            normalized_actual_cols.add("usn")
        else:
            normalized_actual_cols.add(c)

    # 1. Check required columns if specified
    if required_columns is not None:
        for req in required_columns:
            req_clean = str(req).strip().lower()
            if req_clean not in normalized_actual_cols and req not in actual_cols:
                errors.append(
                    ValidationError(
                        row_index=0,
                        usn=None,
                        error_type="MISSING_COLUMN",
                        field=req,
                        message=f"Mandatory column '{req}' is missing from the attendance dataset.",
                        row_data={},
                    )
                )

    # Prepare normalized set of known USNs & Rooms if provided
    normalized_known_usns: Optional[Set[str]] = None
    if known_usns is not None:
        normalized_known_usns = {str(u).strip().upper() for u in known_usns if str(u).strip()}

    normalized_known_rooms: Optional[Set[str]] = None
    if known_rooms is not None:
        normalized_known_rooms = {str(r).strip().upper() for r in known_rooms if str(r).strip()}

    seen_usns: Dict[str, Dict[str, Any]] = {}  # USN -> {"row": row_idx, "status": canonical_status}
    invalid_row_indices: Set[int] = set()

    for idx, row in enumerate(records, start=1):
        raw_usn = row.get("usn")
        cleaned_usn = str(raw_usn).strip().upper() if not _is_blank(raw_usn) else None
        raw_status = row.get("status")
        cleaned_status_str = str(raw_status).strip().lower() if not _is_blank(raw_status) else ""
        canonical_status = STATUS_CANONICAL.get(cleaned_status_str, cleaned_status_str.upper())
        row_has_error = False

        # Blank or missing USN
        if cleaned_usn is None:
            errors.append(
                ValidationError(
                    row_index=idx,
                    usn=None,
                    error_type="BLANK_USN",
                    field="usn",
                    message="USN is missing or blank.",
                    row_data=row,
                )
            )
            row_has_error = True
        else:
            # Duplicate and Conflicting USN check
            if cleaned_usn in seen_usns:
                first_info = seen_usns[cleaned_usn]
                first_row = first_info["row"]
                first_status = first_info["status"]

                errors.append(
                    ValidationError(
                        row_index=idx,
                        usn=cleaned_usn,
                        error_type="DUPLICATE_USN",
                        field="usn",
                        message=f"Duplicate USN '{cleaned_usn}' (first appeared at row {first_row}).",
                        row_data=row,
                    )
                )
                row_has_error = True

                # Check if duplicate has conflicting status
                if canonical_status and first_status and canonical_status != first_status:
                    errors.append(
                        ValidationError(
                            row_index=idx,
                            usn=cleaned_usn,
                            error_type="CONFLICTING_STATUS",
                            field="status",
                            message=(
                                f"Conflicting attendance status for student '{cleaned_usn}': "
                                f"'{raw_status}' at row {idx} conflicts with '{first_status}' at row {first_row}."
                            ),
                            row_data=row,
                        )
                    )
            else:
                seen_usns[cleaned_usn] = {"row": idx, "status": canonical_status}

            # Unknown USN
            if normalized_known_usns is not None and cleaned_usn not in normalized_known_usns:
                errors.append(
                    ValidationError(
                        row_index=idx,
                        usn=cleaned_usn,
                        error_type="UNKNOWN_USN",
                        field="usn",
                        message=f"USN '{cleaned_usn}' not found in known students list.",
                        row_data=row,
                    )
                )
                row_has_error = True

        # Room checks (Missing & Unknown)
        room_val = row.get("room_id") if "room_id" in row else row.get("room")
        if _is_blank(room_val):
            errors.append(
                ValidationError(
                    row_index=idx,
                    usn=cleaned_usn,
                    error_type="MISSING_ROOM",
                    field="room_id",
                    message="Room is missing or blank.",
                    row_data=row,
                )
            )
            row_has_error = True
        elif normalized_known_rooms is not None:
            cleaned_room = str(room_val).strip().upper()
            if cleaned_room not in normalized_known_rooms:
                errors.append(
                    ValidationError(
                        row_index=idx,
                        usn=cleaned_usn,
                        error_type="UNKNOWN_ROOM",
                        field="room_id",
                        message=f"Room '{room_val}' not found in known rooms list.",
                        row_data=row,
                    )
                )
                row_has_error = True

        # Missing Branch
        branch_val = row.get("branch") if "branch" in row else row.get("dept")
        if _is_blank(branch_val):
            errors.append(
                ValidationError(
                    row_index=idx,
                    usn=cleaned_usn,
                    error_type="MISSING_BRANCH",
                    field="branch",
                    message="Branch is missing or blank.",
                    row_data=row,
                )
            )
            row_has_error = True

        # Status checks (Blank & Invalid)
        if _is_blank(raw_status):
            errors.append(
                ValidationError(
                    row_index=idx,
                    usn=cleaned_usn,
                    error_type="BLANK_STATUS",
                    field="status",
                    message="Attendance status is blank or missing.",
                    row_data=row,
                )
            )
            row_has_error = True
        elif cleaned_status_str not in VALID_STATUS_ALIASES:
            errors.append(
                ValidationError(
                    row_index=idx,
                    usn=cleaned_usn,
                    error_type="INVALID_STATUS",
                    field="status",
                    message=(
                        f"Invalid attendance status '{raw_status}'. "
                        "Must be one of PRESENT, ABSENT, PENDING, UNREVIEWED."
                    ),
                    row_data=row,
                )
            )
            row_has_error = True

        if row_has_error:
            invalid_row_indices.add(idx)

    valid_records = [
        r for idx, r in enumerate(records, start=1) if idx not in invalid_row_indices
    ]
    invalid_records = [
        r for idx, r in enumerate(records, start=1) if idx in invalid_row_indices
    ]

    # Error summary counts
    error_summary: Dict[str, int] = {}
    for err in errors:
        error_summary[err.error_type] = error_summary.get(err.error_type, 0) + 1

    return ValidationResult(
        is_valid=len(errors) == 0,
        total_records=len(records),
        valid_records=valid_records,
        invalid_records=invalid_records,
        errors=errors,
        summary=error_summary,
    )


# Alias
validate_attendance = validate_tool
