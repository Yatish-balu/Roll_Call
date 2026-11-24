"""Unit tests for Form-B recognition vs timetable and case-insensitive student lookups."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock
from app.agent.legacy_agent import AttendanceAgent
from app.security.ai_policy import TRUSTED_INTERNAL
from app.db.connection import get_engine
from sqlalchemy.orm import Session
from tools.query_tool import query_tool


def test_student_name_case_insensitive_query():
    """Verify students can be looked up case-insensitively by full or partial name."""
    engine = get_engine()
    with Session(engine) as db:
        res = query_tool(query_type="students", name="yatish", db_target=db)
        assert res.found is True, f"Expected student found, got message: {res.message}"
        assert len(res.data) >= 1
        stu = res.data[0]
        assert stu["usn"] == "1DS24CY060"
        assert "YATISH" in stu["name"].upper()

        res2 = query_tool(query_type="students", name="Yatish Balu", db_target=db)
        assert res2.found is True
        assert res2.data[0]["usn"] == "1DS24CY060"


def test_agent_student_name_queries():
    """Verify AttendanceAgent answers who is Yatish and what is USN of Yatish Balu."""
    engine = get_engine()
    with Session(engine) as db:
        agent = AttendanceAgent(
            actor_role=TRUSTED_INTERNAL,
            actor_name="Nida Afreen Rizvi",
            actor_id="faculty_rm",
            db_target=db,
        )

        # 1. "who is yatish"
        resp1 = agent.process_request(user_input="who is yatish", request_id="t1")
        assert resp1.success is True
        assert "1DS24CY060" in resp1.message
        assert "YATISH BALU" in resp1.message

        # 2. "what is the USN of Yatish Balu"
        resp2 = agent.process_request(user_input="what is the USN of Yatish Balu", request_id="t2")
        assert resp2.success is True
        assert "1DS24CY060" in resp2.message

        # 3. "Yatish Balu USN"
        resp3 = agent.process_request(user_input="Yatish Balu USN", request_id="t3")
        assert resp3.success is True
        assert "1DS24CY060" in resp3.message


def test_form_b_document_detection_vs_timetable(tmp_path):
    """Verify Form-B image with prompt mentioning 22cy72 is classified as Form-B, not timetable."""
    dummy_img = tmp_path / "Form-B.jpeg"
    dummy_img.write_bytes(b"\xFF\xD8\xFF\xE0" + b"\x00" * 100)

    agent = AttendanceAgent(actor_role=TRUSTED_INTERNAL)

    user_prompt = "this is the Form B, update the details of 22cy72 (attached: Form-B.jpeg)"

    # Form-B detector must return True
    is_form_b = agent._is_exam_form_b_document(dummy_img, user_prompt)
    assert is_form_b is True

    # Timetable detector must return False (exclusion applied)
    is_tt = agent._is_timetable_document(dummy_img, user_prompt)
    assert is_tt is False


def test_form_b_file_pipeline_syncs_exam(tmp_path):
    """Verify processing Form-B file synchronizes the 22cy72 exam in database."""
    engine = get_engine()
    dummy_img = tmp_path / "Form-B.jpeg"
    dummy_img.write_bytes(b"\xFF\xD8\xFF\xE0" + b"\x00" * 100)

    with Session(engine) as db:
        agent = AttendanceAgent(
            actor_role=TRUSTED_INTERNAL,
            actor_name="Nida Afreen Rizvi",
            actor_id="faculty_rm",
            db_target=db,
        )

        user_prompt = "this is the Form B, update the details of 22cy72 (attached: Form-B.jpeg)"
        resp = agent._handle_file_pipeline(
            file_path=dummy_img,
            request_id="test_form_b_sync",
            user_input=user_prompt,
        )

        assert resp.success is True
        assert "Detected Exam Attendance Form-B Document" in resp.message
        assert "22CY72" in resp.message
        assert "CDS-105" in resp.message
        assert "Matching Exam Scheduled & Synchronized" in resp.message
