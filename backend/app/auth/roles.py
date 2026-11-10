"""Role definitions and authorization hierarchy for RollCall AI."""

from __future__ import annotations

from typing import Set
from app.schemas.auth import Role

# Hierarchy definition:
# ADMIN inherits FACULTY and VIEWER capabilities.
# FACULTY inherits VIEWER capabilities.
# VIEWER has read-only capabilities.
ROLE_HIERARCHY: dict[Role, Set[Role]] = {
    Role.ADMIN: {Role.ADMIN, Role.FACULTY, Role.VIEWER},
    Role.FACULTY: {Role.FACULTY, Role.VIEWER},
    Role.VIEWER: {Role.VIEWER},
}


def normalize_role(raw_role: str | None) -> Role:
    """
    Normalize raw string from token claims to a valid Role enum.
    Defaults to Role.VIEWER if missing, unrecognized, or Supabase 'authenticated'.
    """
    if not raw_role:
        return Role.VIEWER

    clean = raw_role.strip().upper()
    try:
        return Role(clean)
    except ValueError:
        # Supabase default role is often 'authenticated'
        return Role.VIEWER


def role_satisfies(user_role: Role, required_role: Role) -> bool:
    """Check whether a user's role satisfies the required role per hierarchy."""
    allowed = ROLE_HIERARCHY.get(user_role, set())
    return required_role in allowed

