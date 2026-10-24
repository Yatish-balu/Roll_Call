"""Database CLI utility for inspection, initialization, and seeding."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path when running script directly
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.db import (
    DEFAULT_DB_PATH,
    get_connection,
    init_db,
    insert_student,
    insert_room,
    insert_session,
    insert_attendance,
)

# ==========================================
# Synthetic Seed Data (~200 students, 6 rooms, 4 branches, 5 sessions)
# ==========================================

BRANCHES = [
    {"code": "CS", "branch": "CSE"},
    {"code": "IS", "branch": "ISE"},
    {"code": "EC", "branch": "ECE"},
    {"code": "ME", "branch": "MECH"},
]

FIRST_NAMES = [
    "Aarav", "Aditi", "Alice", "Bob", "Charlie", "David", "Emma", "Farhan",
    "Gaurav", "Harini", "Ishaan", "John", "Kavya", "Liam", "Meera", "Nikhil",
    "Pooja", "Rahul", "Sneha", "Tanvi", "Varun", "Zara", "Karan", "Ananya", "Rohan"
]

LAST_NAMES = [
    "Sharma", "Patel", "Verma", "Rao", "Nair", "Smith", "Johnson", "Brown",
    "Williams", "Jones", "Kumar", "Singh", "Das", "Gupta", "Mishra", "Reddy"
]


def _generate_synthetic_students() -> List[Dict[str, str]]:
    """Generate exactly 200 dummy students (50 per branch)."""
    students: List[Dict[str, str]] = []
    for b in BRANCHES:
        code = b["code"]
        branch = b["branch"]
        for i in range(1, 51):
            usn = f"1MS21{code}{i:03d}"
            fn = FIRST_NAMES[(i - 1) % len(FIRST_NAMES)]
            ln = LAST_NAMES[((i - 1) // len(FIRST_NAMES)) % len(LAST_NAMES)]
            students.append({"usn": usn, "name": f"{fn} {ln}", "branch": branch})
    return students


SAMPLE_STUDENTS: List[Dict[str, str]] = _generate_synthetic_students()

SAMPLE_ROOMS: List[Dict[str, str]] = [
    {"room_id": "LH-101", "name": "Lecture Hall 101"},
    {"room_id": "LH-102", "name": "Lecture Hall 102"},
    {"room_id": "LH-201", "name": "Lecture Hall 201"},
    {"room_id": "LH-202", "name": "Lecture Hall 202"},
    {"room_id": "LAB-1", "name": "Computer Science Lab 1"},
    {"room_id": "LAB-2", "name": "Electronics & Hardware Lab 2"},
]

SAMPLE_SESSIONS: List[Dict[str, str]] = [
    {"session_id": "SESS-20261024-01", "date": "2026-10-24", "subject": "Distributed Systems"},
    {"session_id": "SESS-20261024-02", "date": "2026-10-24", "subject": "Machine Learning"},
    {"session_id": "SESS-20261025-01", "date": "2026-10-25", "subject": "Computer Networks"},
    {"session_id": "SESS-20261025-02", "date": "2026-10-25", "subject": "Database Systems"},
    {"session_id": "SESS-20261026-01", "date": "2026-10-26", "subject": "Embedded Systems"},
]


def _generate_synthetic_attendance() -> List[Dict[str, Any]]:
    """
    Generate realistic multi-session attendance records with all four states:
    PRESENT, ABSENT, PENDING, UNREVIEWED across rooms and branches.
    Deterministic distribution for reconciliation testing.
    """
    records: List[Dict[str, Any]] = []

    # Session 1: 40 CSE students in LH-101 (25 PRESENT, 10 ABSENT, 3 PENDING, 2 UNREVIEWED)
    for i in range(1, 41):
        usn = f"1MS21CS{i:03d}"
        if i <= 25:
            st, src, conf = "PRESENT", "camera", 0.95
        elif i <= 35:
            st, src, conf = "ABSENT", "manual", 1.0
        elif i <= 38:
            st, src, conf = "PENDING", "missing_sheet", 1.0
        else:
            st, src, conf = "UNREVIEWED", "ocr_ambiguous", 0.55
        records.append({
            "session_id": "SESS-20261024-01",
            "usn": usn,
            "room_id": "LH-101",
            "status": st,
            "source": src,
            "confidence": conf,
        })

    # Session 2: 50 ISE students in LH-102 (35 PRESENT, 5 ABSENT, 6 PENDING, 4 UNREVIEWED)
    for i in range(1, 51):
        usn = f"1MS21IS{i:03d}"
        if i <= 35:
            st, src, conf = "PRESENT", "rfid", 1.0
        elif i <= 40:
            st, src, conf = "ABSENT", "manual", 1.0
        elif i <= 46:
            st, src, conf = "PENDING", "missing_sheet", 1.0
        else:
            st, src, conf = "UNREVIEWED", "camera", 0.60
        records.append({
            "session_id": "SESS-20261024-02",
            "usn": usn,
            "room_id": "LH-102",
            "status": st,
            "source": src,
            "confidence": conf,
        })

    # Session 3: 30 ECE students in LH-201 (18 PRESENT, 6 ABSENT, 4 PENDING, 2 UNREVIEWED)
    for i in range(1, 31):
        usn = f"1MS21EC{i:03d}"
        if i <= 18:
            st, src, conf = "PRESENT", "camera", 0.94
        elif i <= 24:
            st, src, conf = "ABSENT", "manual", 1.0
        elif i <= 28:
            st, src, conf = "PENDING", "missing_sheet", 1.0
        else:
            st, src, conf = "UNREVIEWED", "camera", 0.50
        records.append({
            "session_id": "SESS-20261025-01",
            "usn": usn,
            "room_id": "LH-201",
            "status": st,
            "source": src,
            "confidence": conf,
        })

    # Session 4: 45 MECH students in LH-202 (30 PRESENT, 10 ABSENT, 0 PENDING, 5 UNREVIEWED)
    for i in range(1, 46):
        usn = f"1MS21ME{i:03d}"
        if i <= 30:
            st, src, conf = "PRESENT", "rfid", 1.0
        elif i <= 40:
            st, src, conf = "ABSENT", "manual", 1.0
        else:
            st, src, conf = "UNREVIEWED", "ocr_ambiguous", 0.52
        records.append({
            "session_id": "SESS-20261025-02",
            "usn": usn,
            "room_id": "LH-202",
            "status": st,
            "source": src,
            "confidence": conf,
        })

    # Session 5: 20 CSE students in LAB-1 (15 PRESENT, 5 ABSENT, 0 PENDING, 0 UNREVIEWED)
    for i in range(1, 21):
        usn = f"1MS21CS{i:03d}"
        st = "PRESENT" if i <= 15 else "ABSENT"
        src = "manual" if i > 15 else "camera"
        records.append({
            "session_id": "SESS-20261026-01",
            "usn": usn,
            "room_id": "LAB-1",
            "status": st,
            "source": src,
            "confidence": 0.98 if st == "PRESENT" else 1.0,
        })

    return records


SAMPLE_ATTENDANCE: List[Dict[str, Any]] = _generate_synthetic_attendance()



def inspect_database(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Inspect existing tables and record counts in the SQLite database."""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name ASC;")
        tables = [row["name"] for row in cursor.fetchall() if not row["name"].startswith("sqlite_")]

        counts: Dict[str, int] = {}
        for table in tables:
            c_cur = conn.cursor()
            c_cur.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = c_cur.fetchone()[0]

        return {
            "db_path": db_path,
            "tables": tables,
            "counts": counts,
        }
    finally:
        conn.close()


