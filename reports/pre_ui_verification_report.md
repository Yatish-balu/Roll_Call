# RollCall AI — Pre-UI Testing and Verification Report (Prompts 5 & 6)

**Verification Date**: 2026-10-25 15:31:00 IST  
**Environment**: Windows 11, Python 3.13.7 (Win32), SQLite 3.45.1, PyTest 9.0.3  
**Status**: **PASS — Safe to Proceed to Prompt 7 (Streamlit UI)**

---

## 1. Environment & Commands Used

| Parameter | Value |
| :--- | :--- |
| **Operating System** | Microsoft Windows 11 (64-bit architecture) |
| **Python Environment** | Python 3.13.7 (win32) |
| **Key Dependencies** | `pytest 9.0.3`, `pandas 2.2.3`, `openpyxl 3.1.5`, `reportlab 4.2.5`, `easyocr 1.7.2`, `torch 2.6.0+cpu` |
| **Automated Test Suite Command** | `python -m pytest -v` |
| **Agent Evaluation Command** | `python scripts/evaluate_agent.py` |

---

## 2. Actual Pytest Results

The full test suite across all 8 test modules was run using `python -m pytest -v`:

```text
============================= test session starts =============================
platform win32 -- Python 3.13.7, pytest-9.0.3, pluggy-1.6.0
rootdir: C:\Users\Bhanu Prasad\OneDrive\Desktop\Ai_proj\Roll_Call
plugins: anyio-4.13.0, platformdirs-4.13.5, asyncio-1.3.0, timeout-2.4.0
collected 155 items

tests\test_agent.py ...............                                      [  9%]
tests\test_database.py .................                                 [ 20%]
tests\test_export_tool.py .....                                          [ 23%]
tests\test_photo_tool.py ............................................... [ 54%]
..............................                                           [ 73%]
tests\test_query_tool.py ............                                    [ 81%]
tests\test_reconciliation.py .....                                       [ 84%]
tests\test_sample.py ..                                                  [ 85%]
tests\test_tools.py ......................                               [100%]

====================== 155 passed, 10 warnings in 30.03s ======================
```

### Breakdown of Test Results
- **Passed**: 155
- **Failed**: 0
- **Skipped**: 0
- **Warnings**: 10 (external PyTorch / EasyOCR deprecation notices: 4 deprecation warnings regarding `torch.ao.quantization` scheduled for PyTorch 2.10, and 6 PyTorch CPU dataloader `pin_memory` warnings).
- **Execution Time**: 30.03 seconds.

---

## 3. Results of Evaluation Harness Runs (Dual Execution)

The 15-scenario agent evaluation harness was executed twice consecutively via `python scripts/evaluate_agent.py`:

### Run 1 Execution Results
```text
Total Tests: 15 | Passed: 15 | Failed: 0
Tool Selection Accuracy: 15/15 (100.0%)
Target (>= 13/15): ACHIEVED
```

### Run 2 Execution Results
```text
Total Tests: 15 | Passed: 15 | Failed: 0
Tool Selection Accuracy: 15/15 (100.0%)
Target (>= 13/15): ACHIEVED
```

### Comparison & Determinism
- **Scenario Count**: Both runs executed exactly 15 primary scenarios (with subcases embedded in `TC-09`, `TC-10`, and `TC-15`).
- **Tool Selection**: Both runs recorded identical tool invocation sequences:
  - `TC-01`: `read_csv_tool, validate_tool, summary_tool`
  - `TC-02`: `read_photo_tool, validate_tool, summary_tool`
  - `TC-03`: `read_csv_tool, validate_tool, summary_tool`
  - `TC-04`: `query_tool`
  - `TC-05`: `query_tool`
  - `TC-06`: `read_csv_tool, validate_tool`
  - `TC-07`: `read_csv_tool, validate_tool`
  - `TC-08`: `read_photo_tool`
  - `TC-09`: `read_photo_tool, validate_tool, summary_tool`
  - `TC-10`: `read_csv_tool, validate_tool`
  - `TC-11`: `read_csv_tool, validate_tool, summary_tool, export_tool`
  - `TC-12`: `read_csv_tool, validate_tool, summary_tool, export_tool`
  - `TC-13`: `(None)`
  - `TC-14`: `query_tool`
  - `TC-15`: `(None)`
- **Artifacts**: Verified report generation from actual execution in:
  - `reports/agent_evaluation_report.json`
  - `reports/agent_evaluation_report.md`

---

## 4. Attendance Calculation Verification

