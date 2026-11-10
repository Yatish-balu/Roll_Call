"""FastAPI router for Student master data endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Role, get_current_user, require_roles
from app.db import crud
from app.dependencies import get_db
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
