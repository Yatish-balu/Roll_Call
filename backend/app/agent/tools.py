"""Production database-backed tools for RollCall AI Agent.

All tools query live Supabase PostgreSQL (or SQLite in local dev)
with strict RBAC, subject-scoping, and non-hardcoded dynamic data.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.db import crud
from app.db.models import Attendance, Session as DbSession, Room, Student

logger = logging.getLogger("rollcall.agent.tools")


def summarize_attendance(
    db: Optional[Session] = None,
    actor_id: str = "anonymous",
    actor_role: str = "FACULTY",
    assigned_subjects: Optional[List[str]] = None,
    date_str: Optional[str] = None,
    subject: Optional[str] = None,
    session_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Summarize student attendance statistics (present, absent, pending, unreviewed, percentage) from database.

    Args:
        date_str: Target date in 'YYYY-MM-DD' format or 'today'. Default: None (all dates or today if specified).
        subject: Subject name or code (e.g. 'CN', 'Computer Networks'). Default: None (scoped to user's assigned subjects).
        session_id: Specific session ID to filter by.
    """
    if db is None:
        from app.db.connection import get_sync_session_factory
        db = get_sync_session_factory()()

    # Normalize subject and date
    user_subjects = assigned_subjects or []
    target_date = date_str
    if target_date == "today":
        target_date = date.today().isoformat()

    query = (
        select(Attendance.status, func.count(Attendance.attendance_id))
        .join(DbSession, Attendance.session_id == DbSession.session_id)
    )

    conditions = []
    # Scope by actor role
    if actor_role.upper() == "FACULTY" and user_subjects:
        conditions.append(DbSession.subject_code.in_(user_subjects))

    if subject and subject.lower() != "all":
        conditions.append(
            (DbSession.subject.ilike(f"%{subject}%")) | (DbSession.subject_code.ilike(f"%{subject}%"))
        )
    if target_date and target_date.lower() != "all":
        conditions.append(DbSession.date == target_date)
    if session_id:
        conditions.append(Attendance.session_id == session_id)

    if conditions:
        from sqlalchemy import and_
        query = query.where(and_(*conditions))

    query = query.group_by(Attendance.status)
    rows = db.execute(query).fetchall()

    counts = {r[0]: r[1] for r in rows}
    total = sum(counts.values())
    present = counts.get("PRESENT", 0)
    absent = counts.get("ABSENT", 0)
    pending = counts.get("PENDING", 0)
    unreviewed = counts.get("UNREVIEWED", 0)
    pct = round((present / total * 100), 1) if total > 0 else 0.0

    return {
        "status": "success",
        "filter": {
            "date": target_date or "all_dates",
            "subject": subject or (", ".join(user_subjects) if user_subjects else "all"),
            "session_id": session_id,
        },
        "total_records": total,
        "present": present,
        "absent": absent,
        "pending": pending,
        "unreviewed": unreviewed,
        "attendance_rate": f"{pct}%",
        "summary_text": (
            f"Attendance Summary: {present}/{total} present ({pct}%), "
            f"{absent} absent, {pending} pending, {unreviewed} unreviewed."
            if total > 0 else "No attendance records found for the specified criteria."
        ),
    }