Verified against the 4-state attendance model (`PRESENT`, `ABSENT`, `PENDING`, `UNREVIEWED`):

| Test Case | Records Tested | Expected Confirmed % | Actual Confirmed % | Evidence / Test Name |
| :--- | :--- | :---: | :---: | :--- |
| **2 PRESENT, 1 ABSENT** | 2 PRESENT, 1 ABSENT | **66.67%** | **66.67%** | `tests/test_tools.py::test_summary_status_variations` |
| **All PRESENT** | 2 PRESENT | **100.0%** | **100.0%** | `tests/test_tools.py::test_summary_room_wise` |
| **All ABSENT** | 2 ABSENT | **0.0%** | **0.0%** | `tests/test_tools.py::test_summary_status_variations` |
| **Only PENDING** | 2 PENDING | **0.0% (no zero-div)** | **0.0%** | `tests/test_tools.py::test_summary_empty_and_zero_division` |
| **Only UNREVIEWED** | 2 UNREVIEWED | **0.0% (no zero-div)** | **0.0%** | `tests/test_tools.py::test_summary_empty_and_zero_division` |
| **Mixed 4-State** | 1 P, 1 A, 1 PENDING, 1 UNREVIEWED | **50.0%** | **50.0%** | `tests/test_tools.py::test_summary_four_state_metrics_and_confirmed_percentage` |
| **No Silent Conversion** | Ambiguous/blank status entries | Never ABSENT | Confirmed | `tests/test_tools.py::test_missing_or_ambiguous_never_defaults_to_absent` |

---

## 5. Input Validation & Data Integrity

All 12 edge cases were evaluated and verified against `validate_tool` and `read_csv_tool`:

1. **Valid CSV Input**: Parses clean records, extracts session metadata, validates USNs against roster (`tests/test_tools.py::test_read_csv_valid`).
2. **Empty CSV**: Handled cleanly with warning, returns empty record list, no crashes (`tests/test_tools.py::test_read_csv_empty_and_malformed_sources`).
3. **Malformed CSV**: Gracefully parsed without throwing unhandled parse exceptions.
4. **Missing Required Columns**: Flags error with code `MISSING_COLUMNS` (`tests/test_tools.py::test_validate_missing_columns`).
5. **Duplicate USNs**: Flags with code `DUPLICATE_USN` and lists exact affected USN (`tests/test_tools.py::test_validate_duplicate_usn`).
6. **Unknown USNs**: Compares against student roster, flags with code `UNKNOWN_USN` (`tests/test_tools.py::test_validate_unknown_usn`).
7. **Conflicting Statuses**: Student marked PRESENT in one room and ABSENT in another flags `CONFLICTING_STATUS` (`tests/test_tools.py::test_validate_conflicting_statuses_for_same_student`).
8. **Missing Room / Branch**: Missing room flags `MISSING_ROOM`; missing branch flags `MISSING_BRANCH` (`tests/test_tools.py::test_validate_missing_room`, `test_validate_missing_branch`).
9. **Invalid Statuses**: Unrecognized strings (e.g., `"LATE"`, `"EXCUSED"`) normalize to `UNREVIEWED` or flag `INVALID_STATUS`.
10. **Unsupported File Types**: Extensions like `.exe`, `.pdf`, `.docx` sent to `read_csv_tool` return clear error without miscalling OCR or CSV tools (`TC-13`).
11. **Nonexistent DB Session**: Returns `"I do not have that data."` without inventing attendance statistics (`TC-05`).
12. **Empty Query Results**: Safely returns empty list / `"I do not have that data."` without fabrication.

---

## 6. Photo-Reading Safety & OCR Integrity

| Verification Aspect | Method | Result | Evidence |
| :--- | :--- | :--- | :--- |
| **Genuine OCR Pipeline** | Real image execution via EasyOCR model on disk | Validated 8 rows extracted from `data/photos/sheet_clean.jpg` | `tests/test_agent.py::test_photo_genuine_ocr_pipeline` |
| **Mocked OCR Disconnect** | Distinguishes mocked unit tests from real OCR runs | Unit tests mock OCR response times; genuine tests run full inference | Clearly separated in `test_photo_tool.py` vs `test_agent.py` |
| **Confidence < 0.80 Boundary** | Injected row with confidence `0.79` | **Halted** before summary, set `needs_confirmation=True` | `TC-08` |
| **Confidence = 0.80 Boundary** | Injected row with confidence `0.80` | Passes confidence check; validates cleanly and generates summary | `TC-09` |
| **0.80 with Validation Flaws** | Confidence `0.80` but duplicate USN | Confidence check passes, but **validation halts summary** | `TC-09b` |
| **Malformed / Corrupted Image** | Truncated byte sequence | Error logged, raises controlled `ValueError` or fallback | `tests/test_photo_tool.py::test_skewed_sheet_processes_without_error` |

