"""Idempotent seed script to provision default ADMIN and FACULTY accounts for RollCall AI."""

from __future__ import annotations

import logging
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import bcrypt

# Ensure backend directory is on sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv

# Load .env from project root if present
_REPO_ROOT = _BACKEND_DIR.parent
_ENV_FILE = _REPO_ROOT / ".env"
if _ENV_FILE.exists():
    load_dotenv(dotenv_path=_ENV_FILE)
else:
    load_dotenv()

from app.db.connection import get_sync_session_factory
from app.db.models import TeacherSubject, User

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("rollcall.seed")


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password must not exceed 72 UTF-8 bytes for bcrypt.")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def get_seed_configuration() -> List[Dict[str, Optional[str]]]:
    """Retrieve seed account definitions from environment variables with safe defaults."""
    env = os.getenv("APP_ENV", "development").lower()
    is_prod = env == "production"

    admin_pw = os.getenv("SEED_ADMIN_PASSWORD")
    f1_pw = os.getenv("SEED_FACULTY_1_PASSWORD")
    f2_pw = os.getenv("SEED_FACULTY_2_PASSWORD")
    f3_pw = os.getenv("SEED_FACULTY_3_PASSWORD")

    if is_prod:
        missing = []
        if not admin_pw: missing.append("SEED_ADMIN_PASSWORD")
        if not f1_pw: missing.append("SEED_FACULTY_1_PASSWORD")
        if not f2_pw: missing.append("SEED_FACULTY_2_PASSWORD")
        if not f3_pw: missing.append("SEED_FACULTY_3_PASSWORD")
        if missing:
            raise ValueError(f"Production security error: The following seed passwords must be set in environment: {missing}")
    else:
        # Never ship a static default password. If the operator did not choose
        # one, generate a random value per run and show it once. This keeps a
        # seeded development database from being trivially guessable.
        def _dev_password(env_name: str, user_id: str) -> str:
            configured = os.getenv(env_name)
            if configured:
                return configured
            generated = secrets.token_urlsafe(18)
            logger.warning(
                "No %s set; generated a random development password for '%s': %s "
                "(change it after first login).",
                env_name,
                user_id,
                generated,
            )
            return generated

        admin_pw = _dev_password("SEED_ADMIN_PASSWORD", "admin_root")
        f1_pw = _dev_password("SEED_FACULTY_1_PASSWORD", "faculty_ds")
        f2_pw = _dev_password("SEED_FACULTY_2_PASSWORD", "faculty_ml")
        f3_pw = _dev_password("SEED_FACULTY_3_PASSWORD", "faculty_cn")

    return [
        {
            "user_id": os.getenv("SEED_ADMIN_USER_ID", "admin_root"),
            "email": os.getenv("SEED_ADMIN_EMAIL", "admin@rollcall.internal"),
            "password": admin_pw,
            "role": "ADMIN",
            "subjects": [],
        },
        {
            "user_id": os.getenv("SEED_FACULTY_1_USER_ID", "faculty_ds"),
            "email": os.getenv("SEED_FACULTY_1_EMAIL", "faculty.ds@rollcall.internal"),
            "password": f1_pw,
            "role": "FACULTY",
            "subjects": ["DIST-SYS", "DB-SYS"],
        },
        {
            "user_id": os.getenv("SEED_FACULTY_2_USER_ID", "faculty_ml"),
            "email": os.getenv("SEED_FACULTY_2_EMAIL", "faculty.ml@rollcall.internal"),
            "password": f2_pw,
            "role": "FACULTY",
            "subjects": ["ML"],
        },
        {
            "user_id": os.getenv("SEED_FACULTY_3_USER_ID", "faculty_cn"),
            "email": os.getenv("SEED_FACULTY_3_EMAIL", "faculty.cn@rollcall.internal"),
            "password": f3_pw,
            "role": "FACULTY",
            "subjects": ["CN"],
        },
    ]


def seed_users(session_factory=None) -> Dict[str, int]:
    """
    Idempotently seed user accounts without printing or leaking secrets.
    Returns counts of created and skipped users.
    """
    factory = session_factory or get_sync_session_factory()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    accounts = get_seed_configuration()

    created_count = 0
    skipped_count = 0

    with factory() as db:
        for acc in accounts:
            uid = acc["user_id"]
            existing = db.get(User, uid)
            if existing:
                logger.info("User '%s' already exists in database; skipping creation.", uid)
                skipped_count += 1
            else:
                pw_hash = hash_password(acc["password"])
                user = User(
                    user_id=uid,
                    email=acc["email"],
                    role=acc["role"],
                    hashed_password=pw_hash,
                    is_active=1,
                    created_at=now_iso,
                )
                db.add(user)
                db.flush()
                logger.info("Created user '%s' with role '%s'.", uid, acc["role"])
                created_count += 1

            # Seed assigned subjects if not already assigned
            for subj in acc.get("subjects", []):
                from sqlalchemy import select
                stmt = select(TeacherSubject).where(
                    TeacherSubject.user_id == uid,
                    TeacherSubject.subject_code == subj,
                )
                if not db.execute(stmt).first():
                    ts = TeacherSubject(user_id=uid, subject_code=subj)
                    db.add(ts)
                    logger.info("Assigned subject '%s' to teacher '%s'.", subj, uid)

        db.commit()

    logger.info("Seed completed: %d created, %d skipped.", created_count, skipped_count)
    return {"created": created_count, "skipped": skipped_count}


if __name__ == "__main__":
    seed_users()

