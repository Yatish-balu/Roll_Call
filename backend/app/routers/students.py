"""FastAPI router for Student master data endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Role, get_current_user, require_roles
from app.auth.session_scope import resolve_data_scope
from app.db import crud
from app.db.models import Attendance, Session as DbSession
from app.dependencies import get_db
from app.health import health_band
from app.security.context import get_request_id
from app.security.decoys import probe_decoy
from app.security.detection import detector
from app.schemas.auth import AuthenticatedUser
from app.schemas.student import (
    StudentBulkCreate,
    StudentCreate,
    StudentPageResponse,
    StudentResponse,
)

logger = logging.getLogger("rollcall.routers.students")

router = APIRouter(prefix="/students", tags=["Students"])


def _client_ip(request: Optional[Request]) -> Optional[str]:
    """Best-effort client address (never a credential)."""
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client and request.client.host:
        return request.client.host
    return None


@router.get(
    "",
    response_model=StudentPageResponse,
    summary="List students visible to the caller",
    description=(
        "Retrieve paginated student master records ordered by USN, with optional branch "
        "filtering and search. The list is restricted to the caller's authorization scope: "
        "ADMIN sees the institution, every other role only the students supported by their "
        "visible sessions or their mapped subject departments. The scope is applied before "
        "counting and pagination, so totals and pages cannot reveal other students."
    ),
)
def list_students(
    branch: Optional[str] = Query(None, description="Optional branch code filter (e.g. CSE, ECE)"),
    semester: Optional[int] = Query(
        None,
        ge=1,
        le=8,
        description="Optional semester number filter (1 - 8)",
    ),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip before returning"),
    search: Optional[str] = Query(None, description="Search term matching USN, student name, or branch"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    scope = resolve_data_scope(db, current_user)

    # Branch and semester filters are applied by the database query, so the
    # returned page, the reported total and the exported PDF always describe
    # the same population.
    from sqlalchemy import func, or_, select

    from app.db.models import Section, Semester, Student

    condition = scope.student_condition()
    stmt = select(Student)
    count_stmt = select(func.count(Student.usn))
    if condition is not None:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    if semester is not None:
        semester_ids = select(Semester.semester_id).where(
            Semester.semester_number == semester
        )
        stmt = stmt.where(Student.semester_id.in_(semester_ids))
        count_stmt = count_stmt.where(Student.semester_id.in_(semester_ids))

    if branch and branch.strip() and branch.strip().upper() != "ALL":
        clean_branch = branch.strip().upper()
        stmt = stmt.where(func.upper(Student.branch) == clean_branch)
        count_stmt = count_stmt.where(func.upper(Student.branch) == clean_branch)

    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        search_clause = or_(
            func.lower(Student.usn).like(term),
            func.lower(Student.name).like(term),
            func.lower(Student.branch).like(term),
        )
        stmt = stmt.where(search_clause)
        count_stmt = count_stmt.where(search_clause)

    total = db.execute(count_stmt).scalar() or 0
    rows = (
        db.execute(stmt.order_by(Student.branch, Student.usn).limit(limit).offset(offset))
        .scalars()
        .all()
    )

    semester_numbers = {
        row.semester_id: row.semester_number
        for row in db.execute(select(Semester)).scalars().all()
    }
    section_labels = {
        row.section_id: row.section_label for row in db.execute(select(Section)).scalars().all()
    }

    return {
        "items": [
            {
                "usn": row.usn,
                "name": row.name,
                "branch": row.branch,
                "dept_id": row.dept_id,
                "semester_id": row.semester_id,
                "semester": semester_numbers.get(row.semester_id),
                "section_id": row.section_id,
                "section": section_labels.get(row.section_id),
                "batch_id": row.batch_id,
                "roll_no": row.roll_no,
            }
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/{usn}",
    response_model=StudentResponse,
    summary="Get student by USN",
    description=(
        "Retrieve a single student record by their Unique Student Number. Students outside "
        "the caller's authorization scope are reported as not found, so the endpoint never "
        "confirms the existence of a student the caller may not see."
    ),
    responses={
        404: {"description": "Student not found or not visible to the caller"},
    },
)
def get_student_by_usn(
    usn: str,
    request: Request = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    clean_usn = usn.strip().upper()
    scope = resolve_data_scope(db, current_user)

    # Honeypot probe: a decoy identifier produces a security event and the
    # same "not found" answer as a genuinely unknown student.
    if probe_decoy(
        db,
        clean_usn,
        actor_id=current_user.user_id,
        ip_address=_client_ip(request),
        request_id=get_request_id(),
        path="/students",
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with USN '{clean_usn}' not found.",
        )

    # Student-data enumeration detection (never blocks a single lookup).
    detector.record_student_lookup(
        actor_id=current_user.user_id,
        usn=clean_usn,
        ip_address=_client_ip(request),
        request_id=get_request_id(),
    )

    if not scope.is_student_visible(db, clean_usn):
        # Same response as an unknown student: no existence disclosure.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with USN '{clean_usn}' not found.",
        )
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


# ==============================================================================
# N12: Student lookup and ledger
# ==============================================================================

@router.get(
    "/lookup",
    summary="Student lookup (partial USN or name)",
    description=(
        "Search students by partial USN or name (max 20 results). "
        "Teacher sees only students in their assigned subjects; admin sees all."
    ),
)
def lookup_students(
    q: str = Query(..., min_length=1, description="Search term (USN or name)"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from sqlalchemy import func, or_, select

    from app.db.models import Student

    clean_q = q.strip()
    if not clean_q:
        return {"results": [], "total": 0}

    scope = resolve_data_scope(db, current_user)
    condition = scope.student_condition()
    term = f"%{clean_q.lower()}%"

    stmt = select(Student.usn, Student.name, Student.branch).where(
        or_(
            func.lower(Student.usn).like(term),
            func.lower(Student.name).like(term),
        )
    )
    if condition is not None:
        stmt = stmt.where(condition)

    rows = db.execute(stmt.limit(20)).all()

    return {
        "results": [
            {"usn": row.usn, "name": row.name, "branch": row.branch}
            for row in rows
        ],
        "total": len(rows),
    }


@router.get(
    "/{usn}/ledger",
    summary="Student attendance ledger",
    description=(
        "Return a student's attendance history in date order with date, subject, "
        "room, status, source, plus percent and colour band. Teacher sees only "
        "their assigned subjects; admin sees all."
    ),
)
def get_student_ledger(
    usn: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    clean_usn = usn.strip().upper()

    scope = resolve_data_scope(db, current_user)

    # Visibility check (same as get_student_by_usn: no existence disclosure)
    if not scope.is_student_visible(db, clean_usn):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with USN '{clean_usn}' not found.",
        )

    student = crud.get_student(db, usn=clean_usn)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with USN '{clean_usn}' not found.",
        )

    # Query attendance records joined with sessions, scoped to caller
    q = (
        select(
            Attendance.session_id,
            Attendance.usn,
            Attendance.status,
            Attendance.source,
            Attendance.confidence,
            DbSession.date,
            DbSession.subject,
            DbSession.subject_code,
            DbSession.teacher_id,
        )
        .join(DbSession, Attendance.session_id == DbSession.session_id)
        .where(Attendance.usn == clean_usn)
        .order_by(DbSession.date.asc(), DbSession.session_id.asc())
    )

    condition = scope.session_condition()
    if condition is not None:
        q = q.where(condition)

    rows = db.execute(q).all()

    total = len(rows)
    present = sum(1 for r in rows if r.status == "PRESENT")
    absent = sum(1 for r in rows if r.status == "ABSENT")
    pct = round((present / total) * 100, 1) if total > 0 else 0.0

    ledger = [
        {
            "session_id": r.session_id,
            "date": r.date,
            "subject": r.subject,
            "subject_code": r.subject_code,
            "room_id": r.room_id if hasattr(r, "room_id") else None,
            "status": r.status,
            "source": r.source,
            "confidence": r.confidence,
        }
        for r in rows
    ]

    return {
        "usn": clean_usn,
        "name": student.name,
        "branch": student.branch,
        "total_classes": total,
        "present": present,
        "absent": absent,
        "attendance_percentage": f"{pct}%",
        "percent": pct,
        "band": health_band(pct),
        "ledger": ledger,
    }


__all__ = ["router"]

