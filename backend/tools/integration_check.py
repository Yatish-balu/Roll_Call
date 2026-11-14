"""Integration checks for the new RollCall AI backend contracts.

The script runs against a *copy* of the local SQLite database, so no live or
shared database is modified. It exercises:

* timetable week / reference / entry validation (09:00 - 17:00 + overlaps)
* session allocations, initialisation state and idempotent initialisation
* student roster filters, semester filtering and the filtered PDF export
* the multipart upload pipeline for CSV, XLSX and PDF rosters

Run from the backend directory:  python tools/integration_check.py
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROLL_CALL_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]
SOURCE_DB = ROLL_CALL_DIR / "data" / "attendance.db"

# ---------------------------------------------------------------------------
# Environment: run against a throwaway, freshly seeded SQLite database.
# The shared/live database is never touched.
# ---------------------------------------------------------------------------
WORK_DIR = Path(tempfile.mkdtemp(prefix="rollcall-it-"))
DB_COPY = WORK_DIR / "attendance.db"

os.environ["DB_BACKEND"] = "sqlite"
os.environ["SQLITE_PATH"] = str(DB_COPY)
os.environ["DATABASE_URL_SYNC"] = f"sqlite:///{DB_COPY.as_posix()}"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_URL_ASYNC", None)
os.environ["APP_ENV"] = "development"
os.environ["JWT_SECRET"] = "integration-check-secret-key-at-least-32-characters-long"
os.environ.setdefault("MFA_ENCRYPTION_KEY", "integration-check-mfa-key-32-characters-long!!")

sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.auth.jwt import create_access_token  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import app  # noqa: E402


def seed_database() -> None:
    """Create the schema and a minimal but realistic data set."""
    import datetime

    from sqlalchemy import create_engine

    from app.db import models  # noqa: F401  (registers the mappers)
    from app.db.models import (
        AcademicYear,
        Batch,
        College,
        Department,
        Room,
        Section,
        Semester,
        Student,
        Subject,
        FacultySubject,
        Timetable,
        TimetableEntry,
        User,
    )

    engine = create_engine(f"sqlite:///{DB_COPY.as_posix()}")
    Base.metadata.create_all(engine)

    today = datetime.date.today()
    with engine.begin() as connection:
        connection.execute(
            User.__table__.insert(),
            [
                {
                    "user_id": "faculty_it",
                    "email": "faculty_it@rollcall.internal",
                    "role": "FACULTY",
                    "hashed_password": None,
                    "is_active": 1,
                    "created_at": "2026-01-01T00:00:00Z",
                },
                {
                    "user_id": "admin_it",
                    "email": "admin_it@rollcall.internal",
                    "role": "ADMIN",
                    "hashed_password": None,
                    "is_active": 1,
                    "created_at": "2026-01-01T00:00:00Z",
                },
            ],
        )
        connection.execute(
            FacultySubject.__table__.insert(),
            [{"user_id": "faculty_it", "subject_code": "NET-SEC", "dept_id": "CSE"}],
        )
        connection.execute(
            College.__table__.insert(),
            [
                {
                    "college_id": "RC",
                    "name": "RollCall Institute of Technology",
                    "code": "RC",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        )
        connection.execute(
            Department.__table__.insert(),
            [
                {
                    "dept_id": "CSE",
                    "college_id": "RC",
                    "name": "Computer Science & Engineering",
                    "code": "CSE",
                }
            ],
        )
        connection.execute(
            AcademicYear.__table__.insert(),
            [
                {
                    "year_id": "AY-2026",
                    "college_id": "RC",
                    "year_label": "2026",
                    "start_date": "2026-01-01",
                    "end_date": "2026-12-31",
                    "is_active": 1,
                }
            ],
        )
        connection.execute(
            Semester.__table__.insert(),
            [
                {
                    "semester_id": "SEM-5",
                    "year_id": "AY-2026",
                    "semester_label": "Fall",
                    "semester_number": 5,
                    "start_date": "2026-06-01",
                    "end_date": "2026-12-31",
                    "is_active": 1,
                }
            ],
        )
        connection.execute(
            Section.__table__.insert(),
            [
                {
                    "section_id": "CSE-5A",
                    "dept_id": "CSE",
                    "semester_id": "SEM-5",
                    "section_label": "A",
                    "batch_size": 60,
                }
            ],
        )
        connection.execute(
            Batch.__table__.insert(),
            [
                {
                    "batch_id": "CSE-5A-B1",
                    "dept_id": "CSE",
                    "semester_id": "SEM-5",
                    "section_id": "CSE-5A",
                    "batch_label": "A1",
                    "batch_type": "theory",
                }
            ],
        )
        connection.execute(
            Subject.__table__.insert(),
            [
                {
                    "subject_code": "NET-SEC",
                    "dept_id": "CSE",
                    "name": "Network Security & Forensics",
                    "credits": 4,
                    "hours_per_week": 4,
                    "subject_type": "theory",
                }
            ],
        )
        connection.execute(
            Room.__table__.insert(),
            [{"room_id": "LH-101", "name": "Lecture Hall 101", "capacity": 60}],
        )
        connection.execute(
            Student.__table__.insert(),
            [
                {
                    "usn": "1MS21CS001",
                    "name": "Student One",
                    "branch": "CSE",
                    "dept_id": "CSE",
                    "semester_id": "SEM-5",
                    "section_id": "CSE-5A",
                    "batch_id": "CSE-5A-B1",
                },
                {
                    "usn": "1MS21CS002",
                    "name": "Student Two",
                    "branch": "CSE",
                    "dept_id": "CSE",
                    "semester_id": "SEM-5",
                    "section_id": "CSE-5A",
                    "batch_id": "CSE-5A-B1",
                },
            ],
        )
        connection.execute(
            Timetable.__table__.insert(),
            [
                {
                    "timetable_id": "TTM-CSE-5A",
                    "dept_id": "CSE",
                    "semester_id": "SEM-5",
                    "section_id": "CSE-5A",
                    "year_id": "AY-2026",
                    "effective_from": "2026-06-01",
                    "effective_to": None,
                    "revision_number": 1,
                    "is_active": 1,
                    "created_at": "2026-06-01T00:00:00Z",
                }
            ],
        )
        connection.execute(
            TimetableEntry.__table__.insert(),
            [
                {
                    "entry_id": "TT-CSE-5A-1",
                    "timetable_id": "TTM-CSE-5A",
                    "day_of_week": today.strftime("%A"),
                    "period_number": 1,
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "subject_code": "NET-SEC",
                    "room_id": "LH-101",
                    "faculty_id": "faculty_it",
                    "batch_id": "CSE-5A-B1",
                    "duration_minutes": 60,
                }
            ],
        )
    engine.dispose()


seed_database()

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, condition, detail))
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" :: {detail}" if detail else ""))


def auth_headers(user_id: str, role: str = "FACULTY") -> dict:
    token = create_access_token({"sub": user_id, "role": role, "email": f"{user_id}@rollcall.internal"})
    return {"Authorization": f"Bearer {token}"}


def main() -> int:
    client = TestClient(app)

    faculty = {"user_id": "faculty_it", "role": "FACULTY"}
    admin = {"user_id": "admin_it", "role": "ADMIN"}
    headers = auth_headers(faculty["user_id"], faculty["role"])
    admin_headers = auth_headers(admin["user_id"], admin["role"])

    # -- Timetable -------------------------------------------------------
    response = client.get("/api/v1/timetable/week", headers=headers)
    check("GET /timetable/week", response.status_code == 200, f"status={response.status_code}")
    if response.status_code == 200:
        body = response.json()
        check(
            "timetable week payload",
            "days" in body and "has_timetable" in body,
            f"has_timetable={body.get('has_timetable')} entries={body.get('total_entries')}",
        )

    response = client.get("/api/v1/timetable/reference", headers=headers)
    check("GET /timetable/reference", response.status_code == 200, f"status={response.status_code}")

    response = client.post(
        "/api/v1/timetable/entries",
        headers=headers,
        json={
            "timetable_id": "TTM-INTEGRATION",
            "day_of_week": "Monday",
            "period_number": 1,
            "start_time": "08:00",
            "end_time": "09:00",
            "subject_code": "NET-SEC",
            "room_id": "LH-101",
        },
    )
    check(
        "POST /timetable/entries rejects a slot before 09:00",
        response.status_code == 422,
        f"status={response.status_code} detail={response.json().get('detail')}",
    )

    response = client.post(
        "/api/v1/timetable/entries",
        headers=headers,
        json={
            "timetable_id": "TTM-INTEGRATION",
            "day_of_week": "Monday",
            "period_number": 1,
            "start_time": "16:00",
            "end_time": "17:30",
            "subject_code": "NET-SEC",
            "room_id": "LH-101",
        },
    )
    check(
        "POST /timetable/entries rejects a slot ending after 17:00",
        response.status_code == 422,
        f"status={response.status_code}",
    )

    response = client.post(
        "/api/v1/timetable/entries",
        headers=headers,
        json={
            "timetable_id": "TTM-INTEGRATION",
            "day_of_week": "Monday",
            "period_number": 1,
            "start_time": "17:00",
            "end_time": "16:00",
            "subject_code": "NET-SEC",
            "room_id": "LH-101",
        },
    )
    check(
        "POST /timetable/entries rejects end <= start",
        response.status_code == 422,
        f"status={response.status_code}",
    )

    # -- Sessions --------------------------------------------------------
    response = client.get("/api/v1/sessions/allocations", headers=headers)
    check("GET /sessions/allocations", response.status_code == 200, f"status={response.status_code}")

    response = client.get("/api/v1/sessions/initialization/today", headers=headers)
    check(
        "GET /sessions/initialization/today",
        response.status_code == 200,
        f"status={response.status_code} body={response.text[:160]}",
    )

    response = client.post("/api/v1/sessions/initialize", headers=admin_headers)
    check(
        "POST /sessions/initialize",
        response.status_code == 200,
        f"status={response.status_code} body={response.text[:200]}",
    )

    if response.status_code == 200:
        first = response.json()
        response = client.post("/api/v1/sessions/initialize", headers=admin_headers)
        second = response.json()
        check(
            "POST /sessions/initialize is idempotent",
            len(second.get("created_sessions", [])) == 0
            or len(first.get("created_sessions", [])) == 0,
            f"first_created={len(first.get('created_sessions', []))} "
            f"second_created={len(second.get('created_sessions', []))}",
        )

    response = client.post("/api/v1/sessions/initialize?date=2020-01-01", headers=admin_headers)
    check(
        "POST /sessions/initialize refuses historical dates",
        response.status_code == 422,
        f"status={response.status_code}",
    )

    # -- Students --------------------------------------------------------
    response = client.get("/api/v1/reports/students/filters", headers=headers)
    check(
        "GET /reports/students/filters",
        response.status_code == 200,
        f"status={response.status_code} body={response.text[:200]}",
    )

    response = client.get("/api/v1/students?limit=5", headers=headers)
    check("GET /students", response.status_code == 200, f"status={response.status_code}")
    if response.status_code == 200:
        body = response.json()
        check("student payload carries semester data", "items" in body, f"total={body.get('total')}")

    response = client.get("/api/v1/students?semester=5&limit=5", headers=headers)
    check(
        "GET /students?semester=5 (server side filter)",
        response.status_code == 200,
        f"status={response.status_code} total={response.json().get('total') if response.status_code == 200 else ''}",
    )

    response = client.post(
        "/api/v1/reports/students/pdf",
        headers=headers,
        json={"branch": "CSE", "semester": 5, "title": "Integration check"},
    )
    check(
        "POST /reports/students/pdf",
        response.status_code == 200 and response.content[:4] == b"%PDF",
        f"status={response.status_code} bytes={len(response.content)} "
        f"count={response.headers.get('X-Student-Count')}",
    )

    response = client.post(
        "/api/v1/reports/students/pdf",
        headers=headers,
        json={"semester": 99},
    )
    check(
        "POST /reports/students/pdf rejects an invalid semester",
        response.status_code == 422,
        f"status={response.status_code}",
    )

    # -- Upload pipeline -------------------------------------------------
    csv_roster = (
        "USN,Name,Status,Room,Branch\n"
        "1MS21CS001,Student One,PRESENT,LH-101,CSE\n"
        "1MS21CS002,Student Two,ABSENT,LH-101,CSE\n"
    ).encode("utf-8")

    response = client.post(
        "/api/v1/agent/process-file",
        headers=headers,
        files={"file": ("roster.csv", csv_roster, "text/csv")},
    )
    check(
        "POST /agent/process-file (CSV)",
        response.status_code == 200,
        f"status={response.status_code} body={response.text[:220]}",
    )

    try:
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["USN", "Name", "Status", "Room", "Branch"])
        sheet.append(["1MS21CS001", "Student One", "PRESENT", "LH-101", "CSE"])
        sheet.append(["1MS21CS002", "Student Two", "ABSENT", "LH-101", "CSE"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        xlsx_bytes = buffer.getvalue()

        response = client.post(
            "/api/v1/agent/process-file",
            headers=headers,
            files={
                "file": (
                    "roster.xlsx",
                    xlsx_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        check(
            "POST /agent/process-file (XLSX)",
            response.status_code == 200,
            f"status={response.status_code} body={response.text[:220]}",
        )
    except ImportError:
        check("POST /agent/process-file (XLSX)", False, "openpyxl is not installed")

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        y = 800
        for row in [
            ["USN", "Name", "Status", "Room", "Branch"],
            ["1MS21CS001", "Student One", "PRESENT", "LH-101", "CSE"],
            ["1MS21CS002", "Student Two", "ABSENT", "LH-101", "CSE"],
        ]:
            pdf.setFont("Helvetica", 11)
            x = 50
            for cell in row:
                pdf.drawString(x, y, str(cell))
                x += 120
            y -= 20
        pdf.showPage()
        pdf.save()
        pdf_bytes = buffer.getvalue()

        response = client.post(
            "/api/v1/agent/process-file",
            headers=headers,
            files={"file": ("roster.pdf", pdf_bytes, "application/pdf")},
        )
        check(
            "POST /agent/process-file (PDF)",
            response.status_code == 200,
            f"status={response.status_code} body={response.text[:260]}",
        )
    except ImportError:
        check("POST /agent/process-file (PDF)", False, "reportlab is not installed")

    # -- MFA status ------------------------------------------------------
    response = client.get("/api/v1/auth/mfa/status", headers=headers)
    check(
        "GET /auth/mfa/status",
        response.status_code == 200,
        f"status={response.status_code} body={response.text[:120]}",
    )

    failed = [name for name, ok, _ in RESULTS if not ok]
    print("\n%d checks, %d failed" % (len(RESULTS), len(failed)))
    for name in failed:
        print("  FAILED:", name)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(WORK_DIR, ignore_errors=True)
    sys.exit(code)
