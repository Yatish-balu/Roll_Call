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

The same module also derives the **student** scope (C2): a student is visible
to a non-administrator when the student appears in the attendance of a visible
session, or when the student belongs to a department that offers one of the
caller's mapped subject codes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from fastapi import HTTPException, status
from sqlalchemy import and_, false, func, or_, select

from app.db.models import Attendance, Session as DbSession, Student, Subject
from app.schemas.auth import AuthenticatedUser, Role

logger = logging.getLogger("rollcall.auth.session_scope")

# Owner values that mean "this session has no real owner". Migration 0002
# backfills the literal sentinel 'legacy' for pre-ownership sessions.
LEGACY_OWNER_SENTINELS = ("", "legacy")


def session_scope_condition(user_id: str, subject_codes: Sequence[str]):
    """SQLAlchemy predicate restricting sessions to one caller's scope.

    This is the single implementation of the session-visibility policy; it is
    used by the session list/detail endpoints, the attendance endpoints and the
    AI query tools so that every path enforces the same rule.
    """
    unowned = or_(
        DbSession.teacher_id.is_(None),
        DbSession.teacher_id.in_(list(LEGACY_OWNER_SENTINELS)),
    )
    owned_by_viewer = DbSession.teacher_id == user_id

    inner: List[Any] = []
    if user_id:
        inner.append(DbSession.coordinator_faculty_id == user_id)
    codes = [c for c in (subject_codes or []) if c]
    if codes:
        inner.append(func.upper(DbSession.subject_code).in_(codes))

    if not inner:
        return owned_by_viewer
    return or_(owned_by_viewer, and_(unowned, or_(*inner)))


@dataclass(frozen=True)
class DataScope:
    """Data-read scope of one authenticated caller.

    ``unrestricted`` is only true for ADMIN. For everybody else the scope
    restricts which sessions and which students may be read.
    """

    user_id: str
    unrestricted: bool
    subject_codes: FrozenSet[str] = field(default_factory=frozenset)

    # -- sessions ---------------------------------------------------------
    def session_condition(self):
        """SQLAlchemy predicate over :class:`DbSession` for this caller."""
        if self.unrestricted:
            return None
        return session_scope_condition(self.user_id, sorted(self.subject_codes))

    def visible_session_ids(self, db) -> FrozenSet[str]:
        """Session ids this caller may read (empty for a caller with no scope)."""
        if self.unrestricted:
            return frozenset()
        stmt = select(DbSession.session_id).where(session_scope_condition(self.user_id, sorted(self.subject_codes)))
        try:
            rows = db.execute(stmt).scalars().all()
        except Exception:
            return frozenset()
        return frozenset(str(r) for r in rows)

    def is_session_visible(self, db, session_id: str) -> bool:
        """True when the caller may read the given session."""
        if self.unrestricted:
            return True
        clean = (session_id or "").strip()
        if not clean:
            return False
        stmt = select(DbSession.session_id).where(
            session_scope_condition(self.user_id, sorted(self.subject_codes)),
            DbSession.session_id == clean,
        )
        try:
            return db.execute(stmt).first() is not None
        except Exception:
            return False

    # -- students ---------------------------------------------------------
    def student_condition(self):
        """SQLAlchemy predicate over :class:`Student` for this caller.

        A student is in scope when they appear in the attendance of a visible
        session, or when their department offers one of the caller's mapped
        subject codes.
        """
        if self.unrestricted:
            return None
        visible_sessions = select(DbSession.session_id).where(
            session_scope_condition(self.user_id, sorted(self.subject_codes))
        )
        from_attendance = Student.usn.in_(
            select(Attendance.usn).where(Attendance.session_id.in_(visible_sessions))
        )
        codes = sorted(self.subject_codes)
        if codes:
            from_department = Student.usn.in_(
                select(Student.usn).where(
                    Student.dept_id.in_(
                        select(Subject.dept_id).where(
                            func.upper(Subject.subject_code).in_(codes)
                        )
                    )
                )
            )
            return or_(from_attendance, from_department)
        return from_attendance

    def visible_student_usns(self, db) -> FrozenSet[str]:
        """USNs of the students this caller may read."""
        if self.unrestricted:
            return frozenset()
        condition = self.student_condition()
        if condition is None:
            return frozenset()
        try:
            rows = db.execute(select(Student.usn).where(condition)).scalars().all()
        except Exception:
            return frozenset()
        return frozenset(str(r) for r in rows)

    def is_student_visible(self, db, usn: str) -> bool:
        """True when the caller may read this student (and their records)."""
        if self.unrestricted:
            return True
        clean = (usn or "").strip().upper()
        if not clean:
            return False
        condition = self.student_condition()
        if condition is None:
            return False
        try:
            stmt = select(Student.usn).where(condition, Student.usn == clean)
            return db.execute(stmt).first() is not None
        except Exception:
            return False


def resolve_data_scope(db, current_user: AuthenticatedUser) -> DataScope:
    """Build the :class:`DataScope` of the authenticated caller."""
    scope = resolve_session_scope(db, current_user)
    return DataScope(
        user_id=scope.user_id,
        unrestricted=scope.unrestricted,
        subject_codes=scope.subject_codes,
    )


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
