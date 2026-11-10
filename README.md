# RollCall AI — Intelligent Attendance Summary Agent

RollCall AI is a multi-modal attendance aggregation, validation, and reporting platform built for academic institutions and training environments. It ingests CSV spreadsheets and photographs of paper attendance sheets, validates student attendance against institutional constraints, and produces certified room-wise and branch-wise attendance summaries along with automated Excel and PDF reports.

Designed as a modular monorepo, RollCall AI decouples a deterministic Python/FastAPI backend from future frontend clients, combining code-level mathematical rigor, four-state attendance modeling, cryptographic Bearer JWT authentication with Role-Based Access Control (RBAC), and deterministic tool orchestration.

---

## Database Architecture & Dual-Backend Setup

- **Cloud-first production**: Supabase PostgreSQL is the production source of truth. SQLite is retained for local development, isolated tests, and optional offline capabilities only.
- **Environment Variables**: Managed in `.env` using `DB_BACKEND` (`supabase` | `sqlite`), `DATABASE_URL_SYNC` (authoritative write URL for production), `READONLY_DATABASE_URL` (read-only replica), `SQLITE_PATH` (`data/attendance.db`), and `APP_ENV` (`development` | `production`).
- **Production requirements**: When `APP_ENV=production`, `DB_BACKEND=supabase` and `DATABASE_URL_SYNC` are mandatory. A deliberate connectivity check runs at startup; a failed Supabase connection is reported clearly and never silently falls back to SQLite.
- **SSL**: PostgreSQL connections require SSL (`sslmode=require` for psycopg, `ssl=require` for asyncpg).
- **How to Switch Backends**: Set `DB_BACKEND=supabase` or `DB_BACKEND=sqlite` in `.env`; all application and query layers adapt without code modifications.
- **Data Synchronization**: No automatic dual writes or SQLite-to-Supabase synchronization. Run `python backend/scripts/sync.py` only for manual, operator-initiated copies between environments.
- **Alembic Migrations**: Alembic manages schema for both backends using `DATABASE_URL_SYNC`.

---

## Monorepo Project Structure

