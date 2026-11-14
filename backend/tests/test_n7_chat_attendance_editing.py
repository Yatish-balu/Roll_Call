"""N7 regression tests: two-step AI chat attendance editing.

Step A (proposal)  -> pending confirmation, attendance untouched.
Step B (confirmation) -> stored proposal applied exactly once, audited atomically.

These tests exercise the real HTTP API with real JWT verification and inspect
the database directly to prove that nothing is written before the confirmation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session as OrmSession, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.jwt import create_access_token
from app.db.base import Base
from app.db import crud
from app.db.models import (
    Attendance,
    AuditLog,
    PendingEdit,
    Room,
    Session as DbSession,
    Student,
    TeacherSubject,
    User,
)
from app.dependencies import get_db
from app.main import app

pytestmark = pytest.mark.no_auth_override

TEST_SECRET = "test-secret-key-for-n7-chat-editing-at-least-32-chars"

PROPOSE_URL = "/api/v1/agent/attendance/propose"
CONFIRM_URL = "/api/v1/agent/attendance/confirm"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    return create_access_token(
        {
            "sub": user_id,
            "email": f"{user_id}@rollcall.edu",
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        expires_delta=timedelta(hours=1),
        secret=TEST_SECRET,
    )


def _headers(user_id: str, role: str) -> dict:
    return {"Authorization": f"Bearer {_token(user_id, role)}"}


@pytest.fixture
def api(monkeypatch):
    """App client over an in-memory database with real JWT verification."""
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_SECRET)

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=OrmSession, expire_on_commit=False)

    with factory() as db:
        for uid, role in (
            ("admin_root", "ADMIN"),
            ("faculty_ds", "FACULTY"),
            ("faculty_ml", "FACULTY"),
            ("faculty_coord", "FACULTY"),
            ("viewer_ro", "VIEWER"),
        ):
            db.add(
                User(
                    user_id=uid,
                    email=f"{uid}@rollcall.edu",
                    role=role,
                    hashed_password=None,
                    is_active=1,
                    created_at="2020-01-01T00:00:00Z",
                )
            )
        # The migration-0002 sentinel for sessions that predate ownership.
        db.add(
            User(
                user_id="legacy",
                email="legacy@rollcall.edu",
                role="ADMIN",
                hashed_password=None,
                is_active=0,
                created_at="2020-01-01T00:00:00Z",
            )
        )
        db.add(Room(room_id="LH-101", name="Lecture Hall 101"))
        for usn, name in (
            ("1MS21CS001", "Alice Smith"),
            ("1MS21CS002", "Bob Jones"),
            ("1MS21CS003", "Carol White"),
            ("1MS21CS004", "Dan Black"),
        ):
            db.add(Student(usn=usn, name=name, branch="CSE"))

        # (a) owned by faculty_ds, old and completed
        db.add(
            DbSession(
                session_id="SESS-OWNED",
                date="2020-01-01",
                subject="Distributed Systems",
                created_at="2020-01-01T09:00:00Z",
                teacher_id="faculty_ds",
                subject_code="DIST-SYS",
                lifecycle_status="COMPLETED",
            )
        )
        # (b) legacy/unowned session, authorized through the ML subject mapping
        db.add(
            DbSession(
                session_id="SESS-LEGACY-ML",
                date="2020-02-02",
                subject="Machine Learning",
                created_at="2020-02-02T09:00:00Z",
                teacher_id="legacy",
                subject_code="ML",
            )
        )
        # (c) unowned session authorized through the coordinator
        db.add(
            DbSession(
                session_id="SESS-COORD",
                date="2020-03-03",
                subject="Computer Networks",
                created_at="2020-03-03T09:00:00Z",
                teacher_id=None,
                subject_code=None,
                coordinator_faculty_id="faculty_coord",
            )
        )
        # (d) owned by faculty_ml (foreign for faculty_ds)
        db.add(
            DbSession(
                session_id="SESS-FOREIGN",
                date="2020-04-04",
                subject="Machine Learning Lab",
                created_at="2020-04-04T09:00:00Z",
                teacher_id="faculty_ml",
                subject_code="ML",
            )
        )

        db.add(TeacherSubject(user_id="faculty_ds", subject_code="DIST-SYS"))
        db.add(TeacherSubject(user_id="faculty_ml", subject_code="ML"))

        for session_id, usn in (
            ("SESS-OWNED", "1MS21CS001"),
            ("SESS-LEGACY-ML", "1MS21CS002"),
            ("SESS-COORD", "1MS21CS003"),
            ("SESS-FOREIGN", "1MS21CS004"),
        ):
            db.add(
                Attendance(
                    attendance_id=f"ATT-{session_id}-{usn}",
                    session_id=session_id,
                    usn=usn,
                    room_id="LH-101",
                    status="PRESENT",
                    source="camera",
                    confidence=0.95,
                    recorded_at="2020-01-01T09:00:00Z",
                )
            )
        db.commit()

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _attendance_status(factory, session_id: str, usn: str):
    with factory() as db:
        row = db.execute(
            select(Attendance).where(
                Attendance.session_id == session_id,
                Attendance.usn == usn,
            )
        ).scalars().first()
        return row.status if row is not None else None


def _pending_edits(factory):
    table = PendingEdit.__table__
    with factory() as db:
        return [
            dict(row)
            for row in db.execute(select(table)).mappings().all()
        ]


def _audit_rows(factory, **filters):
    table = AuditLog.__table__
    with factory() as db:
        stmt = select(table).order_by(table.c.log_id)
        for column, value in filters.items():
            stmt = stmt.where(table.c[column] == value)
        return [dict(row) for row in db.execute(stmt).mappings().all()]


# ---------------------------------------------------------------------------
# Step A - proposal
# ---------------------------------------------------------------------------

def test_proposal_creates_pending_edit_and_leaves_attendance_untouched(api):
    client, factory = api
    res = client.post(
        PROPOSE_URL,
        json={"session_id": "SESS-OWNED", "usn": "1MS21CS001", "new_status": "ABSENT"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    payload = res.json()

    assert payload["status"] == "proposed"
    assert payload["needs_confirmation"] is True
    assert payload["confirmation_id"]
    assert payload["expires_at"]
    assert payload["current_status"] == "PRESENT"
    assert payload["proposed_status"] == "ABSENT"
    assert payload["student"]["usn"] == "1MS21CS001"
    assert payload["student"]["name"] == "Alice Smith"
    assert payload["session"]["session_id"] == "SESS-OWNED"
    assert payload["session"]["date"] == "2020-01-01"

    # The confirmation card payload Antigravity renders.
    card = payload["confirmation_request"]
    assert card["needed"] is True
    assert card["question"]
    row = card["affected_rows"][0]
    assert row["usn"] == "1MS21CS001"
    assert row["student_name"] == "Alice Smith"
    assert row["current_status"] == "PRESENT"
    assert row["proposed_status"] == "ABSENT"
    assert row["confirmation_id"] == payload["confirmation_id"]

    # A pending edit exists, bound to the requesting user.
    pendings = _pending_edits(factory)
    assert len(pendings) == 1
    pending = pendings[0]
    assert pending["edit_id"] == payload["confirmation_id"]
    assert pending["user_id"] == "faculty_ds"
    assert pending["session_id"] == "SESS-OWNED"
    assert pending["usn"] == "1MS21CS001"
    assert pending["old_status"] == "PRESENT"
    assert pending["new_status"] == "ABSENT"
    assert pending["consumed"] == 0

    # CRITICAL: attendance is unchanged and no success audit entry exists.
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"
    assert _audit_rows(factory) == []


def test_proposal_from_natural_language_request(api):
    client, factory = api
    res = client.post(
        PROPOSE_URL,
        json={"query": "mark 1MS21CS001 absent in SESS-OWNED"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["status"] == "proposed"
    assert payload["session"]["session_id"] == "SESS-OWNED"
    assert payload["student"]["usn"] == "1MS21CS001"
    assert payload["proposed_status"] == "ABSENT"
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"


def test_proposal_is_bound_to_the_requesting_user(api):
    client, factory = api
    res = client.post(
        PROPOSE_URL,
        json={"session_id": "SESS-LEGACY-ML", "usn": "1MS21CS002", "new_status": "PENDING"},
        headers=_headers("faculty_ml", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    pendings = _pending_edits(factory)
    assert len(pendings) == 1
    assert pendings[0]["user_id"] == "faculty_ml"


def test_proposal_expiry_is_five_minutes(api):
    client, factory = api
    res = client.post(
        PROPOSE_URL,
        json={"session_id": "SESS-OWNED", "usn": "1MS21CS001", "new_status": "ABSENT"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    pending = _pending_edits(factory)[0]
    created = datetime.strptime(pending["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    expires = datetime.strptime(pending["expires_at"], "%Y-%m-%dT%H:%M:%SZ")
    assert expires - created == timedelta(minutes=5)
    assert res.json()["expires_in_seconds"] == 300


def test_proposal_by_unauthorized_faculty_is_forbidden(api):
    client, factory = api
    res = client.post(
        PROPOSE_URL,
        json={"session_id": "SESS-OWNED", "usn": "1MS21CS001", "new_status": "ABSENT"},
        headers=_headers("faculty_ml", "FACULTY"),
    )
    assert res.status_code == 403, res.text
    assert _pending_edits(factory) == []
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"
    assert _audit_rows(factory) == []


def test_proposal_for_unknown_session_returns_404(api):
    client, factory = api
    res = client.post(
        PROPOSE_URL,
        json={"session_id": "SESS-NOPE", "usn": "1MS21CS001", "new_status": "ABSENT"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 404, res.text
    assert _pending_edits(factory) == []


def test_proposal_for_unknown_student_returns_404(api):
    client, factory = api
    res = client.post(
        PROPOSE_URL,
        json={"session_id": "SESS-OWNED", "usn": "1MS21CS999", "new_status": "ABSENT"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 404, res.text
    assert _pending_edits(factory) == []


def test_proposal_with_invalid_status_returns_422(api):
    client, factory = api
    res = client.post(
        PROPOSE_URL,
        json={"session_id": "SESS-OWNED", "usn": "1MS21CS001", "new_status": "MAYBE"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 422, res.text
    assert _pending_edits(factory) == []
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"


def test_ambiguous_proposal_requests_clarification(api):
    client, factory = api
    res = client.post(
        PROPOSE_URL,
        json={"query": "please mark the student absent"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["status"] == "clarification_required"
    assert payload["needs_confirmation"] is False
    assert payload["confirmation_id"] is None
    assert payload["clarification"]["question"]
    # No ambiguous pending edit is created and attendance is untouched.
    assert _pending_edits(factory) == []
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"


def test_viewer_cannot_propose_an_attendance_change(api):
    client, factory = api
    res = client.post(
        PROPOSE_URL,
        json={"session_id": "SESS-OWNED", "usn": "1MS21CS001", "new_status": "ABSENT"},
        headers=_headers("viewer_ro", "VIEWER"),
    )
    assert res.status_code == 403, res.text
    assert _pending_edits(factory) == []


def test_proposal_via_subject_mapping_is_allowed(api):
    """A legacy session is proposable through the exact subject-code mapping."""
    client, factory = api
    res = client.post(
        PROPOSE_URL,
        json={"session_id": "SESS-LEGACY-ML", "usn": "1MS21CS002", "new_status": "PENDING"},
        headers=_headers("faculty_ml", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    assert _pending_edits(factory)[0]["user_id"] == "faculty_ml"


def test_proposal_via_coordinator_is_allowed(api):
    client, factory = api
    res = client.post(
        PROPOSE_URL,
        json={"session_id": "SESS-COORD", "usn": "1MS21CS003", "new_status": "ABSENT"},
        headers=_headers("faculty_coord", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    assert _pending_edits(factory)[0]["user_id"] == "faculty_coord"


# ---------------------------------------------------------------------------
# Step B - confirmation
# ---------------------------------------------------------------------------

def _propose(client, session_id="SESS-OWNED", usn="1MS21CS001", status="ABSENT", user="faculty_ds", role="FACULTY"):
    res = client.post(
        PROPOSE_URL,
        json={"session_id": session_id, "usn": usn, "new_status": status},
        headers=_headers(user, role),
    )
    assert res.status_code == 200, res.text
    return res.json()["confirmation_id"]


def test_confirmation_applies_the_stored_proposal_and_audits_it(api):
    client, factory = api
    confirmation_id = _propose(client)

    res = client.post(
        CONFIRM_URL,
        json={"confirmation_id": confirmation_id},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["success"] is True
    assert payload["usn"] == "1MS21CS001"
    assert payload["old_status"] == "PRESENT"
    assert payload["new_status"] == "ABSENT"

    # The stored proposal was applied.
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "ABSENT"

    # Exactly one audit record for the student.
    rows = _audit_rows(factory, action="ATTENDANCE_EDIT")
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["actor_id"] == "faculty_ds"
    assert row["actor_role"] == "FACULTY"
    assert row["session_id"] == "SESS-OWNED"
    assert row["usn"] == "1MS21CS001"
    assert row["old_value"] == "PRESENT"
    assert row["new_value"] == "ABSENT"
    assert row["timestamp"].endswith("Z")

    # The pending confirmation is consumed.
    pending = _pending_edits(factory)[0]
    assert pending["consumed"] == 1


def test_another_user_cannot_confirm_someone_elses_proposal(api):
    client, factory = api
    confirmation_id = _propose(client)

    res = client.post(
        CONFIRM_URL,
        json={"confirmation_id": confirmation_id},
        headers=_headers("faculty_ml", "FACULTY"),
    )
    # Not found: the response must not reveal that another user's proposal exists.
    assert res.status_code == 404, res.text
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"
    assert _audit_rows(factory) == []
    assert _pending_edits(factory)[0]["consumed"] == 0


def test_expired_confirmation_returns_410(api):
    client, factory = api
    confirmation_id = _propose(client)

    with factory() as db:
        db.execute(
            text("UPDATE pending_edits SET expires_at = '2000-01-01T00:00:00Z' WHERE edit_id = :eid"),
            {"eid": confirmation_id},
        )
        db.commit()

    res = client.post(
        CONFIRM_URL,
        json={"confirmation_id": confirmation_id},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 410, res.text
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"
    assert _audit_rows(factory) == []


def test_missing_confirmation_id_is_rejected(api):
    client, _ = api
    res = client.post(CONFIRM_URL, json={}, headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 422, res.text


def test_unknown_confirmation_returns_404(api):
    client, factory = api
    res = client.post(
        CONFIRM_URL,
        json={"confirmation_id": "does-not-exist"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 404, res.text
    assert _audit_rows(factory) == []


def test_already_consumed_confirmation_returns_409(api):
    client, factory = api
    confirmation_id = _propose(client)

    first = client.post(
        CONFIRM_URL,
        json={"confirmation_id": confirmation_id},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert first.status_code == 200, first.text

    second = client.post(
        CONFIRM_URL,
        json={"confirmation_id": confirmation_id},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert second.status_code == 409, second.text
    # The change was applied exactly once and audited exactly once.
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "ABSENT"
    assert len(_audit_rows(factory, action="ATTENDANCE_EDIT")) == 1


def test_client_supplied_overrides_are_ignored(api):
    """A client cannot change the proposed student/session/status."""
    client, factory = api
    confirmation_id = _propose(client, session_id="SESS-OWNED", usn="1MS21CS001", status="ABSENT")

    res = client.post(
        CONFIRM_URL,
        json={
            "confirmation_id": confirmation_id,
            "usn": "1MS21CS004",
            "session_id": "SESS-FOREIGN",
            "new_status": "PRESENT",
            "actor_id": "admin_root",
            "role": "ADMIN",
        },
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    # The stored proposal was applied, not the client-supplied values.
    assert payload["usn"] == "1MS21CS001"
    assert payload["session_id"] == "SESS-OWNED"
    assert payload["new_status"] == "ABSENT"
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "ABSENT"
    assert _attendance_status(factory, "SESS-FOREIGN", "1MS21CS004") == "PRESENT"
    rows = _audit_rows(factory, action="ATTENDANCE_EDIT")
    assert len(rows) == 1
    assert rows[0]["actor_id"] == "faculty_ds"
    assert rows[0]["usn"] == "1MS21CS001"


def test_authorization_is_revalidated_at_confirmation_time(api):
    """Access revoked between proposal and confirmation blocks the change."""
    client, factory = api
    confirmation_id = _propose(client)

    # The session is re-attributed to another teacher: the original proposer
    # is no longer authorized.
    with factory() as db:
        db.execute(
            text("UPDATE sessions SET teacher_id = 'faculty_ml' WHERE session_id = 'SESS-OWNED'")
        )
        db.commit()

    res = client.post(
        CONFIRM_URL,
        json={"confirmation_id": confirmation_id},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 403, res.text
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"
    assert _audit_rows(factory) == []
    assert _pending_edits(factory)[0]["consumed"] == 0


def test_failed_audit_insertion_rolls_back_the_confirmation(api, monkeypatch):
    client, factory = api
    confirmation_id = _propose(client)

    def boom(*args, **kwargs):
        raise RuntimeError("audit backend unavailable")

    monkeypatch.setattr(crud, "create_audit_entry", boom)

    res = client.post(
        CONFIRM_URL,
        json={"confirmation_id": confirmation_id},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code >= 500, res.text

    monkeypatch.undo()
    # Attendance unchanged, no audit row, and the confirmation was not consumed.
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"
    assert _audit_rows(factory) == []
    assert _pending_edits(factory)[0]["consumed"] == 0


def test_viewer_cannot_confirm(api):
    client, factory = api
    confirmation_id = _propose(client)
    res = client.post(
        CONFIRM_URL,
        json={"confirmation_id": confirmation_id},
        headers=_headers("viewer_ro", "VIEWER"),
    )
    assert res.status_code == 403, res.text
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"


def test_admin_can_propose_and_confirm(api):
    client, factory = api
    confirmation_id = _propose(client, session_id="SESS-FOREIGN", usn="1MS21CS004", user="admin_root", role="ADMIN")
    res = client.post(
        CONFIRM_URL,
        json={"confirmation_id": confirmation_id},
        headers=_headers("admin_root", "ADMIN"),
    )
    assert res.status_code == 200, res.text
    rows = _audit_rows(factory, action="ATTENDANCE_EDIT")
    assert len(rows) == 1
    assert rows[0]["actor_role"] == "ADMIN"


def test_confirmation_of_a_session_the_user_cannot_edit_is_forbidden(api):
    """A proposal that was legitimate cannot be confirmed by an unauthorized user."""
    client, factory = api
    # faculty_ml proposes on a legacy session through the ML mapping.
    confirmation_id = _propose(
        client, session_id="SESS-LEGACY-ML", usn="1MS21CS002", user="faculty_ml"
    )
    # The mapping is revoked before the confirmation.
    with factory() as db:
        db.execute(text("DELETE FROM faculty_subjects WHERE user_id = 'faculty_ml'"))
        db.commit()

    res = client.post(
        CONFIRM_URL,
        json={"confirmation_id": confirmation_id},
        headers=_headers("faculty_ml", "FACULTY"),
    )
    assert res.status_code == 403, res.text
    assert _attendance_status(factory, "SESS-LEGACY-ML", "1MS21CS002") == "PRESENT"
    assert _audit_rows(factory) == []


# ---------------------------------------------------------------------------
# Full HTTP workflow
# ---------------------------------------------------------------------------

def test_full_propose_confirm_workflow(api):
    """1-8: the complete two-step workflow over real HTTP."""
    client, factory = api

    # 1-2. Authenticate as faculty and submit an attendance-edit request.
    res = client.post(
        PROPOSE_URL,
        json={
            "query": "mark 1MS21CS001 absent for SESS-OWNED",
            "session_id": "SESS-OWNED",
            "usn": "1MS21CS001",
            "new_status": "ABSENT",
        },
        headers=_headers("faculty_ds", "FACULTY"),
    )
    # 3. Receive a proposal and a confirmation id.
    assert res.status_code == 200, res.text
    proposal = res.json()
    assert proposal["status"] == "proposed"
    confirmation_id = proposal["confirmation_id"]
    assert confirmation_id

    # 4. Attendance is unchanged before the confirmation.
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "PRESENT"
    assert _audit_rows(factory) == []

    # 5. Confirm using the confirmation id.
    confirmed = client.post(
        CONFIRM_URL,
        json={"confirmation_id": confirmation_id},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert confirmed.status_code == 200, confirmed.text

    # 6. The stored proposed status was applied.
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "ABSENT"

    # 7. The audit record was created.
    rows = _audit_rows(factory, action="ATTENDANCE_EDIT")
    assert len(rows) == 1
    assert rows[0]["actor_id"] == "faculty_ds"
    assert rows[0]["actor_role"] == "FACULTY"
    assert rows[0]["old_value"] == "PRESENT"
    assert rows[0]["new_value"] == "ABSENT"

    # 8. A second confirmation is rejected.
    replay = client.post(
        CONFIRM_URL,
        json={"confirmation_id": confirmation_id},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert replay.status_code == 409, replay.text
    assert len(_audit_rows(factory, action="ATTENDANCE_EDIT")) == 1


def test_legacy_api_mount_exposes_the_same_workflow(api):
    """The legacy /api mount serves the identical handlers."""
    client, factory = api
    res = client.post(
        "/api/agent/attendance/propose",
        json={"session_id": "SESS-OWNED", "usn": "1MS21CS001", "new_status": "ABSENT"},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert res.status_code == 200, res.text
    confirmation_id = res.json()["confirmation_id"]
    confirmed = client.post(
        "/api/agent/attendance/confirm",
        json={"confirmation_id": confirmation_id},
        headers=_headers("faculty_ds", "FACULTY"),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert _attendance_status(factory, "SESS-OWNED", "1MS21CS001") == "ABSENT"
