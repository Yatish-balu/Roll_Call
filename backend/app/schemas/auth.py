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


class LoginRequest(BaseModel):
    """User login credential payload."""
    user_id: str = Field(..., description="Unique user identifier", min_length=1, max_length=128)
    password: str = Field("", description="User plaintext password", max_length=1024)
    mfa_code: Optional[str] = Field(None, description="TOTP or single-use recovery code", max_length=64)
    admin_key: Optional[str] = Field(None, description="Administrative authorization key required for ADMIN accounts")
    remember_me: bool = Field(default=False, description="Whether to establish a persistent 7-day session")


class LoginResponse(BaseModel):
    """Successful authentication response payload."""
    token: str = Field(..., description="Signed cryptographic JWT access token")
    role: str = Field(..., description="Authoritative authorization role (ADMIN, FACULTY, VIEWER)")
    name: Optional[str] = Field(None, description="User full display name")
    subject_codes: List[str] = Field(default_factory=list, description="Subject codes assigned to the teacher")
    expires_at_utc: str = Field(..., description="Token expiration timestamp in UTC ISO 8601 format")


class UserMeResponse(BaseModel):
    """Current authenticated user profile payload."""
    user_id: str = Field(..., description="Unique user identifier")
    email: str = Field(..., description="User email address")
    role: str = Field(..., description="Current authoritative authorization role from database")
    is_active: int = Field(1, description="Account active status")
    subject_codes: List[str] = Field(default_factory=list, description="Assigned subject codes")


