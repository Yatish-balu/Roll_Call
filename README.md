# RollCall AI — Intelligent Attendance Summary Agent

RollCall AI is a multi-modal attendance aggregation, validation, and reporting agent built for academic institutions and large-scale training environments. It ingests CSV spreadsheets and photographs of paper attendance sheets, extracts and validates every student record, and produces certified room-wise and branch-wise attendance summaries plus Excel and PDF reports. It is designed around a **deterministic tool-calling architecture** where generative AI is used only for orchestration and image understanding, while the mathematical aggregation, validation, and querying are handled by code tools.

---

## What the Project Does

- **Ingest CSV attendance files** with flexible column names (for example `Student USN`, `Room`, `Dept`) and clean them into a standardized table.
- **Ingest photos of attendance sheets** using a computer-vision pipeline (OpenCV preprocessing plus EasyOCR), returning one row per student with an extracted status and a confidence score.
- **Validate attendance records** against institutional rules: required columns, duplicate USNs, conflicting statuses for the same student, unknown students, missing rooms, missing branches, blank status, and invalid status values.
- **Summarize confirmed attendance** room-wise and branch-wise, using a strict four-state model: `PRESENT`, `ABSENT`, `PENDING`, `UNREVIEWED`.
- **Query the database safely** with read-only, parameterized SQL and high-level attendance/session/student queries.
- **Export verified summaries** to styled Excel workbooks and formatted PDF reports.
- **Orchestrate the workflow** through an agent that enforces the pipeline order: read → validate → confidence check → summarize → export.
- **Protect against hallucination and abuse** by blocking unsafe SQL, refusing to summarize unvalidated data, and returning a controlled “I do not have that data.” message when information is not available.

---

## Project Vision and Key Design Decisions

Traditional attendance tools often force ambiguous rows into binary outcomes by marking faint or unreadable entries as absent, or by defaulting unverified rows to present. That distorts attendance rates and hides records that need human review. RollCall AI takes a different path:

- **Four-state attendance model** — `PRESENT`, `ABSENT`, `PENDING`, and `UNREVIEWED` are kept separate. Confirmed attendance percentages are computed only from verified rows.
- **Explicit confidence handling for photos** — rows extracted from images carry a confidence score. Rows below the project’s confirmation threshold stop the pipeline and require human review instead of being silently accepted.
- **Validation is a hard prerequisite** — summary and export tools refuse to run unless validation has succeeded for that request. That prevents summarizing or exporting bad data.
- **Deterministic aggregation** — percentages, counts, and query results come from code, not from a generative model. If information is missing, the system says so directly.
- **Read-only database access** — the query layer allows only `SELECT`-style reads on allowlisted tables and rejects mutations and multi-statement injection.

---

## Architecture

RollCall AI is organized into three logical layers:

1. **User interaction layer**
   - A FastAPI backend exposes a small REST surface plus an optional launcher path for the Streamlit UI.
   - A Streamlit dashboard gives end users three tabs: upload and review, dashboard and analytics, and a chat-style “Ask RollCall AI” assistant.

2. **Agent orchestration layer**
   - `AttendanceAgent` interprets user intent, selects tools, enforces pipeline ordering, evaluates confidence, and logs structured tool calls.
   - `ToolRegistry` stores registered tool definitions and enforces request-scoped rules such as “summary requires prior successful validation.”
   - `ToolLogger` records each tool invocation duration, outcome, and a sanitized argument summary that redacts sensitive keys.

3. **Deterministic tool layer**
   - `read_csv_tool` reads and normalizes CSV attendance data.
   - `read_photo_tool` preprocesses images and extracts attendance rows with confidence, with an OCR fallback path.
   - `validate_tool` checks records against rules and optional master rosters/rooms.
   - `summary_tool` computes room-wise, branch-wise, and overall attendance metrics.
   - `query_tool` performs safe read-only database queries and structured attendance/session/student lookups.
   - `export_tool` writes Excel and PDF exports from a validated summary.

Data persistence lives in a small SQLite layer with four tables: `students`, `rooms`, `sessions`, and `attendance`.

---

## Data Model and Attendance States

The database has four core tables:

- **students** — `usn`, `name`, `branch`
- **rooms** — `room_id`, `name`
- **sessions** — `session_id`, `date`, `subject`
- **attendance** — `session_id`, `usn`, `room_id`, `status`, `source`, `confidence`

Attendance uses a four-state model:

- `PRESENT` — verified present
- `ABSENT` — verified absent
- `PENDING` — status not yet confirmed or check-in pending
- `UNREVIEWED` — ambiguous, low-confidence, or illegible

