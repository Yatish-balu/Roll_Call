"""60-Second Undo Transaction Engine for RollCall AI.

Provides cryptographic, opaque, time-bounded undo tokens for reversible actions
such as single-student attendance edits. Enforces:
1. HMAC-SHA256 signature verification (zero client tampering).
2. Strict 60-second TTL window.
3. Actor & record binding (cannot apply another user's or record's token).
4. Optimistic concurrency control (rejects undo if record was altered since).
5. Compensating server-side transaction with append-only audit trail (ATTENDANCE_UNDO).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth.jwt import get_jwt_secret
from app.db import crud
from app.db.models import Attendance, AuditLog
from app.services.attendance_edits import (
    AttendanceChange,
    _utcnow_iso,
    assert_session_edit_authorized,
    write_attendance_audit,
)

logger = logging.getLogger("rollcall.services.undo")

UNDO_TTL_SECONDS = 60


def _get_signing_key() -> bytes:
    """Return HMAC key for signing undo tokens."""
    secret = get_jwt_secret()
    return secret.encode("utf-8")


def get_record_version(
    db: Session, record_id: str, session_id: Optional[str] = None, usn: Optional[str] = None
) -> int:
    """Compute optimistic concurrency version for an attendance record.

    Version is (1 + audit entry count for this entity).
    """
    clean_id = str(record_id).strip()
    query = db.query(AuditLog).filter(AuditLog.entity_id == clean_id)
    if session_id and usn:
        entity_alt = f"{session_id}:{usn}"
        query = db.query(AuditLog).filter(
            (AuditLog.entity_id == clean_id) | (AuditLog.entity_id == entity_alt)
        )
    return query.count() + 1


def create_undo_token(
    *,
    actor_id: str,
    record_id: str,
    session_id: str,
    usn: str,
    previous_status: Optional[str],
    new_status: str,
    version: int,
    ttl_seconds: int = UNDO_TTL_SECONDS,
) -> Tuple[str, str]:
    """Create an opaque, HMAC-signed undo token valid for `ttl_seconds`.

    Returns (undo_token, undo_expires_at_iso).
    """
    now = time.time()
    expires_at_ts = now + ttl_seconds
    expires_at_dt = datetime.fromtimestamp(expires_at_ts, tz=timezone.utc)
    expires_at_iso = expires_at_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "actor_id": actor_id,
        "record_id": record_id,
        "session_id": session_id,
        "usn": usn,
        "previous_status": previous_status,
        "new_status": new_status,
        "version": version,
        "created_at": now,
        "expires_at": expires_at_ts,
    }

    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(serialized).decode("utf-8").rstrip("=")

    signature = hmac.new(_get_signing_key(), b64_payload.encode("utf-8"), hashlib.sha256).digest()
    b64_signature = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")

    token = f"{b64_payload}.{b64_signature}"
    return token, expires_at_iso


def verify_undo_token(
    token: str,
    actor_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    record_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify signature, expiry, and actor/record bindings of an undo token.

    Raises HTTPException on validation failure.
    """
    clean_token = (token or "").strip()
    if not clean_token or "." not in clean_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed undo token format.",
        )

    parts = clean_token.split(".")
    if len(parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed undo token format.",
        )

    b64_payload, b64_signature = parts

    # 1. Verify cryptographic signature
    expected_sig = hmac.new(
        _get_signing_key(), b64_payload.encode("utf-8"), hashlib.sha256
    ).digest()
    expected_b64_sig = base64.urlsafe_b64encode(expected_sig).decode("utf-8").rstrip("=")

    if not hmac.compare_digest(b64_signature, expected_b64_sig):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or tampered undo token signature.",
        )

    # 2. Decode payload
    padding = "=" * (-len(b64_payload) % 4)
    try:
        raw_bytes = base64.urlsafe_b64decode(b64_payload + padding)
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse undo token payload: {exc}",
        )

    # 3. Check 60-second expiration window
    expires_at = float(payload.get("expires_at", 0))
    if time.time() > expires_at:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Undo window has expired (must be executed within 60 seconds).",
        )

    # 4. Check actor binding (ADMIN can override)
    clean_role = (actor_role or "").upper()
    if actor_id and payload.get("actor_id") != actor_id and "ADMIN" not in clean_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: undo token is bound to a different actor.",
        )

    # 5. Check record binding if specified
    if record_id and str(payload.get("record_id")) != str(record_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Token target record mismatch: expected {record_id}, got {payload.get('record_id')}.",
        )

    return payload


def execute_undo(
    db: Session,
    *,
    undo_token: str,
    actor_id: str,
    actor_role: str,
    expected_version: Optional[int] = None,
    target_record_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a server-side compensating transaction using a verified undo token."""
    payload = verify_undo_token(
        undo_token,
        actor_id=actor_id,
        actor_role=actor_role,
        record_id=target_record_id,
    )

    rec_id = payload["record_id"]
    sess_id = payload["session_id"]
    usn = payload["usn"]
    previous_status = payload["previous_status"]
    new_status = payload["new_status"]
    token_version = payload["version"]

    # 1. Fetch attendance record
    record = None
    if rec_id.isdigit():
        record = db.get(Attendance, int(rec_id))
    if record is None:
        record = (
            db.query(Attendance)
            .filter(Attendance.session_id == sess_id, Attendance.usn == usn)
            .first()
        )

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attendance record '{rec_id}' no longer exists in database.",
        )

    # 2. Revalidate session authorization
    session_dict = crud.get_session(db, session_id=sess_id)
    if session_dict:
        from app.schemas.auth import AuthenticatedUser, Role

        user_role = Role.ADMIN if "ADMIN" in actor_role.upper() else Role.FACULTY
        auth_user = AuthenticatedUser(
            user_id=actor_id,
            email=f"{actor_id}@rollcall.internal",
            role=user_role,
        )
        assert_session_edit_authorized(auth_user, session_dict, db)

    # 3. Optimistic concurrency check
    curr_version = get_record_version(db, str(record.attendance_id), sess_id, usn)
    if expected_version is not None and expected_version != curr_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Optimistic concurrency conflict: expected record version {expected_version}, "
                f"but current version is {curr_version}. Record has been modified concurrently."
            ),
        )

    # Check that record hasn't changed its status since the action
    if record.status != new_status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot undo: attendance status was changed from '{new_status}' to '{record.status}' "
                "by another operation since this edit."
            ),
        )

    # 4. Compensating Transaction: revert status
    reverted_status = previous_status or "UNREVIEWED"
    record.status = reverted_status

    # 5. Append-only Audit trail: ATTENDANCE_UNDO
    changes = [
        AttendanceChange(
            usn=usn,
            old_status=new_status,
            new_status=reverted_status,
            attendance_id=str(record.attendance_id),
        )
    ]
    write_attendance_audit(
        db,
        actor_id=actor_id,
        actor_role=actor_role,
        session_id=sess_id,
        action="ATTENDANCE_UNDO",
        changes=changes,
        reason="60-second undo compensating transaction",
    )

    db.commit()

    new_version = get_record_version(db, str(record.attendance_id), sess_id, usn)
    logger.info(
        "Successfully undid attendance change for USN %s in session %s (status %s -> %s)",
        usn,
        sess_id,
        new_status,
        reverted_status,
    )

    return {
        "success": True,
        "message": f"Successfully reverted attendance for {usn} to {reverted_status}.",
        "record_id": str(record.attendance_id),
        "session_id": sess_id,
        "usn": usn,
        "previous_status": new_status,
        "current_status": reverted_status,
        "new_version": new_version,
    }
