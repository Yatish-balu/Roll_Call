"""Regression tests for the timetable authorization policy (audit finding H-2).

The timetable API is the only place where a faculty member can create,
modify or remove a *class slot*, and a class slot decides who teaches what
and when. The policy enforced here is:

* a faculty caller may only manage entries they own;
* an entry without an owner (``faculty_id IS NULL``) is not owned by anybody
  and therefore cannot be modified or deleted by a faculty caller;
* a faculty caller may never hand an entry to another teacher, and never
  moves an entry to a subject they are not mapped to;
* an administrator may still manage any entry.

The academic-day window (09:00 - 17:00) and the overlap rules are covered by
``backend/tools/integration_check.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.db.base import Base
from app.db.models import (
    AcademicYear,
    Batch,
    College,
    Department,
    FacultySubject,
    Room,
    Section,
    Semester,
    Subject,
    Timetable,
    TimetableEntry,
    User,
)
from app.dependencies import get_db
from app.main import app
from app.schemas.auth import AuthenticatedUser, Role

ADMIN_ID = "tt-admin-user"
FACULTY_OWNER = "tt-faculty-owner"
FACULTY_OTHER = "tt-faculty-other"
TIMETABLE_ID = "TT-REG"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def test_db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)

    TestingSessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with TestingSessionLocal() as db:
        db.add_all(
            [
                User(
                    user_id=ADMIN_ID,
                    email="tt-admin@rollcall.test",
                    role="ADMIN",
                    hashed_password=None,
                    is_active=1,
                    created_at=_utcnow_iso(),
                ),
                User(
                    user_id=FACULTY_OWNER,
                    email="tt-owner@rollcall.test",
                    role="FACULTY",
                    hashed_password=None,
                    is_active=1,
                    created_at=_utcnow_iso(),
                ),
                User(
                    user_id=FACULTY_OTHER,
                    email="tt-other@rollcall.test",
                    role="FACULTY",
                    hashed_password=None,
                    is_active=1,
                    created_at=_utcnow_iso(),
                ),
                College(
                    college_id="TTC",
                    name="TT College",
                    code="TTC",
                    created_at=_utcnow_iso(),
                ),
                Department(
                    dept_id="TTD",
                    college_id="TTC",
                    name="TT Department",
                    code="TTD",
                ),
                AcademicYear(
                    year_id="TTAY",
                    college_id="TTC",
                    year_label="2026",
                    start_date="2026-01-01",
                    end_date="2026-12-31",
                    is_active=1,
                ),
                Semester(
                    semester_id="TTSEM",
                    year_id="TTAY",
                    semester_label="Fall",
                    semester_number=5,
                    start_date="2026-01-01",
                    end_date="2026-12-31",
                    is_active=1,
                ),
                Section(
                    section_id="TTSEC",
                    dept_id="TTD",
                    semester_id="TTSEM",
                    section_label="A",
                    batch_size=60,
                ),
                Batch(
                    batch_id="TTBAT",
                    dept_id="TTD",
                    semester_id="TTSEM",
                    section_id="TTSEC",
                    batch_label="B1",
                    batch_type="theory",
                ),
                Subject(
                    subject_code="NET-SEC",
                    dept_id="TTD",
                    name="Network Security",
                    credits=3,
                    hours_per_week=3,
                    subject_type="theory",
                ),
                Subject(
                    subject_code="CRYPT",
                    dept_id="TTD",
                    name="Cryptography",
                    credits=3,
                    hours_per_week=3,
                    subject_type="theory",
                ),
                Room(room_id="TTROOM", name="TT Hall", capacity=60),
                Timetable(
                    timetable_id=TIMETABLE_ID,
                    dept_id="TTD",
                    semester_id="TTSEM",
                    section_id="TTSEC",
                    year_id="TTAY",
                    effective_from="2026-01-01",
                    effective_to=None,
                    revision_number=1,
                    is_active=1,
                    created_at=_utcnow_iso(),
                ),
                FacultySubject(
                    user_id=FACULTY_OWNER, subject_code="NET-SEC", dept_id="TTD"
                ),
                FacultySubject(
                    user_id=FACULTY_OTHER, subject_code="CRYPT", dept_id="TTD"
                ),
                TimetableEntry(
                    entry_id="TT-OWNED",
                    timetable_id=TIMETABLE_ID,
                    day_of_week="Monday",
                    period_number=1,
                    start_time="09:00",
                    end_time="10:00",
                    subject_code="NET-SEC",
                    room_id="TTROOM",
                    faculty_id=FACULTY_OWNER,
                    batch_id="TTBAT",
                    duration_minutes=60,
                ),
                TimetableEntry(
                    entry_id="TT-UNOWNED",
                    timetable_id=TIMETABLE_ID,
                    day_of_week="Tuesday",
                    period_number=1,
                    start_time="09:00",
                    end_time="10:00",
                    subject_code="NET-SEC",
                    room_id="TTROOM",
                    faculty_id=None,
                    batch_id="TTBAT",
                    duration_minutes=60,
                ),
            ]
        )
        db.commit()

    yield engine
    engine.dispose()


@pytest.fixture
def as_user():
    def _set(user: AuthenticatedUser | None) -> None:
        if user is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = lambda: user

    yield _set
    app.dependency_overrides.pop(get_current_user, None)


def _user(user_id: str, role: Role) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        email=f"{user_id}@rollcall.test",
        role=role,
        claims={"sub": user_id, "role": role.value},
    )


@pytest.fixture
def client(test_db_engine, as_user):
    TestingSessionLocal = sessionmaker(bind=test_db_engine, class_=Session, expire_on_commit=False)

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    as_user(_user(FACULTY_OWNER, Role.FACULTY))
    test_client = TestClient(app, raise_server_exceptions=False)
    yield test_client
    app.dependency_overrides.pop(get_db, None)


def _entry_payload(**overrides) -> dict:
    payload = {
        "timetable_id": TIMETABLE_ID,
        "day_of_week": "Wednesday",
        "period_number": 1,
        "start_time": "09:00",
        "end_time": "10:00",
        "subject_code": "NET-SEC",
        "room_id": "TTROOM",
    }
    payload.update(overrides)
    return payload


# ==============================================================================
# H-2: create
# ==============================================================================

def test_faculty_cannot_create_an_entry_for_another_faculty(client, as_user):
    as_user(_user(FACULTY_OWNER, Role.FACULTY))
    response = client.post(
        "/api/v1/timetable/entries",
        json=_entry_payload(faculty_id=FACULTY_OTHER),
    )
    assert response.status_code == 201, response.text
    assert response.json()["faculty_id"] == FACULTY_OWNER


def test_faculty_cannot_create_an_entry_for_an_unassigned_subject(client, as_user):
    as_user(_user(FACULTY_OWNER, Role.FACULTY))
    response = client.post(
        "/api/v1/timetable/entries",
        json=_entry_payload(subject_code="CRYPT"),
    )
    assert response.status_code == 403


# ==============================================================================
# H-2: update
# ==============================================================================

def test_faculty_cannot_update_another_faculty_entry(client, as_user):
    as_user(_user(FACULTY_OTHER, Role.FACULTY))
    response = client.put(
        "/api/v1/timetable/entries/TT-OWNED",
        json={"start_time": "11:00", "end_time": "12:00"},
    )
    assert response.status_code == 403


def test_faculty_cannot_update_an_unowned_entry(client, as_user):
    as_user(_user(FACULTY_OTHER, Role.FACULTY))
    response = client.put(
        "/api/v1/timetable/entries/TT-UNOWNED",
        json={"start_time": "11:00", "end_time": "12:00"},
    )
    assert response.status_code == 403


def test_faculty_cannot_move_an_owned_entry_to_an_unassigned_subject(client, as_user):
    as_user(_user(FACULTY_OWNER, Role.FACULTY))
    response = client.put(
        "/api/v1/timetable/entries/TT-OWNED",
        json={"subject_code": "CRYPT"},
    )
    assert response.status_code == 403


def test_faculty_cannot_reassign_an_owned_entry(client, as_user):
    as_user(_user(FACULTY_OWNER, Role.FACULTY))
    response = client.put(
        "/api/v1/timetable/entries/TT-OWNED",
        json={"faculty_id": FACULTY_OTHER},
    )
    # The reassignment is ignored: the entry keeps its owner.
    assert response.status_code == 200, response.text
    assert response.json()["faculty_id"] == FACULTY_OWNER


# ==============================================================================
# H-2: delete
# ==============================================================================

def test_faculty_cannot_delete_another_faculty_entry(client, as_user):
    as_user(_user(FACULTY_OTHER, Role.FACULTY))
    response = client.delete("/api/v1/timetable/entries/TT-OWNED")
    assert response.status_code == 403


def test_faculty_cannot_delete_an_unowned_entry(client, as_user):
    as_user(_user(FACULTY_OTHER, Role.FACULTY))
    response = client.delete("/api/v1/timetable/entries/TT-UNOWNED")
    assert response.status_code == 403


def test_owner_can_delete_their_own_entry(client, as_user):
    as_user(_user(FACULTY_OWNER, Role.FACULTY))
    response = client.delete("/api/v1/timetable/entries/TT-OWNED")
    assert response.status_code == 204


def test_admin_can_manage_any_entry(client, as_user):
    as_user(_user(ADMIN_ID, Role.ADMIN))
    response = client.put(
        "/api/v1/timetable/entries/TT-OWNED",
        json={"start_time": "13:00", "end_time": "14:00"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["start_time"] == "13:00"


# ==============================================================================
# The scoped subject lookup must not raise (regression for the missing import)
# ==============================================================================

def test_scoped_week_view_resolves_subject_codes(client, as_user):
    as_user(_user(FACULTY_OWNER, Role.FACULTY))
    response = client.get("/api/v1/timetable/week")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["has_timetable"] is True
    monday = next(day for day in body["days"] if day["day_of_week"] == "Monday")
    assert any(entry["entry_id"] == "TT-OWNED" for entry in monday["entries"])
