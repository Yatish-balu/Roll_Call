"""Rotation utility must update hashes, revoke sessions and never log secrets."""

import logging
import os
import tempfile
from datetime import datetime, timezone

import bcrypt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SqlSession, sessionmaker

from app.db.base import Base
from app.db.models import AuthRefreshToken, AuthSession, User
from scripts.rotate_password import rotate_password

NEW_PASSWORD = "RotatedPass_2026_Strong"


@pytest.fixture
def rotation_db(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="rollcall.rotate_password")
    temp_dir = tempfile.mkdtemp()
    engine = create_engine(f"sqlite:///{os.path.join(temp_dir, 'rotation.db')}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, class_=SqlSession, expire_on_commit=False)
    monkeypatch.setattr("scripts.rotate_password.get_sync_session_factory", lambda: SessionLocal)

    with SessionLocal() as db:
        old_hash = bcrypt.hashpw(b"OldPass_2026_Strong", bcrypt.gensalt()).decode("utf-8")
        db.add(
            User(
                user_id="faculty_cn",
                email="faculty.cn@rollcall.internal",
                role="FACULTY",
                hashed_password=old_hash,
                is_active=1,
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        )
        db.add(
            AuthSession(
                session_id="SESSION-1",
                user_id="faculty_cn",
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                absolute_expiry=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        )
        db.add(
            AuthRefreshToken(
                token_id="TOKEN-1",
                session_id="SESSION-1",
                token_hash="hash",
                rotation_seq=0,
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        )
        db.commit()

    return SessionLocal, caplog


def test_rotation_updates_hash_and_revokes_sessions(rotation_db):
    SessionLocal, caplog = rotation_db

    assert rotate_password("faculty_cn", NEW_PASSWORD) is True

    with SessionLocal() as db:
        user = db.get(User, "faculty_cn")
        assert bcrypt.checkpw(NEW_PASSWORD.encode("utf-8"), user.hashed_password.encode("utf-8"))
        assert db.get(AuthSession, "SESSION-1").revoked_at
        assert db.get(AuthRefreshToken, "TOKEN-1").revoked_at

    assert NEW_PASSWORD not in caplog.text
    assert "faculty_cn" in caplog.text


def test_rotation_rejects_weak_password(rotation_db):
    SessionLocal, _ = rotation_db

    with pytest.raises(ValueError):
        rotate_password("faculty_cn", "short")

    with SessionLocal() as db:
        user = db.get(User, "faculty_cn")
        assert bcrypt.checkpw(b"OldPass_2026_Strong", user.hashed_password.encode("utf-8"))


def test_rotation_rejects_unknown_account(rotation_db):
    assert rotate_password("does_not_exist", NEW_PASSWORD) is False
