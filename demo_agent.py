"""Interactive / CLI demonstration for RollCall AI Tool-Calling Agent.

Demonstrates:
1. CSV Input -> Read -> Validate -> Summarise.
2. Photo Input -> Read -> Validate -> Summarise.
3. Safe Database Question (with exact anti-hallucination answers).
4. Validation / Confidence Guardrail triggering structured confirmation request.
5. Export to PDF and Excel with verification.
"""

from pathlib import Path
import sqlite3
import pandas as pd

from app.agent import AttendanceAgent
from app.db.schema import init_db
from app.db.crud import insert_student, insert_room, insert_session, insert_attendance
from tools.read_photo_tool import PhotoRow, PhotoExtractionResult, ExtractionSource
from unittest.mock import patch


def main():
    print("=" * 70)
    print("RollCall AI Attendance Agent - Phase 2 (Prompt 5) CLI Demonstration")
    print("=" * 70)

    # 1. Setup in-memory test database
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    insert_student(conn, usn="1MS21CS001", name="Alice Smith", branch="CSE")
    insert_student(conn, usn="1MS21CS002", name="Bob Jones", branch="CSE")
    insert_student(conn, usn="1MS21IS001", name="Charlie Brown", branch="ISE")
    insert_room(conn, room_id="LH-101", name="Lecture Hall 101")
    insert_session(conn, session_id="SESS-20261025-01", date="2026-10-25", subject="Computer Networks")
    insert_attendance(conn, session_id="SESS-20261025-01", usn="1MS21CS001", room_id="LH-101", status="PRESENT", source="csv", confidence=1.0)
    insert_attendance(conn, session_id="SESS-20261025-01", usn="1MS21CS002", room_id="LH-101", status="ABSENT", source="csv", confidence=1.0)

    agent = AttendanceAgent(db_target=conn)

    demo_dir = Path("data/demo")
    demo_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------------
    # Scenario 1: Clean CSV Processing & Summarisation
    # ------------------------------------------------------------------------
    print("\n--- Scenario 1: CSV Input Processing ---")
    clean_csv_path = demo_dir / "clean_demo.csv"
    clean_csv_path.write_text(
        "usn,name,branch,room_id,status\n"
        "1MS21CS001,Alice Smith,CSE,LH-101,PRESENT\n"
        "1MS21CS002,Bob Jones,CSE,LH-101,ABSENT\n"
        "1MS21IS001,Charlie Brown,ISE,LH-101,PRESENT\n"
    )

    resp1 = agent.process_request("Process attendance sheet", file_path=clean_csv_path)
    print(f"Success: {resp1.success}")
    print(f"Message: {resp1.message}")
    print(f"Needs Confirmation: {resp1.needs_confirmation}")
    print("Tools Invoked:")
    for call in resp1.tool_calls:
        print(f"  - {call['tool_name']} ({call['duration_seconds']}s): {call['result_summary']}")

    # ------------------------------------------------------------------------
    # Scenario 2: Photo Input Processing
    # ------------------------------------------------------------------------
    print("\n--- Scenario 2: Photo Input Processing ---")
    dummy_img = demo_dir / "sample_attendance.png"
    dummy_img.write_bytes(b"dummy image data")

    mock_rows = [
        PhotoRow(usn="1MS21CS001", name="Alice Smith", status="PRESENT", confidence=0.92, source=ExtractionSource.LLM),
        PhotoRow(usn="1MS21CS002", name="Bob Jones", status="ABSENT", confidence=0.88, source=ExtractionSource.LLM),
    ]
    mock_res = PhotoExtractionResult(image_path=str(dummy_img), rows=mock_rows, source=ExtractionSource.LLM)

    with patch.object(agent.registry, "execute", wraps=agent.registry.execute) as mock_exec:
        def side_effect(name, **kwargs):
            if name == "read_photo_tool":
                agent.logger.log(kwargs.get("request_id", ""), name, kwargs, True, "Mock photo extraction", 0.05)
                return mock_res
            return agent.registry.tools[name].handler(**kwargs)
        mock_exec.side_effect = side_effect
        resp2 = agent.process_request("Process photo for room LH-101", file_path=dummy_img, default_room="LH-101")

    print(f"Success: {resp2.success}")
    print(f"Message: {resp2.message}")
    print("Tools Invoked:")
    for call in resp2.tool_calls:
        print(f"  - {call['tool_name']}: {call['result_summary']}")

    # ------------------------------------------------------------------------
    # Scenario 3: Database Query (Safe & Anti-Hallucination)
    # ------------------------------------------------------------------------
    print("\n--- Scenario 3: Database Query ---")
    resp3_a = agent.process_request("Who was absent in session SESS-20261025-01?")
    print(f"Query: 'Who was absent in session SESS-20261025-01?'")
    print(f"Result: {resp3_a.message}")

    resp3_b = agent.process_request("Show absentees for session SESS-NON-EXISTENT")
    print(f"Query: 'Show absentees for session SESS-NON-EXISTENT'")
    print(f"Result (Anti-hallucination): {resp3_b.message}")

    # ------------------------------------------------------------------------
    # Scenario 4: Validation Guardrail & Structured Confirmation Request
    # ------------------------------------------------------------------------
    print("\n--- Scenario 4: Validation Error / Guardrail Confirmation ---")
    bad_csv_path = demo_dir / "bad_demo.csv"
    bad_csv_path.write_text(
        "usn,name,branch,room_id,status\n"
        "1MS21CS001,Alice Smith,CSE,LH-101,PRESENT\n"
        "1MS21CS001,Alice Smith,CSE,LH-101,ABSENT\n"  # Duplicate conflicting
    )
    resp4 = agent.process_request("Process unverified attendance", file_path=bad_csv_path)
    print(f"Success: {resp4.success}")
    print(f"Needs Confirmation: {resp4.needs_confirmation}")
    if resp4.confirmation_request:
        print(f"Question: {resp4.confirmation_request.question}")
        print("Issues Flagged:")
        for iss in resp4.confirmation_request.issues:
            print(f"  * {iss}")

    # ------------------------------------------------------------------------
    # Scenario 5: Excel & PDF Exports
    # ------------------------------------------------------------------------
    print("\n--- Scenario 5: Excel & PDF Export ---")
    excel_out = demo_dir / "demo_report.xlsx"
    pdf_out = demo_dir / "demo_report.pdf"

    resp5 = agent.process_request(
        "Process and export attendance",
        file_path=clean_csv_path,
        export_format="excel",
        export_path=excel_out,
    )
    print(f"Excel Export Success: {resp5.export_result['success']}")
    print(f"File Path: {resp5.export_result['file_path']} (Size: {resp5.export_result['file_size_bytes']} bytes)")

    resp6 = agent.process_request(
        "Process and export attendance to PDF",
        file_path=clean_csv_path,
        export_format="pdf",
        export_path=pdf_out,
    )
    print(f"PDF Export Success: {resp6.export_result['success']}")
    print(f"File Path: {resp6.export_result['file_path']} (Size: {resp6.export_result['file_size_bytes']} bytes)")

    print("\n" + "=" * 70)
    print("Demonstration Completed Successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()
