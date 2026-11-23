"""Verify an account's exact password without printing the credential or hash.

Use this after provisioning/rotating a faculty credential (e.g. faculty_ai)
to confirm the intended password matches the stored bcrypt hash.

Usage (PowerShell):
    $env:VERIFY_USER_ID = "faculty_ai"
    $env:VERIFY_PASSWORD = "<intended password>"
    python scripts/verify_credential.py
    Remove-Item Env:VERIFY_PASSWORD

Only the account id and a PASS/FAIL result are printed.
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
from app.db.models import User

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("rollcall.verify_credential")


def verify(user_id: str, password: str) -> bool:
    factory = get_sync_session_factory()
    with factory() as db:
        user = db.get(User, user_id)
        if user is None:
            logger.error("FAIL: account '%s' does not exist.", user_id)
            return False
        if not user.is_active:
            logger.error("FAIL: account '%s' is inactive.", user_id)
            return False
        stored = user.hashed_password or ""
        if not stored.startswith("$2"):
            logger.error("FAIL: account '%s' has no bcrypt hash.", user_id)
            return False
        try:
            ok = bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
        except ValueError:
            ok = False
        logger.info("%s: exact credential %s for account '%s'.",
                    "PASS" if ok else "FAIL", "matches" if ok else "does not match", user_id)
        return ok


def main() -> int:
    user_id = os.getenv("VERIFY_USER_ID", "").strip()
    password = os.getenv("VERIFY_PASSWORD", "")
    if not user_id or not password:
        logger.error("Set VERIFY_USER_ID and VERIFY_PASSWORD before running this script.")
        return 2
    return 0 if verify(user_id, password) else 1


if __name__ == "__main__":
    raise SystemExit(main())
