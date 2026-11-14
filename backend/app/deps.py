"""Convenience dependencies aligned with the roadmap naming (N3).

Re-exports the authoritative authentication/role dependencies from
``app.auth`` under the names used by the playbook:

* ``require_login`` -> ``get_current_user`` (401 when missing/invalid token)
* ``require_role('admin')`` -> ``require_roles(Role.ADMIN)`` (403 when insufficient)

Route handlers import from here so the roadmap's file references stay valid
without duplicating auth logic.
"""

from __future__ import annotations

from typing import Callable

from fastapi import Depends
from app.auth.dependencies import get_current_user, require_roles
from app.auth.roles import Role
from app.schemas.auth import AuthenticatedUser

#: Dependency that requires a valid authenticated user (acts as require_login).
require_login = get_current_user


def require_role(role: str | Role) -> Callable[[AuthenticatedUser], AuthenticatedUser]:
    """Return a dependency that requires the given role or higher in the hierarchy."""
    if isinstance(role, str):
        try:
            role = Role(role.strip().upper())
        except ValueError:
            role = Role.VIEWER
    return require_roles(role)


__all__ = ["require_login", "require_role", "get_current_user", "require_roles", "Role"]
