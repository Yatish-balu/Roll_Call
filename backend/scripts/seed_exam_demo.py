"""Seed realistic DSCE Form-B Exam demonstration data."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure backend directory is in sys.path when executed directly
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.db.connection import get_sync_session_factory
from app.db.models import Exam, ExamSeating, RoomAssignment, User


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_exam_demo_data():
    factory = get_sync_session_factory()
    db = factory()

    try:
        exam_id = "DSCE-CIE3-NOV2026"

        # Clean existing demo exam if present
        existing_exam = db.get(Exam, exam_id)
        if existing_exam:
            db.query(ExamSeating).filter(ExamSeating.exam_id == exam_id).delete()
            db.query(RoomAssignment).filter(RoomAssignment.exam_id == exam_id).delete()
            db.delete(existing_exam)
            db.commit()

        # 1. Create Exam
        exam = Exam(
            exam_id=exam_id,
            name="Continuous Internal Assessment Test-III - November 2026",
            exam_type="THEORY_CIE",
            semester=7,
            department="Department of Computer Science and Engineering (Cyber Security)",
            date="2026-11-02",
            start_time="10:00:00",
            end_time="11:30:00",
            cutoff_minutes=30,
            subject_code="22CY72",
            subject_name="Cyber Forensics & Incident Response",
            created_by="admin_root",
            created_at=_utcnow_iso(),
        )
        db.add(exam)
        db.commit()

        # 2. Rooms
        # Ensure teachers exist
        t1 = db.get(User, "teacher_cn")
        t1_id = t1.user_id if t1 else None

        rooms_data = [
            ("CDS 105", "CY Building", 35, t1_id, "SUBMITTED", "2026-11-02T10:28:15Z"),
            ("CDS 106", "CY Building", 35, t1_id, "OPEN", None),
            ("LH 201", "Main Heritage Block", 30, t1_id, "LATE_LOCKED", None),
            ("LH 202", "Main Heritage Block", 30, t1_id, "SCHEDULED", None),
        ]

        for r_no, block, cap, invig, st, sub_at in rooms_data:
            db.add(RoomAssignment(
                exam_id=exam_id,
                room_no=r_no,
                block_name=block,
                capacity=cap,
                invigilator_id=invig,
                status=st,
                submitted_at=sub_at,
                submitted_by=invig if sub_at else None,
            ))
        db.commit()

        # 3. Students for Room CDS 105 (The Exact Real-World DSCE Form-B Sheet!)
        dsce_sheet_students = [
            (1, "1DS23CY037", "Nikhita Thupakula", "CY", "1", "PRESENT"),
            (2, "1DS23CY038", "Nikita Kulshreshtha", "CY", "2", "PRESENT"),
            (3, "1DS23CY039", "P A Likhith Reddy", "CY", "3", "PRESENT"),
            (4, "1DS23CY040", "Pragathi B S", "CY", "4", "ABSENT"),  # Marked 'Ab' on sheet!
            (5, "1DS23CY041", "Preeti R", "CY", "5", "PRESENT"),
            (6, "1DS23CY042", "Raghvendra", "CY", "6", "PRESENT"),
            (7, "1DS23CY043", "Rahul Narayan", "CY", "7", "PRESENT"),
            (8, "1DS23CY044", "Reshma Mallappa", "CY", "8", "PRESENT"),
            (9, "1DS23CY045", "Rifat Nausheen", "CY", "9", "PRESENT"),
            (10, "1DS23CY046", "Rishabh V S", "CY", "10", "PRESENT"),
            (11, "1DS23CY047", "Riya", "CY", "11", "PRESENT"),
            (12, "1DS23CY048", "Samarth B C", "CY", "12", "PRESENT"),
            (13, "1DS23CY049", "Satwik Tomar", "CY", "13", "PRESENT"),
            (14, "1DS23CY050", "Satyam Kumar", "CY", "14", "PRESENT"),
            (15, "1DS23CY051", "Shashikiran S", "CY", "15", "PRESENT"),
            (16, "1DS23CY052", "Shaurya Ranjan", "CY", "16", "PRESENT"),
            (17, "1DS23CY053", "Shivakumar Ashok M", "CY", "17", "PRESENT"),
            (18, "1DS23CY056", "Srushti V Hugar", "CY", "18", "PRESENT"),
            (19, "1DS23CY057", "Sudhanshu Kumar", "CY", "19", "PRESENT"),
            (20, "1DS23CY058", "Sunay Manoj Kulkarni", "CY", "20", "PRESENT"),
            (21, "1DS23CY059", "Surendra S", "CY", "21", "PRESENT"),
            (22, "1DS23CY060", "Suyash Sinha", "CY", "22", "PRESENT"),
            (23, "1DS23CY061", "Varun M", "CY", "23", "PRESENT"),
            (24, "1DS23CY062", "Vishal V", "CY", "24", "PRESENT"),
            (25, "1DS23CY063", "Vishnu C V", "CY", "25", "PRESENT"),
            (26, "1DS24CY400", "Abhishek Mandavakar", "CY", "26", "ABSENT"),  # Marked 'Ab' on sheet!
            (27, "1DS24CY401", "Adarshyogi Mathapati", "CY", "27", "PRESENT"),
            (28, "1DS24CY402", "Charan S", "CY", "28", "PRESENT"),
            (29, "1DS24CY403", "Nasreen Taj", "CY", "29", "PRESENT"),
            (30, "1DS24CY404", "Nikhil M", "CY", "30", "PRESENT"),
            (31, "1DS22CY059", "Varsha Singh", "CY", "31", "PRESENT"),
            (32, "1DS22CY034", "Prateek Singh", "CY", "32", "PRESENT"),
        ]

        for sl, usn, name, branch, seat, stat in dsce_sheet_students:
            db.add(ExamSeating(
                exam_id=exam_id,
                room_no="CDS 105",
                sl_no=sl,
                usn=usn,
                name=name,
                branch=branch,
                subject_code="22CY72",
                seat_no=seat,
                status=stat,
                marked_by="teacher_cn",
                marked_source="AI_SCAN" if stat == "PRESENT" else "MANUAL",
                marked_at="2026-11-02T10:20:00Z",
            ))

        # Room CDS 106 (Batch 2 CY students)
        for i in range(1, 26):
            usn = f"1DS23CY0{63 + i:02d}"
            name = f"CY Student {i}"
            db.add(ExamSeating(
                exam_id=exam_id,
                room_no="CDS 106",
                sl_no=i,
                usn=usn,
                name=name,
                branch="CY",
                subject_code="22CY72",
                seat_no=str(i),
                status="PRESENT" if i <= 23 else "ABSENT",
                marked_by="teacher_cn" if i <= 20 else None,
                marked_source="MANUAL" if i <= 20 else None,
            ))

        # Room LH 201 (CSE Branch Students - Late Locked)
        for i in range(1, 21):
            usn = f"1DS23CS0{i:02d}"
            name = f"CSE Student {i}"
            db.add(ExamSeating(
                exam_id=exam_id,
                room_no="LH 201",
                sl_no=i,
                usn=usn,
                name=name,
                branch="CSE",
                subject_code="22CS71",
                seat_no=str(i),
                status="PRESENT" if i % 5 != 0 else "ABSENT",
            ))

        db.commit()
        print("Demo Exam 'DSCE-CIE3-NOV2026' seeded successfully with 4 rooms and 77 students.")
        return True
    finally:
        db.close()


if __name__ == "__main__":
    seed_exam_demo_data()
