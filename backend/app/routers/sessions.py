"""FastAPI router for Session master data endpoints."""

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
from app.schemas.session import (
    SessionBulkCreate,
    SessionCreate,
    SessionPageResponse,
    SessionResponse,
)

logger = logging.getLogger("rollcall.routers.sessions")

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.get(
    "",
    response_model=SessionPageResponse,
    summary="List all sessions",
    description="Retrieve paginated sessions, optionally filtered by date (YYYY-MM-DD) and search.",
)
def list_sessions(
    date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Filter sessions by date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip before returning"),
    search: Optional[str] = Query(None, description="Search term matching session_id or subject"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    items, total = crud.get_sessions_paginated(
        db, date=date, search=search, limit=limit, offset=offset
    )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Get session by ID",
    description="Retrieve a single session record by session_id.",
    responses={
        404: {"description": "Session not found"},
    },
)
def get_session_by_id(
    session_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    session = crud.get_session(db, session_id=session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{session_id.strip()}' not found.",
        )
    return session


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create session",
    description="Add a new session record.",
    responses={
        409: {"description": "Session already exists with this session_id"},
    },
)
def create_session(
    payload: SessionCreate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    existing = crud.get_session(db, session_id=payload.session_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session with ID '{payload.session_id}' already exists.",
        )

    try:
        created = crud.insert_session(
            db,
            session_id=payload.session_id,
            date=payload.date,
            subject=payload.subject,
        )
        db.commit()
        return created
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session with ID '{payload.session_id}' already exists.",
        )
    except Exception as exc:
        db.rollback()
        logger.error("Failed to create session %s: %s", payload.session_id, exc)
        raise


@router.post(
    "/bulk",
    status_code=status.HTTP_201_CREATED,
    summary="Bulk create sessions",
    description="Atomically insert multiple session records. If any duplicate or conflict occurs, the entire batch is rolled back.",
    responses={
        409: {"description": "Conflict or duplicate records detected in batch or database"},
    },
)
def bulk_create_sessions(
    payload: SessionBulkCreate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    raw_sessions = [s.model_dump() for s in payload.sessions]

    # Check for duplicate session_ids within the payload itself
    session_ids = [s["session_id"] for s in raw_sessions]
    if len(session_ids) != len(set(session_ids)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bulk insert payload contains duplicate session IDs.",
        )

    # Check for existing records in database to ensure clean 409 error
    for s in raw_sessions:
        if crud.get_session(db, session_id=s["session_id"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Session with ID '{s['session_id']}' already exists.",
            )

    try:
        inserted_count = crud.insert_sessions_bulk(db, sessions=raw_sessions)
        db.commit()
        return {
            "inserted_count": inserted_count,
            "message": f"Successfully created {inserted_count} sessions.",
        }
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bulk insert failed due to duplicate or conflicting records.",
        )
    except Exception as exc:
        db.rollback()
        logger.error("Error during bulk session creation: %s", exc)
        raise

