"""Tests verifying seed_demo script and demo scenarios (Prompt N16)."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Session as DbSession, Student, User
from app.policy import is_editable
from app.schemas.auth import AuthenticatedUser
from scripts.seed_demo import seed_demo_data
from tools.defaulter_tool import get_defaulters_data


@pytest.fixture
def demo_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    seed_demo_data(db_session=db)

    try:
        yield db
    finally:
        db.close()


def test_seed_lock_states(demo_db: Session):
    """Verify demo lock states: 2h editable, 23h editable, 3d locked, legacy locked."""
    s_2h = demo_db.get(DbSession, "SESS-DEMO-2H")
    assert s_2h is not None
    assert is_editable(s_2h.created_at, "FACULTY") is True

    s_23h = demo_db.get(DbSession, "SESS-DEMO-23H")
    assert s_23h is not None
    assert is_editable(s_23h.created_at, "FACULTY") is True

    s_3d = demo_db.get(DbSession, "SESS-DEMO-3D")
    assert s_3d is not None
    assert is_editable(s_3d.created_at, "FACULTY") is False
    assert is_editable(s_3d.created_at, "ADMIN") is True

    s_legacy = demo_db.get(DbSession, "SESS-DEMO-LEGACY")
    assert s_legacy is not None
    assert is_editable(s_legacy.created_at, "FACULTY") is False
    assert is_editable(s_legacy.created_at, "ADMIN") is True


def test_seed_defaulters_planted(demo_db: Session):
    """Verify defaulter engine identifies planted defaulters."""
    admin = AuthenticatedUser(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN")
    defaulters = get_defaulters_data(admin, threshold=75.0, db=demo_db)

    usns = [d["usn"] for d in defaulters]
    # Alice (60%) and Evan (50%) are defaulters
    assert "1MS21CS001" in usns
    assert "1MS21CS005" in usns

    # Bob (exactly 75%) and Charlie (90%) are NOT defaulters
    assert "1MS21CS002" not in usns
    assert "1MS21CS003" not in usns
