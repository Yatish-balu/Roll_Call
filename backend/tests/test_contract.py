"""API Contract Tests verifying response schemas against docs/API_CONTRACT.md (Prompt N18)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.routers.admin import get_admin_overview, get_audit_log, get_faculty_uploads
from app.routers.calendar import get_calendar_day, get_calendar_month
from app.routers.chat import chat_endpoint, ChatMessageRequest
from app.routers.defaulters import list_defaulters
from app.routers.sessions import get_session_attendance, list_sessions
from app.routers.students import get_student_ledger, lookup_students
from app.schemas.auth import AuthenticatedUser
from scripts.seed_demo import seed_demo_data


@pytest.fixture(scope="module")
def contract_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    seed_demo_data(db_session=db)
    try:
        yield db
    finally:
        db.close()


def test_contract_all_endpoints(contract_db: Session):
    admin = AuthenticatedUser(user_id="admin_root", email="admin@rollcall.internal", role="ADMIN")
    teacher = AuthenticatedUser(user_id="faculty_ds", email="faculty.ds@rollcall.internal", role="FACULTY")

    contract_results = []

    # 1. GET /api/sessions (Admin & Teacher)
    res_sess = list_sessions(limit=10, offset=0, current_user=admin, db=contract_db)
    assert "items" in res_sess
    assert "total" in res_sess
    assert len(res_sess["items"]) > 0
    item = res_sess["items"][0]
    expected_sess_fields = ["session_id", "date", "subject_code", "subject_name", "teacher_id", "created_at_utc", "editable", "locked"]
    for f in expected_sess_fields:
        assert f in item, f"Missing field {f} in GET /api/sessions"
    contract_results.append(("/api/sessions", "ADMIN", 200, "None"))

    # 2. GET /api/sessions/{id}/attendance
    res_att = get_session_attendance("SESS-DEMO-2H", current_user=teacher, db=contract_db)
    assert "session" in res_att
    assert "records" in res_att
    assert len(res_att["records"]) > 0
    rec = res_att["records"][0]
    for f in ["usn", "name", "status", "source", "confidence"]:
        assert f in rec, f"Missing field {f} in GET /api/sessions/{{id}}/attendance record"
    contract_results.append(("/api/sessions/{id}/attendance", "FACULTY", 200, "None"))

    # 3. POST /api/chat
    req = ChatMessageRequest(query="Mark USN 1MS21CS001 as Present for DIST-SYS today")
    res_chat = chat_endpoint(req, current_user=teacher, db=contract_db)
    assert "reply" in res_chat
    assert "needs_confirmation" in res_chat
    contract_results.append(("/api/chat", "FACULTY", 200, "None"))

    # 4. GET /api/admin/overview
    res_ov = get_admin_overview(current_user=admin, db=contract_db)
    for f in ["total_records", "present", "absent", "percentage", "branch_wise", "room_wise"]:
        assert f in res_ov, f"Missing field {f} in /api/admin/overview"
    contract_results.append(("/api/admin/overview", "ADMIN", 200, "None"))

    # 5. GET /api/admin/faculty-uploads
    res_fu = get_faculty_uploads(current_user=admin, db=contract_db)
    assert isinstance(res_fu, list)
    assert len(res_fu) > 0
    for f in ["teacher_id", "name", "last_upload_utc", "sessions_last_7_days", "sessions_this_semester"]:
        assert f in res_fu[0], f"Missing field {f} in /api/admin/faculty-uploads"
    contract_results.append(("/api/admin/faculty-uploads", "ADMIN", 200, "None"))

    # 6. GET /api/admin/audit-log
    res_al = get_audit_log(page=1, page_size=10, current_user=admin, db=contract_db)
    assert "total" in res_al
    assert "items" in res_al
    contract_results.append(("/api/admin/audit-log", "ADMIN", 200, "None"))

    # 7. GET /api/defaulters
    res_def = list_defaulters(threshold=75.0, current_user=admin, db=contract_db)
    assert isinstance(res_def, list)
    assert len(res_def) > 0
    for f in ["usn", "name", "branch", "attended", "conducted", "percent", "classes_needed"]:
        assert f in res_def[0], f"Missing field {f} in /api/defaulters"
    contract_results.append(("/api/defaulters", "ADMIN", 200, "None"))

    # 8. GET /api/students/lookup
    res_lu = lookup_students(q="Alice", current_user=teacher, db=contract_db)
    assert isinstance(res_lu, list)
    assert len(res_lu) > 0
    for f in ["usn", "name", "branch"]:
        assert f in res_lu[0], f"Missing field {f} in /api/students/lookup"
    contract_results.append(("/api/students/lookup", "FACULTY", 200, "None"))

    # 9. GET /api/students/{usn}/ledger
    res_led = get_student_ledger(usn="1MS21CS001", current_user=teacher, db=contract_db)
    for f in ["usn", "name", "branch", "percent", "band", "sessions"]:
        assert f in res_led, f"Missing field {f} in /api/students/{{usn}}/ledger"
    contract_results.append(("/api/students/{usn}/ledger", "FACULTY", 200, "None"))

    # 10. GET /api/calendar
    today_month = res_sess["items"][0]["date"][:7]
    res_cal = get_calendar_month(month=today_month, current_user=admin, db=contract_db)
    assert isinstance(res_cal, list)
    if res_cal:
        for f in ["date", "sessions", "present", "absent", "percent", "band"]:
            assert f in res_cal[0], f"Missing field {f} in /api/calendar"
    contract_results.append(("/api/calendar", "ADMIN", 200, "None"))

    # Print summary table
    print("\n--- API CONTRACT VERIFICATION MATRIX ---")
    print(f"{'Endpoint':<35} | {'Role':<8} | {'Status':<6} | {'Missing Fields'}")
    print("-" * 65)
    for ep, role, stat, missing in contract_results:
        print(f"{ep:<35} | {role:<8} | {stat:<6} | {missing}")

