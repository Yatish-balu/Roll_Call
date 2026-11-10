"""FastAPI router for Student master data endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Role, get_current_user, require_roles
from app.db import crud
from app.db.models import Attendance, Session as DbSession, Student, TeacherSubject, Room
from app.dependencies import get_db
from app.health import health_band
from app.schemas.auth import AuthenticatedUser
from app.schemas.student import (
    StudentBulkCreate,
    StudentCreate,
    StudentPageResponse,
    StudentResponse,
)

logger = logging.getLogger("rollcall.routers.students")

router = APIRouter(prefix="/students", tags=["Students"])


@router.get(
    "",
    response_model=StudentPageResponse,
    summary="List all students",
    description="Retrieve paginated student master records ordered by USN, with optional branch filtering and search.",
)
def list_students(
    branch: Optional[str] = Query(None, description="Optional branch code filter (e.g. CSE, ECE)"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip before returning"),
    search: Optional[str] = Query(None, description="Search term matching USN, student name, or branch"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    items, total = crud.get_students_paginated(
        db, branch=branch, search=search, limit=limit, offset=offset
    )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/lookup",
    summary="Search students by partial USN or name (max 20)",
    description="Fast parameterised search across USN and student name. Protected against SQL injection.",
)
def lookup_students(
    q: str = Query(..., min_length=1, description="Partial search string for USN or name"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    clean_q = q.strip()
    if not clean_q:
        return []

    pattern = f"%{clean_q}%"
    stmt = (
        select(Student)
        .where(
            or_(
                Student.usn.ilike(pattern),
                Student.name.ilike(pattern),
            )
        )
        .order_by(Student.usn.asc())
        .limit(20)
    )
    students = db.execute(stmt).scalars().all()
    return [{"usn": s.usn, "name": s.name, "branch": s.branch} for s in students]


@router.get(
    "/{usn}/ledger",
    summary="Individual attendance ledger with time-ordered sessions and health band",
    description="Returns chronological session history. Teachers see only their assigned subjects; admins see all.",
)
def get_student_ledger(
    usn: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    clean_usn = usn.strip().upper()
    student = db.get(Student, clean_usn)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with USN '{clean_usn}' not found.",
        )

    # Determine caller's allowed subject codes
    role_str = str(current_user.role).upper()
    is_admin = role_str == "ADMIN" or role_str.endswith(".ADMIN")

    allowed_subjects: Optional[List[str]] = None
    if not is_admin:
        ts_stmt = select(TeacherSubject.subject_code).where(TeacherSubject.user_id == current_user.user_id)
        assigned = db.execute(ts_stmt).scalars().all()
        allowed_subjects = [s.upper() for s in assigned]

    # Query chronological attendance records
    stmt = (
        select(
            Attendance.session_id,
            DbSession.date,
            DbSession.subject,
            DbSession.subject_code,
            Attendance.room_id,
            Attendance.status,
            Attendance.source,
        )
        .join(DbSession, Attendance.session_id == DbSession.session_id)
        .where(Attendance.usn == clean_usn)
        .order_by(DbSession.date.asc(), DbSession.session_id.asc())
    )

    rows = db.execute(stmt).all()

    sessions = []
    attended_count = 0
    total_count = 0

    for sess_id, s_date, s_subject, s_code, room_id, status_val, source in rows:
        subject_identifier = (s_code or s_subject or "").upper()
        # Non-admin filter: only assigned subjects
        if not is_admin and allowed_subjects is not None:
            if not any(code in subject_identifier or subject_identifier in code for code in allowed_subjects):
                continue

        norm_status = str(status_val).upper()
        is_p = norm_status in ("PRESENT", "P")
        if is_p:
            attended_count += 1
        total_count += 1

        sessions.append({
            "session_id": sess_id,
            "date": s_date,
            "subject": s_subject,
            "room": room_id,
            "status": norm_status,
            "source": source or "CSV",
        })

    pct = round((attended_count / total_count) * 100.0, 1) if total_count > 0 else 0.0
    band = health_band(pct)

    return {
        "usn": student.usn,
        "name": student.name,
        "branch": student.branch,
        "percent": pct,
        "band": band,
        "total_sessions": total_count,
        "attended_sessions": attended_count,
        "sessions": sessions,
    }


@router.get(
    "/{usn}",
    response_model=StudentResponse,
    summary="Get student by USN",
    description="Retrieve a single student record by their Unique Student Number.",
    responses={
        404: {"description": "Student not found"},
    },
)
def get_student_by_usn(
    usn: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    clean_usn = usn.strip().upper()
    student = crud.get_student(db, usn=clean_usn)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with USN '{clean_usn}' not found.",
        )
    return student


@router.post(
    "",
    response_model=StudentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create student",
    description="Add a new student master record.",
    responses={
        409: {"description": "Student already exists with this USN"},
    },
)
def create_student(
    payload: StudentCreate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    existing = crud.get_student(db, usn=payload.usn)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Student with USN '{payload.usn}' already exists.",
        )

    try:
        created = crud.insert_student(
            db,
            usn=payload.usn,
            name=payload.name,
            branch=payload.branch,
        )
        db.commit()
        return created
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Student with USN '{payload.usn}' already exists.",
        )
    except Exception as exc:
        db.rollback()
        logger.error("Failed to create student %s: %s", payload.usn, exc)
        raise


@router.post(
    "/bulk",
    status_code=status.HTTP_201_CREATED,
    summary="Bulk create students",
    description="Atomically insert multiple student master records. If any duplicate or conflict occurs, the entire batch is rolled back.",
    responses={
        409: {"description": "Conflict or duplicate records detected in batch or database"},
    },
)
def bulk_create_students(
    payload: StudentBulkCreate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    raw_students = [s.model_dump() for s in payload.students]

    # Check for duplicate USNs within the payload itself
    usn_list = [s["usn"] for s in raw_students]
    if len(usn_list) != len(set(usn_list)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bulk insert payload contains duplicate student USNs.",
        )

    # Check for existing records in database to ensure clean 409 error
    for s in raw_students:
        if crud.get_student(db, usn=s["usn"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Student with USN '{s['usn']}' already exists.",
            )

    try:
        inserted_count = crud.insert_students_bulk(db, students=raw_students)
        db.commit()
        return {
            "inserted_count": inserted_count,
            "message": f"Successfully created {inserted_count} students.",
        }
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bulk insert failed due to duplicate or conflicting records.",
        )
    except Exception as exc:
        db.rollback()
        logger.error("Error during bulk student creation: %s", exc)
        raise
