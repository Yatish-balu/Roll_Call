"""Tool for reading and parsing attendance CSV files."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import pandas as pd

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


def normalize_column_name(col: str) -> str:
    """Normalize column header: strip, lower, replace spaces and dashes with underscore."""
    clean = str(col).strip().lower().replace(" ", "_").replace("-", "_")
    return COLUMN_MAPPING.get(clean, clean)


def read_csv_tool(
    source: Union[str, Path, io.StringIO, io.BytesIO],
    encoding: str = "utf-8",
) -> pd.DataFrame:
    """
    Read an attendance CSV file or buffer into a cleaned pandas DataFrame.

    - Trims whitespace from all string headers and cell values.
    - Normalizes known column headers (e.g. 'Student USN' -> 'usn', 'Room' -> 'room_id').
    - Drops completely empty rows.
    - Preserves empty strings/None for missing values instead of converting to NaN strings.
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {source}")

    try:
        df = pd.read_csv(
            source,
            encoding=encoding,
            dtype=str,
            skip_blank_lines=True,
        )
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=["usn", "name", "branch", "room_id", "status"])
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

    return df


def read_csv_as_records(
    source: Union[str, Path, io.StringIO, io.BytesIO],
    encoding: str = "utf-8",
) -> List[Dict[str, Any]]:
    """Convenience helper to read CSV and return a list of row dictionaries."""
    df = read_csv_tool(source, encoding=encoding)
    return df.to_dict(orient="records")
