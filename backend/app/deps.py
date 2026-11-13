"""FastAPI RBAC and UserContext dependency helpers (RC-RBAC-002).

Provides ``require_role``, ``require_login``, ``UserContext``, and
``get_user_context`` while bridging to the core JWT / role infrastructure in
``app.auth``.

Authorization policy:
- ``admin`` (``Role.ADMIN``) is college-wide and unrestricted across all
  departments, branches, rooms, and subjects. Department leadership columns
  (``departments.head_of_dept_id`` and ``department_staff``) are deferred and
  never filter admin queries.
- ``teacher`` / ``faculty`` (``Role.FACULTY``) is strictly scoped to owned
  sessions, coordinated sessions, and unowned sessions matching their mapped
  subject codes in ``teacher_subjects`` / ``faculty_subjects``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, FrozenSet, List, Optional, Sequence, Set, Tuple, Union

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    get_current_user,
    require_admin,
    require_faculty,
    require_roles,
    require_viewer,
)
from app.auth.roles import Role, normalize_role, role_satisfies
from app.auth.session_scope import DataScope, LEGACY_OWNER_SENTINELS, normalize_subject_code
from app.db import crud
from app.db.models import FacultySubject, User
from app.dependencies import get_db
from app.schemas.auth import AuthenticatedUser


def _canonical_role_label(role: Union[str, Role]) -> str:
    """Return canonical lowercase role string ('admin', 'teacher', 'faculty', 'viewer')."""
    if isinstance(role, Role):
        return role.value.lower()
    raw = str(role or "viewer").strip().lower()
    if raw in ("role.admin", "admin", "administrator", "superadmin"):
        return "admin"
    if raw in ("role.faculty", "faculty"):
        return "faculty"
    if raw in ("teacher", "instructor", "lecturer", "staff"):
        return "teacher"
    if raw in ("role.viewer", "viewer", "student", "guest"):
        return "viewer"
    return raw or "viewer"


def _to_role_enum(role: Union[str, Role]) -> Role:
    """Map string/enum role names (including 'teacher') into ``Role``."""
    if isinstance(role, Role):
        return role
    raw = str(role or "").strip().lower()
    if raw in ("teacher", "instructor", "lecturer", "staff"):
        return Role.FACULTY
    if raw == "admin":
        return Role.ADMIN
    if raw == "viewer":
        return Role.VIEWER
    return normalize_role(str(role))


@dataclass
class UserContext:
    """Caller authorization context passed to services and ``tools.query_tool``.

    - When ``role == 'admin'``, ``unrestricted`` is always ``True`` regardless
      of whether ``dept_id`` is populated; no ``dept_id`` or ``subject_code``
      filters are ever applied.
    - When ``role in ('teacher', 'faculty')``, ``unrestricted`` is ``False`` and
      queries are restricted to ``user_id`` ownership and mapped ``subject_codes``.
    """

    user_id: str
    role: Union[str, Role] = "viewer"
    dept_id: Optional[str] = None
    subject_codes: Sequence[str] = field(default_factory=tuple)
    email: Optional[str] = None
    unrestricted: bool = field(init=False)

    def __post_init__(self) -> None:
        self.user_id = str(self.user_id or "").strip()
        self.role = _canonical_role_label(self.role)
        normalized_codes: List[str] = []
        seen: Set[str] = set()
        for raw_code in self.subject_codes or ():
            code = normalize_subject_code(raw_code)
            if code and code not in seen:
                seen.add(code)
                normalized_codes.append(code)
        self.subject_codes = tuple(sorted(normalized_codes))
        # Admin is strictly global (all departments, branches, rooms, subjects).
        self.unrestricted = _to_role_enum(self.role) == Role.ADMIN

    @property
    def is_admin(self) -> bool:
        """True when caller has college-wide unrestricted admin privileges."""
        return self.unrestricted

    @property
    def normalized_role(self) -> Role:
        """Return the underlying ``Role`` enum."""
        return _to_role_enum(self.role)

    def to_data_scope(self) -> DataScope:
        """Convert to ``app.auth.session_scope.DataScope``."""
        return DataScope(
            user_id=self.user_id,
            unrestricted=self.unrestricted,
            subject_codes=frozenset(self.subject_codes),
        )

    def session_condition(self):
        """Return SQLAlchemy filter predicate for sessions (``None`` for admin)."""
        if self.unrestricted:
            return None
        return self.to_data_scope().session_condition()

    def student_condition(self):
        """Return SQLAlchemy filter predicate for students (``None`` for admin)."""
        if self.unrestricted:
            return None
        return self.to_data_scope().student_condition()

    def _sqlite_session_ids(self, conn: sqlite3.Connection) -> FrozenSet[str]:
        cur = conn.cursor()
        cols = {
            str(row[1]).lower()
            for row in cur.execute("PRAGMA table_info(sessions)").fetchall()
        }
        has_coord = "coordinator_faculty_id" in cols
        has_teacher = "teacher_id" in cols
        has_subject_code = "subject_code" in cols

        if not has_subject_code and not has_teacher:
            return frozenset()

        clauses: List[str] = []
        params: List[Any] = []

        if has_teacher and self.user_id:
            clauses.append("teacher_id = ?")
            params.append(self.user_id)

        unowned_inner: List[str] = []
        if has_coord and self.user_id:
            unowned_inner.append("coordinator_faculty_id = ?")
            params.append(self.user_id)
        if has_subject_code and self.subject_codes:
            placeholders = ", ".join("?" for _ in self.subject_codes)
            unowned_inner.append(f"UPPER(subject_code) IN ({placeholders})")
            params.extend(self.subject_codes)

        if unowned_inner:
            inner_sql = " OR ".join(unowned_inner)
            if has_teacher:
                sentinels = ", ".join("?" for _ in LEGACY_OWNER_SENTINELS)
                clauses.append(
                    f"((teacher_id IS NULL OR teacher_id IN ({sentinels})) AND ({inner_sql}))"
                )
                # Order params carefully: prepend sentinel params before inner_sql params.
                params = params[: (1 if (has_teacher and self.user_id) else 0)] + list(
                    LEGACY_OWNER_SENTINELS
                ) + params[(1 if (has_teacher and self.user_id) else 0) :]
            else:
                clauses.append(f"({inner_sql})")

        if not clauses:
            return frozenset()

        sql = f"SELECT session_id FROM sessions WHERE {' OR '.join(clauses)}"  # nosec B608
        rows = cur.execute(sql, tuple(params)).fetchall()
        return frozenset(str(row[0]) for row in rows)

    def _sqlite_student_usns(self, conn: sqlite3.Connection) -> FrozenSet[str]:
        usns: Set[str] = set()
        session_ids = sorted(self.visible_session_ids(conn))
        cur = conn.cursor()
        if session_ids:
            placeholders = ", ".join("?" for _ in session_ids)
            rows = cur.execute(
                f"SELECT DISTINCT usn FROM attendance WHERE session_id IN ({placeholders})",  # nosec B608
                tuple(session_ids),
            ).fetchall()
            usns.update(str(row[0]) for row in rows if row[0])

        if self.subject_codes:
            tables = {
                str(row[0]).lower()
                for row in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "subjects" in tables and "students" in tables:
                student_cols = {
                    str(row[1]).lower()
                    for row in cur.execute("PRAGMA table_info(students)").fetchall()
                }
                if "dept_id" in student_cols:
                    placeholders = ", ".join("?" for _ in self.subject_codes)
                    rows = cur.execute(
                        f"SELECT DISTINCT st.usn FROM students st "  # nosec B608
                        f"JOIN subjects sub ON st.dept_id = sub.dept_id "
                        f"WHERE UPPER(sub.subject_code) IN ({placeholders})",
                        tuple(self.subject_codes),
                    ).fetchall()
                    usns.update(str(row[0]) for row in rows if row[0])

        return frozenset(usns)

    def visible_session_ids(self, db: Any = None) -> FrozenSet[str]:
        """Return session IDs visible to a restricted caller (empty for admin)."""
        if self.unrestricted or db is None:
            return frozenset()
        if isinstance(db, sqlite3.Connection):
            return self._sqlite_session_ids(db)
        if isinstance(db, (str, Path)):
            resolved = Path(db).resolve()
            if not resolved.exists():
                return frozenset()
            conn = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
            try:
                return self._sqlite_session_ids(conn)
            finally:
                conn.close()
        return self.to_data_scope().visible_session_ids(db)

    def visible_student_usns(self, db: Any = None) -> FrozenSet[str]:
        """Return student USNs visible to a restricted caller (empty for admin)."""
        if self.unrestricted or db is None:
            return frozenset()
        if isinstance(db, sqlite3.Connection):
            return self._sqlite_student_usns(db)
        if isinstance(db, (str, Path)):
            resolved = Path(db).resolve()
            if not resolved.exists():
                return frozenset()
            conn = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
            try:
                return self._sqlite_student_usns(conn)
            finally:
                conn.close()
        return self.to_data_scope().visible_student_usns(db)


def require_role(
    required_role: Union[str, Role],
    *extra_roles: Union[str, Role],
) -> Callable[[AuthenticatedUser], AuthenticatedUser]:
    """Require at least one of the given roles (e.g. ``require_role('admin')``).

    Supports string role labels (``'admin'``, ``'teacher'``, ``'faculty'``,
    ``'viewer'``) as well as ``Role`` enum values, using the project role
    hierarchy where ``ADMIN > FACULTY > VIEWER`` with unrestricted college-wide
    admin access.
    """
    normalized = tuple(_to_role_enum(r) for r in (required_role, *extra_roles))
    return require_roles(*normalized)


def require_login(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """FastAPI dependency requiring any authenticated user."""
    return current_user


def get_user_context(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserContext:
    """Build the authoritative ``UserContext`` for the authenticated user.

    Reads optional ``dept_id`` (informational only; never scopes admin) and
    subject mappings from ``faculty_subjects`` / ``teacher_subjects``.
    """
    user_id = (current_user.user_id or "").strip()
    db_user = db.get(User, user_id) if user_id else None
    dept_id = getattr(db_user, "dept_id", None) if db_user is not None else None

    if current_user.role == Role.ADMIN:
        return UserContext(
            user_id=user_id,
            role="admin",
            dept_id=dept_id,
            subject_codes=(),
            email=current_user.email,
        )

    codes: List[str] = list(crud.get_teacher_subjects(db, user_id=user_id) or [])
    try:
        fac_rows = (
            db.query(FacultySubject.subject_code)
            .filter(FacultySubject.faculty_id == user_id)
            .all()
        )
        for row in fac_rows:
            if row and row[0]:
                codes.append(str(row[0]))
    except Exception:
        pass

    return UserContext(
        user_id=user_id,
        role=current_user.role,
        dept_id=dept_id,
        subject_codes=tuple(codes),
        email=current_user.email,
    )


__all__ = [
    "Role",
    "UserContext",
    "get_current_user",
    "get_user_context",
    "normalize_role",
    "require_admin",
    "require_faculty",
    "require_login",
    "require_role",
    "require_roles",
    "require_viewer",
    "role_satisfies",
]

