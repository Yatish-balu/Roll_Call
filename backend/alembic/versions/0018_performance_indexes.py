"""Add performance indexes for the dashboard / report query paths.

Frequently filtered columns that previously required full table scans:

* ``sessions.date``        - dashboard "today's classes" and report date filters.
* ``sessions.subject_code``- attendance report / subject filters (D8 proxy).
* ``sessions.coordinator_faculty_id`` - session visibility scoping resolves
  coordinator-owned sessions for every scoped request.

``attendance.session_id`` / ``attendance.usn`` and ``users.user_id`` are already
covered by ``idx_attendance_session_id`` / ``idx_attendance_usn`` and the
``users`` primary key, so they are intentionally not duplicated here.

Revision ID: 0018_performance_indexes
Revises: 0017_consolidate_subjects
Create Date: 2026-11-13
"""

from alembic import op

revision = "0018_performance_indexes"
down_revision = "0017_consolidate_subjects"
branch_labels = None
depends_on = None

_INDEXES = (
    ("idx_sessions_date", "sessions", "date"),
    ("idx_sessions_subject_code", "sessions", "subject_code"),
    ("idx_sessions_coordinator_faculty", "sessions", "coordinator_faculty_id"),
)


def upgrade() -> None:
    for name, table, column in _INDEXES:
        # IF NOT EXISTS keeps the migration idempotent for environments where
        # the index was already created manually.
        op.execute(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ("{column}")')


def downgrade() -> None:
    for name, _table, _column in reversed(_INDEXES):
        op.execute(f'DROP INDEX IF EXISTS "{name}"')
