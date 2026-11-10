"""Script for verifying manual reconciliation of 5 test sessions against expected totals."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.db import (
    init_db,
    insert_students_bulk,
    insert_rooms_bulk,
    insert_sessions_bulk,
    insert_attendance_bulk,
    get_session_attendance_details,
)
from tools.summary_tool import summary_tool
from tools.database import (
    SAMPLE_STUDENTS,
    SAMPLE_ROOMS,
    SAMPLE_SESSIONS,
    SAMPLE_ATTENDANCE,
)

# Manually pre-calculated expected totals for 100% mathematical reconciliation
EXPECTED_TOTALS = {
    "SESS-20261024-01": {
        "present": 25,
        "absent": 10,
        "pending": 3,
        "unreviewed": 2,
        "unresolved": 5,
        "confirmed": 35,
        "total": 40,
        "percentage": 71.43,
        "room": "LH-101",
        "branch": "CSE",
    },
    "SESS-20261024-02": {
        "present": 35,
        "absent": 5,
        "pending": 6,
        "unreviewed": 4,
        "unresolved": 10,
        "confirmed": 40,
        "total": 50,
        "percentage": 87.50,
        "room": "LH-102",
        "branch": "ISE",
    },
    "SESS-20261025-01": {
        "present": 18,
        "absent": 6,
        "pending": 4,
        "unreviewed": 2,
        "unresolved": 6,
        "confirmed": 24,
        "total": 30,
        "percentage": 75.00,
        "room": "LH-201",
        "branch": "ECE",
    },
    "SESS-20261025-02": {
        "present": 30,
        "absent": 10,
        "pending": 0,
        "unreviewed": 5,
        "unresolved": 5,
        "confirmed": 40,
        "total": 45,
        "percentage": 75.00,
        "room": "LH-202",
        "branch": "MECH",
    },
    "SESS-20261026-01": {
        "present": 15,
        "absent": 5,
        "pending": 0,
        "unreviewed": 0,
        "unresolved": 0,
        "confirmed": 20,
        "total": 20,
        "percentage": 75.00,
        "room": "LAB-1",
        "branch": "CSE",
    },
}


def run_reconciliation_audit() -> Dict[str, Any]:
    """Execute end-to-end mathematical reconciliation verification."""
    # 1. Setup in-memory test database
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    insert_students_bulk(conn, SAMPLE_STUDENTS)
    insert_rooms_bulk(conn, SAMPLE_ROOMS)
    insert_sessions_bulk(conn, SAMPLE_SESSIONS)
    insert_attendance_bulk(conn, SAMPLE_ATTENDANCE)

    results: List[Dict[str, Any]] = []
    all_passed = True

    print("=" * 80)
    print("RollCall AI - 5-Session Attendance Reconciliation Audit")
    print("=" * 80)

    for sess in SAMPLE_SESSIONS:
        sess_id = sess["session_id"]
        expected = EXPECTED_TOTALS[sess_id]

        # Retrieve session records joined with student branch and room
        records = get_session_attendance_details(conn, sess_id)
        report = summary_tool(records)
        overall = report.overall

        # Check overall
        matches = (
            overall["present"] == expected["present"]
            and overall["absent"] == expected["absent"]
            and overall["pending"] == expected["pending"]
            and overall["unreviewed"] == expected["unreviewed"]
            and overall["unresolved"] == expected["unresolved"]
            and overall["confirmed"] == expected["confirmed"]
            and overall["total"] == expected["total"]
            and abs(overall["percentage"] - expected["percentage"]) < 0.01
        )

        # Check room-wise
        room_recs = report.room_wise_records()
        room_match = False
        for r in room_recs:
            if r["room_id"] == expected["room"]:
                room_match = (
                    r["present"] == expected["present"]
                    and r["absent"] == expected["absent"]
                    and r["pending"] == expected["pending"]
                    and r["unreviewed"] == expected["unreviewed"]
                    and abs(r["percentage"] - expected["percentage"]) < 0.01
                )
                break

        # Check branch-wise
        branch_recs = report.branch_wise_records()
        branch_match = False
        for b in branch_recs:
            if b["branch"] == expected["branch"]:
                branch_match = (
                    b["present"] == expected["present"]
                    and b["absent"] == expected["absent"]
                    and b["pending"] == expected["pending"]
                    and b["unreviewed"] == expected["unreviewed"]
                    and abs(b["percentage"] - expected["percentage"]) < 0.01
                )
                break

        passed = matches and room_match and branch_match
        if not passed:
            all_passed = False

        status_str = "PASS [100% MATCH]" if passed else "FAIL [MISMATCH]"
        print(f"\nSession: {sess_id} ({sess['subject']}) -> {status_str}")
        print(
            f"  Calculated: Present={overall['present']}, Absent={overall['absent']}, "
            f"Pending={overall['pending']}, Unreviewed={overall['unreviewed']}, "
            f"Confirmed={overall['confirmed']}, Total={overall['total']}, Confirmed%={overall['percentage']}%"
        )
        print(
            f"  Expected:   Present={expected['present']}, Absent={expected['absent']}, "
            f"Pending={expected['pending']}, Unreviewed={expected['unreviewed']}, "
            f"Confirmed={expected['confirmed']}, Total={expected['total']}, Confirmed%={expected['percentage']}%"
        )

        results.append({
            "session_id": sess_id,
            "subject": sess["subject"],
            "passed": passed,
            "calculated": overall,
            "expected": expected,
        })

    conn.close()

    print("\n" + "=" * 80)
    print(f"Audit Summary: {'ALL 5 SESSIONS RECONCILED (100%)' if all_passed else 'RECONCILIATION FAILED'}")
    print("=" * 80)

    return {
        "all_passed": all_passed,
        "sessions_checked": len(results),
        "results": results,
    }


if __name__ == "__main__":
    audit = run_reconciliation_audit()
    sys.exit(0 if audit["all_passed"] else 1)
