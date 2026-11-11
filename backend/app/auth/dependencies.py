"""FastAPI dependencies for JWT authentication and role-based authorization."""

from __future__ import annotations

import logging
from typing import Callable, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt import AuthenticationError, decode_and_verify_token
from app.auth.roles import Role, normalize_role, role_satisfies
from app.db.connection import get_sync_session_factory
from app.db.models import AuthSession, User
from app.schemas.auth import AuthenticatedUser


logger = logging.getLogger("rollcall.auth.dependencies")

# Bearer token extractor without auto_error to control response format cleanly
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> AuthenticatedUser:
    """
    Extract, decode, and cryptographically verify the Bearer JWT token from the Authorization header.
    Authoritatively loads active status and role from database if user exists.
    Raises 401 Unauthorized on missing, invalid, expired tokens, or deactivated accounts.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication token. Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        user = decode_and_verify_token(token)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check authoritative database record if user exists locally.
    # This lookup is a security control (deactivation + role changes), so it must
    # fail CLOSED: if the database cannot be reached we reject the request rather
    # than trusting the role baked into the token.
    try:
        SessionLocal = get_sync_session_factory()
        with SessionLocal() as db:
            db_user = db.get(User, user.user_id)
            if db_user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User account no longer exists.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if not db_user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User account is deactivated.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            # Database role is authoritative
            user.role = normalize_role(db_user.role)
            session_id = user.claims.get("sid")
            if session_id:
                auth_session = db.get(AuthSession, str(session_id))
                if (
                    auth_session is None
                    or auth_session.user_id != user.user_id
                    or auth_session.revoked_at is not None
                ):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Authentication session is no longer active.",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Fail-closed: authoritative user lookup failed during token verification: %s", exc
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is temporarily unavailable. Please try again later.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user



def require_roles(*allowed_roles: Role) -> Callable[[AuthenticatedUser], AuthenticatedUser]:
    """
    Generate a dependency that verifies the authenticated user possesses one of the allowed roles
    or higher according to the authorization hierarchy (ADMIN > FACULTY > VIEWER).
    Raises 403 Forbidden if user lacks sufficient privileges.
    """
    def role_verifier(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        # Check if user's role satisfies at least one required role
        has_permission = any(role_satisfies(user.role, req_role) for req_role in allowed_roles)
        if not has_permission:
            roles_str = ", ".join(r.value for r in allowed_roles)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Insufficient privileges. Required role: {roles_str}. Your role: {user.role.value}.",
            )
        return user

    return role_verifier


# Common convenience role dependencies
require_admin = require_roles(Role.ADMIN)
require_faculty = require_roles(Role.FACULTY)
require_viewer = require_roles(Role.VIEWER)

