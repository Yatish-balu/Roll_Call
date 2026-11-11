"""Service layer for RollCall AI.

Shared application services that are used by more than one router (or by a
router and the chat/UI paths) so that authorization and auditing stay
consistent across every entry point.
"""

from app.services.attendance_edits import (
    PENDING_EDIT_TTL_MINUTES,
    SYSTEM_ACTOR_ID,
    SYSTEM_ACTOR_ROLE,
    AttendanceChange,
    EditIntent,
    actor_exists,
    actor_identity,
    assert_session_edit_authorized,
    capture_attendance_statuses,
    confirm_attendance_edit,
    ensure_system_actor,
    propose_attendance_edit,
    resolve_edit_intent,
    session_is_editable,
    write_attendance_audit,
)

__all__ = [
    "PENDING_EDIT_TTL_MINUTES",
    "SYSTEM_ACTOR_ID",
    "SYSTEM_ACTOR_ROLE",
    "AttendanceChange",
    "EditIntent",
    "actor_exists",
    "actor_identity",
    "assert_session_edit_authorized",
    "capture_attendance_statuses",
    "confirm_attendance_edit",
    "ensure_system_actor",
    "propose_attendance_edit",
    "resolve_edit_intent",
    "session_is_editable",
    "write_attendance_audit",
]
