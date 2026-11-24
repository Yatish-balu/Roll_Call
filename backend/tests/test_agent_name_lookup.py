"""Name-based lookups must work as well as USN-based ones."""

import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SqlSession, sessionmaker

from app.agent.legacy_agent import AttendanceAgent
from app.auth.roles import Role
from app.db import crud
from app.db.base import Base
from app.db.models import User


@pytest.fixture
def agent():
    temp_dir = tempfile.mkdtemp()
    engine = create_engine(f"sqlite:///{os.path.join(temp_dir, 'names.db')}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=SqlSession, expire_on_commit=False)
    with factory() as db:
        crud.insert_student(db, usn="1DS24CY060", name="YATISH BALU", branch="CY")
        db.add(
            User(
                user_id="yatish_balu",
                name="Yatish Balu",
                email="yatish@rollcall.edu",
                role=Role.FACULTY,
                is_active=1,
                created_at="2026-11-25T00:00:00Z",
            )
        )
        db.commit()
    return AttendanceAgent(db_target=factory(), actor_id="faculty_cn", role=Role.FACULTY)


def test_who_is_name_lookup(agent):
    res = agent._handle_query_intent("who is yatish", "req-1")
    assert res.success is True
    assert "YATISH BALU" in res.message
    assert "1DS24CY060" in res.message


def test_usn_of_name_lookup(agent):
    res = agent._handle_query_intent("what is the USN of Yatish Balu", "req-2")
    assert res.success is True
    assert "1DS24CY060" in res.message
