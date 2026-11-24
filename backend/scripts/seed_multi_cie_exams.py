"""Seed realistic multi-subject DSCE CIE-3 Exam demonstration data with branch consolidation matrix."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.db.connection import get_sync_session_factory
from app.db.models import Exam, ExamSeating, RoomAssignment, User


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


CIE_EXAMS_DATA = [
    {
        "exam_id": "DSCE-CIE3-NOV2026",
        "name": "Continuous Internal Assessment Test-III - November 2026",
        "date": "2026-11-02",
        "start_time": "10:00:00",
        "end_time": "11:30:00",
        "subject_code": "22CY72",
        "subject_name": "Cyber Forensics & Incident Response",
        "semester": 7,
        "department": "Department of Computer Science and Engineering (Cyber Security)",
    },
    {
        "exam_id": "DSCE-CIE3-22CY72",
        "name": "Continuous Internal Assessment Test-III - Cyber Forensics",
        "date": "2026-11-02",
        "start_time": "10:00:00",
        "end_time": "11:30:00",
        "subject_code": "22CY72",
        "subject_name": "Cyber Forensics & Incident Response",
        "semester": 7,
        "department": "Department of Computer Science and Engineering (Cyber Security)",
    },
    {
        "exam_id": "DSCE-CIE3-22CY73",
        "name": "Continuous Internal Assessment Test-III - Cloud Security",
        "date": "2026-11-02",
        "start_time": "14:00:00",
        "end_time": "15:30:00",
        "subject_code": "22CY73",
        "subject_name": "Cloud Security & DevSecOps",
        "semester": 7,
        "department": "Department of Computer Science and Engineering (Cyber Security)",
    },
    {
        "exam_id": "DSCE-CIE3-22CY741",
        "name": "Continuous Internal Assessment Test-III - Mobile & IoT Security",
        "date": "2026-11-03",
        "start_time": "10:00:00",
        "end_time": "11:30:00",
        "subject_code": "22CY741",
        "subject_name": "Mobile & IoT Security",
        "semester": 7,
        "department": "Department of Computer Science and Engineering (Cyber Security)",
    },
    {
        "exam_id": "DSCE-CIE3-22HS71A",
        "name": "Continuous Internal Assessment Test-III - Universal Human Values",
        "date": "2026-11-04",
        "start_time": "10:00:00",
        "end_time": "11:30:00",
        "subject_code": "22HS71A",
        "subject_name": "Universal Human Values & Ethics",
        "semester": 7,
        "department": "Department of Computer Science and Engineering (Cyber Security)",
    },
    {
        "exam_id": "DSCE-CIE3-22CY77",
        "name": "Continuous Internal Assessment Test-III - Penetration Testing",
        "date": "2026-11-04",
        "start_time": "14:00:00",
        "end_time": "15:30:00",
        "subject_code": "22CY77",
        "subject_name": "Penetration Testing & Vulnerability Assessment",
        "semester": 7,
        "department": "Department of Computer Science and Engineering (Cyber Security)",
    },
]

# The 32 students in CDS 105 from the real-world DSCE Form-B
DSCE_CDS105_STUDENTS = [
    (1, "1DS23CY037", "Nikhita Thupakula", "CY", "1"),
    (2, "1DS23CY038", "Nikita Kulshreshtha", "CY", "2"),
    (3, "1DS23CY039", "P A Likhith Reddy", "CY", "3"),
    (4, "1DS23CY040", "Pragathi B S", "CY", "4"),
    (5, "1DS23CY041", "Preeti R", "CY", "5"),
    (6, "1DS23CY042", "Raghvendra", "CY", "6"),
    (7, "1DS23CY043", "Rahul Narayan", "CY", "7"),
    (8, "1DS23CY044", "Reshma Mallappa", "CY", "8"),
    (9, "1DS23CY045", "Rifat Nausheen", "CY", "9"),
    (10, "1DS23CY046", "Rishabh V S", "CY", "10"),
    (11, "1DS23CY047", "Riya", "CY", "11"),
    (12, "1DS23CY048", "Samarth B C", "CY", "12"),
    (13, "1DS23CY049", "Satwik Tomar", "CY", "13"),
    (14, "1DS23CY050", "Satyam Kumar", "CY", "14"),
    (15, "1DS23CY051", "Shashikiran S", "CY", "15"),
    (16, "1DS23CY052", "Shaurya Ranjan", "CY", "16"),
    (17, "1DS23CY053", "Shivakumar Ashok M", "CY", "17"),
    (18, "1DS23CY056", "Srushti V Hugar", "CY", "18"),
    (19, "1DS23CY057", "Sudhanshu Kumar", "CY", "19"),
    (20, "1DS23CY058", "Sunay Manoj Kulkarni", "CY", "20"),
    (21, "1DS23CY059", "Surendra S", "CY", "21"),
    (22, "1DS23CY060", "Suyash Sinha", "CY", "22"),
    (23, "1DS23CY061", "Varun M", "CY", "23"),
    (24, "1DS23CY062", "Vishal V", "CY", "24"),
    (25, "1DS23CY063", "Vishnu C V", "CY", "25"),
    (26, "1DS24CY400", "Abhishek Mandavakar", "CY", "26"),
    (27, "1DS24CY401", "Adarshyogi Mathapati", "CY", "27"),
    (28, "1DS24CY402", "Charan S", "CY", "28"),
    (29, "1DS24CY403", "Nasreen Taj", "CY", "29"),
    (30, "1DS24CY404", "Nikhil M", "CY", "30"),
    (31, "1DS22CY059", "Varsha Singh", "CY", "31"),
    (32, "1DS22CY034", "Prateek Singh", "CY", "32"),
]


def seed_multi_cie_exams():
    factory = get_sync_session_factory()
    db = factory()
    try:
        t_fac = db.get(User, "faculty_ds") or db.get(User, "test_faculty")
        fac_id = t_fac.user_id if t_fac else "faculty_ds"

        for ex_info in CIE_EXAMS_DATA:
            eid = ex_info["exam_id"]
            existing = db.get(Exam, eid)
            if existing:
                db.query(ExamSeating).filter(ExamSeating.exam_id == eid).delete()
                db.query(RoomAssignment).filter(RoomAssignment.exam_id == eid).delete()
                db.delete(existing)
                db.commit()

            # Create Exam record
            exam_obj = Exam(
                exam_id=eid,
                name=ex_info["name"],
                exam_type="THEORY_CIE",
                semester=ex_info["semester"],
                department=ex_info["department"],
                date=ex_info["date"],
                start_time=ex_info["start_time"],
                end_time=ex_info["end_time"],
                cutoff_minutes=45,
                subject_code=ex_info["subject_code"],
                subject_name=ex_info["subject_name"],
                created_by="admin_root",
                created_at=_utcnow_iso(),
            )
            db.add(exam_obj)
            db.commit()

            # Create Room Assignments
            # Assign faculty_ds to CDS 105 with OVERRIDE:TESTING so it stays OPEN
            rooms_list = [
                ("CDS 105", "CY Building", 35, fac_id, "OPEN", "OVERRIDE:TESTING"),
                ("CDS 106", "CY Building", 35, "test_faculty", "OPEN", "OVERRIDE:TESTING"),
                ("LH 201", "Main Heritage Block", 30, "test_faculty", "OPEN", "OVERRIDE:TESTING"),
                ("LH 202", "Main Heritage Block", 30, "test_faculty", "OPEN", "OVERRIDE:TESTING"),
            ]
            for r_no, blk, cap, inv, st, sub_by in rooms_list:
                db.add(
                    RoomAssignment(
                        exam_id=eid,
                        room_no=r_no,
                        block_name=blk,
                        capacity=cap,
                        invigilator_id=inv,
                        status=st,
                        submitted_at=None,
                        submitted_by=sub_by,
                    )
                )
            db.commit()

            # Seed Seating:
            # 1. CDS 105 students (32 CY students)
            sub = ex_info["subject_code"]
            for sl, usn, name, branch, seat in DSCE_CDS105_STUDENTS:
                # Determine status per subject
                stat = "PRESENT"
                if sub == "22CY72" and usn in ("1DS23CY040", "1DS24CY400"):
                    stat = "ABSENT"
                elif sub == "22CY73" and usn == "1DS23CY045":
                    stat = "ABSENT"
                elif sub == "22CY741" and usn == "1DS23CY041":
                    stat = "ABSENT"
                elif sub == "22CY77" and usn in ("1DS23CY040", "1DS23CY048"):
                    stat = "ABSENT"

                db.add(
                    ExamSeating(
                        exam_id=eid,
                        room_no="CDS 105",
                        sl_no=sl,
                        usn=usn,
                        name=name,
                        branch=branch,
                        subject_code=sub,
                        seat_no=seat,
                        status=stat,
                        marked_by=fac_id,
                        marked_source="AI_SCAN" if stat == "PRESENT" else "MANUAL",
                        marked_at=_utcnow_iso(),
                    )
                )

            # 2. CDS 106 students (25 CY students)
            for i in range(1, 26):
                usn = f"1DS23CY0{63 + i:02d}"
                name = f"CY Student {i}"
                stat = "PRESENT"
                if sub == "22CY77" and i == 24:
                    stat = "ABSENT"
                db.add(
                    ExamSeating(
                        exam_id=eid,
                        room_no="CDS 106",
                        sl_no=32 + i,
                        usn=usn,
                        name=name,
                        branch="CY",
                        subject_code=sub,
                        seat_no=str(i),
                        status=stat,
                        marked_by="test_faculty",
                        marked_source="MANUAL",
                        marked_at=_utcnow_iso(),
                    )
                )

            # 3. LH 201 students (20 CSE branch students)
            for i in range(1, 21):
                usn = f"1DS23CS0{i:02d}"
                name = f"CSE Student {i}"
                stat = "PRESENT"
                if sub == "22CY73" and i == 5:
                    stat = "ABSENT"
                db.add(
                    ExamSeating(
                        exam_id=eid,
                        room_no="LH 201",
                        sl_no=i,
                        usn=usn,
                        name=name,
                        branch="CSE",
                        subject_code=sub,
                        seat_no=str(i),
                        status=stat,
                        marked_by="test_faculty",
                        marked_source="MANUAL",
                        marked_at=_utcnow_iso(),
                    )
                )

            db.commit()
            print(f"Seeded exam: {eid} ({sub}) with 77 students across 3 rooms.")

        print("All CIE-3 multi-subject exams seeded successfully!")
        return True
    finally:
        db.close()


if __name__ == "__main__":
    seed_multi_cie_exams()
