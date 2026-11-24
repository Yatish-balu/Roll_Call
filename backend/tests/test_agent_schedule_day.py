"""Schedule intent must honour the requested day (today vs whole week)."""

import datetime
import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SqlSession, sessionmaker

from app.agent.legacy_agent import AttendanceAgent
from app.auth.roles import Role
from app.db import crud
from app.db.base import Base


@pytest.fixture
def schedule_agent():
    temp_dir = tempfile.mkdtemp()
    engine = create_engine(f"sqlite:///{os.path.join(temp_dir, 'schedule.db')}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=SqlSession, expire_on_commit=False)
    today = datetime.date.today()
    with factory() as db:
        for offset in (-2, -1, 0, 1, 3):
            day = (today + datetime.timedelta(days=offset)).isoformat()
            crud.insert_session(
                db,
                session_id=f"SESS-{offset}",
                date=day,
                subject="Software Engineering",
                subject_code="22CY51",
            )
        db.commit()
    return AttendanceAgent(
        db_target=factory(),
        actor_id="faculty_mangala",
        actor_name="Mangala L",
        role=Role.FACULTY,
        assigned_subjects=["22CY51"],
    )


def test_today_returns_only_today(schedule_agent):
    res = schedule_agent._handle_schedule_intent("Show my class schedule for today", "req-1")
    assert res.success is True
    assert res.data
    assert all(item["date"] == datetime.date.today().isoformat() for item in res.data)
    assert datetime.date.today().isoformat() in res.message


def test_week_query_can_span_dates(schedule_agent):
    res = schedule_agent._handle_schedule_intent("show my schedule for this week", "req-2")
    assert res.success is True
    assert len({item["date"] for item in res.data}) >= 2