```text
Roll_Call/
├── backend/                                   # Python FastAPI Backend API & Services
│   ├── app/                                   # Application core package
│   │   ├── __init__.py
│   │   ├── main.py                            # FastAPI entrypoint, CORS, exception handlers & routing
│   │   ├── agent.py                           # AttendanceAgent: tool execution loop, guardrails & validation
│   │   ├── dependencies.py                    # Database dependency injection (get_db)
│   │   ├── ui.py                              # Legacy Streamlit UI interface
│   │   ├── auth/                              # Authentication & Authorization (Supabase-compatible)
│   │   │   ├── __init__.py
│   │   │   ├── dependencies.py                # get_current_user, require_roles (ADMIN, FACULTY, VIEWER)
│   │   │   ├── jwt.py                         # Cryptographic JWT verification (HS256/RS256, expiration, issuer)
│   │   │   ├── rate_limiter.py                # In-memory sliding-window rate limiter
│   │   │   └── roles.py                       # Role hierarchy & normalization engine
│   │   ├── db/                                # Database & ORM layer
│   │   │   ├── __init__.py
│   │   │   ├── base.py                        # SQLAlchemy DeclarativeBase
│   │   │   ├── connection.py                  # Database engine & canonical path resolver
│   │   │   ├── crud.py                        # Dual-mode CRUD operations (SQLAlchemy ORM + SQLite)
│   │   │   ├── models.py                      # SQLAlchemy ORM models (Student, Room, Session, Attendance)
│   │   │   └── schema.py                      # Raw SQLite DDL schema creation helpers
│   │   ├── routers/                           # FastAPI API v1 Endpoints
│   │   │   ├── __init__.py
│   │   │   ├── agent.py                       # /api/v1/agent (Chat, File-Upload, Confirmation, Status)
│   │   │   ├── analytics.py                   # /api/v1/analytics (Session, Date & Overview summaries)
│   │   │   ├── attendance.py                  # /api/v1/attendance (Records, Bulk, Reconcile, Deletion)
│   │   │   ├── reports.py                     # /api/v1/reports (Excel & PDF report exports)
│   │   │   ├── rooms.py                       # /api/v1/rooms (Room master data, search & pagination)
│   │   │   ├── sessions.py                    # /api/v1/sessions (Session master data, search & pagination)
│   │   │   └── students.py                    # /api/v1/students (Student master data, search & pagination)
│   │   └── schemas/                           # Pydantic v2 validation models
│   ├── tools/                                 # Specialized Agent Attendance Tools
│   │   ├── export_tool.py                     # ReportLab PDF & openpyxl Excel report generation
│   │   ├── query_tool.py                      # Parameterized, read-only SQL inspection tool
│   │   ├── read_csv_tool.py                   # CSV ingestion, header normalization & validation
│   │   ├── read_photo_tool.py                 # EasyOCR / Gemini Vision photo attendance extraction
│   │   ├── summary_tool.py                    # Four-state metrics aggregation
│   │   └── validate_tool.py                   # Roster and rule validation guardrail
│   ├── tests/                                 # Pytest test suite (332 passing tests)
│   ├── alembic/                               # Alembic migration environment
│   ├── scripts/                               # Evaluation & benchmarking utilities
│   ├── alembic.ini                            # Migration runner configuration
│   ├── pytest.ini                             # Backend test runner configuration
│   ├── requirements.txt                       # Backend Python dependencies
│   └── .env.example                           # Backend environment template
│
├── frontend/                                  # Next.js + TypeScript Web Client (Planned: Phase 7.1)
│   └── (Reserved for upcoming Next.js client initialization)
│
├── data/                                      # Data assets & Local SQLite Database
│   ├── attendance.db                          # Primary SQLite development database (SHA256 verified)
│   ├── attendance_backup_before_migration.db  # Pre-migration reference database
│   ├── test1.csv                              # Sample attendance CSV dataset
│   ├── demo/                                  # Demonstration sample datasets
│   └── photos/                                # Sample attendance sheet photos for OCR testing
│
├── docs/                                      # Architectural and system documentation
├── reports/                                   # Evaluation output and testing audit reports
├── .env                                       # Root environment configuration (active credentials)
├── .env.example                               # Root environment configuration template
├── .gitignore                                 # Git ignore rules
├── pytest.ini                                 # Root test runner configuration (discovers backend/tests)
└── README.md                                  # Monorepo documentation
```

---

## Core System Architecture & Features

1. **Deterministic Tool-Calling Architecture:**
   Generative AI (Gemini / Gemma) is strictly bounded to orchestration and vision understanding. Mathematical computations, aggregations, database queries, and validations are exclusively executed by deterministic code tools.

2. **Four-State Attendance Model:**
   - `PRESENT`: Student confirmed present.
   - `ABSENT`: Student confirmed absent.
   - `PENDING`: Missing attendance sheets or unverified roster entries.
   - `UNREVIEWED`: Ambiguous marks, low-confidence OCR, or illegible photos.
   *Confirmed percentage:* `PRESENT / (PRESENT + ABSENT) * 100`. Unverified marks are never forced into binary assumptions.

3. **Role-Based Access Control (RBAC):**
   - `ADMIN`: Full access across master data creation/modification, full attendance administration, and record deletion.
   - `FACULTY`: View master data, upload CSV/photos, record/reconcile attendance, export reports, and chat with AI agent.
   - `VIEWER`: Read-only access to master data, attendance records, analytics, and reports. No database mutations allowed.

4. **Security & Guardrails:**
   - Cryptographic Bearer JWT verification (HS256/RS256, expiration, issuer/audience validation).
   - Privilege escalation defense: User-editable `user_metadata` is never trusted for elevated privileges; only server-controlled `app_metadata` grants roles.
   - Thread-safe sliding-window rate limiter on expensive endpoints (`/agent/chat`, `/agent/process-file`, `/reports/*`).
   - File upload security: Streaming 10 MB limit enforcement, executable binary signature filtering (`MZ`, `ELF`), null-byte checks, and image magic byte validation.
   - Read-only parameterized database queries with SQL injection prevention.

---

## Getting Started

### Prerequisites

- Python 3.10+ (Python 3.13 tested)
- Git

### 1. Clone Repository & Setup Environment

```bash
git clone <repo-url>
cd Roll_Call
```

Create and activate a virtual environment:

