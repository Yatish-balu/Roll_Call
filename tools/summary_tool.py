from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union
import pandas as pd

_DEFAULT_SYMBOL_MAP: Dict[str, str] = {
    # Most common single-mark attendance-key conventions.
    "present": "PRESENT",
    "p": "PRESENT",
    "1": "PRESENT",
    "yes": "PRESENT",
    "true": "PRESENT",
    "x": "PRESENT",
    "tick": "PRESENT",
    "ok": "PRESENT",

    "absent": "ABSENT",
    "a": "ABSENT",
    "0": "ABSENT",
    "no": "ABSENT",
    "false": "ABSENT",
    "n": "ABSENT",

    "pending": "PENDING",
    "p/": "PENDING",

    "unreviewed": "UNREVIEWED",
    "ambiguous": "UNREVIEWED",

    "": "PENDING",
}


def normalize_status(
    status_val: Any,
    symbol_map: Optional[Dict[str, str]] = None,
    *,
    default_unknown: str = "UNREVIEWED",
    default_blank: str = "PENDING",
) -> str:
    """
    Normalize a single attendance mark to 'PRESENT', 'ABSENT', 'PENDING', or 'UNREVIEWED'.
    Neither PENDING nor UNREVIEWED is ever defaulted to ABSENT.

    symbol_map : optional dict from raw mark -> canonical status. If None, the default
        RollCall symbol map is used so 'p'/'x'/'tick' -> PRESENT and 'a'/'n' -> ABSENT, etc.
        Passing an explicit map lets an institute/teacher define per-sheet meanings (e.g.
        circle = PRESENT in one department, circle = ABSENT in another).

    default_unknown : canonical status applied to marks not present in symbol_map.
        Defaults to 'UNREVIEWED' so ambiguous marks never silently inflate present/absent counts.

    default_blank : canonical status applied to empty/blank/NaN marks.
        Defaults to 'PENDING'.
    """
    if symbol_map is None:
        symbol_map = _DEFAULT_SYMBOL_MAP

    if status_val is None or pd.isna(status_val):
        return default_blank

    clean = str(status_val).strip().lower()
    if clean == "":
        return default_blank

    mapped = symbol_map.get(clean)
    if mapped is not None:
        return mapped

    return default_unknown


@dataclass
class SummaryReport:
    """Holds room-wise, branch-wise, and overall attendance metrics."""
    room_wise: pd.DataFrame
    branch_wise: pd.DataFrame
    overall: Dict[str, Any]

    def room_wise_records(self) -> List[Dict[str, Any]]:
        return self.room_wise.to_dict(orient="records")

    def branch_wise_records(self) -> List[Dict[str, Any]]:
        return self.branch_wise.to_dict(orient="records")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "room_wise": self.room_wise_records(),
            "branch_wise": self.branch_wise_records(),
            "overall": self.overall,
        }


def _calculate_group_summary(
    df: pd.DataFrame,
    group_col: str,
    output_name: str,
    status_col: str = "norm_status",
) -> pd.DataFrame:
    """
    Calculate present, absent, pending, unreviewed, unresolved, total, and confirmed percentage
    grouped by a specific column.
    Confirmed attendance percentage is calculated strictly as: PRESENT / (PRESENT + ABSENT).

    status_col is the column already normalized by `summary_tool` before grouping.
    """
    summary_cols = [
        output_name,
        "present",
        "absent",
        "pending",
        "unreviewed",
        "unresolved",
        "confirmed",
        "total",
        "percentage",
    ]
    if df.empty or group_col not in df.columns:
        return pd.DataFrame(columns=summary_cols)

    groups = []
    for val, subset in df.groupby(group_col, dropna=False):
        group_label = str(val).strip() if pd.notna(val) and str(val).strip() else "UNKNOWN"
        present_count = int((subset["norm_status"] == "PRESENT").sum())
        absent_count = int((subset["norm_status"] == "ABSENT").sum())
        pending_count = int((subset["norm_status"] == "PENDING").sum())
        unreviewed_count = int((subset["norm_status"] == "UNREVIEWED").sum())

        confirmed_count = present_count + absent_count
        unresolved_count = pending_count + unreviewed_count
        total_count = confirmed_count + unresolved_count

        pct = round((present_count / confirmed_count * 100), 2) if confirmed_count > 0 else 0.0

        groups.append({
            output_name: group_label,
            "present": present_count,
            "absent": absent_count,
            "pending": pending_count,
            "unreviewed": unreviewed_count,
            "unresolved": unresolved_count,
            "confirmed": confirmed_count,
            "total": total_count,
            "percentage": pct,
            "unresolved_by_status": {
                "pending": pending_count,
                "unreviewed": unreviewed_count,
            },
        })

    result_df = pd.DataFrame(groups)
    if not result_df.empty:
        result_df = result_df.sort_values(by=output_name).reset_index(drop=True)
    return result_df


