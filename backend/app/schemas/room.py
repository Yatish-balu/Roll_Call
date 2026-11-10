"""Room Pydantic v2 schemas for API validation and serialization."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RoomBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Room display name or description")

    @field_validator("name")
    @classmethod
    def strip_and_validate_non_empty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Room name cannot be empty or whitespace only")
        return cleaned


class RoomCreate(RoomBase):
    room_id: str = Field(..., min_length=1, max_length=50, description="Unique Room identifier (e.g. LH-101)")

    @field_validator("room_id")
    @classmethod
    def validate_room_id(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Room ID cannot be empty or whitespace only")
        return cleaned


class RoomUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Updated room name")

    @field_validator("name")
    @classmethod
    def strip_optional(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Room name cannot be empty or whitespace only")
            return cleaned
        return v


class RoomResponse(RoomBase):
    room_id: str = Field(..., description="Unique Room identifier")

    model_config = ConfigDict(from_attributes=True)


class RoomPageResponse(BaseModel):
    items: List[RoomResponse] = Field(default_factory=list, description="Paginated room records")
    total: int = Field(ge=0, description="Total matching room records")
    limit: int = Field(ge=1, le=200, description="Maximum records returned per page")
    offset: int = Field(ge=0, description="Starting offset index")

    model_config = ConfigDict(from_attributes=True)


class RoomBulkCreate(BaseModel):
    rooms: List[RoomCreate] = Field(..., min_length=1, description="List of rooms to create")

