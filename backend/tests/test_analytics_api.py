"""Tests for Phase 5.5: Analytics API Router.

Verifies:
1. Correct session summary (overall, room-wise, and branch-wise).
2. Four distinct attendance state counts (PRESENT, ABSENT, PENDING, UNREVIEWED).
3. Confirmed percentage formula: PRESENT / (PRESENT + ABSENT) * 100.
4. Safe zero-denominator handling without division errors.
5. Missing session handling (404 Not Found).
6. Date-based summary aggregation and empty date handling.
7. Invalid date format validation (422).
8. Institute-wide overall overview endpoint.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Student, Room, Session as DbSession, Attendance
from app.dependencies import get_db
from app.main import app


@pytest.fixture
def test_db_engine():
    """In-memory SQLite database isolated per test session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def seeded_client(test_db_engine):
    """FastAPI TestClient with isolated in-memory DB and pre-seeded dataset."""
    TestingSessionLocal = sessionmaker(bind=test_db_engine, class_=Session, expire_on_commit=False)

    with TestingSessionLocal() as session:
        # Seed students
        session.add_all([
            Student(usn="1MS21CS001", name="Alice", branch="CSE"),
            Student(usn="1MS21CS002", name="Bob", branch="CSE"),
            Student(usn="1MS21EC001", name="Charlie", branch="ECE"),
            Student(usn="1MS21EC002", name="David", branch="ECE"),
        ])
        # Seed rooms
        session.add_all([
            Room(room_id="LH-101", name="Lecture Hall 101"),
            Room(room_id="LH-102", name="Lecture Hall 102"),
        ])
        # Seed sessions
        session.add_all([
            DbSession(session_id="SESS-001", date="2026-03-15", subject="Computer Networks"),
            DbSession(session_id="SESS-002", date="2026-03-15", subject="Algorithms"),
            DbSession(session_id="SESS-EMPTY", date="2026-03-16", subject="No Records Session"),
        ])
        # Seed attendance for SESS-001:
        # 1MS21CS001: PRESENT in LH-101 (CSE)
        # 1MS21CS002: ABSENT in LH-101 (CSE)
        # 1MS21EC001: PENDING in LH-102 (ECE)
        # 1MS21EC002: UNREVIEWED in LH-102 (ECE)
        session.add_all([
            Attendance(session_id="SESS-001", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="csv", confidence=1.0),
            Attendance(session_id="SESS-001", usn="1MS21CS002", room_id="LH-101", status="ABSENT", source="csv", confidence=1.0),
            Attendance(session_id="SESS-001", usn="1MS21EC001", room_id="LH-102", status="PENDING", source="csv", confidence=1.0),
            Attendance(session_id="SESS-001", usn="1MS21EC002", room_id="LH-102", status="UNREVIEWED", source="csv", confidence=0.5),
        ])
        # Seed attendance for SESS-002:
        # 1MS21CS001: PRESENT in LH-101 (CSE)
        # 1MS21EC001: PRESENT in LH-101 (ECE)
        session.add_all([
            Attendance(session_id="SESS-002", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="manual", confidence=1.0),
            Attendance(session_id="SESS-002", usn="1MS21EC001", room_id="LH-101", status="PRESENT", source="manual", confidence=1.0),
        ])
        session.commit()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app, raise_server_exceptions=False)
    yield test_client
    app.dependency_overrides.clear()


# ==============================================================================
# 1. Session Summary Tests
# ==============================================================================