def summary_tool(
    data: Union[pd.DataFrame, List[Dict[str, Any]]],
    symbol_map: Optional[Dict[str, str]] = None,
    *,
    default_unknown: str = "UNREVIEWED",
    default_blank: str = "PENDING",
) -> SummaryReport:
    """
    Generate room-wise and branch-wise attendance summary tables:
    - Calculates count of PRESENT and ABSENT students.
    - Calculates unresolved counts (PENDING, UNREVIEWED) as separate metrics.
    - Confirmed attendance percentage is strictly: PRESENT / (PRESENT + ABSENT).

    Args:
        data: DataFrame or list of dictionary records containing attendance entries.
        symbol_map: optional dict from raw mark -> canonical status. If None, the default
            RollCall symbol map is used. Pass an explicit map when the sheet uses a custom
            convention so that the summary reflects the sheet's actual meaning.
        default_unknown: canonical status applied to marks not present in symbol_map.
        default_blank: canonical status applied to empty/blank/NaN marks.

    Returns:
        SummaryReport object with room_wise, branch_wise DataFrames and overall stats.
    """
    if isinstance(data, pd.DataFrame):
        df = data.copy()
    else:
        df = pd.DataFrame(data)

    empty_cols_room = [
        "room_id", "present", "absent", "pending", "unreviewed", "unresolved", "confirmed", "total", "percentage"
    ]
    empty_cols_branch = [
        "branch", "present", "absent", "pending", "unreviewed", "unresolved", "confirmed", "total", "percentage"
    ]

    if df.empty:
        return SummaryReport(
            room_wise=pd.DataFrame(columns=empty_cols_room),
            branch_wise=pd.DataFrame(columns=empty_cols_branch),
            overall={
                "present": 0,
                "absent": 0,
                "pending": 0,
                "unreviewed": 0,
                "unresolved": 0,
                "confirmed": 0,
                "total": 0,
                "percentage": 0.0,
                "confirmed_percentage": 0.0,
            },
        )

    # Symbol configuration: if an explicit map is supplied, isolate the inferred/ambiguous
    # remainder so the summary can be reported separately later. If no map is supplied, keep
    # the existing default behavior.
    _symbol_map = symbol_map if symbol_map is not None else _DEFAULT_SYMBOL_MAP
    _default_unknown = default_unknown
    _default_blank = default_blank

    # NOTE: `_symbol_map.get(clean, default_unknown)` in normalize_status above can be
    # read as "if the mark is not in the map, use default_unknown". That is not the same
    # as "look up the mark in the map, and if there is no entry treat it as unknown." If a
    # caller passes an explicit map but the mark is still missing from that map, the mark is
    # treated as unknown rather than falling back to the default RollCall map. This matches the
    # requirement that custom maps are authoritative: a mark not in a custom map is ambiguous,
    # not silently remapped by the project default.

    # Standardize column names if needed
    col_mapping = {
        "room": "room_id",
        "room_no": "room_id",
        "dept": "branch",
        "department": "branch",
    }
    df = df.rename(columns=col_mapping)

    # Normalize status column using the configured symbol path so summary counts match
    # the sheet semantics rather than a single hardcoded global rule.
    status_col = "status" if "status" in df.columns else df.columns[0]
    df["norm_status"] = df[status_col].map(
        lambda v: normalize_status(v, _symbol_map, default_unknown=_default_unknown, default_blank=_default_blank)
    )

    # Calculate room-wise summary
    room_col = "room_id" if "room_id" in df.columns else ("room" if "room" in df.columns else None)
    if room_col:
        room_df = _calculate_group_summary(df, room_col, "room_id")
    else:
        room_df = pd.DataFrame(columns=empty_cols_room)

    # Calculate branch-wise summary
    branch_col = "branch" if "branch" in df.columns else ("dept" if "dept" in df.columns else None)
    if branch_col:
        branch_df = _calculate_group_summary(df, branch_col, "branch")
    else:
        branch_df = pd.DataFrame(columns=empty_cols_branch)

    # Overall summary
    total_present = int((df["norm_status"] == "PRESENT").sum())
    total_absent = int((df["norm_status"] == "ABSENT").sum())
    total_pending = int((df["norm_status"] == "PENDING").sum())
    total_unreviewed = int((df["norm_status"] == "UNREVIEWED").sum())

    total_confirmed = total_present + total_absent
    total_unresolved = total_pending + total_unreviewed
    total_all = total_confirmed + total_unresolved
    overall_pct = round((total_present / total_confirmed * 100), 2) if total_confirmed > 0 else 0.0

    overall = {
        "present": total_present,
        "absent": total_absent,
        "pending": total_pending,
        "unreviewed": total_unreviewed,
        "unresolved": total_unresolved,
        "confirmed": total_confirmed,
        "total": total_all,
        "percentage": overall_pct,
        "confirmed_percentage": overall_pct,
    }

    return SummaryReport(
        room_wise=room_df,
        branch_wise=branch_df,
        overall=overall,
    )


# Alias
generate_summary = summary_tool
