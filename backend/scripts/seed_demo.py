"""Comprehensive demo seed script for RollCall AI (Prompt N16).

Provisions realistic test accounts, subject mappings, lock state demonstration sessions,
and planted defaulter/health-band student records. Safe to re-run idempotently.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
import uuid

import bcrypt

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv

_REPO_ROOT = _BACKEND_DIR.parent
_ENV_FILE = _REPO_ROOT / ".env"
if _ENV_FILE.exists():
    load_dotenv(dotenv_path=_ENV_FILE)
else:
    load_dotenv()

from app.db.connection import get_sync_session_factory
from app.db.models import Attendance, Session as DbSession, Student, Room, TeacherSubject, User

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("rollcall.seed_demo")


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def seed_demo_data(db_session=None):
    close_db = False
    if db_session is None:
        factory = get_sync_session_factory()
        db = factory()
        close_db = True
    else:
        db = db_session

    try:
        now = datetime.now(timezone.utc)
        ts_now = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        # 1. Users
        users_data = [
            ("admin_root", "admin@rollcall.internal", "ADMIN", "AdminSecurePass_2026!"),
            ("faculty_ds", "faculty.ds@rollcall.internal", "FACULTY", "FacultyPass_DIST_2026!"),
            ("faculty_ml", "faculty.ml@rollcall.internal", "FACULTY", "FacultyPass_ML_2026!"),
            ("faculty_cn", "faculty.cn@rollcall.internal", "FACULTY", "FacultyPass_CN_2026!"),
            ("legacy", "legacy@rollcall.internal", "ADMIN", None),
        ]

        for uid, email, role, pw in users_data:
            existing = db.get(User, uid)
            hashed = hash_pw(pw) if pw else None
            is_act = 0 if uid == "legacy" else 1
            if existing:
                existing.email = email
                existing.role = role
                if hashed:
                    existing.hashed_password = hashed
                existing.is_active = is_act
            else:
                db.add(User(user_id=uid, email=email, role=role, hashed_password=hashed, is_active=is_act, created_at=ts_now))

        db.flush()

        # 2. Teacher Subject Mappings
        mappings = [
            ("faculty_ds", "DIST-SYS"),
            ("faculty_ds", "DBMS"),
            ("faculty_ml", "ML-101"),
            ("faculty_ml", "PYTHON"),
            ("faculty_cn", "CN-201"),
        ]
        for uid, code in mappings:
            exists = db.query(TeacherSubject).filter_by(user_id=uid, subject_code=code).first()
            if not exists:
                db.add(TeacherSubject(user_id=uid, subject_code=code))

        # 3. Rooms
        for rid, rname in [("LH-101", "Lecture Hall 101"), ("LH-102", "Lecture Hall 102"), ("LAB-1", "Systems Lab 1")]:
            r_ex = db.get(Room, rid)
            if not r_ex:
                db.add(Room(room_id=rid, name=rname))

        # 4. Students (with planted defaulter/health states)
        students_data = [
            ("1MS21CS001", "Alice Smith", "CSE"),      # Will have 60.0% (< 75 defaulter)
            ("1MS21CS002", "Bob Jones", "CSE"),        # Will have 75.0% (exact 75.0 not defaulter)
            ("1MS21CS003", "Charlie Brown", "CSE"),    # Will have 90.0% (> 85 green band)
            ("1MS21CS004", "Diana Prince", "CSE"),     # Will have 80.0% (yellow band)
            ("1MS21CS005", "Evan Wright", "CSE"),      # Will have 50.0% (red band, defaulter)
            ("1MS21EC001", "Fiona Gallagher", "ECE"),  # Will have 70.0% (yellow band boundary)
            ("1MS21EC002", "George Clark", "ECE"),     # Will have 85.1% (green band boundary)
            ("1MS21IS001", "Hannah Abbott", "ISE"),    # Will have 100.0%
        ]
        for usn, sname, branch in students_data:
            s_ex = db.get(Student, usn)
            if s_ex:
                s_ex.name = sname
                s_ex.branch = branch
            else:
                db.add(Student(usn=usn, name=sname, branch=branch))

        db.flush()

        # 5. Sessions representing exact demo lock states:
        # Session A: Teacher 1, 2 hours old (editable)
        ts_2h = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        date_today = now.strftime("%Y-%m-%d")

        # Session B: Teacher 1, 23 hours 30 min old (editable)
        ts_23h30 = (now - timedelta(hours=23, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        date_yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

        # Session C: Teacher 1, 3 days old (locked for teacher, editable for admin with reason)
        ts_3d = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        date_3d = (now - timedelta(days=3)).strftime("%Y-%m-%d")

        # Session D: Teacher 2, 2 hours old (editable for Teacher 2, forbidden for Teacher 1)
        ts_t2 = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Session E: Legacy session, 30 days old (teacher_id='legacy')
        ts_30d = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        date_30d = (now - timedelta(days=30)).strftime("%Y-%m-%d")

        sessions_spec = [
            ("SESS-DEMO-2H", date_today, "Distributed Systems", "faculty_ds", "DIST-SYS", ts_2h),
            ("SESS-DEMO-23H", date_yesterday, "Database Systems", "faculty_ds", "DBMS", ts_23h30),
            ("SESS-DEMO-3D", date_3d, "Distributed Systems", "faculty_ds", "DIST-SYS", ts_3d),
            ("SESS-DEMO-T2", date_today, "Machine Learning", "faculty_ml", "ML-101", ts_t2),
            ("SESS-DEMO-LEGACY", date_30d, "Computer Networks", "legacy", "CN-201", ts_30d),
        ]

        for sid, sdate, subj, tid, code, created in sessions_spec:
            s_obj = db.get(DbSession, sid)
            if s_obj:
                s_obj.date = sdate
                s_obj.subject = subj
                s_obj.teacher_id = tid
                s_obj.subject_code = code
                s_obj.created_at = created
            else:
                db.add(DbSession(session_id=sid, date=sdate, subject=subj, teacher_id=tid, subject_code=code, created_at=created))

        db.flush()

        # 6. Seed attendance marks for the demo sessions
        # For SESS-DEMO-2H (10 students):
        # Alice: PRESENT, Bob: PRESENT, Charlie: PRESENT, Diana: PRESENT, Evan: ABSENT, Fiona: PRESENT, George: PRESENT, Hannah: PRESENT
        att_specs = [
            ("SESS-DEMO-2H", "1MS21CS001", "PRESENT"),
            ("SESS-DEMO-2H", "1MS21CS002", "PRESENT"),
            ("SESS-DEMO-2H", "1MS21CS003", "PRESENT"),
            ("SESS-DEMO-2H", "1MS21CS004", "PRESENT"),
            ("SESS-DEMO-2H", "1MS21CS005", "ABSENT"),
            ("SESS-DEMO-2H", "1MS21EC001", "PRESENT"),
            ("SESS-DEMO-2H", "1MS21EC002", "PRESENT"),
            ("SESS-DEMO-2H", "1MS21IS001", "PRESENT"),

            ("SESS-DEMO-3D", "1MS21CS001", "ABSENT"),
            ("SESS-DEMO-3D", "1MS21CS002", "PRESENT"),
            ("SESS-DEMO-3D", "1MS21CS003", "PRESENT"),
            ("SESS-DEMO-3D", "1MS21CS005", "ABSENT"),

            ("SESS-DEMO-T2", "1MS21CS001", "ABSENT"),
            ("SESS-DEMO-T2", "1MS21CS002", "PRESENT"),

            ("SESS-DEMO-LEGACY", "1MS21CS001", "PRESENT"),
            ("SESS-DEMO-LEGACY", "1MS21CS002", "PRESENT"),
        ]

        for sid, usn, att_status in att_specs:
            existing_att = db.query(Attendance).filter_by(session_id=sid, usn=usn).first()
            if existing_att:
                existing_att.status = att_status
            else:
                db.add(Attendance(
                    attendance_id=f"demo_{uuid.uuid4().hex[:12]}",
                    session_id=sid,
                    usn=usn,
                    room_id="LH-101",
                    status=att_status,
                    source="SEED",
                    confidence=1.0,
                    recorded_at=ts_now,
                ))

        db.commit()
        logger.info("Demo data seed completed successfully!")
    finally:
        if close_db:
            db.close()


if __name__ == "__main__":
    seed_demo_data()