def setup_database(db_path: str = DEFAULT_DB_PATH, seed: bool = True) -> Dict[str, Any]:
    """Initialize schema tables and optionally seed starter data."""
    print(f"[*] Initializing database schema at: {db_path}")
    conn = init_db(db_path)

    seeded_info = {"students": 0, "rooms": 0, "sessions": 0, "attendance": 0}

    if seed:
        print("[*] Seeding sample data...")
        for s in SAMPLE_STUDENTS:
            try:
                insert_student(conn, usn=s["usn"], name=s["name"], branch=s["branch"])
                seeded_info["students"] += 1
            except sqlite3.IntegrityError:
                pass

        for r in SAMPLE_ROOMS:
            try:
                insert_room(conn, room_id=r["room_id"], name=r["name"])
                seeded_info["rooms"] += 1
            except sqlite3.IntegrityError:
                pass

        for sess in SAMPLE_SESSIONS:
            try:
                insert_session(conn, session_id=sess["session_id"], date=sess["date"], subject=sess["subject"])
                seeded_info["sessions"] += 1
            except sqlite3.IntegrityError:
                pass

        for att in SAMPLE_ATTENDANCE:
            try:
                insert_attendance(
                    conn,
                    session_id=att["session_id"],
                    usn=att["usn"],
                    room_id=att["room_id"],
                    status=att["status"],
                    source=att["source"],
                    confidence=att["confidence"],
                    upsert=True,
                )
                seeded_info["attendance"] += 1
            except sqlite3.IntegrityError:
                pass

    conn.close()
    inspection = inspect_database(db_path)
    return {
        "status": "success",
        "db_path": db_path,
        "seeded": seeded_info,
        "inspection": inspection,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="RollCall Database Management Tool")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="Path to SQLite database")
    parser.add_argument("--inspect", action="store_true", help="Inspect database status only")
    parser.add_argument("--no-seed", action="store_true", help="Initialize schema without seeding data")
    args = parser.parse_args()

    if args.inspect:
        info = inspect_database(args.db_path)
        print(f"Database: {info['db_path']}")
        print(f"Tables found ({len(info['tables'])}): {info['tables']}")
        for tbl, count in info["counts"].items():
            print(f"  - {tbl}: {count} rows")
    else:
        res = setup_database(args.db_path, seed=not args.no_seed)
        print("\n[+] Database setup completed successfully!")
        print(f"    Path: {res['db_path']}")
        print(f"    Tables: {res['inspection']['tables']}")
        print(f"    Row Counts: {res['inspection']['counts']}")


if __name__ == "__main__":
    main()
