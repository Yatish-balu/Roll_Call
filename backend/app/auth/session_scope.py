"""Server-side session visibility scope.

The FastAPI layer is the authorization authority for session metadata. This
module holds the single policy used by every endpoint that exposes session
information, so the list endpoint, the detail endpoint and the aggregation
endpoints can never drift apart.

Policy (mirrors the N3 session-ownership policy in ``app.routers.attendance``):

* ``ADMIN`` keeps institution-wide session access.
* A session owned by a real teacher is visible to that teacher only.
* An unowned session (no owner, or the ``legacy`` migration sentinel) is
  visible to its coordinator, or to a teacher whose ``teacher_subjects``
  mapping contains the session's subject code. The match is an EXACT,
  normalized equality comparison - never a substring match.
* Sessions without a subject code and without a coordinator stay ADMIN-only.
  Legacy sessions are never re-assigned as a side effect of being read.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, Optional, Set

from fastapi import HTTPException, status

from app.schemas.auth import AuthenticatedUser, Role

logger = logging.getLogger("rollcall.auth.session_scope")

# Owner values that mean "this session has no real owner". Migration 0002
# backfills the literal sentinel 'legacy' for pre-ownership sessions.
LEGACY_OWNER_SENTINELS = ("", "legacy")


def normalize_subject_code(raw: Optional[str]) -> str:
    """Normalize a subject code for EXACT equality comparisons.

    ``' ml '`` and ``'ML'`` are the same code; ``'HTML'`` is a different code
    than ``'ML'``. Callers must compare with ``==`` on the normalized value,
    never with ``in``/``includes`` on the raw string.
    """
    if raw is None:
        return ""
    return str(raw).strip().upper()


@dataclass(frozen=True)
class SessionScope:
    """Resolved visibility scope of one authenticated caller."""

    user_id: str
    is_admin: bool
    subject_codes: FrozenSet[str] = field(default_factory=frozenset)

    @property
    def unrestricted(self) -> bool:
        """True when the caller may see every session (ADMIN)."""
        return self.is_admin

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _owner_of(session: Dict[str, Any]) -> str:
        owner = session.get("teacher_id")
        return "" if owner is None else str(owner).strip()

    @staticmethod
    def _coordinator_of(session: Dict[str, Any]) -> str:
        coordinator = session.get("coordinator_faculty_id")
        return "" if coordinator is None else str(coordinator).strip()

    def is_unowned(self, session: Dict[str, Any]) -> bool:
        """True when the session has no real owner (unset or legacy sentinel)."""
        return self._owner_of(session) in LEGACY_OWNER_SENTINELS

    def owns(self, session: Dict[str, Any]) -> bool:
        """True when the caller is the explicit owner of the session."""
        owner = self._owner_of(session)
        return bool(owner) and owner not in LEGACY_OWNER_SENTINELS and owner == self.user_id

    def coordinates(self, session: Dict[str, Any]) -> bool:
        """True when the caller is the recorded coordinator of the session."""
        coordinator = self._coordinator_of(session)
        return bool(coordinator) and coordinator == self.user_id

    def subject_mapped(self, session: Dict[str, Any]) -> bool:
        """True when the session's subject code is mapped to the caller.

        The comparison is an exact, normalized equality check - ``'ML'`` never
        matches ``'HTML'``.
        """
        code = normalize_subject_code(session.get("subject_code"))
        if not code or not self.subject_codes:
            return False
        return code in self.subject_codes

    def allows(self, session: Dict[str, Any]) -> bool:
        """Return True when the caller may see this session."""
        if self.unrestricted:
            return True
        if session is None:
            return False
        if self.owns(session):
            return True
        if not self.is_unowned(session):
            # Owned by another teacher: not visible, even for a teacher who is
            # mapped to the same subject code.
            return False
        return self.coordinates(session) or self.subject_mapped(session)

    def assert_allowed(self, session: Dict[str, Any]) -> None:
        """Raise 403 when the caller may not see this session."""
        if self.allows(session):
            return
        subject_code = normalize_subject_code(session.get("subject_code"))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Forbidden: session '{session.get('session_id')}' has no faculty owner and "
                + (
                    f"subject code '{subject_code}' is not mapped to your account."
                    if subject_code
                    else "no subject code, so access requires an administrator."
                )
            ),
        )


def resolve_session_scope(db, current_user: AuthenticatedUser) -> SessionScope:
    """Build the :class:`SessionScope` for the authenticated caller.

    The identity always comes from the verified token (``current_user.user_id``);
    the assigned subject codes are read from the authoritative
    ``teacher_subjects`` mapping table.
    """
    from app.db import crud  # local import: keeps the auth layer decoupled

    user_id = (current_user.user_id or "").strip()
    subject_codes: Set[str] = set()
    if user_id:
        for raw_code in crud.get_teacher_subjects(db, user_id=user_id) or []:
            normalized = normalize_subject_code(raw_code)
            if normalized:
                subject_codes.add(normalized)

    return SessionScope(
        user_id=user_id,
        is_admin=current_user.role == Role.ADMIN,
        subject_codes=frozenset(subject_codes),
    )