```bash
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

Install the backend Python dependencies:

```bash
pip install -r backend/requirements.txt
```

### 3. Environment Configuration

Copy the template to create `.env` in the repository root:

```bash
cp .env.example .env
```

Key environment variables:
- `APP_ENV`: `development` (default) or `production`.
- `JWT_SECRET_KEY`: Minimum 32-character secret key for JWT authentication.
- `DATABASE_URL_SYNC`: Authoritative synchronous write URL for production (Supabase PostgreSQL). Required when `APP_ENV=production` and `DB_BACKEND=supabase`.
- `DATABASE_URL_ASYNC`: Asynchronous URL for Supabase (not currently wired into the FastAPI request path).
- `READONLY_DATABASE_URL`: Read-only replica URL for secure queries. Must not equal `DATABASE_URL_SYNC`.
- `SQLITE_PATH`: Defaults to `data/attendance.db`. Canonical path resolution automatically handles execution from any directory.
- `GEMINI_API_KEY`: Optional; enables Gemini Vision extraction for photo attendance.
- `ALLOWED_ORIGINS`: Comma-separated list of allowed CORS origins (default: safe localhost ports).
- `RATE_LIMIT_ENABLED`: `true` to enforce rate limits on expensive operations.
- `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE`: Connection pool tunables for PostgreSQL.

---

## Running the Backend Application

The backend can be started either from the repository root or from the `backend/` directory:

### Option A: From Repository Root (Recommended)

```bash
python -m uvicorn backend.app.main:app --reload --port 8000
```

### Option B: From `backend/` Directory

```bash
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

### API Endpoints & Interactive Documentation

Once started, navigate to:
- **Interactive Swagger Docs:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc Documentation:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- **Health Check:** [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

### Startup Failure Behaviour (Production)

When `APP_ENV=production`, the application performs a deliberate database connectivity check during startup. If `DB_BACKEND` is not `supabase`, or `DATABASE_URL_SYNC` is missing, or the Supabase connection cannot be established, the application fails to start with a clear error message. SQLite is never used as a silent fallback in production.

---

## Running Tests

All 332 automated tests can be executed from either the repository root or the `backend/` directory:

### From Repository Root

```bash
pytest -v
```

### From `backend/` Directory

```bash
cd backend
pytest -v
```

### Running Specific Test Suites

```bash
# Security & RBAC tests
pytest backend/tests/test_auth_api.py backend/tests/test_security_regression.py -v

# Agent & tool pipeline tests
pytest backend/tests/test_agent_api.py backend/tests/test_tools.py -v
```

---

## Database Management & Migrations

### Database Location

The primary SQLite database is located at:
`data/attendance.db`
Both `data/attendance.db` and `data/attendance_backup_before_migration.db` are SHA256 verified against:
`BC08C731CDF034157B7E676AF12F1AB332654F3E62868864800D9731B3564629`.

### Alembic Migrations

Alembic commands can be run from the repository root or from `backend/`:

```bash
# From repository root
alembic -c backend/alembic.ini heads

# From backend directory
cd backend
alembic heads
```

---

## Scripts & Evaluation Harness

```bash
# Run the 15-scenario agent evaluation benchmark
python backend/scripts/evaluate_agent.py

# Generate comprehensive development and architecture PDF report
python backend/scripts/generate_complete_report_pdf.py
```

---

## Implementation Status

| Component | Status | Technology |
| :--- | :---: | :--- |
| **FastAPI Backend API** | Implemented | FastAPI, Pydantic v2, Python 3.13 |
| **Authentication & RBAC** | Implemented | PyJWT (HS256/RS256), Supabase claims compatible |
| **Database Layer** | Implemented | SQLite + SQLAlchemy 2.0 ORM + Alembic |
| **AI Tool-Calling Agent** | Implemented | Deterministic pipeline, EasyOCR, Gemini Vision |
| **Rate Limiting & Hardening** | Implemented | In-memory sliding-window, magic byte validation |
| **Automated Test Suite** | 332 Passing | Pytest, TestClient, In-memory isolation |
| **Monorepo Separation** | Implemented | `backend/`, `frontend/`, `data/`, `docs/` |
| **Next.js Web Frontend** | Planned (Phase 7.1) | Next.js 14+, TypeScript, Tailwind CSS |
| **Supabase PostgreSQL** | Planned | Remote Supabase deployment with Auth & RLS |