def test_get_session_summary_success(seeded_client):
    res = seeded_client.get("/api/v1/analytics/sessions/SESS-001/summary")
    assert res.status_code == 200
    data = res.json()

    assert data["session_id"] == "SESS-001"
    assert data["date"] == "2026-03-15"

    overall = data["overall"]
    # 4 distinct states verified
    assert overall["present"] == 1
    assert overall["absent"] == 1
    assert overall["pending"] == 1
    assert overall["unreviewed"] == 1
    assert overall["confirmed"] == 2  # 1 present + 1 absent
    assert overall["unresolved"] == 2  # 1 pending + 1 unreviewed
    assert overall["total"] == 4

    # Confirmed percentage = 1 present / (1 present + 1 absent) * 100 = 50.0%
    assert overall["percentage"] == 50.0
    assert overall["confirmed_percentage"] == 50.0

    # Room-wise breakdown
    room_wise = {r["room_id"]: r for r in data["room_wise"]}
    assert "LH-101" in room_wise
    assert "LH-102" in room_wise
    assert room_wise["LH-101"]["present"] == 1
    assert room_wise["LH-101"]["absent"] == 1
    assert room_wise["LH-101"]["percentage"] == 50.0

    assert room_wise["LH-102"]["pending"] == 1
    assert room_wise["LH-102"]["unreviewed"] == 1
    assert room_wise["LH-102"]["confirmed"] == 0
    assert room_wise["LH-102"]["percentage"] == 0.0  # Zero denominator safe handling

    # Branch-wise breakdown
    branch_wise = {b["branch"]: b for b in data["branch_wise"]}
    assert "CSE" in branch_wise
    assert "ECE" in branch_wise
    assert branch_wise["CSE"]["present"] == 1
    assert branch_wise["CSE"]["absent"] == 1
    assert branch_wise["ECE"]["pending"] == 1
    assert branch_wise["ECE"]["unreviewed"] == 1


def test_get_session_summary_missing_session_returns_404(seeded_client):
    res = seeded_client.get("/api/v1/analytics/sessions/NONEXISTENT/summary")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_get_session_summary_empty_session(seeded_client):
    res = seeded_client.get("/api/v1/analytics/sessions/SESS-EMPTY/summary")
    assert res.status_code == 200
    data = res.json()
    assert data["session_id"] == "SESS-EMPTY"
    assert data["overall"]["total"] == 0
    assert data["overall"]["percentage"] == 0.0
    assert data["room_wise"] == []
    assert data["branch_wise"] == []


# ==============================================================================
# 2. Date-based Summary Aggregation Tests
# ==============================================================================

def test_get_date_summary_aggregates_multiple_sessions(seeded_client):
    # SESS-001 (1P, 1A, 1Pend, 1Unr) + SESS-002 (2P, 0A, 0Pend, 0Unr)
    # Total for 2026-03-15 = 3 PRESENT, 1 ABSENT, 1 PENDING, 1 UNREVIEWED
    res = seeded_client.get("/api/v1/analytics/date/2026-03-15/summary")
    assert res.status_code == 200
    data = res.json()
    assert data["date"] == "2026-03-15"

    overall = data["overall"]
    assert overall["present"] == 3
    assert overall["absent"] == 1
    assert overall["pending"] == 1
    assert overall["unreviewed"] == 1
    assert overall["confirmed"] == 4  # 3 present + 1 absent
    assert overall["total"] == 6

    # Confirmed percentage = 3 / 4 * 100 = 75.0%
    assert overall["percentage"] == 75.0


def test_get_date_summary_empty_date(seeded_client):
    res = seeded_client.get("/api/v1/analytics/date/2026-12-31/summary")
    assert res.status_code == 200
    data = res.json()
    assert data["date"] == "2026-12-31"
    assert data["overall"]["total"] == 0
    assert data["overall"]["confirmed"] == 0
    assert data["overall"]["percentage"] == 0.0
    assert data["room_wise"] == []


def test_get_date_summary_invalid_date_format_returns_422(seeded_client):
    res = seeded_client.get("/api/v1/analytics/date/15-03-2026/summary")
    assert res.status_code == 422

    res_invalid_cal = seeded_client.get("/api/v1/analytics/date/2026-02-31/summary")
    assert res_invalid_cal.status_code == 422


# ==============================================================================
# 3. Overall Overview Tests
# ==============================================================================

def test_get_analytics_overview(seeded_client):
    res = seeded_client.get("/api/v1/analytics/overview")
    assert res.status_code == 200
    data = res.json()
    overall = data["overall"]
    assert overall["present"] == 3
    assert overall["absent"] == 1
    assert overall["total"] == 6
    assert len(data["room_wise"]) > 0
    assert len(data["branch_wise"]) > 0