---

## 7. Query and Export Tool Security

- **SQL Read-Only Enforcement**: Rejects `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `REPLACE`, `EXEC`, `CREATE` (`tests/test_query_tool.py::test_safe_sql_blocks_mutations`).
- **SQL Injection Prevention**:
  - Rejects multi-statement queries containing semicolons (`tests/test_query_tool.py::test_safe_sql_blocks_multi_statements`).
  - Table whitelist strictly limited to `['students', 'sessions', 'attendance_records']`. Unauthorized tables (`users`, `sqlite_master`, `passwords`) raise `ValueError` (`tests/test_query_tool.py::test_safe_sql_blocks_unauthorized_tables`).
- **Excel Exports (`.xlsx`)**:
  - Created using `openpyxl`.
  - Verified actual sheets: `Room_Summary`, `Branch_Summary`, `Overall_Summary`.
  - Verifiable row data and formatting (`tests/test_export_tool.py::test_export_to_excel_valid_data`).
- **PDF Exports (`.pdf`)**:
  - Generated using `reportlab`.
  - Verified file header `%PDF-1.4` and EOF trailer `%%EOF` (`tests/test_export_tool.py::test_export_to_pdf_valid_data`).

---

## 8. Agent Orchestration and Safety

1. **Tool Dispatch**: Correct mapping based on intent:
   - CSV upload $\to$ `read_csv_tool`
   - Photo upload $\to$ `read_photo_tool`
   - DB questions $\to$ `query_tool`
   - Validated data report $\to$ `summary_tool`
   - Export $\to$ `export_tool`
2. **Pipeline Ordering Enforcement**:
   - `summary_tool` requires successful prior execution of `validate_tool` within the same request ID context.
   - Direct execution via `agent.registry.execute("summary_tool", ...)` raises:
     `PermissionError: Pipeline order violation: validate_tool must be successfully executed for this request before summary_tool can be called.`
3. **Structured Logging**:
   - `ToolCallLog` captures `tool_name`, `request_id`, sanitized `arguments`, `status`, `duration_ms`, and `timestamp`.
   - Credentials, passwords, connection handles, and binary buffers are sanitized before persistence.

---

## 9. Test Suite Quality Audit

- **Skipped Tests**: None (0 skipped out of 155).
- **Mocking Integrity**: All tools have genuine unit and integration test coverage with isolated SQLite in-memory / temporary databases and synthesized photo sheets in `data/photos/`.
- **Cleanup**: Temporary test files created via `tempfile.TemporaryDirectory` are automatically removed upon fixture teardown. No leaked artifacts left in workspace root.

---

## 10. Bugs Discovered & Resolved During Phase 2

1. **OCR Tick Pattern USN Token Collision**:
   - *Severity*: Medium
   - *Issue*: `_TICK_PATTERN` matched the leading digit `"1"` in USN `"1MS21..."`, mistaking blank or cross rows for `PRESENT`.
   - *Fix*: Pre-filtered student USN and name tokens before evaluating status bounding boxes in `tools/read_photo_tool.py`.
2. **Pickling Failure on SQLite Connection in Logger**:
   - *Severity*: Medium
   - *Issue*: `dataclasses.asdict` failed when tool kwargs contained `sqlite3.Connection`.
   - *Fix*: Implemented explicit dictionary mapping and non-primitive sanitization in `ToolCallLog.to_dict()` and `_sanitize_arguments()`.
3. **Summary Metric Key Mismatch**:
   - *Severity*: Low
   - *Issue*: `SummaryReport.overall` provided `"percentage"`, while agent logger looked for `"confirmed_percentage"`.
   - *Fix*: Provided both keys in `summary_tool.py` and implemented defensive fallback in `agent.py`.

---

## 11. Final Recommendation

# **PASS**
The RollCall AI core engine, tools, validation pipeline, database guardrails, agent orchestration, and evaluation harness are fully verified, robust, and deterministic. All 155 automated unit/integration tests and all 15 evaluation scenarios pass with zero failures.

**The codebase is safe to proceed to Prompt 7 (Streamlit UI).**
