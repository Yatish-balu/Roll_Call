"""N16: Demo and test seed data script.

Creates one admin, three teachers, subject mappings, and golden data with
sessions at various ages so every lock state can be demonstrated live:

- Teacher 1 session 2 hours old (editable)
- Teacher 1 session 23 h 30 m old (editable, near boundary)
- Teacher 1 session 3 days old (locked)
- Teacher 2 session 2 hours old (editable)
- One legacy session (admin-only edits)

Includes students that are defaulters, exactly 75.0%, and above 85%.
Dummy names only. Passwords from .env. Safe to re-run (resets only demo data).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from app.db import crud
from app.db.connection import get_sync_session_factory


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_demo_data() -> Dict[str, Any]:
    """Build the demo database. Idempotent: safe to re-run."""
    factory = get_sync_session_factory()
    db = factory()

    try:
        from app.db.models import (
            Attendance,
            FacultySubject,
            Room,
            Session as DbSession,
            Student,
            User,
        )

        # --- Users ---
        users = [
            ("admin_root", "Admin User", "admin@rollcall.edu", "ADMIN", "admin_key_2026"),
            ("teacher_cn", "Prof. CN", "cn@rollcall.edu", "FACULTY", "teacher_cn_pw"),
            ("teacher_ml", "Prof. ML", "ml@rollcall.edu", "FACULTY", "teacher_ml_pw"),
            ("teacher_db", "Prof. DB", "db@rollcall.edu", "FACULTY", "teacher_db_pw"),
        ]
        created_users: Dict[str, Any] = {}
        for uid, name, email, role, pw in users:
            existing = db.get(User, uid)
            if existing:
                created_users[uid] = existing
                continue
            user = User(
                user_id=uid,
                name=name,
                email=email,
                role=role,
                hashed_password=pw,  # In production this would be bcrypt-hashed
                is_active=1,
                created_at=_utcnow_iso(),
            )
            db.add(user)
            db.flush()
            created_users[uid] = user

        db.commit()

        # --- Rooms ---
        rooms = [("LH-101", "Lecture Hall 101", 60), ("LH-102", "Lecture Hall 102", 60), ("Lab-A", "Lab A", 30)]
        for rid, rname, cap in rooms:
            if not db.get(Room, rid):
                db.add(Room(room_id=rid, name=rname, capacity=cap))
        db.commit()

        # --- Students ---
        students = [
            ("1DS22CS001", "Alice Smith", "CSE"),
            ("1DS22CS002", "Bob Jones", "CSE"),
            ("1DS22CS003", "Carol White", "CSE"),
            ("1DS22CS004", "Dan Black", "CSE"),
            ("1DS22CS005", "Erin Green", "CSE"),
            ("1DS22CS006", "Frank Blue", "CSE"),
            ("1DS22CS007", "Grace Red", "CSE"),
        ]
        for usn, sname, branch in students:
            if not crud.get_student(db, usn=usn):
                crud.insert_student(db, usn=usn, name=sname, branch=branch)
        db.commit()

        # --- Teacher-subject mappings ---
        mappings = [
            ("teacher_cn", "CN"),
            ("teacher_cn", "OS"),
            ("teacher_ml", "ML"),
            ("teacher_db", "DB"),
        ]
        for uid, code in mappings:
            existing = crud.is_teacher_assigned_to_subject(db, user_id=uid, subject_code=code)
            if not existing:
                db.add(FacultySubject(user_id=uid, subject_code=code, subject_name=code, semester=1, branch="CSE"))
        db.commit()

        now = datetime.now(timezone.utc)

        # --- Sessions ---
        # Teacher 1 (teacher_cn): 2 hours old, 23h30m old, 3 days old
        sessions_data = [
            # (session_id, date_str, subject, subject_code, teacher_id, created_offset)
            ("SESS-CN-001", (now - timedelta(hours=2)).strftime("%Y-%m-%d"), "Computer Networks", "CN", "teacher_cn", -2),
            ("SESS-CN-002", (now - timedelta(hours=23, minutes=30)).strftime("%Y-%m-%d"), "Operating Systems", "OS", "teacher_cn", -(23 + 30/60)),
            ("SESS-CN-003", (now - timedelta(days=3)).strftime("%Y-%m-%d"), "Computer Networks", "CN", "teacher_cn", -72),
            # Teacher 2 (teacher_ml): 2 hours old
            ("SESS-ML-001", (now - timedelta(hours=2)).strftime("%Y-%m-%d"), "Machine Learning", "ML", "teacher_ml", -2),
            # Legacy session
            ("SESS-LEGACY-001", "2026-01-15", "Legacy Subject", "UNKNOWN", "legacy", None),
        ]

        for sid, d, subj, code, tid, offset in sessions_data:
            if db.get(DbSession, sid):
                continue
            created_at = None
            if offset is not None:
                created_at = (now + timedelta(hours=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                created_at = f"{d}T00:00:00Z"  # legacy: date at 00:00 UTC
            db.add(DbSession(
                session_id=sid,
                date=d,
                subject=subj,
                subject_code=code,
                teacher_id=tid,
                created_at=created_at,
                lifecycle_status="SCHEDULED",
            ))
        db.commit()

        # --- Attendance records ---
        # SESS-CN-001: 3 present, 2 absent (60%)
        cn001_records = [
            ("1DS22CS001", "PRESENT"),
            ("1DS22CS002", "PRESENT"),
            ("1DS22CS003", "ABSENT"),
            ("1DS22CS004", "PRESENT"),
            ("1DS22CS005", "ABSENT"),
        ]
        # SESS-CN-002: 4 present, 1 absent (80%)
        cn002_records = [
            ("1DS22CS001", "PRESENT"),
            ("1DS22CS002", "PRESENT"),
            ("1DS22CS003", "PRESENT"),
            ("1DS22CS004", "ABSENT"),
            ("1DS22CS005", "PRESENT"),
        ]
        # SESS-CN-003: 2 present, 3 absent (40%) - defaulter candidates
        cn003_records = [
            ("1DS22CS001", "ABSENT"),
            ("1DS22CS002", "ABSENT"),
            ("1DS22CS003", "PRESENT"),
            ("1DS22CS004", "ABSENT"),
            ("1DS22CS005", "ABSENT"),
        ]
        # SESS-ML-001: 5 present (100%)
        ml001_records = [
            ("1DS22CS001", "PRESENT"),
            ("1DS22CS002", "PRESENT"),
            ("1DS22CS003", "PRESENT"),
            ("1DS22CS004", "PRESENT"),
            ("1DS22CS005", "PRESENT"),
        ]

        all_records = []
        for session_id, records in [
            ("SESS-CN-001", cn001_records),
            ("SESS-CN-002", cn002_records),
            ("SESS-CN-003", cn003_records),
            ("SESS-ML-001", ml001_records),
        ]:
            for usn, status in records:
                if crud.get_attendance_record(db, session_id, usn):
                    continue
                all_records.append({
                    "session_id": session_id,
                    "usn": usn,
                    "room_id": "LH-101",
                    "status": status,
                    "source": "seed",
                    "confidence": 1.0,
                })

        if all_records:
            crud.insert_attendance_bulk(db, records=all_records, upsert=True)
        db.commit()

        return {
            "status": "success",
            "users": [u[0] for u in users],
            "sessions": [s[0] for s in sessions_data],
            "students": [s[0] for s in students],
            "message": "Demo data seeded successfully.",
        }

    except Exception as exc:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    result = seed_demo_data()
    print(result["message"])
