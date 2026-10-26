# RollCall AI — Attendance Summary Agent
## Complete Development, Implementation and Testing Report
**Scope**: Core Engine and Pre-UI Verification (Phase 1, Phase 2, Prompt 5, and Prompt 6)  
**Date**: October 25, 2026  
**Document Revision**: 1.0.0  
**Project Group**: Group 7 (4-Phase Antigravity Workflow)  
**Status**: Pre-UI Verification Passed (155/155 PyTest Tests Passed, 15/15 Agent Evaluation Scenarios Passed)  

---

## Table of Contents
1. [Executive Summary](#1-executive-summary)
2. [Project Objectives and Requirements](#2-project-objectives-and-requirements)
3. [Development Phases and Chronological Work](#3-development-phases-and-chronological-work)
   - [Phase 1: Foundation and Core Engine](#phase-1-foundation-and-core-engine)
   - [Phase 2: Photo Reading and Agent Brain](#phase-2-photo-reading-and-agent-brain)
   - [Prompt 5: Tool-Calling Agent and Guardrail Integration](#prompt-5-tool-calling-agent-and-guardrail-integration)
   - [Prompt 6: Evaluation Harness and Benchmark Runner](#prompt-6-evaluation-harness-and-benchmark-runner)
4. [System Architecture and Data Flow](#4-system-architecture-and-data-flow)
   - [Component Decomposition](#component-decomposition)
   - [Execution Sequence and Guardrail Flow](#execution-sequence-and-guardrail-flow)
5. [Attendance Data Model and Business Rules](#5-attendance-data-model-and-business-rules)
   - [The Four-State Attendance Model](#the-four-state-attendance-model)
   - [Mathematical Formulation of Confirmed Attendance](#mathematical-formulation-of-confirmed-attendance)
   - [Data Integrity Rules and Anomaly Handling](#data-integrity-rules-and-anomaly-handling)
6. [Agent Workflow and Tool Selection](#6-agent-workflow-and-tool-selection)
   - [Tool Registry Architecture](#tool-registry-architecture)
   - [Pipeline Ordering Enforcement](#pipeline-ordering-enforcement)
   - [Anti-Hallucination Guardrails](#anti-hallucination-guardrails)
7. [Comprehensive Testing Methodology](#7-comprehensive-testing-methodology)
   - [Test Environment and Configuration](#test-environment-and-configuration)
   - [PyTest Test Suite Breakdown](#pytest-test-suite-breakdown)
   - [Evaluation Benchmark Harness](#evaluation-benchmark-harness)
8. [Detailed Test Cases and Verification Results](#8-detailed-test-cases-and-verification-results)
   - [Attendance Calculations Suite](#attendance-calculations-suite)
   - [CSV and Data Validation Suite](#csv-and-data-validation-suite)
   - [Photo OCR and Confidence Suite](#photo-ocr-and-confidence-suite)
   - [Database Query and Security Suite](#database-query-and-security-suite)
   - [Export Verification Suite](#export-verification-suite)
   - [Agent Orchestration and Safety Suite](#agent-orchestration-and-safety-suite)
9. [Photo OCR Pipeline and Confidence Boundary Handling](#9-photo-ocr-pipeline-and-confidence-boundary-handling)
10. [Database Security, Guardrails, and Data Integrity](#10-database-security-guardrails-and-data-integrity)
11. [Export Tool Implementation and File Validation](#11-export-tool-implementation-and-file-validation)
12. [Warnings, Limitations, and Untested Areas](#12-warnings-limitations-and-untested-areas)
13. [Developer Reproducibility Guide](#13-developer-reproducibility-guide)
14. [Requirements-to-Evidence Traceability Matrix](#14-requirements-to-evidence-traceability-matrix)
15. [Final Results and Readiness Assessment](#15-final-results-and-readiness-assessment)

---

## 1. Executive Summary

### 1.1 Project Overview
**RollCall AI** is an intelligent, multi-modal attendance aggregation, validation, and reporting agent designed for academic institutions and enterprise training environments. Collecting and reconciling roll call records across diverse lecture halls, physical classroom sheets, and digital departmental spreadsheets is notoriously error-prone, labor-intensive, and prone to mathematical inaccuracies. RollCall AI solves this problem by integrating computer vision OCR, algorithmic validation, read-only SQL querying, structured multi-format reporting, and a deterministic tool-calling orchestration engine.

### 1.2 The Core Operational Dilemma
Traditional automated attendance systems fail in educational environments because they naively force ambiguous, illegible, or unrecorded rows into binary classifications (`PRESENT` or `ABSENT`). When a physical paper sheet contains a smudge, an unverified checkmark, or a student listed in the wrong room, existing tools silently record the student as absent or invent false data. 

RollCall AI solves this by enforcing a strict **Four-State Attendance Model**:
1. `PRESENT`: Authenticated and confirmed present.
2. `ABSENT`: Authenticated and confirmed absent.
3. `PENDING`: Awaiting confirmation or physical verification.
4. `UNREVIEWED`: Ambiguous mark, low extraction confidence, or illegible entry.

Under this model, **all counts and percentages originate strictly from deterministic code, never from generative AI model hallucinations**.

### 1.3 Key Architectural Deliverables
Up through the completion of Prompt 6 (and the pre-UI verification phase), the following major deliverables were implemented, tested, and audited:
- **Core Database Engine (`app/db/`)**: Relational SQLite schema (`students`, `rooms`, `sessions`, `attendance`) with foreign key constraints, indexing, and complete CRUD operations.
- **Data Ingestion Tools (`tools/read_csv_tool.py`, `tools/read_photo_tool.py`)**: Robust parsing of CSV spreadsheets and multi-stage OCR extraction (EasyOCR and vision fallback) capable of reading physical paper attendance sheets.
- **Validation Engine (`tools/validate_tool.py`)**: Strict validation catching duplicate roll numbers (USNs), unregistered students, missing rooms/branches, blank statuses, and conflicting room attendance.
- **Summary Calculation Engine (`tools/summary_tool.py`)**: Room-wise and branch-wise attendance metrics enforcing the verified formula $\text{Confirmed \%} = \frac{\text{PRESENT}}{\text{PRESENT} + \text{ABSENT}} \times 100$.
- **Database Query Engine (`tools/query_tool.py`)**: Safe, read-only SQL query dispatcher rejecting mutations, multi-statement injection, and unapproved tables, with an anti-hallucination fallback returning `"I do not have that data."` on unrecorded metrics.
- **Export Engine (`tools/export_tool.py`)**: Automated generation of styled Excel spreadsheets (`.xlsx`) via OpenPyXL and publication-grade PDF documents (`.pdf`) via ReportLab.
- **Tool-Calling Agent (`app/agent.py`)**: `AttendanceAgent` orchestrator enforcing strict pipeline ordering (`Read` $\to$ `Validate` $\to$ `Check Confidence` $\to$ `Summarise` $\to$ `Export`), a hard confidence threshold of `0.80`, direct-invocation bypass protection, and structured execution logging.
- **Evaluation Benchmark Harness (`scripts/evaluate_agent.py`, `tests/agent_test_cases.py`)**: 15 official multi-modal test scenarios benchmarking tool-selection accuracy, safety invariants, and numerical truth.

### 1.4 Reported and Verified Test Outcomes
- **Automated PyTest Suite**: 155 unit and integration tests executed across 8 test suites with **155 Passed, 0 Failed, 0 Skipped** (in 30.03 seconds).
- **Agent Evaluation Harness**: 15 official test scenarios executed in dual consecutive deterministic runs with **15/15 Passed (100.0% Tool Selection Accuracy)**.
- **Readiness Conclusion**: The core engine, backend tools, validation order enforcement, and safety invariants are fully verified and safe for user interface development.

---

## 2. Project Objectives and Requirements

The functional and safety requirements established for the RollCall AI core engine were derived from the *4-Phase Antigravity Workflow Specification* and formal academic requirements:

### 2.1 Confirmed Functional Requirements
1. **Multi-Modal Data Ingestion**:
   - Ingest CSV spreadsheets containing student roll numbers, names, rooms, branches, and statuses.
   - Ingest physical photographs of paper attendance sheets via optical character recognition (OCR).
2. **Database Integrity & Historical Querying**:
   - Store historical attendance records in a persistent SQLite relational database.
   - Provide safe natural-language querying for absentees, session statistics, and student rosters.
3. **Rigorous Attendance Validation**:
   - Cross-reference student roll numbers (USNs) against registered institutional rosters.
   - Detect and flag duplicate USN records within a session.
   - Detect conflicting attendance statuses (e.g. marked present in Room 101 and absent in Room 102 simultaneously).
   - Detect missing room identifiers or branch codes.
4. **Four-State Reconciliation**:
   - Preserve `PENDING` and `UNREVIEWED` as distinct unresolved categories.
   - Prevent unresolved rows from defaulting to `ABSENT`.
5. **Deterministic Summaries**:
   - Compute exact room-wise and branch-wise breakdown tables.
   - Prevent division-by-zero errors when all records are unresolved.
6. **Multi-Format Export**:
   - Produce verifiable multi-tab Excel workbooks (`.xlsx`).
   - Produce formatted PDF reports (`.pdf`) with verified binary headers.
7. **Agentic Tool Selection**:
   - Automatically determine the necessary sequence of tools based on user intent and input file types.

### 2.2 Safety, Security, and Governance Requirements
1. **Pipeline Ordering Enforcement**: The agent must physically block any attempt to invoke `summary_tool` or `export_tool` prior to successful execution of `validate_tool`.
2. **OCR Confidence Threshold (`0.80`)**: Any photo-extracted record exhibiting an OCR confidence score below `0.80` must immediately halt automated processing and require manual user confirmation.
3. **Passing Confidence Threshold Is Insufficient for Bypassing Validation**: A row with confidence $\ge 0.80$ that contains logical defects (e.g. duplicate USN) must still halt at the validation stage.
4. **SQL Injection and Mutation Immunity**: Arbitrary SQL execution is restricted to read-only `SELECT` statements on an allowlisted table subset (`students`, `rooms`, `sessions`, `attendance`). All multi-statement attempts (semicolons) and mutation verbs (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`) are rejected.
5. **Anti-Hallucination Invariant**: When queried regarding unrecorded metrics (e.g. exam scores, GPAs, or nonexistent sessions), the agent must return the exact string `"I do not have that data."` without inventing figures.
6. **Credential and Sensitive Data Sanitization**: Tool execution logs must sanitize passwords, API keys, tokens, and binary buffers before persistence.

---

## 3. Development Phases and Chronological Work

### Phase 1: Foundation and Core Engine
During Phase 1, the core data storage and deterministic processing libraries were established:
- **Application Structure**: Standardized directory hierarchy comprising `app/`, `tools/`, `data/`, `tests/`, `reports/`, and `docs/`.
- **Database Layer (`app/db/`)**:
  - `connection.py`: SQLite connection factory with timeout handling and `sqlite3.Row` factory configuration.
  - `schema.py`: DDL defining `students`, `rooms`, `sessions`, and `attendance` tables, indexes, and cascading foreign keys.
  - `crud.py`: Strongly typed data access functions supporting single and bulk operations.
- **Phase 1 Ingestion and Summary Tools**:
  - `tools/read_csv_tool.py`: Pandas-based CSV reader normalizing column variations and whitespace.
  - `tools/validate_tool.py`: Rule-based validation engine checking roster membership, duplicates, and missing metadata.
  - `tools/summary_tool.py`: Grouping engine calculating room-wise, branch-wise, and overall totals.
- **Synthetic Test Data (`tools/database.py`)**:
  - Generated exactly 200 synthetic students across 4 branches (`CSE`, `ISE`, `ECE`, `MECH`), 6 lecture rooms, and 5 historical sessions.

### Phase 2: Photo Reading and Agent Brain
Phase 2 expanded the architecture to handle unstructured vision input and autonomous tool orchestration:
- **Vision OCR Extraction (`tools/read_photo_tool.py`)**:
  - Implemented multi-stage computer vision preprocessing using OpenCV (grayscale conversion, adaptive thresholding, morphological deskewing, noise reduction).
  - Integrated EasyOCR for offline text and tick-mark detection.
  - Formatted structured rows (`PhotoRow`) tracking bounding boxes, text, normalized statuses, and numerical confidence scores ($0.0$ to $1.0$).
- **Synthetic Test Image Generation (`data/photos/generate_test_photos.py`)**:
  - Synthesized clean, tilted, noisy, partial, ambiguous, and empty attendance sheet images for reproducible test verification.

### Prompt 5: Tool-Calling Agent and Guardrail Integration
Prompt 5 brought the core components under unified agent control:
- **`tools/query_tool.py`**:
  - Implemented `validate_read_only_sql` checking AST tokens, forbidding semicolons, enforcing table allowlists, and rejecting mutation verbs.
  - Created high-level parameterized query dispatchers: `query_attendance`, `query_session_stats`, `query_absentees`, `query_students`, and `safe_sql_query`.
- **`tools/export_tool.py`**:
  - Implemented `export_to_excel` using OpenPyXL, writing styled headers, cell borders, and summary worksheets (`Room_Summary`, `Branch_Summary`, `Overall_Summary`).
  - Implemented `export_to_pdf` using ReportLab, compiling formatted report tables.
  - Implemented `export_tool` dispatcher validating inputs, ensuring target directory creation, and verifying written file existence and readability.
- **`app/agent.py`**:
  - Implemented `ToolRegistry` housing definitions and handlers for all six registered tools.
  - Implemented request-scoped ordering enforcement: invoking `summary_tool` without a prior successful `validate_tool` execution within the same request ID raises a `PermissionError`.
  - Implemented `ToolLogger` capturing sanitized execution logs, durations, and status codes.
  - Implemented `AttendanceAgent` routing natural language, CSV uploads, photo uploads, database queries, and export requests.
- **Discrepancy Correction**: Fixed a key naming mismatch in `summary_tool.py` where overall confirmed attendance rate was keyed as `"percentage"`, ensuring both `"percentage"` and `"confirmed_percentage"` are provided for downstream consumers.

### Prompt 6: Evaluation Harness and Benchmark Runner
Prompt 6 established an objective evaluation harness to benchmark agent autonomy and guardrails:
- **`tests/agent_test_cases.py`**: Declarative definition of 15 official test scenarios (`TC-01` through `TC-15`) covering valid data, photo boundaries, validation errors, unanswerable queries, and direct bypass attacks.
- **`scripts/evaluate_agent.py`**: Automated runner executing all 15 scenarios against the live agent, comparing actual tool sequences against expected sequences, verifying output assertions, and generating JSON/Markdown reports.

---

## 4. System Architecture and Data Flow

### 4.1 Component Decomposition

```
+-----------------------------------------------------------------------------------+
|                                 USER INTERFACE                                    |
|             (Natural Language Queries / CSV Uploads / Photo Sheet Uploads)        |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                                 AttendanceAgent                                   |
|                      (Intent Parsing & Tool Orchestrator)                         |
+-----------------------------------------------------------------------------------+
       |                    |                    |                   |
       | (CSV Upload)       | (Photo Upload)     | (DB Query)        | (Summary/Export)
       v                    v                    v                   v
+---------------+   +----------------+   +---------------+   +-------------------+
| read_csv_tool |   | read_photo_tool|   |  query_tool   |   |   summary_tool    |
| (Pandas / OS) |   |  (EasyOCR/CV2) |   | (SQLite RO)   |   | (Group Aggregator)|
+---------------+   +----------------+   +---------------+   +-------------------+
       |                    |                                        ^
       |                    | (Confidence >= 0.80)                   | (Validated Data)
       v                    v                                        |
+--------------------------------------------------------------------+
|                         validate_tool                              |
|           (Roster Check, Duplicate Check, Conflict Check)          |
+--------------------------------------------------------------------+
                               |
                               | (If Valid & Export Requested)
                               v
                     +-------------------+
                     |    export_tool    |
                     | (OpenPyXL / RLab) |
                     +-------------------+
                               |
                               v
                     +-------------------+
                     |  Excel / PDF File |
                     +-------------------+
```

### 4.2 Detailed Sequence and Pipeline Guardrail Flow
1. **Input Reception**: User supplies a query string or attaches a file (`.csv`, `.jpg`, `.png`).
2. **Intent & Dispatch**:
   - If input is a CSV file $\to$ `read_csv_tool` extracts tabular rows.
   - If input is an image file $\to$ `read_photo_tool` preprocesses the image and extracts rows with confidence scores.
   - If input is a query string $\to$ `query_tool` parses the question and queries SQLite.
3. **Confidence Guardrail**:
   - For photo extraction, every row's confidence score is evaluated against `CONFIDENCE_CONFIRMATION_THRESHOLD = 0.80`.
   - If any row falls below `0.80`, pipeline halts immediately, sets `needs_confirmation = True`, and returns itemized low-confidence rows to the caller.
4. **Validation Guardrail**:
   - Extracted records pass into `validate_tool`.
   - Checks are conducted against registered students, known rooms, and existing records.
   - If validation errors exist (duplicate USN, unknown USN, conflicting rooms, missing metadata), pipeline halts, sets `needs_confirmation = True`, and itemizes errors.
5. **Summary Computation**:
   - Only when `validate_tool` passes cleanly is `summary_tool` permitted to execute.
   - If a caller attempts to invoke `summary_tool` directly without prior validation, `ToolRegistry` raises `PermissionError`.
6. **Export Generation**:
   - If the request specified an export format (`excel` or `pdf`), `export_tool` compiles the summary tables into a verifiable binary file on disk.
7. **Logging**:
   - Every tool call is logged in `ToolLogger` with request ID, duration, sanitized arguments, status, and summary message.

---

## 5. Attendance Data Model and Business Rules

### 5.1 The Four-State Attendance Model

| Status | Formal Definition | Mathematical Treatment | Human Review Required? |
| :--- | :--- | :--- | :---: |
| `PRESENT` | Student verified attending session. | Counted in confirmed numerator & denominator. | No |
| `ABSENT` | Student verified not attending session. | Counted in confirmed denominator only. | No |
| `PENDING` | Student status awaiting manual check-in or roster verification. | Excluded from confirmed calculations; tracked as unresolved. | Yes |
| `UNREVIEWED` | OCR mark ambiguous, smudge detected, or cell unverified. | Excluded from confirmed calculations; tracked as unresolved. | Yes |

### 5.2 Mathematical Formulation of Confirmed Attendance

The overall confirmed attendance percentage is calculated using strictly confirmed records:

$$\text{Confirmed Attendance \%} = \begin{cases} \left( \frac{\text{Count}(\text{PRESENT})}{\text{Count}(\text{PRESENT}) + \text{Count}(\text{ABSENT})} \right) \times 100 & \text{if } \text{Count}(\text{PRESENT}) + \text{Count}(\text{ABSENT}) > 0 \\ 0.00\% & \text{if } \text{Count}(\text{PRESENT}) + \text{Count}(\text{ABSENT}) = 0 \end{cases}$$

#### Why PENDING and UNREVIEWED Are Excluded From the Denominator
If ambiguous or unreviewed rows were counted in the denominator as absent, an OCR scanning defect or an unconfirmed student would artificially depress the faculty member's attendance rate. Conversely, counting them as present would falsely inflate compliance. By maintaining them as a separate metric ($\text{Unresolved} = \text{PENDING} + \text{UNREVIEWED}$), RollCall AI guarantees that confirmed percentages represent verified reality while explicitly highlighting records requiring human review.

### 5.3 Data Integrity Rules and Anomaly Handling
- **Duplicate USN (`DUPLICATE_USN`)**: A student roll number appearing more than once within the same session triggers a validation error, preventing silent overwrites.
- **Conflicting Statuses (`CONFLICTING_STATUS`)**: A student recorded as `PRESENT` in Room 101 and `ABSENT` in Room 102 during the same session is flagged as a high-severity conflict.
- **Unknown Student (`UNKNOWN_USN`)**: A USN not found in the institutional `students` table is flagged.
- **Missing Room/Branch (`MISSING_ROOM`, `MISSING_BRANCH`)**: Attendance records lacking physical room assignments or department codes are blocked from summarisation.

---

## 6. Agent Workflow and Tool Selection

### 6.1 Tool Registry Architecture
All system tools are registered with strict JSON-schema parameter specifications inside `ToolRegistry` ([`app/agent.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/app/agent.py)):

1. `read_csv_tool`: Ingests `.csv` files into normalized tabular DataFrames.
2. `read_photo_tool`: Processes image paths through EasyOCR, returning rows with confidence ratings.
3. `validate_tool`: Evaluates record arrays against institutional rosters and integrity rules.
4. `summary_tool`: Aggregates room-wise and branch-wise statistics from validated records.
5. `query_tool`: Executes safe, parameterized read-only queries against SQLite.
6. `export_tool`: Compiles summary reports into verified `.xlsx` and `.pdf` files.

### 6.2 Pipeline Ordering Enforcement
To prevent the agent or external callers from bypassing validation, `ToolRegistry` enforces request-scoped state tracking:
```python
if tool_name in ("summary_tool", "export_tool"):
    if request_id not in self.validated_requests:
        raise PermissionError(
            f"Pipeline order violation: validate_tool must be successfully executed "
            f"for this request before {tool_name} can be called."
        )
```
Whenever `validate_tool` finishes with zero errors, `request_id` is added to `self.validated_requests`. If errors exist, the ID is never added, rendering subsequent summary calls impossible.

### 6.3 Anti-Hallucination Guardrails
To prevent generative fabrication of figures:
- Database inquiries check whether target tables or sessions exist.
- Questions referencing non-existent sessions (`TC-05`) or metrics outside the schema like exam scores or GPAs (`TC-14`) bypass SQL generation and immediately return:
  ```text
  "I do not have that data."
  ```

---

## 7. Comprehensive Testing Methodology

### 7.1 Test Environment and Configuration
The testing harness was verified on the following host environment:
- **Operating System**: Microsoft Windows 11 (64-bit)
- **Python Runtime**: Python 3.13.7 (Win32 architecture)
- **Testing Framework**: PyTest 9.0.3 with plugins `anyio 4.13.0`, `platformdirs 4.13.5`, `asyncio 1.3.0`, `timeout 2.4.0`
- **Core Dependencies**: `pandas 2.2.3`, `openpyxl 3.1.5`, `reportlab 4.2.5`, `easyocr 1.7.2`, `torch 2.6.0+cpu`

### 7.2 PyTest Test Suite Breakdown
The complete automated test suite comprises 155 tests across 8 test suites:

| Suite Name | Test File Path | Tests | Focus Area | Status |
| :--- | :--- | :---: | :--- | :---: |
| **Agent Core** | [`tests/test_agent.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_agent.py) | 15 | End-to-end orchestration, genuine EasyOCR inference, ordering permissions | **PASS** |
| **Database CRUD** | [`tests/test_database.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_database.py) | 17 | Relational schema, foreign keys, transaction rollbacks, bulk inserts | **PASS** |
| **Export Tool** | [`tests/test_export_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_export_tool.py) | 5 | Excel sheet structures, PDF magic signatures, directory creation | **PASS** |
| **Photo Tool** | [`tests/test_photo_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_photo_tool.py) | 77 | CV2 preprocessing, deskewing, tick marks, EasyOCR fallback, vision mocking | **PASS** |
| **Query Tool** | [`tests/test_query_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_query_tool.py) | 12 | SQL injection immunity, semicolon blocking, table whitelist, read-only AST | **PASS** |
| **Reconciliation** | [`tests/test_reconciliation.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_reconciliation.py) | 5 | Mathematical reconciliation across 5 sessions against pre-calculated totals | **PASS** |
| **Environment** | [`tests/test_sample.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_sample.py) | 2 | Runtime arithmetic and package namespace imports | **PASS** |
| **Tools Suite** | [`tests/test_tools.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_tools.py) | 22 | CSV edge cases, validation rules, 4-state summary metrics, zero division | **PASS** |
| **Total** | | **155** | **Zero Failures, Zero Skips** | **PASS** |

### 7.3 Evaluation Benchmark Harness
The evaluation harness (`scripts/evaluate_agent.py`) executes 15 official benchmark scenarios (`TC-01` through `TC-15`) designed to probe every operational permutation:
- CSV processing, photo extraction, database queries, summaries, and exports.
- Safety boundaries at 0.79 vs 0.80 confidence.
- Parameterized validation failures (missing rooms, missing branches, duplicates).
- Direct permission bypass attacks and SQL injection attempts.

---

## 8. Detailed Test Cases and Verification Results

The table below documents the 15 official evaluation scenarios evaluated across two consecutive deterministic runs:

| Test ID | Scenario Name | Input / Setup | Expected Tool Sequence | Expected Outcome | Actual Result | Status |
| :---: | :--- | :--- | :--- | :--- | :--- | :---: |
| `TC-01` | Valid CSV Input | Clean CSV with 4 valid students in `LH-101` / `LH-102` | `read_csv_tool, validate_tool, summary_tool` | Pipeline completes; confirmed summary generated | Tools invoked; summary matches 75.0% | **PASS** |
| `TC-02` | Valid Photo Input | Synthetic clean sheet image (`sheet_clean.jpg`) | `read_photo_tool, validate_tool, summary_tool` | OCR extracts rows; validates cleanly; summarises | 8 rows extracted; 100% confirmed rate | **PASS** |
| `TC-03` | Valid Data with Summary Request | CSV input with explicit text asking for summary | `read_csv_tool, validate_tool, summary_tool` | Summary computed strictly after validation | Validation confirmed; summary generated | **PASS** |
| `TC-04` | DB Absentees in Existing Session | Natural language query for absentees in `SESS-20261024-01` | `query_tool` | Returns exact absent student names from SQLite | `Bob Jones`, `Aditi Patel` returned | **PASS** |
| `TC-05` | DB Nonexistent Session | Query for non-existent session `SESS-UNKNOWN-999` | `query_tool` | Anti-hallucination return: `"I do not have that data."` | Exact string returned; no invented figures | **PASS** |
| `TC-06` | CSV with Duplicate USNs | CSV containing identical USN `1MS21CS001` in two rows | `read_csv_tool, validate_tool` | Halts before `summary_tool`; flags `DUPLICATE_USN` | `needs_confirmation=True`; summary blocked | **PASS** |
| `TC-07` | CSV with Conflicting Statuses | Student marked `PRESENT` in `LH-101` and `ABSENT` in `LH-102` | `read_csv_tool, validate_tool` | Halts before `summary_tool`; flags `CONFLICTING_STATUS` | `needs_confirmation=True`; summary blocked | **PASS** |
| `TC-08` | Photo Row Confidence 0.79 | Photo row injected with confidence `0.79` | `read_photo_tool` | Halts before `summary_tool`; requires confirmation | `needs_confirmation=True`; summary blocked | **PASS** |
| `TC-09` | Photo Row Confidence 0.80 | Photo row with confidence `0.80` (Clean vs Bad) | `read_photo_tool, validate_tool, summary_tool` | 0.80 passes confidence; subcase duplicate halts at val | Passes threshold; bad row caught by validator | **PASS** |
| `TC-10` | Missing Room or Branch | Subcase 10a: missing room. Subcase 10b: missing branch | `read_csv_tool, validate_tool` | Validation halts before summary; flags missing metadata | `MISSING_ROOM` and `MISSING_BRANCH` caught | **PASS** |
| `TC-11` | Export Verified Summary to Excel | Clean CSV with request to export as Excel | `read_csv_tool, validate_tool, summary_tool, export_tool` | Generates openable `.xlsx` file with valid sheets | `.xlsx` verified openable with OpenPyXL | **PASS** |
| `TC-12` | Export Verified Summary to PDF | Clean CSV with request to export as PDF | `read_csv_tool, validate_tool, summary_tool, export_tool` | Generates valid `.pdf` with `%PDF-` header | `.pdf` verified with ReportLab/PyPDF | **PASS** |
| `TC-13` | Unsupported File Type | File upload with extension `.xyz` | `(None)` | Returns controlled error; calls no processing tools | Error returned; zero tools misinvoked | **PASS** |
| `TC-14` | Unanswerable Database Query | Question regarding exam scores in `SESS-20261024-01` | `query_tool` | Anti-hallucination return: `"I do not have that data."` | Exact string returned; no numbers invented | **PASS** |
| `TC-15` | Validation Bypass Attempt | Request: "Summarize without validating" & Direct API call | `(None)` | Both natural language & direct `registry.execute` blocked | Direct API call raised `PermissionError` | **PASS** |

---

## 9. Photo OCR Pipeline and Confidence Boundary Handling

### 9.1 Multi-Stage Image Processing Pipeline
When an image is submitted to `read_photo_tool`, it undergoes systematic image conditioning before text extraction:
1. **Grayscale Conversion**: Eliminates color variance caused by classroom lighting.
2. **Deskewing**: Calculates orientation angle using Hough line transforms and rotates image to horizontal alignment.
3. **Adaptive Thresholding (Otsu / Sauvola)**: Binarizes handwritten and printed text against paper grain.
4. **Cell Localization**: Employs morphological kernel operations to isolate tabular grid boundaries.
5. **EasyOCR Text & Mark Extraction**: Executes deep convolutional neural network (CNN) inference to detect text tokens and checkmark symbols (`✓`, `✔`, `P`, `1`, `✗`, `A`, `0`).

### 9.2 The 0.80 Confidence Threshold Boundary
OCR accuracy over handwritten sheets is non-deterministic. Therefore, RollCall AI enforces a strict boundary at `CONFIDENCE_CONFIRMATION_THRESHOLD = 0.80`:
- **Scenario `TC-08` (Confidence 0.79)**: When an extracted row has confidence `0.79`, the agent logs:
  `"Extraction confidence below 0.80 detected. User confirmation required before proceeding."`
  The agent sets `needs_confirmation = True` and **never calls `summary_tool`**.
- **Scenario `TC-09` (Confidence 0.80)**: When a row has confidence `0.80`, it passes the confidence filter. However, meeting `0.80` **does not bypass validation**. In subcase `TC-09b`, a row with `0.80` confidence but a duplicate USN successfully passes the confidence check but is immediately flagged and blocked by `validate_tool`.

---

## 10. Database Security, Guardrails, and Data Integrity

### 10.1 SQL Injection Immunity & Read-Only Enforcement
Database access through `query_tool` enforces multi-tiered security in [`tools/query_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tools/query_tool.py):
1. **Mutation Rejection**: Regular expressions and keyword parsers reject any SQL command starting with or containing `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `REPLACE`, `EXEC`, or `CREATE`.
2. **Multi-Statement Blocking**: Any SQL query containing semicolons (`;`) is rejected with:
   `ValueError("Multiple SQL statements are not allowed for security reasons.")`
3. **Table Allowlister**: Queries are restricted to authorized schema tables: `students`, `rooms`, `sessions`, and `attendance`. Queries attempting to access system tables (`sqlite_master`, `sqlite_sequence`) or unauthorized tables (`users`, `passwords`) raise an immediate `ValueError`.
4. **Parameterized Statements**: All filters (`session_id`, `room_id`, `usn`) are passed as parameterized tuples (`?`), preventing variable escaping attacks.

### 10.2 Credential Sanitization in Tool Logs
The `ToolLogger` inspects all arguments prior to recording:
- Sensitive keys (`api_key`, `secret`, `token`, `password`) are replaced with `[REDACTED]`.
- Large binary payloads (e.g. image byte buffers, DataFrame matrices) are summarized as `<DataFrame with N records>` to prevent memory leaks and unpicklable object errors during serialization.

---

## 11. Export Tool Implementation and File Validation

### 11.1 Excel Report Generation (`tools/export_tool.py`)
- Employs `openpyxl` to build structured workbooks.
- Creates three distinct worksheets:
  1. `Room_Summary`: Room ID, present count, absent count, unresolved count, total count, confirmed percentage.
  2. `Branch_Summary`: Branch code, present count, absent count, unresolved count, total count, confirmed percentage.
  3. `Overall_Summary`: Institution-level aggregation metrics.
- Formats headers with navy fill (`#1F4E78`), white bold text, thin border grids, and two-decimal numerical formatting (`0.00%`).
- Verified by opening with `openpyxl.load_workbook()` and asserting sheet names and non-empty row counts.

### 11.2 PDF Report Generation (`tools/export_tool.py`)
- Employs `reportlab.platypus` with `SimpleDocTemplate`, `Table`, `Paragraph`, and `Spacer`.
- Formats summary tables with alternating row shading, bold headers, and timestamps.
- Verified by inspecting the binary header (`%PDF-1.4`) and end-of-file trailer (`%%EOF`).

---

## 12. Warnings, Limitations, and Untested Areas

### 12.1 External PyTorch / EasyOCR Deprecation Warnings
During the 155-test PyTest run, **10 warnings** were emitted by underlying third-party dependencies:
1. `DeprecationWarning: torch.ao.quantization is deprecated and will be removed in 2.10`: Emitted 4 times from EasyOCR's `detection.py` and `recognition.py` calling `torch.quantization.quantize_dynamic`.
2. `UserWarning: 'pin_memory' argument is set as true but no accelerator is found`: Emitted 6 times from PyTorch CPU DataLoader in EasyOCR.

**Assessment**: These warnings originate within the external EasyOCR library (version 1.7.2) when running on CPU without CUDA accelerators. They do not affect execution correctness, mathematical results, or test outcomes.

### 12.2 Documented Limitations & Untested Areas
- **Browser User Interface**: User interface components (Streamlit) were not part of Phase 1 or Phase 2 scope and were not tested in the pre-UI audit.
- **Production Roster Integration**: All tests utilized synthetic student rosters (200 records); deployment against institutional LDAP or Active Directory was not tested.
- **Extreme Handwriting Variance**: While verified against synthetic handwriting test sheets, real-world crumpled, low-resolution, or severely degraded paper sheets remain subject to human confirmation flows.
- **Concurrency & High Load**: SQLite is configured for single-writer concurrency; high-throughput simultaneous multi-user writes were not benchmarked.

---

## 13. Developer Reproducibility Guide

To reproduce the exact audit results on a clean machine:

### Step 1: Environment Setup
```bash
# Clone repository
git clone git@github.com:Yatish-balu/Roll_Call.git
cd Roll_Call

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install required dependencies
pip install -r requirements.txt
pip install pytest openpyxl reportlab easyocr torch torchvision
```

### Step 2: Database Initialization & Synthetic Seed
```bash
# Initialize SQLite schema and seed 200 synthetic students across 5 sessions
python tools/database.py
```

### Step 3: Run Full PyTest Test Suite
```bash
# Execute all 155 unit and integration tests with verbose reporting
python -m pytest -v
```
*Expected Result*: `155 passed, 10 warnings in ~30s`.

### Step 4: Run Agent Evaluation Harness
```bash
# Execute the 15-scenario evaluation runner
python scripts/evaluate_agent.py
```
*Expected Result*: `15 passed, 0 failed, 15/15 (100.0%) tool selection accuracy`.

### Step 5: Run Standalone CLI Demonstration
```bash
# Execute the 5-scenario demo showcasing all capabilities
python demo_agent.py
```

---

## 14. Requirements-to-Evidence Traceability Matrix

| Requirement ID | Requirement Description | Implementation File | Verification Test File | Specific Test Function / Scenario | Audit Outcome |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **REQ-01** | Multi-modal CSV ingestion | [`tools/read_csv_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tools/read_csv_tool.py) | [`tests/test_tools.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_tools.py) | `test_read_csv_valid`, `TC-01` | **VERIFIED** |
| **REQ-02** | Multi-modal photo OCR ingestion | [`tools/read_photo_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tools/read_photo_tool.py) | [`tests/test_agent.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_agent.py) | `test_photo_genuine_ocr_pipeline`, `TC-02` | **VERIFIED** |
| **REQ-03** | Roster validation & unknown USNs | [`tools/validate_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tools/validate_tool.py) | [`tests/test_tools.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_tools.py) | `test_validate_unknown_usn` | **VERIFIED** |
| **REQ-04** | Duplicate USN detection | [`tools/validate_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tools/validate_tool.py) | [`tests/test_tools.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_tools.py) | `test_validate_duplicate_usn`, `TC-06` | **VERIFIED** |
| **REQ-05** | Conflicting room status detection | [`tools/validate_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tools/validate_tool.py) | [`tests/test_tools.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_tools.py) | `test_validate_conflicting_statuses_for_same_student`, `TC-07` | **VERIFIED** |
| **REQ-06** | Four-state attendance model | [`tools/summary_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tools/summary_tool.py) | [`tests/test_tools.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_tools.py) | `test_summary_four_state_metrics_and_confirmed_percentage` | **VERIFIED** |
| **REQ-07** | Zero-division mathematical safety | [`tools/summary_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tools/summary_tool.py) | [`tests/test_tools.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_tools.py) | `test_summary_empty_and_zero_division` | **VERIFIED** |
| **REQ-08** | OCR 0.80 confidence guardrail | [`app/agent.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/app/agent.py) | [`scripts/evaluate_agent.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/scripts/evaluate_agent.py) | `TC-08`, `TC-09` | **VERIFIED** |
| **REQ-09** | Pipeline validation ordering | [`app/agent.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/app/agent.py) | [`tests/test_agent.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_agent.py) | `test_agent_bypassing_validation_raises_error`, `TC-15` | **VERIFIED** |
| **REQ-10** | SQL injection & mutation blocking | [`tools/query_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tools/query_tool.py) | [`tests/test_query_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_query_tool.py) | `test_safe_sql_blocks_mutations`, `test_safe_sql_blocks_multi_statements` | **VERIFIED** |
| **REQ-11** | Anti-hallucination query response | [`tools/query_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tools/query_tool.py) | [`scripts/evaluate_agent.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/scripts/evaluate_agent.py) | `TC-05`, `TC-14` | **VERIFIED** |
| **REQ-12** | Validated Excel export | [`tools/export_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tools/export_tool.py) | [`tests/test_export_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_export_tool.py) | `test_export_to_excel_valid_data`, `TC-11` | **VERIFIED** |
| **REQ-13** | Validated PDF export | [`tools/export_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tools/export_tool.py) | [`tests/test_export_tool.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_export_tool.py) | `test_export_to_pdf_valid_data`, `TC-12` | **VERIFIED** |
| **REQ-14** | Structured tool execution logging | [`app/agent.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/app/agent.py) | [`tests/test_agent.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/tests/test_agent.py) | `test_tool_logging_and_metadata` | **VERIFIED** |
| **REQ-15** | Benchmark runner & report generator | [`scripts/evaluate_agent.py`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/scripts/evaluate_agent.py) | [`reports/`](file:///c:/Users/Bhanu%20Prasad/OneDrive/Desktop/Ai_proj/Roll_Call/reports/) | Dual runs comparing deterministic output | **VERIFIED** |

---

## 15. Final Results and Readiness Assessment

### 15.1 Summary of Verified Capabilities
Through the completion of Prompt 6 and the pre-UI verification audit:
- The core data model, relational SQLite schema, and CRUD layer are verified mathematically.
- The 4-state attendance model (`PRESENT`, `ABSENT`, `PENDING`, `UNREVIEWED`) prevents false classifications and division-by-zero errors.
- The computer vision OCR pipeline reads attendance sheets and accurately flags low confidence below `0.80`.
- The database querying engine enforces read-only access and anti-hallucination safeguards.
- The agent orchestrator enforces strict pipeline ordering, preventing summary or export execution on unvalidated data.
- The evaluation harness benchmarks all 15 scenarios with 100.0% tool-selection accuracy.

### 15.2 Formal Readiness Verdict

# **PRE-UI VERIFICATION STATUS: PASS**

> **Core Engine Readiness**: The core backend architecture, tools, security invariants, and evaluation benchmarks are **fully verified, mathematically sound, and deterministic**. All 155 PyTest tests and all 15 evaluation scenarios pass with zero failures. The project is officially ready for Phase 3 (Streamlit User Interface implementation).
