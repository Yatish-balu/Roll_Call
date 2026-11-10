"""Authentication and authorization Pydantic v2 schemas."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class Role(str, Enum):
    """User authorization roles."""
    ADMIN = "ADMIN"
    FACULTY = "FACULTY"
    VIEWER = "VIEWER"


class TokenPayload(BaseModel):
    """Decoded JWT payload structure, compatible with Supabase Auth."""
    sub: str = Field(..., description="Subject identifier (Supabase user UUID)")
    email: Optional[str] = Field(None, description="User email address")
    role: Optional[str] = Field(None, description="Direct role claim if present")
    exp: Optional[int] = Field(None, description="Expiration unix timestamp")
    iat: Optional[int] = Field(None, description="Issued-at unix timestamp")
    iss: Optional[str] = Field(None, description="Issuer URL")
    aud: Optional[Union[str, List[str]]] = Field(None, description="Audience claim")
    app_metadata: Dict[str, Any] = Field(default_factory=dict, description="Application metadata containing role")
    user_metadata: Dict[str, Any] = Field(default_factory=dict, description="User profile metadata")

    model_config = ConfigDict(extra="allow")


class AuthenticatedUser(BaseModel):
    """Verified user identity extracted strictly from JWT claims."""
    user_id: str = Field(..., description="Unique user identifier from verified token sub")
    email: Optional[str] = Field(None, description="Verified user email")
    role: Role = Field(Role.VIEWER, description="Verified authorization role")
    claims: Dict[str, Any] = Field(default_factory=dict, description="Raw verified token claims")

    model_config = ConfigDict(from_attributes=True)