The confirmed attendance percentage is computed strictly as:

```
PRESENT / (PRESENT + ABSENT) * 100
```

If there are no confirmed rows, the result is `0.00%` rather than crashing with a division error. `PENDING` and `UNREVIEWED` are preserved as unresolved counts and are not folded into the confirmed percentage.

---

## How Processing Works

### CSV path

1. The CSV reader normalizes headers, strips whitespace, drops fully empty rows, and returns a clean DataFrame.
2. The validator checks required columns, duplicate USNs, conflicting statuses, unknown students/rooms, missing rooms/branches, and invalid or blank statuses.
3. If validation passes, the summary tool computes room-wise and branch-wise metrics.
4. If an export was requested, the export tool writes an Excel or PDF file from the summary.

### Photo path

1. The image is preprocessed (grayscale, denoising, deskewing, adaptive thresholding).
2. A vision backend is tried first; if it is unavailable or returns bad JSON, the tool falls back to EasyOCR.
3. Each extracted row gets a normalized status and a confidence score.
4. If confidence is below the project threshold, the pipeline stops and asks for confirmation.
5. Otherwise the rows proceed into validation and then summary/export, exactly like CSV data.

### Query path

1. The agent parses the question and routes it to the query tool.
2. The query tool runs a validated, read-only query against the SQLite database.
3. If the requested information does not exist, the response uses the project’s controlled fallback message rather than inventing numbers.

---

## Tech Stack and Dependencies

Core Python dependencies from `requirements.txt`:

- `fastapi` — web API framework
- `uvicorn[standard]` — ASGI server
- `pandas` — tabular data handling
- `openpyxl` — Excel generation
- `reportlab` — PDF generation
- `pytest` — test runner
- `python-dotenv` — environment variable loading
- `streamlit` — web UI

Additional capabilities used by parts of the project:

- `sqlite3` — built-in database
- `opencv-python` / `cv2` — image preprocessing for photo extraction
- `numpy` — image array handling
- `Pillow` — image support
- `easyocr` — OCR fallback for attendance sheet photos
- `google-generativeai` — optional vision LLM backend for photo extraction when an API key is available

Optional environment variables:

- `GEMINI_API_KEY` — enables the Gemini vision path in photo extraction
- `PHOTO_LLM_MODEL` — Gemini model to use (default: `gemini-2.0-flash`)
- `PHOTO_MIN_CONFIDENCE` — minimum confidence threshold for photo rows (default: `0.5`)
- `PHOTO_OCR_GPU` — set to `1` to enable EasyOCR GPU mode (default: `0`)
- `DATABASE_PATH` — path to the SQLite database (default: `data/attendance.db`)

---

## Project Structure

```text
Roll_Call/
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI entrypoint and optional Streamlit launcher
│   ├── ui.py                 # Streamlit dashboard (upload, dashboard, ask tabs)
│   ├── agent.py              # AttendanceAgent, ToolRegistry, ToolLogger, guardrails
│   └── db/
│       ├── __init__.py
│       ├── connection.py     # SQLite connection factory
│       ├── schema.py         # Table DDL and index definitions
│       ├── crud.py           # Database create/read/update helpers
│       └── connection.py     # Connection helpers used by tools and UI
├── tools/
│   ├── __init__.py           # Public tool exports
│   ├── read_csv_tool.py      # CSV reading and header normalization
│   ├── read_photo_tool.py    # Photo preprocessing + LLM/OCR extraction
│   ├── validate_tool.py      # Attendance validation rules and result objects
│   ├── summary_tool.py       # Room-wise and branch-wise summary metrics
│   ├── query_tool.py         # Safe read-only querying and high-level query helpers
│   ├── export_tool.py        # Excel and PDF export generation
│   └── database.py           # DB initialization, inspection, and synthetic seed data
├── data/
│   ├── .gitkeep
│   ├── test1.csv             # Small sample CSV for local smoke testing
│   ├── attendance.db         # SQLite database file (generated/used at runtime)
│   └── photos/               # Test photos for the photo extraction pipeline
├── tests/
│   ├── __init__.py
│   ├── test_sample.py        # Basic environment sanity tests
│   ├── test_tools.py         # CSV, validation, and summary tool tests
│   ├── test_photo_tool.py    # Photo preprocessing and extraction tests
│   ├── test_agent.py         # Agent orchestration, guardrails, and pipeline tests
│   ├── test_database.py      # Schema and CRUD tests
│   ├── test_reconciliation.py # Mathematical reconciliation checks
│   ├── test_query_tool.py    # Safe SQL and query dispatcher tests
│   ├── test_export_tool.py   # Excel/PDF export tests
│   ├── test_ui.py            # Streamlit UI logic tests
│   └── agent_test_cases.py   # Declared agent benchmark scenarios
├── scripts/
│   ├── evaluate_agent.py     # Automated agent evaluation runner
│   └── generate_complete_report_pdf.py # ReportLab PDF report generator script
├── reports/                  # Generated evaluation and test-report artifacts
├── docs/                     # Project documentation folder
├── .env.example              # Template environment configuration
├── .gitignore                # Version-control ignore rules
├── requirements.txt          # Python dependencies
└── README.md                 # This file
```