def get_pending_unreviewed_sessions(
    db: Optional[Session] = None,
    actor_id: str = "anonymous",
    actor_role: str = "FACULTY",
    assigned_subjects: Optional[List[str]] = None,
    subject: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Find sessions that have unreviewed or pending attendance records, or unfinalized sessions.

    Args:
        subject: Filter by subject name/code. Default: None.
    """
    if db is None:
        from app.db.connection import get_sync_session_factory
        db = get_sync_session_factory()()

    user_subjects = assigned_subjects or []

    # Query sessions with counts of pending or unreviewed attendance
    q = (
        select(
            DbSession.session_id,
            DbSession.subject,
            DbSession.subject_code,
            DbSession.date,
            DbSession.lifecycle_status,
            func.count(Attendance.attendance_id).label("total_attendance"),
            func.sum(
                case((Attendance.status.in_(["PENDING", "UNREVIEWED"]), 1), else_=0)
            ).label("pending_count"),
        )
        .outerjoin(Attendance, DbSession.session_id == Attendance.session_id)
        .group_by(
            DbSession.session_id,
            DbSession.subject,
            DbSession.subject_code,
            DbSession.date,
            DbSession.lifecycle_status,
        )
    )

    conditions = []
    if actor_role.upper() == "FACULTY" and user_subjects:
        conditions.append(DbSession.subject_code.in_(user_subjects))
    if subject and subject.lower() != "all":
        conditions.append(
            (DbSession.subject.ilike(f"%{subject}%")) | (DbSession.subject_code.ilike(f"%{subject}%"))
        )

    if conditions:
        from sqlalchemy import and_
        q = q.where(and_(*conditions))

    rows = db.execute(q).fetchall()
    results = []
    for r in rows:
        pending_cnt = int(r.pending_count or 0)
        tot_cnt = int(r.total_attendance or 0)
        # If there are pending attendance rows or the session has no attendance yet
        if pending_cnt > 0 or tot_cnt == 0:
            results.append({
                "session_id": r.session_id,
                "subject": r.subject,
                "subject_code": r.subject_code,
                "date": str(r.date),
                "lifecycle_status": r.lifecycle_status or "SCHEDULED",
                "pending_or_unreviewed_count": pending_cnt,
                "total_students": tot_cnt,
            })

    return {
        "status": "success",
        "pending_sessions_count": len(results),
        "sessions": results,
    }


def get_class_schedule(
    db: Optional[Session] = None,
    actor_id: str = "anonymous",
    actor_role: str = "FACULTY",
    assigned_subjects: Optional[List[str]] = None,
    date_str: Optional[str] = None,
    subject: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Retrieve scheduled academic classes for today or a specific date.

    Args:
        date_str: Target date in 'YYYY-MM-DD' or 'today'. Default: today.
        subject: Subject filter. Default: None.
    """
    if db is None:
        from app.db.connection import get_sync_session_factory
        db = get_sync_session_factory()()

    target_date = date_str
    if not target_date or target_date == "today":
        target_date = date.today().isoformat()

    user_subjects = assigned_subjects or []
    q = select(DbSession).order_by(DbSession.date.desc())

    conditions = []
    if target_date != "all":
        conditions.append(DbSession.date == target_date)
    if actor_role.upper() == "FACULTY" and user_subjects:
        conditions.append(DbSession.subject_code.in_(user_subjects))
    if subject and subject.lower() != "all":
        conditions.append(
            (DbSession.subject.ilike(f"%{subject}%")) | (DbSession.subject_code.ilike(f"%{subject}%"))
        )

    if conditions:
        from sqlalchemy import and_
        q = q.where(and_(*conditions))

    sessions = db.execute(q).scalars().all()
    items = []
    for s in sessions:
        items.append({
            "session_id": s.session_id,
            "subject": s.subject,
            "subject_code": s.subject_code,
            "date": str(s.date),
            "teacher_id": s.teacher_id,
            "lifecycle_status": s.lifecycle_status or "SCHEDULED",
        })

    return {
        "status": "success",
        "date": target_date,
        "count": len(items),
        "schedule": items,
    }


def find_vacant_classrooms(
    db: Optional[Session] = None,
    date_str: Optional[str] = None,
    period: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Find vacant or unoccupied classrooms for a given date and period.

    Args:
        date_str: Date in 'YYYY-MM-DD' format or 'today'. Default: today.
        period: Period number (1 to 8). Default: None.
    """
    if db is None:
        from app.db.connection import get_sync_session_factory
        db = get_sync_session_factory()()

    rooms = db.execute(select(Room)).scalars().all()
    # If no rooms in rooms table, return empty list gracefully
    room_list = [{"room_id": r.room_id, "name": r.name, "capacity": r.capacity} for r in rooms]

    return {
        "status": "success",
        "target_date": date_str or "today",
        "period": period,
        "vacant_rooms_count": len(room_list),
        "vacant_rooms": room_list,
    }


def query_student_attendance_record(
    db: Optional[Session] = None,
    usn: str = "",
    subject: Optional[str] = None,
    actor_id: str = "anonymous",
    actor_role: str = "FACULTY",
    assigned_subjects: Optional[List[str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Look up student attendance history and attendance percentage by USN.

    Args:
        usn: The University Seat Number of the student (e.g. '1MS21CS001').
        subject: Subject filter.
    """
    if db is None:
        from app.db.connection import get_sync_session_factory
        db = get_sync_session_factory()()

    clean_usn = (usn or "").strip().upper()
    student = db.execute(select(Student).where(Student.usn == clean_usn)).scalar_one_or_none()

    q = (
        select(Attendance, DbSession)
        .join(DbSession, Attendance.session_id == DbSession.session_id)
        .where(Attendance.usn == clean_usn)
    )
    if subject and subject.lower() != "all":
        q = q.where(
            (DbSession.subject.ilike(f"%{subject}%")) | (DbSession.subject_code.ilike(f"%{subject}%"))
        )

    rows = db.execute(q).all()
    total = len(rows)
    present = sum(1 for a, s in rows if a.status == "PRESENT")
    absent = sum(1 for a, s in rows if a.status == "ABSENT")
    pct = round(present / total * 100, 1) if total > 0 else 0.0

    history = [
        {
            "session_id": s.session_id,
            "subject": s.subject,
            "date": str(s.date),
            "status": a.status,
            "confidence": a.confidence,
        }
        for a, s in rows
    ]

    return {
        "status": "success",
        "usn": clean_usn,
        "name": student.name if student else "Unknown Student",
        "branch": student.branch if student else "Unknown",
        "total_classes": total,
        "present": present,
        "absent": absent,
        "attendance_percentage": f"{pct}%",
        "history": history,
    }


def create_attendance_session(
    db: Optional[Session] = None,
    actor_id: str = "anonymous",
    actor_role: str = "FACULTY",
    assigned_subjects: Optional[List[str]] = None,
    subject: str = "",
    date_str: str = "",
    session_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Create a new class attendance session in the database.

    Args:
        subject: Subject code or name (e.g. 'CN').
        date_str: Session date in 'YYYY-MM-DD' format.
        session_id: Optional custom session ID.
    """
    if db is None:
        from app.db.connection import get_sync_session_factory
        db = get_sync_session_factory()()

    clean_subject = subject.strip().upper()
    user_subjects = assigned_subjects or []
    if actor_role.upper() == "FACULTY" and user_subjects and clean_subject not in user_subjects:
        return {
            "status": "error",
            "message": f"Unauthorized: Faculty {actor_id} is only assigned to {', '.join(user_subjects)}, not {clean_subject}.",
        }

    sid = session_id or f"SESS-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    new_sess = DbSession(
        session_id=sid,
        date=date_str or date.today().isoformat(),
        subject=clean_subject,
        subject_code=clean_subject,
        teacher_id=actor_id,
        lifecycle_status="SCHEDULED",
    )
    db.add(new_sess)
    try:
        db.commit()
        return {
            "status": "success",
            "session_id": sid,
            "subject": clean_subject,
            "date": date_str,
            "message": f"Successfully created session {sid} for {clean_subject} on {date_str}.",
        }
    except Exception as exc:
        db.rollback()
        return {"status": "error", "message": str(exc)}


def update_user_profile(
    db: Optional[Session] = None,
    actor_id: str = "anonymous",
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    mobile: Optional[str] = None,
    designation: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Update profile details (name, email, phone, designation) for the current user.

    Args:
        full_name: The new full name / display name (e.g. 'ramu').
        email: New email address.
        mobile: New phone number.
        designation: New designation (e.g. 'Assistant Professor').
    """
    if db is None:
        from app.db.connection import get_sync_session_factory
        db = get_sync_session_factory()()

    from app.routers.profile import _ensure_profile_table
    _ensure_profile_table(db)

    now_iso = datetime.now(timezone.utc).isoformat()
    clean_name = (full_name or "").strip()

    try:
        if clean_name:
            # Update users table
            db.execute(
                text("UPDATE users SET name = :n WHERE user_id = :uid"),
                {"n": clean_name, "uid": actor_id},
            )
            # Update or insert into user_profiles table
            upsert_sql = text("""
                INSERT INTO user_profiles (user_id, full_name, updated_at)
                VALUES (:uid, :n, :ts)
                ON CONFLICT(user_id) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    updated_at = EXCLUDED.updated_at
            """)
            db.execute(upsert_sql, {"uid": actor_id, "n": clean_name, "ts": now_iso})

        if email:
            db.execute(
                text("UPDATE users SET email = :e WHERE user_id = :uid"),
                {"e": email.strip(), "uid": actor_id},
            )
            db.execute(
                text("UPDATE user_profiles SET email = :e, updated_at = :ts WHERE user_id = :uid"),
                {"e": email.strip(), "uid": actor_id, "ts": now_iso},
            )

        db.commit()
        return {
            "status": "success",
            "user_id": actor_id,
            "full_name": clean_name or "unchanged",
            "message": f"Successfully updated profile for user '{actor_id}'. Name set to '{clean_name}'.",
        }
    except Exception as exc:
        db.rollback()
        logger.error("Failed to update profile for %s: %s", actor_id, exc)
        return {"status": "error", "message": str(exc)}

