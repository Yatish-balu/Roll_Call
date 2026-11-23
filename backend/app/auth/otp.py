"""One-time-password helpers for the password-reset flow.

The ``otp_codes`` table is created by migration ``0023_otp_codes`` and declared
on the shared model metadata in :mod:`app.db.models`, so schema-drift checks
can see it.

- :func:`store_otp` invalidates any previous code for the user and inserts a new
  6-digit code with an expiry (10 minutes by default).
- :func:`verify_otp` accepts a code exactly once: it must match, be unused and
  not expired, and is marked as used in the same statement.
- :func:`cleanup_expired_otps` removes codes that can no longer be used.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import otp_codes

DEFAULT_OTP_MINUTES = 10
metadata = Base.metadata


def _utcnow_naive() -> datetime:
    """UTC now as a naive datetime, matching the DATETIME columns in SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def generate_otp() -> str:
    """Return a cryptographically random 6-digit string."""
    return f"{secrets.randbelow(1_000_000):06d}"


def store_otp(db: Session, user_id: str, minutes_valid: int = DEFAULT_OTP_MINUTES) -> str:
    """Invalidate earlier codes for ``user_id`` and store a fresh one.

    Returns the plain 6-digit code so the caller can deliver it (email/SMS).
    """
    code = generate_otp()
    expires = _utcnow_naive() + timedelta(minutes=max(1, minutes_valid))

    # One active code per user: drop any previous (used or expired) rows first
    # so the unique constraint on user_id can never reject the insert.
    db.execute(delete(otp_codes).where(otp_codes.c.user_id == user_id))
    db.execute(
        insert(otp_codes).values(
            user_id=user_id,
            code=code,
            expires_at=expires,
            used=False,
        )
    )
    db.commit()
    return code


def verify_otp(db: Session, user_id: str, code: str) -> bool:
    """Return ``True`` when ``code`` is the user's live OTP.

    A successful verification consumes the code; a failed one leaves it intact
    so the user can retry within the 10-minute window.
    """
    candidate = (code or "").strip()
    if not candidate:
        return False

    row = db.execute(
        select(otp_codes.c.id).where(
            otp_codes.c.user_id == user_id,
            otp_codes.c.code == candidate,
            otp_codes.c.used.is_(False),
            otp_codes.c.expires_at > _utcnow_naive(),
        )
    ).first()
    if row is None:
        return False

    # Consume atomically: only the request that flips used=False -> True wins.
    consumed = db.execute(
        update(otp_codes)
        .where(otp_codes.c.id == row[0], otp_codes.c.used.is_(False))
        .values(used=True)
    )
    db.commit()
    return consumed.rowcount == 1


def cleanup_expired_otps(db: Session) -> int:
    """Delete expired codes; returns the number of rows removed."""
    deleted = db.execute(delete(otp_codes).where(otp_codes.c.expires_at < _utcnow_naive()))
    db.commit()
    return deleted.rowcount or 0