---

## How to Download and Set Up the Project

### Prerequisites

- Python 3.10 or later
- Git (if cloning from a remote repository)

### 1. Get the project code

If the project is hosted in a Git repository, clone it:

```bash
git clone <repository-url>
cd Roll_Call
```

If you already have the files locally, skip the clone and open the `Roll_Call` folder.

### 2. Create and activate a virtual environment

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS/Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

If you plan to use photo extraction with the Gemini vision backend, also make sure the optional Gemini client library is available in your environment.

### 4. Configure environment variables

Copy the example file:

**Windows (PowerShell):**

```powershell
copy .env.example .env
```

**macOS/Linux:**

```bash
cp .env.example .env
```

Edit `.env` if you need custom values. At minimum, the project is designed to run with a local SQLite database at `data/attendance.db`.

If you want photo extraction to use the Gemini vision path, set `GEMINI_API_KEY` in `.env`.

### 5. Initialize the database (optional but typical for local development)

```bash
python -m tools.database
```

This initializes the schema and seeds synthetic sample data so the project has students, rooms, sessions, and attendance records to work with locally.

To inspect the database instead of initializing it:

```bash
python -m tools.database --inspect
```

---

## Running the Application

### FastAPI backend

```bash
uvicorn app.main:app --reload --port 8000
```

After it starts:

- API root: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- Interactive API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- ReDoc: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

### Streamlit UI

```bash
streamlit run app/ui.py --server.port 8501 --server.headless false
```

The UI provides three tabs:

1. **Upload & Review** — upload a CSV or photo, process it through the agent, review validation issues, edit records, and save confirmed attendance to the database.
2. **Dashboard & Analytics** — view room-wise and branch-wise summaries and download Excel or PDF exports.
3. **Ask RollCall AI** — ask natural-language questions about attendance, absentees, sessions, or students.

---

## Running the Tests

```bash
pytest
```

For verbose output:

```bash
pytest -v
```

To run a specific test file:

```bash
pytest Roll_Call/tests/test_tools.py -v
```

---

## Agent Evaluation Harness

The project includes an automated agent benchmark runner:

```bash
python scripts/evaluate_agent.py
```

This runs the declared benchmark scenarios and writes evaluation artifacts under `reports/`.

---

## Demo Script

A standalone demo script is available for local walkthroughs:

```bash
python demo_agent.py
```

---

## Notes on Test Photos and Sample Data

- A small sample CSV (`data/test1.csv`) is provided for quick local testing.
- Synthetic test photos are generated under `data/photos/` so the photo pipeline can be tested without manually collecting images.
- The database seed script creates 200 synthetic students across four branches, six rooms, and five sessions.

---

## Security and Safety Notes

- The query layer is designed to be read-only and to reject mutation keywords and multi-statement SQL.
- Tool logs sanitize sensitive keys such as `api_key`, `secret`, and `token`.
- The agent does not summarize or export until validation has succeeded for that request.
- Photo rows with low confidence stop the pipeline for human review rather than being silently accepted.

---

## Current Development Status

The core engine, tools, agent orchestration, database layer, query security, export generation, and agent evaluation harness are implemented and tested. The project also has a Streamlit UI and UI-level tests. Recent local test runs of the full test suite have passed with a large majority of tests passing and a single skipped photo pipeline test that is skipped by design rather than failing.

For the most recent detailed test outcomes, see the generated report files under `Roll_Call/reports/`.

---

## Documentation in This Repository

- `docs/README.md` — documentation index
- `reports/` — generated evaluation and test-report artifacts
- This `README.md` — project overview, setup, architecture, and usage

---

## License and Usage

This project is intended for attendance processing, validation, and reporting workflows. Adjust configuration, data, and deployment to your institution’s rules and privacy requirements before using it with real student data.
