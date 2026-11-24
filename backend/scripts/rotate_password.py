"""Rotate one existing user's password without printing or logging the secret.

Seed scripts intentionally skip accounts that already exist, so rotating a
committed seed password also requires updating the stored hash. This utility
does that, and revokes every active session/refresh token at the same time.

Usage (PowerShell):
    $env:ROTATE_USER_ID = "faculty_cn"
    $env:ROTATE_NEW_PASSWORD = "<new strong password>"   # set from a secret manager
    python scripts/rotate_password.py

Neither the password nor its hash is ever logged.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import bcrypt

from app.db.connection import get_sync_session_factory
from app.db.models import AuthRefreshToken, AuthSession, User
from app.security.rate_limit import clear_limit, LimitScope

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("rollcall.rotate_password")


def rotate_password(user_id: str, new_password: str) -> bool:
    """Update the hash and revoke sessions. Returns False if the user is absent."""
    if logger.disabled:
        logger.disabled = False
    if len(new_password.encode("utf-8")) > 72:
        raise ValueError("Password must not exceed 72 UTF-8 bytes for bcrypt.")
    if len(new_password) < 12:
        raise ValueError("Password must be at least 12 characters.")

    new_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    from datetime import datetime, timezone

    revoked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    factory = get_sync_session_factory()
    with factory() as db:
        user = db.get(User, user_id)
        if user is None:
            logger.error("Rotation aborted: account '%s' does not exist.", user_id)
            return False

        user.hashed_password = new_hash
        db.query(AuthSession).filter(AuthSession.user_id == user_id).update(
            {AuthSession.revoked_at: revoked_at}, synchronize_session=False
        )
        session_ids = [
            row[0]
            for row in db.query(AuthSession.session_id)
            .filter(AuthSession.user_id == user_id)
            .all()
        ]
        if session_ids:
            db.query(AuthRefreshToken).filter(
                AuthRefreshToken.session_id.in_(session_ids)
            ).update({AuthRefreshToken.revoked_at: revoked_at}, synchronize_session=False)

        clear_limit(db, LimitScope.PASSWORD_CHANGE, f"user:{user_id}")
        clear_limit(db, LimitScope.LOGIN, f"user:{user_id}")
        db.commit()
        logger.info("Password rotated and sessions revoked for account '%s'.", user_id)
        return True


def main() -> int:
    user_id = os.getenv("ROTATE_USER_ID", "").strip()
    new_password = os.getenv("ROTATE_NEW_PASSWORD", "")
    if not user_id or not new_password:
        logger.error("Set ROTATE_USER_ID and ROTATE_NEW_PASSWORD before running this script.")
        return 2
    try:
        return 0 if rotate_password(user_id, new_password) else 1
    except ValueError as exc:
        logger.error("Rotation refused: %s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
