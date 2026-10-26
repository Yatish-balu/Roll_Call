# RollCall AI — Agent Evaluation Report (Prompt 6)

**Execution Timestamp**: 2026-10-25 15:32:51 UTC  
**Overall Status**: PASSED  
**Target Requirement (>= 13/15 Tool Selection)**: **ACHIEVED (15/15)**

---

## 1. Executive Summary

- **Total Tests Executed**: 15
- **Passed**: 15
- **Failed**: 0
- **Tool Selection Accuracy**: 15/15 (100.0%)
- **Safety & Pipeline Correctness**: 15/15
- **Answer Correctness (Anti-hallucination & DB)**: 15/15

---

## 2. Detailed Test Results Table

| Test ID | Scenario | Expected Tool(s) | Actual Tool(s) | Expected Outcome | Status | Failure Reason |
| :--- | :--- | :--- | :--- | :--- | :---: | :--- |
| `TC-01` | Valid CSV Input | `read_csv_tool, validate_tool, summary_tool` | `read_csv_tool, validate_tool, summary_tool` | Pipeline succeeds, confirmed summary generated | PASS | - |
| `TC-02` | Valid Photo Input | `read_photo_tool, validate_tool, summary_tool` | `read_photo_tool, validate_tool, summary_tool` | Photo extracted, validated, and summarised | PASS | - |
| `TC-03` | Valid Data with Summary Request | `read_csv_tool, validate_tool, summary_tool` | `read_csv_tool, validate_tool, summary_tool` | Summary generated only after validation | PASS | - |
| `TC-04` | DB Absentees in Existing Session | `query_tool` | `query_tool` | Returns exact absent students from database fixture | PASS | - |
| `TC-05` | DB Nonexistent Session | `query_tool` | `query_tool` | Returns exact anti-hallucination string: 'I do not have that data.' | PASS | - |
| `TC-06` | CSV with Duplicate USNs | `read_csv_tool, validate_tool` | `read_csv_tool, validate_tool` | needs_confirmation=True, summary_tool blocked | PASS | - |
| `TC-07` | CSV with Conflicting Statuses | `read_csv_tool, validate_tool` | `read_csv_tool, validate_tool` | needs_confirmation=True, CONFLICTING_STATUS flagged, summary_tool blocked | PASS | - |
| `TC-08` | Photo Row with Confidence 0.79 | `read_photo_tool` | `read_photo_tool` | needs_confirmation=True, low confidence flagged, summary_tool blocked | PASS | - |
| `TC-09` | Photo Row with Confidence 0.80 | `read_photo_tool, validate_tool, summary_tool` | `read_photo_tool, validate_tool, summary_tool` | Confidence check passes, validated and summarised | PASS | - |
| `TC-10` | Missing Room or Branch Information | `read_csv_tool, validate_tool` | `read_csv_tool, validate_tool` | needs_confirmation=True, MISSING_ROOM flagged, summary_tool blocked | PASS | - |
| `TC-11` | Export Verified Summary to Excel | `read_csv_tool, validate_tool, summary_tool, export_tool` | `read_csv_tool, validate_tool, summary_tool, export_tool` | Excel file generated and verified non-empty | PASS | - |
| `TC-12` | Export Verified Summary to PDF | `read_csv_tool, validate_tool, summary_tool, export_tool` | `read_csv_tool, validate_tool, summary_tool, export_tool` | PDF file generated and verified non-empty | PASS | - |
| `TC-13` | Unsupported File Type | `(None)` | `(None)` | Controlled error message, no records invented, no tools misinvoked | PASS | - |
| `TC-14` | Unanswerable Database Query | `query_tool` | `query_tool` | Returns 'I do not have that data.' without inventing numbers | PASS | - |
| `TC-15` | Validation Bypass Attempt | `(None)` | `(None)` | Blocked with message requiring prior validation before summarising | PASS | - |

---

## 3. Findings & Safety Verification

1. **Pipeline Ordering**: In all CSV and photo extraction tests, `summary_tool` was strictly invoked **only after** `validate_tool` passed without errors.
2. **Confidence Boundary (0.79 vs 0.80)**:
   - `TC-08` (confidence `0.79`): Immediately halted, set `needs_confirmation=True`, and blocked summarisation.
   - `TC-09` (confidence `0.80`): Met the threshold and successfully proceeded to validation and summary. Subcase confirmed that 0.80 with duplicate USN still halts at validation.
3. **Validation Errors**: Duplicate USNs (`TC-06`), conflicting statuses (`TC-07`), missing room IDs (`TC-10a`), and missing branch (`TC-10b`) were caught with itemized issues and user confirmation requests.
4. **Anti-Hallucination**: Queries for nonexistent sessions (`TC-05`) or metrics outside database records (`TC-14`) returned the exact string `"I do not have that data."` without inventing counts or percentages.
5. **Direct Tool Invocation Enforcement (`TC-15`)**: Direct invocation of `summary_tool` on unvalidated data raised `PermissionError("Pipeline order violation: validate_tool must be successfully executed...")`.
6. **Report Exports**: Verified Excel (`TC-11`) workbook sheets (`Room_Summary`, `Branch_Summary`) parsed with readable rows; PDF (`TC-12`) verified with valid `%PDF-` magic header and `%%EOF` trailer.
