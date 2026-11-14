"""FastAPI router for Room master data endpoints."""

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
from app.schemas.room import (
    RoomBulkCreate,
    RoomCreate,
    RoomPageResponse,
    RoomResponse,
)

logger = logging.getLogger("rollcall.routers.rooms")

router = APIRouter(prefix="/rooms", tags=["Rooms"])


@router.get(
    "",
    response_model=RoomPageResponse,
    summary="List all rooms",
    description="Retrieve paginated room master records ordered by room_id, with optional search.",
)
def list_rooms(
    limit: int = Query(50, ge=1, le=200, description="Maximum number of records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip before returning"),
    search: Optional[str] = Query(None, description="Search term matching room_id or room name"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    items, total = crud.get_rooms_paginated(db, search=search, limit=limit, offset=offset)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/{room_id}",
    response_model=RoomResponse,
    summary="Get room by ID",
    description="Retrieve a single room master record by room_id.",
    responses={
        404: {"description": "Room not found"},
    },
)
def get_room_by_id(
    room_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    clean_id = room_id.strip()
    if clean_id.upper() == "UNALLOCATED":
        crud.ensure_unallocated_room(db)
        room = crud.get_room(db, room_id="UNALLOCATED")
        if room:
            return room
        return {"room_id": "UNALLOCATED", "name": "Unallocated Classroom"}
    room = crud.get_room(db, room_id=clean_id)
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room with ID '{clean_id}' not found.",
        )
    return room


@router.post(
    "",
    response_model=RoomResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create room",
    description="Add a new room master record.",
    responses={
        409: {"description": "Room already exists with this room_id"},
    },
)
def create_room(
    payload: RoomCreate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    existing = crud.get_room(db, room_id=payload.room_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Room with ID '{payload.room_id}' already exists.",
        )

    try:
        created = crud.insert_room(
            db,
            room_id=payload.room_id,
            name=payload.name,
        )
        db.commit()
        return created
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Room with ID '{payload.room_id}' already exists.",
        )
    except Exception as exc:
        db.rollback()
        logger.error("Failed to create room %s: %s", payload.room_id, exc)
        raise


@router.post(
    "/bulk",
    status_code=status.HTTP_201_CREATED,
    summary="Bulk create rooms",
    description="Atomically insert multiple room master records. If any duplicate or conflict occurs, the entire batch is rolled back.",
    responses={
        409: {"description": "Conflict or duplicate records detected in batch or database"},
    },
)
def bulk_create_rooms(
    payload: RoomBulkCreate,
    current_user: AuthenticatedUser = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    raw_rooms = [r.model_dump() for r in payload.rooms]

    # Check for duplicate room_ids within the payload itself
    room_ids = [r["room_id"] for r in raw_rooms]
    if len(room_ids) != len(set(room_ids)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bulk insert payload contains duplicate room IDs.",
        )

    # Check for existing records in database to ensure clean 409 error
    for r in raw_rooms:
        if crud.get_room(db, room_id=r["room_id"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Room with ID '{r['room_id']}' already exists.",
            )

    try:
        inserted_count = crud.insert_rooms_bulk(db, rooms=raw_rooms)
        db.commit()
        return {
            "inserted_count": inserted_count,
            "message": f"Successfully created {inserted_count} rooms.",
        }
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bulk insert failed due to duplicate or conflicting records.",
        )
    except Exception as exc:
        db.rollback()
        logger.error("Error during bulk room creation: %s", exc)
        raise

