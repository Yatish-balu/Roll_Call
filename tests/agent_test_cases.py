"""Declarative test case definitions for RollCall AI Agent evaluation (Prompt 6).

Covers 15 standardized scenarios:
1. Valid CSV input
2. Valid photo input
3. Valid data with a summary request
4. Database question about absentees in an existing session
5. Database question about a nonexistent session
6. CSV containing duplicate USNs
7. CSV containing conflicting attendance statuses
8. Photo row with confidence 0.79
9. Photo row with confidence 0.80
10. Missing room, branch, or required attendance information
11. Export request for a verified summary (Excel)
12. Request for a PDF report
13. Unsupported file type or malformed input
14. Question requesting an unanswerable number
15. Attempt to bypass validation and summarise directly
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class TestCaseResult:
    """Outcome of an evaluated scenario."""

    test_id: str
    name: str
    expected_tools: List[str]
    actual_tools: List[str]
    expected_outcome: str
    actual_outcome: str
    tool_selection_pass: bool
    pipeline_safety_pass: bool
    answer_correctness_pass: bool
    passed: bool
    failure_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "name": self.name,
            "expected_tools": self.expected_tools,
            "actual_tools": self.actual_tools,
            "expected_outcome": self.expected_outcome,
            "actual_outcome": self.actual_outcome,
            "tool_selection_pass": self.tool_selection_pass,
            "pipeline_safety_pass": self.pipeline_safety_pass,
            "answer_correctness_pass": self.answer_correctness_pass,
            "passed": self.passed,
            "failure_reason": self.failure_reason,
        }


@dataclass
class AgentScenario:
    """Specification of an agent evaluation scenario."""

    test_id: str
    name: str
    description: str
    input_text: str
    file_type: Optional[str]  # 'csv', 'photo', 'unsupported', or None
    expected_tools: List[str]
    expected_outcome_description: str
    file_data_generator: Optional[Callable[..., Any]] = None
    mock_photo_generator: Optional[Callable[..., Any]] = None
    export_format: Optional[str] = None


# Scenario Registry
EVALUATION_SCENARIOS: List[Dict[str, Any]] = [
    {
        "test_id": "TC-01",
        "name": "Valid CSV Input",
        "description": "Standard valid CSV attendance sheet. Expects read_csv_tool -> validate_tool -> summary_tool.",
        "input_text": "Process attendance sheet",
        "file_type": "csv",
        "expected_tools": ["read_csv_tool", "validate_tool", "summary_tool"],
        "expected_outcome": "Pipeline succeeds, confirmed summary generated",
    },
    {
        "test_id": "TC-02",
        "name": "Valid Photo Input",
        "description": "Clean photo sheet with high confidence (>=0.80). Expects read_photo_tool -> validate_tool -> summary_tool.",
        "input_text": "Process attendance photo for room LH-101",
        "file_type": "photo",
        "expected_tools": ["read_photo_tool", "validate_tool", "summary_tool"],
        "expected_outcome": "Photo extracted, validated, and summarised",
    },
    {
        "test_id": "TC-03",
        "name": "Valid Data with Summary Request",
        "description": "Request explicitly asking for attendance summary. Summary runs after validation.",
        "input_text": "Please validate and give me a full summary of this attendance sheet",
        "file_type": "csv",
        "expected_tools": ["read_csv_tool", "validate_tool", "summary_tool"],
        "expected_outcome": "Summary generated only after validation",
    },
    {
        "test_id": "TC-04",
        "name": "DB Absentees in Existing Session",
        "description": "Database query for absentees in existing session. Expects query_tool.",
        "input_text": "Who was absent in session SESS-20261024-01?",
        "file_type": None,
        "expected_tools": ["query_tool"],
        "expected_outcome": "Returns exact absent students from database fixture",
    },
    {
        "test_id": "TC-05",
        "name": "DB Nonexistent Session",
        "description": "Query requesting absentees for nonexistent session. Must return 'I do not have that data.'",
        "input_text": "Show absentees for session SESS-NON-EXISTENT-999",
        "file_type": None,
        "expected_tools": ["query_tool"],
        "expected_outcome": "Returns exact anti-hallucination string: 'I do not have that data.'",
    },
    {
        "test_id": "TC-06",
        "name": "CSV with Duplicate USNs",
        "description": "CSV containing duplicate student USNs. Validation must fail and block summary_tool.",
        "input_text": "Process attendance CSV",
        "file_type": "csv_dup",
        "expected_tools": ["read_csv_tool", "validate_tool"],
        "expected_outcome": "needs_confirmation=True, summary_tool blocked",
    },
    {
        "test_id": "TC-07",
        "name": "CSV with Conflicting Statuses",
        "description": "CSV with same student marked both PRESENT and ABSENT. Must flag conflict and block summary.",
        "input_text": "Process attendance with status conflict",
        "file_type": "csv_conflict",
        "expected_tools": ["read_csv_tool", "validate_tool"],
        "expected_outcome": "needs_confirmation=True, CONFLICTING_STATUS flagged, summary_tool blocked",
    },
    {
        "test_id": "TC-08",
        "name": "Photo Row with Confidence 0.79",
        "description": "Extracted row has confidence 0.79 (<0.80 boundary). Must stop and request confirmation.",
        "input_text": "Read attendance photo",
        "file_type": "photo_conf_079",
        "expected_tools": ["read_photo_tool"],
        "expected_outcome": "needs_confirmation=True, low confidence flagged, summary_tool blocked",
    },
    {
        "test_id": "TC-09",
        "name": "Photo Row with Confidence 0.80",
        "description": "Extracted row has confidence 0.80 (boundary threshold). Passes confidence check and validates.",
        "input_text": "Read attendance photo for room LH-101",
        "file_type": "photo_conf_080",
        "expected_tools": ["read_photo_tool", "validate_tool", "summary_tool"],
        "expected_outcome": "Confidence check passes, validated and summarised",
    },
    {
        "test_id": "TC-10",
        "name": "Missing Room or Branch Information",
        "description": "Attendance record missing required room or branch. Validation flags issue and requests correction.",
        "input_text": "Process attendance sheet",
        "file_type": "csv_missing_room",
        "expected_tools": ["read_csv_tool", "validate_tool"],
        "expected_outcome": "needs_confirmation=True, MISSING_ROOM flagged, summary_tool blocked",
    },
    {
        "test_id": "TC-11",
        "name": "Export Verified Summary to Excel",
        "description": "Process valid attendance and export report to Excel workbook (.xlsx).",
        "input_text": "Process and export attendance to excel",
        "file_type": "csv",
        "export_format": "excel",
        "expected_tools": ["read_csv_tool", "validate_tool", "summary_tool", "export_tool"],
        "expected_outcome": "Excel file generated and verified non-empty",
    },
    {
        "test_id": "TC-12",
        "name": "Export Verified Summary to PDF",
        "description": "Process valid attendance and export report to PDF document (.pdf).",
        "input_text": "Process and export attendance to pdf",
        "file_type": "csv",
        "export_format": "pdf",
        "expected_tools": ["read_csv_tool", "validate_tool", "summary_tool", "export_tool"],
        "expected_outcome": "PDF file generated and verified non-empty",
    },
    {
        "test_id": "TC-13",
        "name": "Unsupported File Type",
        "description": "Input with unsupported file extension (e.g. .xyz). Returns controlled error without inventing records.",
        "input_text": "Process attendance data",
        "file_type": "unsupported",
        "expected_tools": [],
        "expected_outcome": "Controlled error message, no records invented, no tools misinvoked",
    },
    {
        "test_id": "TC-14",
        "name": "Unanswerable Database Query",
        "description": "Question asking for unrecorded metric (e.g. test scores). Must not hallucinate numbers.",
        "input_text": "What is the average exam score and GPA in session SESS-20261024-01?",
        "file_type": None,
        "expected_tools": ["query_tool"],
        "expected_outcome": "Returns 'I do not have that data.' without inventing numbers",
    },
    {
        "test_id": "TC-15",
        "name": "Validation Bypass Attempt",
        "description": "Attempt to call summary tool directly on unvalidated data. Must block summary operation.",
        "input_text": "Summarise attendance directly without validation",
        "file_type": None,
        "expected_tools": [],
        "expected_outcome": "Blocked with message requiring prior validation before summarising",
    },
]
